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

from test_b8 import FakeConn, observer_source


ROOT = Path(__file__).parent / "fixtures"
FIXTURE_PATH = ROOT / "entity-particle-v23.2.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())
SOURCE = json.loads((ROOT / "entity-particle-v23.2.source.json").read_text())


def test_owner_fixture_exact_identity_and_59_case_inventory():
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == SOURCE["sha256"]
    assert SOURCE["commit"] == "0735a9c957d069f719bee9c91e8be0f9322f4920"
    assert FIXTURE["protocol"] == PROTOCOL == "23.2.0"
    assert FIXTURE["knowledge_contract"] == SOURCE["knowledge_contract"]
    assert FIXTURE["knowledge_contract"]["decision"] == "2026-09-30-01"
    ids = [case["id"] for section, key in (
        ("nearby", "cases"), ("nearby", "handle_transaction_cases"),
        ("entity_lifecycle", "cases"), ("particle_stage_2", "cases"),
    ) for case in FIXTURE[section][key]]
    assert len(ids) == len(set(ids)) == 59
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
