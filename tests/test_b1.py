"""protocol 21.0.0 b1 round-trip tests.

Covers the b1 reachability checklist:
  1. hello succeeds (flat response cached)
  2. setBlock("minecraft:stone") succeeds
  3. setBlock("minecraft:oak_log[axis=y]") succeeds
  4. getBlock returns the full canonical block_state_ref
  5. b1 error reasons (unknown_block / invalid_property_value / build_denied)
     surface with the right reason / data
plus: error responses echo the request id; postToChat maps to chat.post.

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


# Live server hello response is flat (catalog is a single catalogHash scalar).
HELLO = {
    "protocol": "21.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "y_sea": 63,
    "catalogHash": None,
    "world": "world",
    "origin": [200, 0, 200],
}


# 1. hello declares the client protocol and caches the flat response.
def test_hello_declares_protocol_and_caches():
    from mc_remote.minecraft import PROTOCOL

    conn = FakeConn({"hello": HELLO})
    mc = Minecraft(conn)
    resp = mc.hello()
    assert resp == HELLO
    assert conn.calls == [("hello", {"protocol": PROTOCOL})]  # §6.1 object params
    assert mc.protocol == "21.0.0"
    assert mc.mc_version == "1.21.11"
    assert mc.supported_mc_versions == ["1.21.11"]
    assert mc.y_sea == 63
    assert mc.catalog_hash is None  # null -> always a cache miss
    assert mc._world == "world"  # build state synced from hello
    assert (mc._origin.x, mc._origin.y, mc._origin.z) == (200, 0, 200)


# hello negotiation failures surface as reasons (protocol_required / mismatch).
def test_hello_protocol_mismatch_error():
    line = ('{"jsonrpc":"2.0","id":1,"error":{"code":-32600,'
            '"message":"protocol_mismatch","data":{"reason":"protocol_mismatch",'
            '"server":"21.0.0","client_requires":"2100.0.0b1"}}}')
    try:
        Connection._parse_response(line, 1)
    except McRpcError as e:
        assert e.reason == "protocol_mismatch"
        assert e.data["server"] == "21.0.0"
        assert e.data["client_requires"] == "2100.0.0b1"
    else:
        raise AssertionError("expected McRpcError")


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


# postToChat maps to the chat.post wire method (params = [message]).
def test_posttochat_payload():
    conn = FakeConn({"chat.post": "ok"})
    mc = Minecraft(conn)
    mc.postToChat("hi there")
    assert conn.calls == [("chat.post", ["hi there"])]


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
# (missing_namespace was abolished: a bare name is valid and gets minecraft:
# prepended -- DECISIONS 2026-06-27-02/03.)
def test_unknown_block_error():
    try:
        Connection._parse_response(
            _error_line(1, -32602, "unknown_block", ref="definitely_not_a_block"), 1)
    except McRpcError as e:
        assert e.code == -32602
        assert e.reason == "unknown_block"
        assert e.data["ref"] == "definitely_not_a_block"
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


# world-state family. unloaded_chunk was dropped in b1 (auto-load), and
# build_denied was promoted into b1 (config default_build_range): -32000 band
# with data.ref -- knowledge wire-format §7.3 (2026-06-28).
def test_build_denied_error():
    line = _error_line(9, -32000, "build_denied", ref=[7000, 120, 7000])
    try:
        Connection._parse_response(line, 9)
    except McRpcError as e:
        assert e.code == -32000
        assert e.reason == "build_denied"
        assert e.data["ref"] == [7000, 120, 7000]
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
