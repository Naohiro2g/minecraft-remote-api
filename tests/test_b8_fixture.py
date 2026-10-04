"""Consume the protocol owner's exact B8 bytes on the Python surface.

Paper searches, WorkAdmission, and registry transactions are server claims.
These tests check request projection and response/error transport only.
"""

import hashlib
import json
from pathlib import Path

import pytest

from mc_remote.connection import McRpcError
from mc_remote.minecraft import Minecraft, PROTOCOL
from mc_remote.observer import validate_snapshot

from test_b8 import FakeConn, observer_source


ROOT = Path(__file__).parent / "fixtures"
FIXTURE_PATH = ROOT / "entity-particle-v23.2.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())
SOURCE = json.loads((ROOT / "entity-particle-v23.2.source.json").read_text())


def test_owner_fixture_exact_identity_and_111_case_inventory():
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == SOURCE["sha256"]
    assert len(FIXTURE_PATH.read_bytes()) == SOURCE["bytes"] == 36481
    assert SOURCE["repository"] == "Naohiro2g/minecraft-remote-tooling"
    assert SOURCE["commit"] == "dc1ab834183e29f2eb03059b07e99d2b463776ee"
    assert SOURCE["path"] == "packages/protocol/test/fixtures/entity-particle-v23.2.json"
    assert FIXTURE["protocol"] == PROTOCOL == "23.2.0"
    assert FIXTURE["knowledge_contract"] == SOURCE["knowledge_contract"]
    assert FIXTURE["knowledge_contract"]["decisions"] == ["2026-09-30-01", "2026-09-30-02", "2026-09-30-06"]
    ids = [case["id"] for section, key in (
        ("nearby", "cases"), ("nearby", "handle_transaction_cases"),
        ("entity_lifecycle", "cases"), ("particle_stage_2", "cases"),
        ("sound", "cases"), ("resource_ids", "cases"),
    ) for case in FIXTURE[section][key]]
    assert len(ids) == len(set(ids)) == 111
    # N19 and H03..H07 only describe server arithmetic/transaction internals.
    server_only = {"B8-N19", "B8-H03", "B8-H04", "B8-H05", "B8-H06", "B8-H07"}
    assert server_only <= set(ids)


@pytest.mark.parametrize("case", FIXTURE["nearby"]["cases"][:-1], ids=lambda case: case["id"])
def test_owner_nearby_params_results_and_server_errors(case):
    params = case["params"]
    reason = case.get("reason")
    # Cases with only server search metadata use an empty stub response; the
    # client does not implement sphere geometry, filtering, or work accounting.
    response = McRpcError(-32000, reason, {"reason": reason}) if reason else case.get("result", [])
    conn = FakeConn(response)
    mc = Minecraft(conn)
    if case["id"] in {"B8-N08", "B8-N09", "B8-N10"}:
        with pytest.raises(ValueError):
            mc.getNearbyEntities(*params)
        assert conn.calls == []
    elif reason:
        with pytest.raises(McRpcError) as caught:
            mc.getNearbyEntities(*params)
        assert caught.value is response
        assert conn.calls == [(FIXTURE["methods"]["nearby"], params)]
    else:
        result = mc.getNearbyEntities(*params)
        assert [(item.handle, item.type, item.pos) for item in result] == [
            (item["handle"], item["type"], tuple(item["pos"])) for item in response
        ]
        assert conn.calls == [(FIXTURE["methods"]["nearby"], params)]


@pytest.mark.parametrize("case", FIXTURE["nearby"]["handle_transaction_cases"][:2], ids=lambda case: case["id"])
def test_owner_nearby_handle_reuse_or_replacement_is_a_server_fact(case):
    entry = {"handle": case["result_handle"], "type": "minecraft:cow", "pos": [0, 0, 0]}
    conn = FakeConn([entry])
    result = Minecraft(conn).getNearbyEntities(0, 0, 0, 1, 1)
    assert result[0].handle == case["result_handle"]
    assert len(conn.calls) == 1


@pytest.mark.parametrize("case", FIXTURE["entity_lifecycle"]["cases"], ids=lambda case: case["id"])
def test_owner_entity_lifecycle_projection(case):
    method = case["method"]
    api = {"entity.getPose": "getEntityPose", "entity.setPose": "setEntityPose", "entity.remove": "removeEntity"}[method]
    reason = case.get("reason", case.get("first_reason"))
    response = McRpcError(-32000, reason, {"reason": reason}) if reason else case["result"]
    conn = FakeConn(response)
    call = getattr(Minecraft(conn), api)
    if reason:
        with pytest.raises(McRpcError) as caught:
            call(*case["params"])
        assert caught.value is response
    else:
        assert call(*case["params"]) == response
    assert conn.calls == [(method, case["params"])]
    if "next_reason" in case:
        error = McRpcError(-32000, case["next_reason"], {"reason": case["next_reason"]})
        conn.response = error
        with pytest.raises(McRpcError) as caught:
            call(*case["params"])
        assert caught.value is error
        assert len(conn.calls) == 2


@pytest.mark.parametrize("case", FIXTURE["particle_stage_2"]["cases"], ids=lambda case: case["id"])
def test_owner_particle_stage2_projection(case):
    params = case.get("params")
    if params is None:
        params = [1, 2, 3, 0, 0, 0, case["particle"], 0, 1]
    reason = case.get("reason")
    response = McRpcError(-32602, reason, {"reason": reason}) if reason else case["result"]
    conn = FakeConn(response)
    if case["id"] == "B8-P22":
        with pytest.raises(ValueError):
            Minecraft(conn).spawnParticle(*params)
        assert conn.calls == []
        return
    if reason:
        with pytest.raises(McRpcError) as caught:
            Minecraft(conn).spawnParticle(*params)
        assert caught.value is response
    else:
        assert Minecraft(conn).spawnParticle(*params) == response
        source, frames = observer_source()
        source.observe_request(FIXTURE["methods"]["particle"], params, 2)
        source.observe_result(FIXTURE["methods"]["particle"], response, 2)
        assert [frame["payload"] for frame in frames] == [{"params": params}, {"result": response}]
    assert conn.calls == [(FIXTURE["methods"]["particle"], params)]


@pytest.mark.parametrize("case", FIXTURE["sound"]["cases"], ids=lambda case: case["id"])
def test_owner_sound_keyword_projection(case):
    method, params = case["method"], case["params"]
    reason = case.get("reason")
    response = McRpcError(case.get("code", -32000), reason, {"reason": reason}) if reason else None
    conn = FakeConn(response)
    call = getattr(Minecraft(conn), method.removeprefix("world."))
    options = params[4] if len(params) == 5 else {}
    if case["id"] == "B8-S16":
        # Wire null is invalid, but Python's None explicitly means omission.
        conn.response = None
        call(*params[:4], **options)
        assert conn.calls == [(method, [*params[:4], {"receiver": "world"}])]
        return
    if case["id"] == "B8-S31":
        # Raw options=null is not expressible through the keyword-only API.
        with pytest.raises(TypeError):
            call(*params)
        assert conn.calls == []
        return
    if case["id"] in {"B8-S11", "B8-S14", "B8-S18", "B8-S34"}:
        with pytest.raises(ValueError):
            call(*params[:4], **options)
        assert conn.calls == []
        return
    if case["id"] in {"B8-S17", "B8-S33", "B8-S35"}:
        with pytest.raises(TypeError):
            call(*params[:4], **options)
        assert conn.calls == []
        return
    if reason:
        with pytest.raises(McRpcError) as caught:
            call(*params[:4], **options)
        assert caught.value is response
    else:
        assert call(*params[:4], **options) is None
    # The default receiver is world; volume/pitch omission is preserved.
    assert conn.calls == [(method, [*params[:4], {"receiver": "world", **options}])]


@pytest.mark.parametrize("case", FIXTURE["sound"]["cases"], ids=lambda case: case["id"])
def test_owner_sound_raw_wire_observer_projection(case):
    source, frames = observer_source()
    source.observe_request(case["method"], case["params"], 2)
    if case.get("reason") == "invalid_params" or case["id"] == "B8-S11":
        assert frames == []
    else:
        assert frames[0]["payload"] == {"params": case["params"]}
    if "reason" in case:
        source.observe_error(case["method"], McRpcError(case.get("code", -32000), case["reason"], {"reason": case["reason"]}), 2)
        assert frames[-1]["payload"]["error"]["data"] == {"reason": case["reason"]}
    else:
        source.observe_result(case["method"], None, 2)
        assert frames[-1]["payload"] == {"result": None}
    validate_snapshot(source.snapshot(frames))
    source.connection_closed()


@pytest.mark.parametrize("case", FIXTURE["resource_ids"]["cases"], ids=lambda case: case["id"])
def test_owner_resource_id_matrix_on_python_and_observer(case):
    identifier = case["input"]
    kind = case["kind"]
    if kind == "block":
        method, params, response = "world.setBlock", [0, 0, 0, {"block_id": identifier, "state": {}}], None
        invoke = lambda mc: mc.setBlock(0, 0, 0, identifier)
    elif kind == "dimension":
        method, params = "build.setDimension", [identifier]
        response = {"dimension": case.get("canonical"), "origin": [200, 0, 200]}
        invoke = lambda mc: mc.setDimension(identifier)
    elif kind == "particle":
        method, params, response = "world.spawnParticle", [0, 0, 0, 0, 0, 0, identifier, 0, 1], 1
        invoke = lambda mc: mc.spawnParticle(*params)
    elif kind == "entity":
        method, params, response = "world.spawnEntity", [0, 0, 0, identifier], "mcr_eh_fixture"
        invoke = lambda mc: mc.spawnEntity(*params)
    else:
        method, params, response = "world.playSound", [0, 0, 0, identifier], None
        invoke = lambda mc: mc.playSound(*params, receiver=None)
    conn = FakeConn(response)
    source, frames = observer_source()
    source.observe_request(method, params, 2)
    if "reason" in case:
        with pytest.raises(ValueError):
            invoke(Minecraft(conn))
        assert conn.calls == []
        assert frames == []
    else:
        invoke(Minecraft(conn))
        assert conn.calls == [(method, params)]
        assert frames[0]["payload"] == {"params": params}
        validate_snapshot(source.snapshot(frames))
    source.connection_closed()
