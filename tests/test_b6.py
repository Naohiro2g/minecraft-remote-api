"""Protocol 23.0.0 b6 tests: pickaxe_poke event and the sign slice.

protocol 23 replaces the b5 ``block_right_click`` event with ``pickaxe_poke``
and adds ``world.getSign`` / ``world.setSign`` / ``world.updateSignLine``
(DECISIONS 2026-08-26-03..06); everything else carried over from b5 is
exercised in test_b5.py and is not repeated here.
"""

from mc_remote.b5_values import ChatPostedEvent, PickaxePokeEvent, ProjectileHitEvent
from mc_remote.connection import McRemoteError
from mc_remote.minecraft import Minecraft, PROTOCOL
from mc_remote.sign_value import LineValue, SignValue


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


def test_protocol_pins_23_0_0():
    assert PROTOCOL == "23.0.0"


def test_poll_events_decodes_pickaxe_poke():
    handle = "mcr_eh_" + "B" * 22
    valid = {
        "events": [
            {
                "sequence": 1,
                "type": "pickaxe_poke",
                "dimension": "minecraft:overworld",
                "origin": [0, 64, 0],
                "pos": [1, 65, 2],
                "face": "UP",
                "block": {"block_id": "minecraft:stone", "state": {}},
                "hand": "HAND",
                "item": "minecraft:diamond_pickaxe",
            },
            {
                "sequence": 2,
                "type": "chat_posted",
                "dimension": "minecraft:overworld",
                "origin": [0, 64, 0],
                "message": "hello",
            },
            {
                "sequence": 3,
                "type": "projectile_hit",
                "dimension": "minecraft:overworld",
                "origin": [0, 64, 0],
                "projectile": "minecraft:arrow",
                "pos": [1.25, 65.5, 2.75],
                "target": {"kind": "entity", "handle": handle},
            },
        ],
        "through_sequence": 3,
        "latest_sequence": 3,
        "filtered_out": 0,
        "overflow_dropped_total": 2,
        "capacity_dropped_total": 1,
        "explicitly_discarded_total": 0,
    }
    responses = [dict(valid, through_sequence=-1), valid, dict(valid, events=[])]

    def response(_params):
        return responses.pop(0)

    conn = FakeConn({"events.poll": response})
    mc = Minecraft(conn)
    try:
        mc.pollEvents(max_events=10)
    except McRemoteError:
        pass
    else:
        raise AssertionError("malformed cursor result was accepted")
    batch = mc.pollEvents(max_events=10)
    poke = batch.events[0]
    assert isinstance(poke, PickaxePokeEvent)
    assert poke.item == "minecraft:diamond_pickaxe"
    assert isinstance(batch.events[1], ChatPostedEvent)
    assert isinstance(batch.events[2], ProjectileHitEvent)
    assert batch.loss_totals == {
        "overflow": 2,
        "capacity": 1,
        "explicitly_discarded": 0,
    }
    mc.pollEvents(max_events=10)
    assert conn.calls == [
        ("events.poll", [0, {"max_events": 10}]),
        ("events.poll", [0, {"max_events": 10}]),
        ("events.poll", [3, {"max_events": 10}]),
    ]


def test_poll_events_rejects_pickaxe_poke_missing_item():
    result = {
        "events": [
            {
                "sequence": 1,
                "type": "pickaxe_poke",
                "dimension": "minecraft:overworld",
                "origin": [0, 64, 0],
                "pos": [1, 65, 2],
                "face": "UP",
                "block": {"block_id": "minecraft:stone", "state": {}},
                "hand": "HAND",
            }
        ],
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


def test_poll_events_rejects_legacy_block_right_click_type():
    result = {
        "events": [
            {
                "sequence": 1,
                "type": "block_right_click",
                "dimension": "minecraft:overworld",
                "origin": [0, 64, 0],
                "pos": [1, 65, 2],
                "face": "UP",
                "block": {"block_id": "minecraft:stone", "state": {}},
                "hand": "HAND",
            }
        ],
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
        raise AssertionError(
            "protocol 21/22 block_right_click type was accepted under protocol 23"
        )


def _line_value(text, color="black", decorations=()):
    return {"text": text, "color": color, "decorations": list(decorations)}


def test_get_sign_decodes_canonical_lines_and_waxed():
    result = {
        "front": [
            _line_value("Welcome", color="gold", decorations=["bold", "italic"]),
            _line_value(""),
            _line_value(""),
            _line_value("Home"),
        ],
        "back": [_line_value("")] * 4,
        "waxed": True,
    }
    conn = FakeConn({"world.getSign": result})
    sign = Minecraft(conn).getSign(1, 65, 2)
    assert conn.calls == [("world.getSign", [1, 65, 2])]
    assert isinstance(sign, SignValue)
    assert sign.waxed is True
    assert sign.front[0] == LineValue(
        text="Welcome", color="gold", decorations=("bold", "italic")
    )
    assert sign.front[1] == LineValue(text="", color="black", decorations=())
    assert sign.back == (LineValue(text="", color="black", decorations=()),) * 4


def test_get_sign_rejects_decorations_out_of_canonical_order():
    result = {
        "front": [_line_value("x", decorations=["italic", "bold"])]
        + [_line_value("")] * 3,
        "back": [_line_value("")] * 4,
        "waxed": False,
    }
    conn = FakeConn({"world.getSign": result})
    try:
        Minecraft(conn).getSign(0, 64, 0)
    except McRemoteError:
        pass
    else:
        raise AssertionError("out-of-order decorations were accepted")


def test_set_sign_replaces_only_the_specified_face():
    conn = FakeConn({"world.setSign": None})
    Minecraft(conn).setSign(
        1,
        65,
        2,
        front=["a", {"text": "b", "color": "red", "decorations": ["bold"]}, "c", "d"],
    )
    assert conn.calls == [
        (
            "world.setSign",
            [
                1,
                65,
                2,
                {
                    "front": [
                        "a",
                        {"text": "b", "color": "red", "decorations": ["bold"]},
                        "c",
                        "d",
                    ]
                },
            ],
        )
    ]


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


def test_set_sign_rejects_unknown_color_or_decoration_token():
    conn = FakeConn({"world.setSign": None})
    for bad_line in (
        {"text": "x", "color": "invisible"},
        {"text": "x", "decorations": ["flashing"]},
    ):
        try:
            Minecraft(conn).setSign(0, 64, 0, front=[bad_line, "b", "c", "d"])
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid sign style token accepted: {bad_line!r}")
    assert conn.calls == []


def test_set_sign_rejects_non_null_result():
    conn = FakeConn({"world.setSign": {"unexpected": "value"}})
    try:
        Minecraft(conn).setSign(0, 64, 0, front=["a", "b", "c", "d"])
    except McRemoteError:
        pass
    else:
        raise AssertionError("non-null setSign result was accepted")


def test_update_sign_line_patches_one_line():
    conn = FakeConn({"world.updateSignLine": None})
    Minecraft(conn).updateSignLine(1, 65, 2, "front", 2, "hello")
    assert conn.calls == [
        ("world.updateSignLine", [1, 65, 2, "front", 2, "hello"])
    ]


def test_update_sign_line_rejects_invalid_face_or_index():
    conn = FakeConn({"world.updateSignLine": None})
    for face, line_index in (("side", 0), ("front", -1), ("front", 4), ("front", 1.5)):
        try:
            Minecraft(conn).updateSignLine(0, 64, 0, face, line_index, "x")
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid face/index accepted: {face!r}, {line_index!r}")
    assert conn.calls == []


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
