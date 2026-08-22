"""HTTP-level tests for the in-process browser-loopback station."""

import hashlib
import http.client
import io
import itertools
import json
import socket
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from mc_remote import _wirescope_station_contract as contract
from mc_remote import _wirescope_app as app_module
from mc_remote._wirescope_app import WireScopeApp
from mc_remote._wirescope_session import end_envelope
from mc_remote.observer import PythonObserverSource
import mc_remote.wirescope as wirescope


SOURCE_COMMIT = "192d1e3ccd213fb5012b92655e51b779270e15be"
BUNDLED_APP_SOURCE_COMMIT = "602ecdf809f87a7e33e50d7c465b7248429e26dc"
HELLO = {
    "protocol": "22.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "dimension": "minecraft:overworld",
    "origin": [200, 0, 200],
    "world_constants": {"y_sea": 62},
}
ALIASES = itertools.count(1)


class Terminal(io.StringIO):
    def isatty(self):
        return True


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def app_fixture():
    payloads = {
        "LICENSE": b"AGPL-3.0-only\n",
        "NOTICE": b"WireScope component notice\n",
        "assets/app.js": b'globalThis.wirescope = true;\n',
        "assets/app.css": b"body { color: black; }\n",
        "index.html": b'<script src="/assets/app.js"></script>\n',
    }
    archive_file = io.BytesIO()
    with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(payloads, key=lambda value: value.encode("utf-8")):
            archive.writestr(path, payloads[path])
    archive_bytes = archive_file.getvalue()
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
            "recipe": "npm ci && npm run build:artifact",
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
        "assets": [
            {
                "path": path,
                "bytes": len(payloads[path]),
                "sha256": sha256(payloads[path]),
            }
            for path in sorted(payloads, key=lambda value: value.encode("utf-8"))
        ],
        "license_expression": "AGPL-3.0-only",
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    return WireScopeApp.from_bytes(
        manifest_bytes,
        archive_bytes,
        manifest_sha256=sha256(manifest_bytes),
    )


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("timed out waiting for WireScope station")


def request(runtime, method, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", runtime.http_station.port)
    connection.request(method, path, body=body, headers=headers or {})
    return connection, connection.getresponse()


def activate(runtime):
    alias = f"MIND-STORM-{next(ALIASES):06d}"
    source = PythonObserverSource(
        runtime.pipeline.accept_frame,
        lifecycle_consumer=runtime.pipeline.accept_lifecycle,
        target_id_factory=lambda: "target-python-test",
        alias_factory=lambda: alias,
    )
    source.observe_request("hello", {"protocol": "22.0.0"}, 1)
    source.observe_result("hello", HELLO, 1)
    wait_for(lambda: runtime.pipeline.station_ready)
    return source


def assert_security_headers(response):
    for name, expected in contract.STATION_REQUIRED_RESPONSE_HEADERS.items():
        assert response.getheader(name) == expected
    assert response.getheader("Access-Control-Allow-Origin") is None


def test_verified_app_serves_exact_paths_from_memory_only():
    app = app_fixture()
    assert app.get("/").content_type == "text/html; charset=utf-8"
    assert app.get("/assets/app.js").content_type == (
        "text/javascript; charset=utf-8"
    )
    assert app.get("/assets/app.css").content_type == "text/css; charset=utf-8"
    assert app.get("/../LICENSE") is None
    assert app.get("//assets/app.js") is None
    assert app.get("/missing.js") is None


def test_installed_manifest_pin_is_decoded_from_wheel_record(monkeypatch):
    digest = bytes(range(32))
    encoded = (
        app_module.base64.urlsafe_b64encode(digest)
        .decode("ascii")
        .rstrip("=")
    )

    class RecordPath:
        hash = SimpleNamespace(mode="sha256", value=encoded)

        def as_posix(self):
            return "mc_remote/_wirescope_app/wirescope-app.manifest.json"

    monkeypatch.setattr(
        app_module.metadata,
        "distribution",
        lambda _name: SimpleNamespace(files=[RecordPath()]),
    )
    assert app_module._record_manifest_sha256() == digest.hex()


def test_bundled_delivery_pair_matches_build_input_and_component_files():
    package_root = Path(app_module.__file__).parent
    artifact_root = package_root / "_wirescope_app"
    archive = artifact_root / "wirescope-app.zip"
    manifest = artifact_root / "wirescope-app.manifest.json"

    assert archive.stat().st_size == app_module.BUNDLED_ARCHIVE_BYTES
    assert manifest.stat().st_size == app_module.BUNDLED_MANIFEST_BYTES
    assert sha256(archive.read_bytes()) == app_module.BUNDLED_ARCHIVE_SHA256
    assert sha256(manifest.read_bytes()) == app_module.BUNDLED_MANIFEST_SHA256
    manifest_document = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_document["source"]["commit"] == BUNDLED_APP_SOURCE_COMMIT
    assert manifest_document["protocols"] == {
        "observer_schema": {"name": "mcremote.observer", "version": 1},
        "observer_session": 1,
        "scratch_handoff": 1,
        "station_attach": 1,
    }
    with zipfile.ZipFile(archive) as bundled:
        assert bundled.read("LICENSE") == (
            Path("LICENSES/AGPL-3.0-only.txt").read_bytes()
        )
        assert bundled.read("NOTICE") == (
            Path("LICENSES/WireScope-NOTICE.txt").read_bytes()
        )
        app_scripts = [
            name
            for name in bundled.namelist()
            if name.startswith("assets/") and name.endswith(".js")
        ]
        assert len(app_scripts) == 1
        app_script = bundled.read(app_scripts[0])
        assert b"player.getPose" in app_script
        assert b"player.setPose" in app_script
        assert b"events.poll" in app_script
        assert b"world.getHeight" in app_script
        assert b"world.spawnParticle" in app_script
        assert b"world.spawnEntity" in app_script
        assert b"connection.flush" in app_script


def test_bootstrap_and_assets_require_exact_authority_and_leak_no_secret():
    terminal = Terminal()
    runtime = wirescope._start_loopback_station(
        app=app_fixture(),
        terminal=terminal,
        random_bits=lambda _bits: 0,
    )
    try:
        connection, response = request(
            runtime,
            "GET",
            contract.STATION_BOOTSTRAP_PATH,
        )
        bootstrap = contract.parse_bootstrap(response.read())
        assert response.status == 200
        assert bootstrap["station_ready"] is False
        assert set(bootstrap) == {
            "station_attach_protocol_version",
            "observer_session_protocol_version",
            "observer_schema",
            "artifact",
            "station_ready",
        }
        assert_security_headers(response)
        connection.close()

        activate(runtime)
        connection, response = request(
            runtime,
            "GET",
            contract.STATION_BOOTSTRAP_PATH,
            headers={"Origin": runtime.http_station.policy.origin},
        )
        raw = response.read()
        assert contract.parse_bootstrap(raw)["station_ready"] is True
        assert b"attach_code" not in raw
        assert b"target" not in raw
        connection.close()

        connection, response = request(runtime, "GET", "/assets/app.js")
        assert response.status == 200
        assert response.getheader("Content-Type") == (
            "text/javascript; charset=utf-8"
        )
        assert response.read() == b'globalThis.wirescope = true;\n'
        connection.close()

        bad = http.client.HTTPConnection("127.0.0.1", runtime.http_station.port)
        bad.putrequest("GET", contract.STATION_BOOTSTRAP_PATH, skip_host=True)
        bad.putheader("Host", f"localhost:{runtime.http_station.port}")
        bad.endheaders()
        response = bad.getresponse()
        assert response.status == 400
        assert contract.parse_attach_error(response.read()) == {
            "error": "invalid-request"
        }
        bad.close()
    finally:
        runtime.close()


def test_attach_errors_preserve_attempt_accounting_and_strict_boundaries():
    runtime = wirescope._start_loopback_station(
        app=app_fixture(),
        terminal=Terminal(),
        random_bits=lambda _bits: 0,
    )
    origin = runtime.http_station.policy.origin
    headers = {"Content-Type": "application/json", "Origin": origin}
    try:
        cases = (
            (b'{}', 400, "invalid-request"),
            (b'{"attach_code":"bad"}', 400, "malformed-code"),
        )
        for body, status, code in cases:
            connection, response = request(
                runtime,
                "POST",
                contract.STATION_ATTACH_PATH,
                body=body,
                headers=headers,
            )
            assert response.status == status
            assert contract.parse_attach_error(response.read()) == {"error": code}
            assert_security_headers(response)
            connection.close()

        activate(runtime)
        for expected_status in (403, 403, 403, 403, 429):
            body = b'{"attach_code":"00000001"}'
            connection, response = request(
                runtime,
                "POST",
                contract.STATION_ATTACH_PATH,
                body=body,
                headers=headers,
            )
            assert response.status == expected_status
            response.read()
            connection.close()

        runtime2 = wirescope._start_loopback_station(
            app=app_fixture(),
            terminal=Terminal(),
            random_bits=lambda _bits: 0,
        )
        try:
            activate(runtime2)
            wrong_origin = {
                "Content-Type": "application/json",
                "Origin": "http://example.invalid",
            }
            connection, response = request(
                runtime2,
                "POST",
                contract.STATION_ATTACH_PATH,
                body=b'{"attach_code":"00000001"}',
                headers=wrong_origin,
            )
            assert response.status == 400
            response.read()
            connection.close()

            connection, response = request(
                runtime2,
                "POST",
                contract.STATION_ATTACH_PATH,
                body=b"x" * (contract.STATION_ATTACH_REQUEST_MAX_BYTES + 1),
                headers={
                    "Content-Type": "application/json",
                    "Origin": runtime2.http_station.policy.origin,
                },
            )
            assert response.status == 400
            assert contract.parse_attach_error(response.read()) == {
                "error": "invalid-request"
            }
            connection.close()
            assert runtime2.pipeline.attach("0000-0000") == "redeemed"
        finally:
            runtime2.close()
    finally:
        runtime.close()


def test_successful_attach_streams_strict_snapshot_then_normal_end():
    terminal = Terminal()
    runtime = wirescope._start_loopback_station(
        app=app_fixture(),
        terminal=terminal,
        random_bits=lambda _bits: 0,
    )
    try:
        source = activate(runtime)
        assert terminal.getvalue() == "WireScope attach code: 0000-0000\n"
        origin = runtime.http_station.policy.origin
        connection, response = request(
            runtime,
            "POST",
            contract.STATION_ATTACH_PATH,
            body=b'{"attach_code":"0000-0000"}',
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        assert response.status == 200
        assert response.getheader("Content-Type") == "application/x-ndjson"
        assert_security_headers(response)

        first_line = response.readline()
        first = contract.validate_ndjson_line(first_line)
        assert first["type"] == "mcremote.wirescope.snapshot"
        assert [
            frame["method"]
            for frame in first["snapshot"]["streams"][0]["frames"]
        ] == ["hello", "hello"]
        assert first["history_window"] == {"dropped_frames": 0}

        source.connection_closed()
        final_line = response.readline()
        assert contract.validate_ndjson_line(final_line) == end_envelope(
            "target-ended"
        )
        assert response.read() == b""
        connection.close()
    finally:
        port = runtime.http_station.port
        runtime.close()
        with socket.socket() as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_runtime_close_terminates_open_stream_with_source_closed():
    runtime = wirescope._start_loopback_station(
        app=app_fixture(),
        terminal=Terminal(),
        random_bits=lambda _bits: 0,
    )
    source = activate(runtime)
    origin = runtime.http_station.policy.origin
    connection, response = request(
        runtime,
        "POST",
        contract.STATION_ATTACH_PATH,
        body=b'{"attach_code":"00000000"}',
        headers={"Content-Type": "application/json", "Origin": origin},
    )
    assert contract.validate_ndjson_line(response.readline())["type"] == (
        "mcremote.wirescope.snapshot"
    )
    runtime.close()
    assert contract.validate_ndjson_line(response.readline()) == end_envelope(
        "source-closed"
    )
    assert response.read() == b""
    connection.close()
    source.connection_closed()
