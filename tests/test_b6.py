"""Protocol 23.0.0 b6 tests: pickaxe_poke event and the sign slice.

Fixture-driven against the b6 shared compatibility fixtures owned by
scratch-editor's ``@mc-remote/protocol`` (DECISIONS `2026-08-27-02`,
`10-protocol/b6-compatibility-fixture-plan_ja.md`):
``tests/fixtures/sign-v23.json`` and ``tests/fixtures/events-v23.json``,
copied byte-for-byte from
``agent/b6-source-refresh@104f194deddc9c244e6e07c4223965c792551f9d``.
Case IDs (``B6-I0x``/``B6-H0x``/``B6-S0x``/``B6-P0x``) are the plan's
canonical case ledger; each test below names the case(s) it projects.
"""

import hashlib
import json
from pathlib import Path

from mc_remote.b5_values import (
    ChatPostedEvent,
    EntityHandle,
    PickaxePokeEvent,
    ProjectileHitEvent,
)
from mc_remote.connection import McRemoteError, McRpcError
from mc_remote.minecraft import Minecraft, PROTOCOL
from mc_remote.sign_value import LineValue, SignValue, line_spec

FIXTURES = Path(__file__).parent / "fixtures"
SIGN_FIXTURE_PATH = FIXTURES / "sign-v23.json"
EVENTS_FIXTURE_PATH = FIXTURES / "events-v23.json"
SIGN_FIXTURE = json.loads(SIGN_FIXTURE_PATH.read_text(encoding="utf-8"))
EVENTS_FIXTURE = json.loads(EVENTS_FIXTURE_PATH.read_text(encoding="utf-8"))

SIGN_FIXTURE_SHA256 = (
    "7ffb63c264602cba56117eefff1f9604b955df04c5cc655e877772b8ff7cd30e"
)
EVENTS_FIXTURE_SHA256 = (
    "31760d267f3c2641042fbe8595fda9c259134a1c05423271a99cb74da1efa9aa"
)


class FakeConn:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        response = self.responses[method]
        return response(params) if callable(response) else response

    def close(self):
        pass


def _line_value(entry) -> LineValue:
    return LineValue(
        text=entry["text"], color=entry["color"], decorations=tuple(entry["decorations"])
    )


def test_shared_fixture_bytes_match_owner_digest():
    """Guards against silent drift from the fixture owner's exact bytes."""
    assert (
        hashlib.sha256(SIGN_FIXTURE_PATH.read_bytes()).hexdigest()
        == SIGN_FIXTURE_SHA256
    )
    assert (
        hashlib.sha256(EVENTS_FIXTURE_PATH.read_bytes()).hexdigest()
        == EVENTS_FIXTURE_SHA256
    )


def test_b6_i01_fixtures_remain_protocol_23_0_0_under_b7_client():
    assert PROTOCOL == "23.1.0"
    assert SIGN_FIXTURE["protocol"] == "23.0.0"
    assert EVENTS_FIXTURE["protocol"] == "23.0.0"


# ---------------------------------------------------------------------------
# B6-H01 / B6-H02 / B6-H03 -- entity handle
# ---------------------------------------------------------------------------


def test_b6_h01_h03_fixture_handle_is_opaque_and_length_unconstrained():
    """B6-H01 (mcr_eh_ prefix accepted), B6-H03 (opaque; no suffix-length rule).

    The owner fixture's positive handle is intentionally short (9-char
    suffix) to prove the client does not elevate the plugin's own 22-char
    issuance length into a client-side contract.
    """
    handle = EVENTS_FIXTURE["projectile_targets"]["entity"]["handle"]
    assert handle == "mcr_eh_fixture-1"
    entity_handle = EntityHandle(handle)
    assert entity_handle == handle


def test_b6_h02_legacy_prefix_not_accepted_as_protocol_23_handle():
    """B6-H02: protocol 22's mceh_ is not an alias under protocol 23."""
    legacy = "mceh_" + "A" * 22
    try:
        EntityHandle(legacy)
    except ValueError:
        pass
    else:
        raise AssertionError("legacy mceh_ handle was accepted under protocol 23")


# ---------------------------------------------------------------------------
# B6-P01 / B6-P02 -- pickaxe_poke / events.poll
# ---------------------------------------------------------------------------


def test_b6_p01_poll_events_decodes_fixture_poll_result():
    """B6-P01: decode the shared events.poll result's three events."""
    result = EVENTS_FIXTURE["poll_result"]
    conn = FakeConn({"events.poll": result})
    batch = Minecraft(conn).pollEvents()
    assert conn.calls == [("events.poll", [0])]

    poke, chat, projectile = batch.events
    fixture_poke = result["events"][0]
    assert isinstance(poke, PickaxePokeEvent)
    assert poke.pos == tuple(fixture_poke["pos"])
    assert poke.face == fixture_poke["face"]
    assert poke.hand == fixture_poke["hand"]
    assert poke.item == fixture_poke["item"]
    assert poke.block.block_id == fixture_poke["block"]["block_id"]

    assert isinstance(chat, ChatPostedEvent)
    assert chat.message == result["events"][1]["message"]

    assert isinstance(projectile, ProjectileHitEvent)
    fixture_target = result["events"][2]["target"]
    assert projectile.target.kind == "block"
    assert projectile.target.face == fixture_target["face"]
    assert projectile.target.pos == tuple(fixture_target["pos"])


def test_b6_p02_rejects_fixture_legacy_block_right_click_event():
    """B6-P02: protocol 23 does not decode the historical block_right_click."""
    legacy_event = EVENTS_FIXTURE["legacy_rejected_events"]["block_right_click"]
    result = {
        "events": [legacy_event],
        "through_sequence": 1,
        "latest_sequence": 1,
        "filtered_out": 0,
        "overflow_dropped_total": 0,
        "capacity_dropped_total": 0,
        "explicitly_discarded_total": 0,
    }
    conn = FakeConn({"events.poll": result})
    try:
        Minecraft(conn).pollEvents()
    except McRemoteError:
        pass
    else:
        raise AssertionError("legacy block_right_click event was accepted")


# ---------------------------------------------------------------------------
# B6-S01 / B6-S02 -- LineSpec input / LineValue canonical output
# ---------------------------------------------------------------------------


def test_b6_s01_line_spec_accepts_fixture_shorthand_and_object_forms():
    cases = SIGN_FIXTURE["line_specs"]["B6-S01"]
    assert line_spec(cases["string_shorthand"]) == cases["string_shorthand"]
    assert line_spec(cases["object_named_color"]) == cases["object_named_color"]
    assert line_spec(cases["object_hex_color"]) == cases["object_hex_color"]
    assert line_spec(cases["object_all_decorations"]) == cases["object_all_decorations"]


def test_b6_s02_line_value_decodes_fixture_canonical_results():
    cases = SIGN_FIXTURE["line_values"]["B6-S02"]

    def _via_get_sign(line_entry):
        result = {
            "front": [line_entry] * 4,
            "back": [line_entry] * 4,
            "waxed": False,
        }
        conn = FakeConn({"world.getSign": result})
        return Minecraft(conn).getSign(0, 0, 0).front[0]

    assert _via_get_sign(cases["from_string_shorthand"]) == _line_value(
        cases["from_string_shorthand"]
    )
    assert _via_get_sign(cases["from_object_named_color"]) == _line_value(
        cases["from_object_named_color"]
    )

    unsorted_case = cases["from_object_unsorted_input"]
    # Input tolerates any decoration order (no client-side sort).
    spec = line_spec(
        {
            "text": unsorted_case["result"]["text"],
            "color": unsorted_case["result"]["color"],
            "decorations": unsorted_case["input_decorations"],
        }
    )
    assert spec["decorations"] == unsorted_case["input_decorations"]
    # Canonical output decode still requires the sorted result.
    assert _via_get_sign(unsorted_case["result"]) == _line_value(
        unsorted_case["result"]
    )


# ---------------------------------------------------------------------------
# B6-S03 / B6-S04 / B6-S05 -- get / set / updateSignLine wire shape
# ---------------------------------------------------------------------------


def test_b6_s03_get_sign_sends_and_decodes_fixture_shape():
    case = SIGN_FIXTURE["get_sign"]["B6-S03"]
    conn = FakeConn({"world.getSign": case["result"]})
    sign = Minecraft(conn).getSign(*case["params"])
    assert conn.calls == [("world.getSign", case["params"])]
    assert isinstance(sign, SignValue)
    assert sign.waxed == case["result"]["waxed"]
    assert sign.front == tuple(_line_value(entry) for entry in case["result"]["front"])
    assert sign.back == tuple(_line_value(entry) for entry in case["result"]["back"])


def test_b6_s04_set_sign_sends_fixture_params():
    case = SIGN_FIXTURE["set_sign"]["B6-S04"]
    conn = FakeConn({"world.setSign": case["result"]})
    x, y, z, faces = case["params"]
    result = Minecraft(conn).setSign(x, y, z, front=faces.get("front"), back=faces.get("back"))
    assert result is None
    assert conn.calls == [("world.setSign", case["params"])]


def test_b6_s05_update_sign_line_sends_fixture_params():
    case = SIGN_FIXTURE["update_sign_line"]["B6-S05"]
    conn = FakeConn({"world.updateSignLine": case["result"]})
    result = Minecraft(conn).updateSignLine(*case["params"])
    assert result is None
    assert conn.calls == [("world.updateSignLine", case["params"])]


# ---------------------------------------------------------------------------
# B6-S06 -- invalid_params / invalid_property_value client-side rejection
# ---------------------------------------------------------------------------


def test_b6_s06_invalid_params_rejected_before_sending():
    cases = {c["case"]: c for c in SIGN_FIXTURE["invalid_params"]["B6-S06"]}
    conn = FakeConn({"world.updateSignLine": None, "world.setSign": None})

    # face_out_of_enum
    bad = cases["face_out_of_enum"]
    _, _, _, face, line_index, line = bad["params"]
    try:
        Minecraft(conn).updateSignLine(1, 2, 3, face, line_index, line)
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-enum face was accepted")

    # line_index_out_of_range
    bad = cases["line_index_out_of_range"]
    _, _, _, face, line_index, line = bad["params"]
    try:
        Minecraft(conn).updateSignLine(1, 2, 3, face, line_index, line)
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range line_index was accepted")

    # unknown_color_token
    bad = cases["unknown_color_token"]
    faces = bad["params"][3]
    try:
        Minecraft(conn).setSign(1, 2, 3, front=faces["front"])
    except ValueError:
        pass
    else:
        raise AssertionError("unknown color token was accepted")

    # unknown_decoration_token
    bad = cases["unknown_decoration_token"]
    _, _, _, face, line_index, line = bad["params"]
    try:
        Minecraft(conn).updateSignLine(1, 2, 3, face, line_index, line)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown decoration token was accepted")

    # wrong_param_count has no client-side equivalent: Minecraft.updateSignLine
    # requires all 6 arguments, so this wire shape cannot be constructed by
    # this client in the first place (Python raises its own TypeError).
    assert "wrong_param_count" in cases
    try:
        Minecraft(conn).updateSignLine(*cases["wrong_param_count"]["params"])
    except TypeError:
        pass
    else:
        raise AssertionError(
            "updateSignLine accepted a call with too few arguments"
        )

    assert conn.calls == []


# ---------------------------------------------------------------------------
# B6-S07 -- stable error reasons propagate unchanged
# ---------------------------------------------------------------------------


def _raise_reasoned_error(reason):
    def _response(_params):
        raise McRpcError(-32000, reason, {"reason": reason})

    return _response


def test_b6_s07_error_reasons_propagate_unchanged():
    cases = SIGN_FIXTURE["errors"]["B6-S07"]

    not_a_sign = cases["not_a_sign"]
    conn = FakeConn({"world.getSign": _raise_reasoned_error(not_a_sign["reason"])})
    try:
        Minecraft(conn).getSign(*not_a_sign["params"])
    except McRemoteError as exc:
        assert exc.reason == not_a_sign["reason"]
    else:
        raise AssertionError("not_a_sign error was swallowed")

    sign_waxed = cases["sign_waxed"]
    conn = FakeConn(
        {"world.updateSignLine": _raise_reasoned_error(sign_waxed["reason"])}
    )
    try:
        Minecraft(conn).updateSignLine(*sign_waxed["params"])
    except McRemoteError as exc:
        assert exc.reason == sign_waxed["reason"]
    else:
        raise AssertionError("sign_waxed error was swallowed")

    sign_update_failed = cases["sign_update_failed"]
    x, y, z, faces = sign_update_failed["params"]
    conn = FakeConn(
        {"world.setSign": _raise_reasoned_error(sign_update_failed["reason"])}
    )
    try:
        Minecraft(conn).setSign(
            x, y, z, front=faces.get("front"), back=faces.get("back")
        )
    except McRemoteError as exc:
        assert exc.reason == sign_update_failed["reason"]
    else:
        raise AssertionError("sign_update_failed error was swallowed")


# ---------------------------------------------------------------------------
# Supplementary defensive coverage (not tied to a single B6-* case ID)
# ---------------------------------------------------------------------------


def test_poll_events_rejects_pickaxe_poke_missing_item():
    fixture_poke = dict(EVENTS_FIXTURE["poll_result"]["events"][0])
    del fixture_poke["item"]
    result = {
        "events": [fixture_poke],
        "through_sequence": 1,
        "latest_sequence": 1,
        "filtered_out": 0,
        "overflow_dropped_total": 0,
        "capacity_dropped_total": 0,
        "explicitly_discarded_total": 0,
    }
    conn = FakeConn({"events.poll": result})
    try:
        Minecraft(conn).pollEvents()
    except McRemoteError:
        pass
    else:
        raise AssertionError("pickaxe_poke event without item was accepted")


def test_get_sign_rejects_decorations_out_of_canonical_order():
    bad_line = {"text": "x", "color": "black", "decorations": ["italic", "bold"]}
    result = {
        "front": [bad_line] * 4,
        "back": [bad_line] * 4,
        "waxed": False,
    }
    conn = FakeConn({"world.getSign": result})
    try:
        Minecraft(conn).getSign(0, 0, 0)
    except McRemoteError:
        pass
    else:
        raise AssertionError("out-of-order decorations were accepted")


def test_set_sign_requires_at_least_one_face():
    conn = FakeConn({"world.setSign": None})
    try:
        Minecraft(conn).setSign(0, 64, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("setSign with neither face was accepted")
    assert conn.calls == []


def test_set_sign_rejects_a_face_without_exactly_four_lines():
    conn = FakeConn({"world.setSign": None})
    try:
        Minecraft(conn).setSign(0, 64, 0, front=["a", "b", "c"])
    except TypeError:
        pass
    else:
        raise AssertionError("a 3-line face was accepted")
    assert conn.calls == []


def test_set_sign_rejects_non_null_result():
    conn = FakeConn({"world.setSign": {"unexpected": "value"}})
    try:
        Minecraft(conn).setSign(0, 64, 0, front=["a", "b", "c", "d"])
    except McRemoteError:
        pass
    else:
        raise AssertionError("non-null setSign result was accepted")


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
