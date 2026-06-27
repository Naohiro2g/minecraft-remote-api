"""protocol 21.0.0 b1 round-trip tests.

Covers the b1 reachability checklist:
  1. hello succeeds (manifest envelope cached)
  2. setBlock("minecraft:stone") succeeds
  3. setBlock("minecraft:oak_log[axis=y]") succeeds
  4. getBlock returns the full canonical block_state_ref
  5. namespace omission / invalid state / unloaded chunk return the right reason
plus: error responses echo the request id.

The Minecraft layer is tested against a fake connection; the JSON-RPC wire
(request build + response/error parsing) is tested directly on Connection's
static helpers, so no socket/server is needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote.connection import Connection, McRpcError, McRemoteError  # noqa: E402
from mc_remote.minecraft import Minecraft  # noqa: E402


class FakeConn:
    """Records rpc calls and returns canned results (or raises)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        r = self.responses[method]
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(params)
        return r

    def close(self):
        pass


HELLO = {
    "protocol": "21.0.0",
    "server": {"mc_version": "1.21.11", "loader": "paper"},
    "catalogs": {
        "block": {
            "format": "mcremote-block-catalog-v1",
            "hash": None,
            "namespaces": [],
            "inline": False,
        }
    },
}


# 1. hello succeeds and the manifest envelope is cached.
def test_hello_caches_manifest():
    mc = Minecraft(FakeConn({"hello": HELLO}))
    resp = mc.hello()
    assert resp == HELLO
    assert mc.protocol == "21.0.0"
    assert mc.server["mc_version"] == "1.21.11"
    block = mc.catalogs["block"]
    assert block["format"] == "mcremote-block-catalog-v1"
    assert block["hash"] is None and block["namespaces"] == []


# 2 & 3. setBlock sends coords + block_state_ref string verbatim.
def test_setblock_payloads():
    conn = FakeConn({"world.setBlock": "ok"})
    mc = Minecraft(conn)
    mc.setBlock(0, 0, 0, "minecraft:stone")
    mc.setBlock(1, 2, 3, "minecraft:oak_log[axis=y]")
    assert conn.calls == [
        ("world.setBlock", [0, 0, 0, "minecraft:stone"]),
        ("world.setBlock", [1, 2, 3, "minecraft:oak_log[axis=y]"]),
    ]


# 4. getBlock returns the full canonical block_state_ref string.
def test_getblock_returns_full_canonical():
    conn = FakeConn({"world.getBlock": "minecraft:oak_log[axis=y]"})
    mc = Minecraft(conn)
    assert mc.getBlock(0, 0, 0) == "minecraft:oak_log[axis=y]"
    assert conn.calls == [("world.getBlock", [0, 0, 0])]


def test_setblocks_payload():
    conn = FakeConn({"world.setBlocks": "ok"})
    mc = Minecraft(conn)
    mc.setBlocks(0, 0, 0, 2, 2, 2, "minecraft:stone")
    assert conn.calls == [
        ("world.setBlocks", [0, 0, 0, 2, 2, 2, "minecraft:stone"]),
    ]


# Build setters: API name is camelCase, wire method is build.* (knowledge
# DECISIONS 2026-06-26-04). Lock the non-obvious mapping.
def test_build_setters_wire_names():
    conn = FakeConn({"build.setWorld": "ok", "build.setOrigin": "ok"})
    mc = Minecraft(conn)
    mc.setWorld("nether")
    mc.setBuildOrigin(10, 0, 20)
    assert conn.calls == [
        ("build.setWorld", ["nether"]),
        ("build.setOrigin", [10, 0, 20]),
    ]
    assert mc._world == "nether"


def _error_line(req_id, code, reason, **data):
    import json

    data = {"reason": reason, **data}
    return json.dumps(
        {"jsonrpc": "2.0", "id": req_id,
         "error": {"code": code, "message": reason.replace("_", " "), "data": data}}
    )


# 5. ref-validation and world-state errors carry the right reason / data.
def test_missing_namespace_error():
    try:
        Connection._parse_response(_error_line(1, -32602, "missing_namespace", ref="stone"), 1)
    except McRpcError as e:
        assert e.code == -32602
        assert e.reason == "missing_namespace"
        assert e.data["ref"] == "stone"
    else:
        raise AssertionError("expected McRpcError")


def test_invalid_property_value_error_with_allowed():
    line = _error_line(7, -32602, "invalid_property_value",
                       ref="minecraft:oak_log[axis=w]", property="axis",
                       value="w", allowed=["x", "y", "z"])
    try:
        Connection._parse_response(line, 7)
    except McRpcError as e:
        assert e.reason == "invalid_property_value"
        assert e.data["allowed"] == ["x", "y", "z"]
    else:
        raise AssertionError("expected McRpcError")


def test_unloaded_chunk_error_carries_pos():
    line = _error_line(9, -32001, "unloaded_chunk", pos=[123, 64, -50])
    try:
        Connection._parse_response(line, 9)
    except McRpcError as e:
        assert e.code == -32001
        assert e.reason == "unloaded_chunk"
        assert e.data["pos"] == [123, 64, -50]
    else:
        raise AssertionError("expected McRpcError")


# error responses echo the request id; results require a matching id.
def test_result_id_match_and_mismatch():
    import json

    ok = json.dumps({"jsonrpc": "2.0", "id": 5, "result": "done"})
    assert Connection._parse_response(ok, 5) == "done"
    try:
        Connection._parse_response(ok, 6)
    except McRemoteError as e:
        assert "id mismatch" in str(e)
    else:
        raise AssertionError("expected id mismatch")


def test_error_surfaces_even_with_null_id():
    import json

    line = json.dumps(
        {"jsonrpc": "2.0", "id": None,
         "error": {"code": -32602, "message": "bad", "data": {"reason": "malformed_ref"}}}
    )
    try:
        Connection._parse_response(line, 3)
    except McRpcError as e:
        assert e.reason == "malformed_ref"
    else:
        raise AssertionError("expected McRpcError")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
