"""Current protocol round-trip regression tests.

Covers the b1 reachability checklist:
  1. hello succeeds (flat response cached)
  2. setBlock sends a structured BlockSpec
  3. getBlock returns the full canonical immutable BlockValue
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


# Live server hello: catalog is a single catalogHash scalar; y_sea is bundled
# under world_constants (knowledge DECISIONS 2026-07-02-02).
HELLO = {
    "protocol": "22.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "world_constants": {"y_sea": 63},
    "catalogHash": None,
    "dimension": "minecraft:overworld",
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
    assert mc.protocol == "22.0.0"
    assert mc.mc_version == "1.21.11"
    assert mc.supported_mc_versions == ["1.21.11"]
    assert mc.y_sea == 63
    assert mc.catalog_hash is None  # null -> always a cache miss
    assert mc._dimension == "minecraft:overworld"  # server-canonical context
    assert (mc._origin.x, mc._origin.y, mc._origin.z) == (200, 0, 200)


def test_invalid_hello_build_context_is_not_cached():
    invalid = dict(HELLO, dimension="overworld")
    mc = Minecraft(FakeConn({"hello": invalid}))
    try:
        mc.hello()
    except McRemoteError:
        pass
    else:
        raise AssertionError("accepted a non-canonical hello dimension")
    assert mc.protocol is None
    assert mc._dimension == "minecraft:overworld"
    assert (mc._origin.x, mc._origin.y, mc._origin.z) == (200, 0, 200)


# y_sea is read from world_constants, never from a top-level key: an un-flipped
# server (legacy top-level y_sea, no world_constants) must surface as None so the
# b1 gate catches the drift (knowledge DECISIONS 2026-07-02-02, atomic flip).
def test_y_sea_only_from_world_constants():
    legacy = dict(HELLO)
    legacy.pop("world_constants")
    legacy["y_sea"] = 63  # top-level only, as an un-flipped server would send
    mc = Minecraft(FakeConn({"hello": legacy}))
    mc.hello()
    assert mc.y_sea is None
    # null world_constants.y_sea is a valid b1 value (number | null)
    nullwc = dict(HELLO, world_constants={"y_sea": None})
    mc2 = Minecraft(FakeConn({"hello": nullwc}))
    mc2.hello()
    assert mc2.y_sea is None


# hello negotiation failures surface as reasons (protocol_required / mismatch).
def test_hello_protocol_mismatch_error():
    line = ('{"jsonrpc":"2.0","id":1,"error":{"code":-32600,'
            '"message":"protocol_mismatch","data":{"reason":"protocol_mismatch",'
            '"server":"22.0.0","client_requires":"2200.0.0b5"}}}')
    try:
        Connection._parse_response(line, 1)
    except McRpcError as e:
        assert e.reason == "protocol_mismatch"
        assert e.data["server"] == "22.0.0"
        assert e.data["client_requires"] == "2200.0.0b5"
    else:
        raise AssertionError("expected McRpcError")


# 2. setBlock sends coordinates plus an exact BlockSpec object.
def test_setblock_payloads():
    conn = FakeConn({"world.setBlock": None})
    mc = Minecraft(conn)
    mc.setBlock(0, 0, 0, "minecraft:stone")
    mc.setBlock(1, 2, 3, "minecraft:oak_log", state={"axis": "y"})
    assert conn.calls == [
        ("world.setBlock", [0, 0, 0, {"block_id": "minecraft:stone", "state": {}}]),
        (
            "world.setBlock",
            [1, 2, 3, {"block_id": "minecraft:oak_log", "state": {"axis": "y"}}],
        ),
    ]


# 3. getBlock returns the full canonical immutable BlockValue.
def test_getblock_returns_full_canonical():
    conn = FakeConn(
        {"world.getBlock": {"block_id": "minecraft:oak_log", "state": {"axis": "y"}}}
    )
    mc = Minecraft(conn)
    value = mc.getBlock(0, 0, 0)
    assert value.block_id == "minecraft:oak_log"
    assert value.state == {"axis": "y"}
    assert conn.calls == [("world.getBlock", [0, 0, 0])]


def test_setblocks_payload():
    conn = FakeConn({"world.setBlocks": None})
    mc = Minecraft(conn)
    mc.setBlocks(0, 0, 0, 2, 2, 2, "minecraft:stone")
    assert conn.calls == [
        (
            "world.setBlocks",
            [0, 0, 0, 2, 2, 2, {"block_id": "minecraft:stone", "state": {}}],
        ),
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
    conn = FakeConn(
        {
            "build.setDimension": {
                "dimension": "myworld:world",
                "origin": [200, 0, 200],
            },
            "build.setOrigin": {
                "dimension": "myworld:world",
                "origin": [10, 0, 20],
            },
        }
    )
    mc = Minecraft(conn)
    assert mc.setDimension("myworld:world") == {
        "dimension": "myworld:world",
        "origin": [200, 0, 200],
    }
    assert mc.setBuildOrigin(10, 0, 20) == {
        "dimension": "myworld:world",
        "origin": [10, 0, 20],
    }
    assert conn.calls == [
        ("build.setDimension", ["myworld:world"]),
        ("build.setOrigin", [10, 0, 20]),
    ]
    assert mc._dimension == "myworld:world"
    assert (mc._origin.x, mc._origin.y, mc._origin.z) == (10, 0, 20)


def test_build_setter_uses_canonical_result_not_input():
    result = {"dimension": "minecraft:overworld", "origin": [200, 0, 200]}
    mc = Minecraft(FakeConn({"build.setDimension": result}))

    assert mc.setDimension("overworld") == result
    assert mc._dimension == "minecraft:overworld"


def test_dimension_refs_are_forwarded_without_aliasing_or_normalizing():
    results = {
        "world": "minecraft:world",
        "normal": "minecraft:normal",
        "nether": "minecraft:nether",
        "end": "minecraft:end",
    }

    def canonical_result(params):
        return {"dimension": results[params[0]], "origin": [200, 0, 200]}

    conn = FakeConn({"build.setDimension": canonical_result})
    mc = Minecraft(conn)
    assert not hasattr(mc, "setWorld")
    for dimension_ref, canonical in results.items():
        result = mc.setDimension(dimension_ref)
        assert result["dimension"] == canonical
    assert conn.calls == [
        ("build.setDimension", [dimension_ref]) for dimension_ref in results
    ]

    before = list(conn.calls)
    for malformed in (" Overworld", "Overworld", "minecraft:overworld "):
        try:
            mc.setDimension(malformed)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted malformed DimensionRef: {malformed!r}")
    assert conn.calls == before


def test_build_setter_failure_or_invalid_result_preserves_context():
    failure = McRpcError(-32602, "unknown dimension", {"reason": "unknown_dimension"})
    mc = Minecraft(FakeConn({"build.setDimension": failure}))
    before = (mc._dimension, mc._origin)
    try:
        mc.setDimension("missing:dimension")
    except McRpcError as exc:
        assert exc.reason == "unknown_dimension"
    else:
        raise AssertionError("expected unknown_dimension")
    assert (mc._dimension, mc._origin) == before

    invalid_results = (
        None,
        {"dimension": "overworld", "origin": [200, 0, 200]},
        {"dimension": "minecraft:overworld", "origin": [200, 0]},
        {
            "dimension": "minecraft:overworld",
            "origin": [200, 0, 200],
            "extra": True,
        },
    )
    for invalid in invalid_results:
        mc.conn = FakeConn({"build.setDimension": invalid})
        try:
            mc.setDimension("overworld")
        except McRemoteError:
            pass
        else:
            raise AssertionError(f"accepted invalid build context: {invalid!r}")
        assert (mc._dimension, mc._origin) == before


def test_set_build_origin_failure_or_invalid_result_preserves_context():
    initial = {"dimension": "myworld:world", "origin": [12, 34, 56]}
    mc = Minecraft(FakeConn({"build.setDimension": initial}))
    mc.setDimension("myworld:world")
    before = (
        mc._dimension,
        (mc._origin.x, mc._origin.y, mc._origin.z),
    )

    failure = McRpcError(-32000, "build denied", {"reason": "build_denied"})
    mc.conn = FakeConn({"build.setOrigin": failure})
    try:
        mc.setBuildOrigin(1, 2, 3)
    except McRpcError as exc:
        assert exc.reason == "build_denied"
    else:
        raise AssertionError("expected build_denied")
    assert (
        mc._dimension,
        (mc._origin.x, mc._origin.y, mc._origin.z),
    ) == before

    invalid = {
        "dimension": "minecraft:the_end",
        "origin": [1, 2, 3],
        "extra": True,
    }
    mc.conn = FakeConn({"build.setOrigin": invalid})
    try:
        mc.setBuildOrigin(1, 2, 3)
    except McRemoteError:
        pass
    else:
        raise AssertionError("accepted non-exact build.setOrigin result")
    assert (
        mc._dimension,
        (mc._origin.x, mc._origin.y, mc._origin.z),
    ) == before


def _error_line(req_id, code, reason, **data):
    import json

    data = {"reason": reason, **data}
    return json.dumps(
        {"jsonrpc": "2.0", "id": req_id,
         "error": {"code": code, "message": reason.replace("_", " "), "data": data}}
    )


# 5. block-validation and world-state errors carry protocol 22 fields.
def test_unknown_block_error():
    try:
        Connection._parse_response(
            _error_line(
                1, -32602, "unknown_block", block_id="definitely_not_a_block"
            ),
            1,
        )
    except McRpcError as e:
        assert e.code == -32602
        assert e.reason == "unknown_block"
        assert e.data["block_id"] == "definitely_not_a_block"
        assert "ref" not in e.data
    else:
        raise AssertionError("expected McRpcError")


def test_unknown_dimension_error_keeps_actionable_dimension():
    line = _error_line(
        2,
        -32602,
        "unknown_dimension",
        dimension="myworld:missing",
    )
    try:
        Connection._parse_response(line, 2)
    except McRpcError as exc:
        assert exc.reason == "unknown_dimension"
        assert exc.data["dimension"] == "myworld:missing"
        assert "[unknown_dimension]" in str(exc)
        assert "dimension='myworld:missing'" in str(exc)
    else:
        raise AssertionError("expected unknown_dimension")


def test_invalid_property_value_error_with_allowed():
    line = _error_line(
        7,
        -32602,
        "invalid_property_value",
        block_id="minecraft:oak_log",
        property="axis",
        value="w",
        allowed=["x", "y", "z"],
    )
    try:
        Connection._parse_response(line, 7)
    except McRpcError as e:
        assert e.reason == "invalid_property_value"
        assert e.data["allowed"] == ["x", "y", "z"]
    else:
        raise AssertionError("expected McRpcError")


# world-state family. unloaded_chunk was dropped in b1 (auto-load), and
# build_denied may carry policy-specific bounds/violating details, never a
# legacy combined-ref field.
def test_build_denied_error():
    line = _error_line(
        9,
        -32000,
        "build_denied",
        bounds={"min": [-100, -64, -100], "max": [100, 320, 100]},
        violating=[7000, 120, 7000],
    )
    try:
        Connection._parse_response(line, 9)
    except McRpcError as e:
        assert e.code == -32000
        assert e.reason == "build_denied"
        assert e.data["violating"] == [7000, 120, 7000]
        assert "ref" not in e.data
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
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32602,
                "message": "bad",
                "data": {"reason": "invalid_params"},
            },
        }
    )
    try:
        Connection._parse_response(line, 3)
    except McRpcError as e:
        assert e.reason == "invalid_params"
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
