"""Protocol 23.1.0 b7 direction/full-lightning fixture projection tests."""

import hashlib
import json
import math
from pathlib import Path

from mc_remote.connection import McRemoteError, McRpcError
from mc_remote.direction_value import (
    DIRECTION_NORM_TOLERANCE,
    decode_direction_value,
)
from mc_remote.minecraft import Minecraft, PROTOCOL
from mc_remote.observer import PythonObserverSource, validate_snapshot


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "direction-lightning-v23.1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
FIXTURE_SHA256 = "586d24bf40136eec31f1827f23ef5b317f15100a17a635d7fe9f165e0af40dce"


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


def _all_case_ids(value):
    ids = []
    if isinstance(value, dict):
        if isinstance(value.get("id"), str):
            ids.append(value["id"])
        for item in value.values():
            ids.extend(_all_case_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.extend(_all_case_ids(item))
    return ids


def _reason_error(reason, code=-32000):
    def raise_error(_params):
        raise McRpcError(code, reason, {"reason": reason})

    return raise_error


def test_owner_fixture_identity_protocol_and_93_case_ledger():
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    assert FIXTURE["schema"] == "mcremote.direction-lightning.v23.1"
    assert FIXTURE["protocol"] == PROTOCOL == "23.1.0"
    assert FIXTURE["knowledge_contract"] == {
        "commit": "2bddadd1114e05a9076911de83aec0836df36345",
        "path": "10-protocol/wire-format-design_ja.md",
        "section": "5.8.2",
    }
    ids = _all_case_ids(FIXTURE)
    assert len(ids) == len(set(ids)) == 93


def test_hello_permission_snapshot_remains_an_uninterpreted_server_fact():
    case = FIXTURE["session_admission"]["hello_snapshot_cases"][0]
    hello = {
        "protocol": "23.1.0",
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalogHash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": case["hello_permissions"],
    }
    lightning_method = FIXTURE["methods"]["strike_lightning"]
    conn = FakeConn({"hello": hello, lightning_method: None})
    mc = Minecraft(conn)

    assert mc.hello() == hello
    assert mc.permissions == case["hello_permissions"]
    assert mc.strikeLightning(1, 2, 3) is None
    assert conn.calls == [
        ("hello", {"protocol": "23.1.0"}),
        (lightning_method, [1, 2, 3]),
    ]
    assert FIXTURE["session_admission"]["command_permission_recheck"] is False


def test_direction_decoder_projects_fixture_results_without_recanonicalizing():
    for case in FIXTURE["direction"]["valid_vectors"]:
        result = case["result"]
        direction = decode_direction_value(result, case["id"])
        assert direction == tuple(result)
        assert isinstance(direction, tuple)
        assert abs(math.hypot(*direction) - 1.0) <= DIRECTION_NORM_TOLERANCE


def test_direction_four_methods_send_exact_fixture_shapes():
    methods = FIXTURE["methods"]
    cases = {case["id"]: case for case in FIXTURE["direction"]["method_cases"]}
    set_vector = FIXTURE["direction"]["valid_vectors"][8]
    handle = cases["B7-D35"]["params"][0]
    responses = {
        methods["player_get_direction"]: cases["B7-D30"]["result"],
        methods["player_set_direction"]: set_vector["result"],
        methods["entity_get_direction"]: cases["B7-D35"]["result"],
        methods["entity_set_direction"]: set_vector["result"],
    }
    conn = FakeConn(responses)
    mc = Minecraft(conn)

    assert mc.getDirection() == tuple(cases["B7-D30"]["result"])
    assert mc.setDirection(*set_vector["input"]) == tuple(set_vector["result"])
    assert mc.getEntityDirection(handle) == tuple(cases["B7-D35"]["result"])
    assert mc.setEntityDirection(handle, *set_vector["input"]) == tuple(
        set_vector["result"]
    )
    assert conn.calls == [
        (methods["player_get_direction"], []),
        (methods["player_set_direction"], set_vector["input"]),
        (methods["entity_get_direction"], [handle]),
        (methods["entity_set_direction"], [handle, *set_vector["input"]]),
    ]


def test_direction_inputs_preserve_extreme_values_and_leave_zero_to_server():
    methods = FIXTURE["methods"]
    vectors = {case["id"]: case for case in FIXTURE["direction"]["valid_vectors"]}
    seen = []

    def canonical_result(params):
        seen.append(params)
        return [1, 0, 0]

    conn = FakeConn({methods["player_set_direction"]: canonical_result})
    mc = Minecraft(conn)
    for case_id in ("B7-D11", "B7-D12"):
        mc.setDirection(*vectors[case_id]["input"])
    assert seen == [vectors["B7-D11"]["input"], vectors["B7-D12"]["input"]]

    zero = FIXTURE["direction"]["invalid_vectors"][0]
    conn = FakeConn(
        {methods["player_set_direction"]: _reason_error(zero["reason"], -32602)}
    )
    try:
        Minecraft(conn).setDirection(*zero["params"])
    except McRpcError as exc:
        assert exc.reason == "zero_direction"
        assert exc.code == -32602
    else:
        raise AssertionError("zero_direction server error was swallowed")
    assert conn.calls == [(methods["player_set_direction"], zero["params"])]


def test_direction_rejects_non_finite_input_and_invalid_server_results():
    method = FIXTURE["methods"]["player_set_direction"]
    conn = FakeConn({method: [1, 0, 0]})
    mc = Minecraft(conn)
    for invalid in (True, "1", math.nan, math.inf, -math.inf):
        try:
            mc.setDirection(invalid, 0, 1)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid direction input accepted: {invalid!r}")
    assert conn.calls == []

    for result in ([1, 0], [1, 0, 0, 0], [True, 0, 0], [2, 0, 0]):
        conn = FakeConn({FIXTURE["methods"]["player_get_direction"]: result})
        try:
            Minecraft(conn).getDirection()
        except McRemoteError:
            pass
        else:
            raise AssertionError(f"invalid direction result accepted: {result!r}")


def test_entity_handles_remain_unparsed_and_server_reasons_are_preserved():
    method = FIXTURE["methods"]["entity_get_direction"]
    for case in FIXTURE["handles"]["unresolved_strings"]:
        conn = FakeConn({method: _reason_error(case["reason"])})
        try:
            Minecraft(conn).getEntityDirection(case["handle"])
        except McRpcError as exc:
            assert exc.reason == case["reason"]
        else:
            raise AssertionError(f"{case['id']} error was swallowed")
        assert conn.calls == [(method, [case["handle"]])]

    conn = FakeConn({method: [1, 0, 0]})
    try:
        Minecraft(conn).getEntityDirection(123)
    except TypeError:
        pass
    else:
        raise AssertionError("non-string entity handle was accepted")
    assert conn.calls == []


def test_new_server_reasons_project_unchanged_without_retry():
    methods = FIXTURE["methods"]
    method_params = {
        methods["player_set_direction"]: [1, 0, 0],
        methods["entity_set_direction"]: ["mcr_eh_fixture-current", 1, 0, 0],
        methods["strike_lightning"]: [1, 2, 3],
    }
    reasons = {
        "auth_required",
        "zero_direction",
        "player_offline",
        "permission_denied",
        "entity_not_found",
        "entity_unavailable",
        "entity_dimension_changed",
        "internal_error",
        "build_denied",
        "backpressure",
        "work_limit_exceeded",
    }
    for reason in reasons:
        method = (
            methods["entity_set_direction"]
            if reason.startswith("entity_")
            else methods["strike_lightning"]
            if reason in {"build_denied", "work_limit_exceeded"}
            else methods["player_set_direction"]
        )
        conn = FakeConn({method: _reason_error(reason)})
        mc = Minecraft(conn)
        try:
            if method == methods["entity_set_direction"]:
                mc.setEntityDirection(*method_params[method])
            elif method == methods["strike_lightning"]:
                mc.strikeLightning(*method_params[method])
            else:
                mc.setDirection(*method_params[method])
        except McRpcError as exc:
            assert exc.reason == reason
        else:
            raise AssertionError(f"{reason} was swallowed")
        assert conn.calls == [(method, method_params[method])]


def test_strike_lightning_sends_exact_params_requires_null_and_has_no_effect_alias():
    case = FIXTURE["lightning"]["wire_cases"][0]
    conn = FakeConn({case["method"]: case["result"]})
    mc = Minecraft(conn)
    assert mc.strikeLightning(*case["params"]) is None
    assert conn.calls == [(case["method"], case["params"])]
    assert not hasattr(mc, "strikeLightningEffect")
    assert FIXTURE["rejected_methods"] == ["world.strikeLightningEffect"]

    conn = FakeConn({case["method"]: {"unexpected": True}})
    try:
        Minecraft(conn).strikeLightning(*case["params"])
    except McRemoteError:
        pass
    else:
        raise AssertionError("non-null lightning result was accepted")


def test_particle_builder_stage1_keeps_existing_python_surface():
    cases = FIXTURE["particle_builder_regression"]["cases"]
    for case in cases[:2]:
        conn = FakeConn(
            {FIXTURE["particle_builder_regression"]["method"]: case["result"]}
        )
        result = Minecraft(conn).spawnParticle(*case["params"])
        assert result == case["result"]
        assert conn.calls == [
            (FIXTURE["particle_builder_regression"]["method"], case["params"])
        ]


def test_observer_projects_b7_params_results_and_errors():
    frames = []
    source = PythonObserverSource(
        frames.append,
        clock=iter(range(1786118400000, 1786118400100)).__next__,
        target_id_factory=lambda: "target-python-b7",
        alias_factory=lambda: "MIND-STORM-000027",
    )
    hello = {
        "protocol": "23.1.0",
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalogHash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": FIXTURE["session_admission"]["hello_snapshot_cases"][0][
            "hello_permissions"
        ],
    }
    source.observe_request("hello", {"protocol": "23.1.0"}, 1)
    source.observe_result("hello", hello, 1)
    frames.clear()

    exchanges = [
        ("player.getDirection", [], [0, 0, 1]),
        ("player.setDirection", [1, 2, 3], [0.267261, 0.534522, 0.801784]),
        ("entity.getDirection", ["mcr_eh_fixture-current"], [1, 0, 0]),
        (
            "entity.setDirection",
            ["mcr_eh_fixture-current", 1, 2, 3],
            [0.267261, 0.534522, 0.801784],
        ),
        ("world.strikeLightning", [1.25, 2.5, -3.75], None),
    ]
    for request_id, (method, params, result) in enumerate(exchanges, start=2):
        source.observe_request(method, params, request_id)
        source.observe_result(method, result, request_id)
    source.observe_request("world.strikeLightning", [1, 2, 3], 7)
    source.observe_error(
        "world.strikeLightning",
        McRpcError(-32000, "busy", {"reason": "backpressure"}),
        7,
    )

    snapshot = validate_snapshot(source.snapshot(frames, emitted_at=1786118400200))
    assert snapshot["streams"][0]["hello"]["permissions"] == {
        "online": True,
        "offline": False,
        "build_range": 100,
    }
    projected = snapshot["streams"][0]["frames"]
    assert [frame["method"] for frame in projected] == [
        method for method, _, _ in exchanges for _ in range(2)
    ] + ["world.strikeLightning", "world.strikeLightning"]
    assert projected[-1]["payload"]["error"]["data"]["reason"] == "backpressure"


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
