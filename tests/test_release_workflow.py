"""Exercise release.yml's actual verification scripts without publishing."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.request

import pytest


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/release.yml"
TAG = "v2320.0.0b9"
SOURCE = "a" * 40


def step_script(name):
    step = WORKFLOW.read_text().split(f"      - name: {name}\n", 1)[1]
    match = re.search(r"        run: \|\n((?:          [^\n]*\n|\n)*)", step)
    assert match is not None
    return textwrap.dedent(match[1])


def python_script(name, marker):
    script = step_script(name)
    return script.split(f"python - <<'{marker}'\n", 1)[1].split(f"\n{marker}", 1)[0]


@pytest.fixture
def release_assets(tmp_path):
    directory = tmp_path / "release-assets"
    directory.mkdir()
    artifacts = []
    for role, filename in (
        ("wheel", "minecraft_remote_api-2320.0.0b9-py3-none-any.whl"),
        ("sdist", "minecraft_remote_api-2320.0.0b9.tar.gz"),
    ):
        body = f"candidate {role} bytes".encode()
        (directory / filename).write_bytes(body)
        artifacts.append({
            "role": role, "file": filename,
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    manifest = {
        "schema": "mc-remote.release-manifest", "schema_version": 1,
        "release_tag": TAG, "source_commit": SOURCE, "artifacts": artifacts,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, directory, manifest


def run_asset_verification(root, *, tag=TAG, source=SOURCE):
    if not all(shutil.which(tool) for tool in ("bash", "jq", "sha256sum")):
        pytest.skip("release artifact verification runs on the Linux CI runner")
    return subprocess.run(
        ["bash", "-c", step_script("Verify the assets against manifest.json")],
        cwd=root, env={**os.environ, "TAG_NAME": tag, "SOURCE_COMMIT": source},
        capture_output=True, text=True,
    )


def test_shared_verification_preserves_release_bytes_and_manifest(release_assets):
    root, directory, manifest = release_assets
    expected = {item.name: item.read_bytes() for item in directory.iterdir()}
    completed = run_asset_verification(root)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert {item.name: item.read_bytes() for item in (root / "dist").iterdir()} == expected


@pytest.mark.parametrize("fault", ["tag", "source", "wheel-version", "wheel-bytes", "sdist-bytes", "digest"])
def test_shared_verification_stops_on_identity_or_byte_mismatch(release_assets, fault):
    root, directory, manifest = release_assets
    tag, source = TAG, SOURCE
    if fault == "tag":
        manifest["release_tag"] = "v2320.0.0b8"
    elif fault == "source":
        source = "b" * 40
    elif fault == "wheel-version":
        tag = manifest["release_tag"] = "v2320.0.0b10"
    elif fault in {"wheel-bytes", "sdist-bytes"}:
        index = 0 if fault == "wheel-bytes" else 1
        (directory / manifest["artifacts"][index]["file"]).write_bytes(b"changed")
    else:
        manifest["artifacts"][0]["sha256"] = "0" * 64
    (directory / "manifest.json").write_text(json.dumps(manifest))
    completed = run_asset_verification(root, tag=tag, source=source)
    assert completed.returncode != 0
    assert "::error::" in completed.stdout


@pytest.mark.parametrize("tag,eligible", [
    ("v2301.0.0b7.post3", False), ("v2320.0.0b8", False),
    ("v2320.0.0b8.post1", False), ("v2320.0.0b9", True),
    ("v2320.0.0b10", True), ("v2320.0.0rc1", True),
    ("v2320.0.0", True), ("v2330.0.0b1", True),
])
def test_pypi_starts_at_b9_and_excludes_historical_beta(tmp_path, tag, eligible):
    output = tmp_path / "outputs"
    completed = subprocess.run(
        [sys.executable, "-c", python_script("Resolve the published Release tag", "PYPI_FLOOR")],
        env={**os.environ, "TAG_NAME": tag, "GITHUB_OUTPUT": str(output)},
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.read_text() == f"pypi_eligible={str(eligible).lower()}\n"


@pytest.mark.parametrize("fault", [None, "version", "digest", "size", "yanked", "local-bytes"])
def test_post_publish_verification_checks_warehouse_against_release_bytes(
    release_assets, monkeypatch, fault,
):
    root, directory, manifest = release_assets
    published = {
        "info": {"version": TAG[1:]},
        "urls": [{
            "filename": item["file"], "digests": {"sha256": item["sha256"]},
            "size": (directory / item["file"]).stat().st_size, "yanked": False,
        } for item in manifest["artifacts"]],
    }
    if fault == "version":
        published["info"]["version"] = "2320.0.0b8"
    elif fault == "digest":
        published["urls"][0]["digests"]["sha256"] = "0" * 64
    elif fault == "size":
        published["urls"][0]["size"] += 1
    elif fault == "yanked":
        published["urls"][0]["yanked"] = True
    elif fault == "local-bytes":
        (directory / manifest["artifacts"][0]["file"]).write_bytes(b"changed")

    def urlopen(url, timeout):
        assert url == f"https://pypi.org/pypi/minecraft-remote-api/{TAG[1:]}/json"
        assert timeout == 30
        return io.BytesIO(json.dumps(published).encode())

    monkeypatch.chdir(root)
    monkeypatch.setenv("TAG_NAME", TAG)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    code = python_script("Verify the PyPI.org files match the Release assets", "PYPI")
    if fault is None:
        exec(code, {})
    else:
        with pytest.raises(SystemExit):
            exec(code, {})
