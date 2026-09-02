#!/usr/bin/env python3
"""Serve the bundled b7 WireScope and emit deterministic b7 observer frames."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mc_remote._wirescope_app import WireScopeApp
from mc_remote.connection import McRpcError
from mc_remote.observer import PythonObserverSource
from mc_remote.wirescope import _start_loopback_station


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "mc_remote" / "_wirescope_app"
MANIFEST_SHA256 = (
    "7498e32150884aec8c3d562b454d8b042032aa21893ae7fe886c06df2baf028f"
)


class _Terminal:
    def write(self, value):
        print(value, end="", flush=True)

    def flush(self):
        return None


def _load_app():
    manifest = (ARTIFACT_ROOT / "wirescope-app.manifest.json").read_bytes()
    archive = (ARTIFACT_ROOT / "wirescope-app.zip").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("bundled WireScope manifest identity mismatch")
    return WireScopeApp.from_bytes(
        manifest,
        archive,
        manifest_sha256=MANIFEST_SHA256,
    )


def _hello():
    return {
        "protocol": "23.1.0",
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalogHash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": {
            "online": True,
            "offline": False,
            "build_range": 100,
        },
    }


def _emit_b7_frames(source):
    exchanges = (
        ("player.getDirection", [], [0, 0, 1]),
        ("player.setDirection", [1, 2, 3], [0.267261, 0.534522, 0.801784]),
        (
            "entity.getDirection",
            ["mcr_eh_browser-fixture"],
            [1, 0, 0],
        ),
        (
            "entity.setDirection",
            ["mcr_eh_browser-fixture", 1, 2, 3],
            [0.267261, 0.534522, 0.801784],
        ),
        ("world.strikeLightning", [1.25, 2.5, -3.75], None),
    )
    request_id = 2
    for method, params, result in exchanges:
        source.observe_request(method, params, request_id)
        source.observe_result(method, result, request_id)
        request_id += 1
        source.observe_request(method, params, request_id)
        source.observe_error(
            method,
            McRpcError(-32000, "fixture error", {"reason": "backpressure"}),
            request_id,
        )
        request_id += 1


def main():
    runtime = _start_loopback_station(
        app=_load_app(),
        terminal=_Terminal(),
        random_bits=lambda _bits: 0,
    )
    source = PythonObserverSource(
        runtime.pipeline.accept_frame,
        lifecycle_consumer=runtime.pipeline.accept_lifecycle,
        target_id_factory=lambda: "target-python-b7-browser-e2e",
        alias_factory=lambda: "B7-WIRESCOPE-000001",
    )
    try:
        source.observe_request("hello", {"protocol": "23.1.0"}, 1)
        source.observe_result("hello", _hello(), 1)
        print(f"WireScope URL: {runtime.url}", flush=True)
        input("Attach the browser, then press Enter to emit b7 frames: ")
        _emit_b7_frames(source)
        print(
            json.dumps(
                {
                    "methods": [
                        "player.getDirection",
                        "player.setDirection",
                        "entity.getDirection",
                        "entity.setDirection",
                        "world.strikeLightning",
                    ],
                    "success_and_error_exchanges": 5,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        input("Inspect the browser, then press Enter to close: ")
    finally:
        source.connection_closed()
        runtime.close()


if __name__ == "__main__":
    main()
