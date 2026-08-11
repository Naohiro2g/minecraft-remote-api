"""Tests for detached WireScope artifact integrity boundaries."""

import hashlib
import io
import json
import zipfile

import pytest

from mc_remote._wirescope_artifact import (
    WireScopeArtifactError,
    parse_detached_manifest,
    verify_archive,
    verify_artifact_archive,
)


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


SOURCE_COMMIT = "e0794c1d09ecc99efceec786fe9d46c23a250db3"


def artifact_fixture(*, manifest_update=None, asset_payloads=None):
    asset_payloads = asset_payloads or {
        "LICENSE": b"GNU AFFERO GENERAL PUBLIC LICENSE Version 3\n",
        "NOTICE": b"WireScope component notice\n",
        "assets/app.js": b'console.log("WireScope")\n',
        "index.html": b'<script src="/assets/app.js"></script>\n',
    }
    archive_file = io.BytesIO()
    with zipfile.ZipFile(
        archive_file,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in sorted(asset_payloads, key=lambda item: item.encode("utf-8")):
            archive.writestr(path, asset_payloads[path])
    archive_bytes = archive_file.getvalue()
    assets = [
        {
            "path": path,
            "bytes": len(asset_payloads[path]),
            "sha256": sha256(asset_payloads[path]),
        }
        for path in sorted(asset_payloads, key=lambda item: item.encode("utf-8"))
    ]
    manifest = {
        "manifest_schema": "mcremote.wirescope.app-manifest",
        "manifest_version": 1,
        "archive": {
            "file": "wirescope-app.zip",
            "format": "zip",
            "format_version": 1,
            "sha256": sha256(archive_bytes),
        },
        "source": {
            "repository": "https://github.com/Naohiro2g/scratch-editor",
            "commit": SOURCE_COMMIT,
            "subdirectory": "mc-remote/live",
            "corresponding_source_url": (
                "https://github.com/Naohiro2g/scratch-editor/tree/"
                f"{SOURCE_COMMIT}/mc-remote/live"
            ),
        },
        "build": {
            "recipe": (
                "npm ci && npm run build:artifact --workspace=@mc-remote/live"
                f" -- --source-commit {SOURCE_COMMIT}"
            ),
            "toolchain": {
                "node": "22.20.0",
                "rolldown-vite": "7.3.1",
                "typescript": "5.9.3",
                "jszip": "3.10.1",
            },
            "input_identity": {
                "source_commit": SOURCE_COMMIT,
                "package_json_sha256": "1" * 64,
                "package_lock_sha256": "2" * 64,
            },
        },
        "protocols": {
            "observer_schema": {"name": "mcremote.observer", "version": 1},
            "observer_session": 1,
            "scratch_handoff": 1,
            "station_attach": 1,
        },
        "assets": assets,
        "license_expression": "AGPL-3.0-only",
    }
    if manifest_update is not None:
        manifest_update(manifest)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n"
    )
    return manifest_bytes, archive_bytes


def test_detached_manifest_is_pinned_by_its_exact_outer_bytes():
    payload, _archive = artifact_fixture()
    parsed = parse_detached_manifest(
        payload,
        expected_sha256=sha256(payload).upper(),
    )
    assert parsed.document["manifest_schema"] == (
        "mcremote.wirescope.app-manifest"
    )
    assert parsed.archive_sha256 == parsed.document["archive"]["sha256"]
    assert parsed.sha256 == sha256(payload)

    changed = payload + b" "
    with pytest.raises(WireScopeArtifactError, match="manifest SHA-256 mismatch"):
        parse_detached_manifest(changed, expected_sha256=sha256(payload))


@pytest.mark.parametrize(
    "payload, message",
    [
        (b'{"key":1,"key":2}', "duplicate key"),
        (b"[]", "detached manifest must be a JSON object"),
        (b'{"value":NaN}', "non-JSON numeric constant"),
        (b'{"value":1} trailing', "one complete JSON document"),
        (b'\xff', "valid UTF-8"),
    ],
)
def test_detached_manifest_parser_rejects_ambiguous_or_invalid_json(
    payload,
    message,
):
    with pytest.raises(WireScopeArtifactError, match=message):
        parse_detached_manifest(payload, expected_sha256=sha256(payload))


def test_archive_hash_is_checked_against_manifest_adapter_output():
    archive = b"deterministic ZIP fixture bytes"
    assert verify_archive(archive, expected_sha256=sha256(archive)) == sha256(
        archive
    )
    with pytest.raises(WireScopeArtifactError, match="archive SHA-256 mismatch"):
        verify_archive(archive + b"changed", expected_sha256=sha256(archive))


def test_exact_scratch_manifest_and_all_archive_assets_are_verified():
    manifest_bytes, archive_bytes = artifact_fixture()
    manifest = parse_detached_manifest(
        manifest_bytes,
        expected_sha256=sha256(manifest_bytes),
    )
    assert verify_artifact_archive(archive_bytes, manifest) == sha256(archive_bytes)
    assert [asset.path for asset in manifest.assets] == [
        "LICENSE",
        "NOTICE",
        "assets/app.js",
        "index.html",
    ]


@pytest.mark.parametrize(
    "update, message",
    [
        (
            lambda manifest: manifest.update({"runtime_port": 43123}),
            "unknown field: runtime_port",
        ),
        (
            lambda manifest: manifest.update({"license_expression": "MIT"}),
            "license_expression is unsupported",
        ),
        (
            lambda manifest: manifest["protocols"].update(
                {"observer_session": 2}
            ),
            "protocols.observer_session is unsupported",
        ),
        (
            lambda manifest: manifest["source"].update(
                {"corresponding_source_url": "https://example.invalid/source"}
            ),
            "source.corresponding_source_url is unsupported",
        ),
        (
            lambda manifest: manifest["assets"][0].update(
                {"path": "../LICENSE"}
            ),
            "safe relative ZIP path",
        ),
    ],
)
def test_exact_manifest_rejects_unversioned_or_unsafe_changes(update, message):
    manifest_bytes, _archive_bytes = artifact_fixture(manifest_update=update)
    with pytest.raises(WireScopeArtifactError, match=message):
        parse_detached_manifest(
            manifest_bytes,
            expected_sha256=sha256(manifest_bytes),
        )


def test_archive_inventory_and_asset_hash_must_match_detached_manifest():
    manifest_bytes, archive_bytes = artifact_fixture()
    manifest = parse_detached_manifest(
        manifest_bytes,
        expected_sha256=sha256(manifest_bytes),
    )
    changed_manifest_bytes, changed_archive = artifact_fixture(
        asset_payloads={
            "LICENSE": b"changed license\n",
            "NOTICE": b"WireScope component notice\n",
            "assets/app.js": b'console.log("WireScope")\n',
            "index.html": b'<script src="/assets/app.js"></script>\n',
        }
    )
    assert changed_manifest_bytes != manifest_bytes
    with pytest.raises(WireScopeArtifactError, match="archive SHA-256 mismatch"):
        verify_artifact_archive(changed_archive, manifest)

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as original:
        mismatched_file = io.BytesIO()
        with zipfile.ZipFile(mismatched_file, "w") as mismatched:
            for entry in original.infolist():
                if entry.filename != "NOTICE":
                    mismatched.writestr(entry.filename, original.read(entry))
    mismatched_bytes = mismatched_file.getvalue()
    mismatched_manifest_bytes, _unused_archive = artifact_fixture(
        manifest_update=lambda value: value["archive"].update(
            {"sha256": sha256(mismatched_bytes)}
        )
    )
    manifest = parse_detached_manifest(
        mismatched_manifest_bytes,
        expected_sha256=sha256(mismatched_manifest_bytes),
    )
    with pytest.raises(WireScopeArtifactError, match="inventory does not match"):
        verify_artifact_archive(mismatched_bytes, manifest)


@pytest.mark.parametrize("expected", ["", "0" * 63, "g" * 64, None])
def test_hash_verifier_rejects_malformed_expected_digest(expected):
    with pytest.raises(WireScopeArtifactError, match="SHA-256"):
        verify_archive(b"archive", expected_sha256=expected)


def test_hash_verifier_requires_exact_bytes():
    with pytest.raises(TypeError, match="payload must be bytes"):
        verify_archive(bytearray(b"archive"), expected_sha256="0" * 64)
