"""Python component tests for SSOT wire §5.8.3 at fc208b8b.

These are local tests, not protocol-owner shared fixture consumption.
"""

import copy
import importlib.util
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from mc_remote.connection import McRemoteError, McRpcError
from mc_remote.minecraft import BuildMode, EntityHandle, Minecraft, PROTOCOL
from mc_remote.observer import PythonObserverSource, validate_snapshot


HANDLE = "mcr_eh_b8-current"
POSE = {"dimension": "minecraft:the_end", "pos": [1.235, -2.346, 3], "yaw": -180, "pitch": 45.67}
NEARBY = [
    {"handle": HANDLE, "type": "minecraft:armor_stand", "pos": [1.235, 2, 3.457]},
    {"handle": "mcr_eh_b8-other", "type": "minecraft:pig", "pos": [1.235, 2, 3.457]},
]
DUST = {"particle_id": "minecraft:dust", "receiver": "self", "data": {"color": [0, 160, 255], "size": 1}}
BLOCK = {"particle_id": "minecraft:block", "data": {"block_id": "oak_log", "state": {"axis": "y"}}}
PARTICLE_PREFIX = [1.23456, 2.34567, 3.45678, 0, 0, 0]


class FakeConn:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def rpc(self, method, params):
        self.calls.append((method, params))
        if isinstance(self.response, Exception):
            raise self.response
        return copy.deepcopy(self.response)


def test_b8_protocol_and_package_fold():
    assert PROTOCOL == "23.2.0"
    project = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert 'version = "2320.0.0b8"' in project


@pytest.mark.parametrize("radius,limit,result", [(0, 1, []), (64, 64, NEARBY), (2.34567, 2, NEARBY)])
def test_nearby_preserves_server_order_and_numbers(radius, limit, result):
    conn = FakeConn(result)
    mc = Minecraft(conn, build_mode=BuildMode.FAST)
    entities = mc.getNearbyEntities(1.23456, -2.34567, 3.45678, radius, limit)
    assert conn.calls == [("world.getNearbyEntities", [1.23456, -2.34567, 3.45678, radius, limit])]
    assert isinstance(entities, tuple)
    assert [(item.handle, item.type, item.pos) for item in entities] == [
        (item["handle"], item["type"], tuple(item["pos"])) for item in result
    ]
    if entities:
        assert isinstance(entities[0].handle, EntityHandle)
        with pytest.raises(FrozenInstanceError):
            entities[0].type = "changed"


@pytest.mark.parametrize("radius,limit", [(-1, 1), (64.001, 1), (math.nan, 1), (True, 1), (1, 0), (1, 65), (1, 1.5), (1, True)])
def test_nearby_rejects_invalid_bounds_without_rpc(radius, limit):
    conn = FakeConn([])
    with pytest.raises(ValueError):
        Minecraft(conn).getNearbyEntities(0, 0, 0, radius, limit)
    assert conn.calls == []


@pytest.mark.parametrize("result", [None, {}, [None], [{**NEARBY[0], "type": "pig"}], [{**NEARBY[0], "handle": "mceh_old"}], [{**NEARBY[0], "pos": [1, 2]}], [{**NEARBY[0], "pos": [True, 2, 3]}], [{**NEARBY[0], "extra": 1}], NEARBY])
def test_nearby_rejects_malformed_or_over_limit_server_results(result):
    with pytest.raises(McRemoteError):
        Minecraft(FakeConn(result)).getNearbyEntities(0, 0, 0, 16, 1)


def test_entity_pose_sends_original_input_and_returns_post_read_without_context_change():
    conn = FakeConn(POSE)
    mc = Minecraft(conn)
    context = (mc._dimension, tuple(mc._origin))
    assert mc.getEntityPose(HANDLE) == POSE
    assert mc.setEntityPose(HANDLE, "the_end", 1.23456, -2.34567, 3, 540, 45.6789) == POSE
    assert conn.calls == [
        ("entity.getPose", [HANDLE]),
        ("entity.setPose", [HANDLE, "the_end", 1.23456, -2.34567, 3, 540, 45.6789]),
    ]
    assert (mc._dimension, tuple(mc._origin)) == context


@pytest.mark.parametrize("pitch", [-90, 90])
def test_entity_pose_pitch_endpoints(pitch):
    conn = FakeConn({**POSE, "pitch": pitch})
    assert Minecraft(conn).setEntityPose(HANDLE, "overworld", 0, 0, 0, 725.12345, pitch)["pitch"] == pitch
    assert conn.calls[0][1][-2:] == [725.12345, pitch]


@pytest.mark.parametrize("values", [(0, 0, 0, math.inf, 0), (math.nan, 0, 0, 0, 0), (True, 0, 0, 0, 0), (0, 0, 0, 0, 90.01)])
def test_entity_pose_invalid_inputs_do_not_teleport(values):
    conn = FakeConn(POSE)
    with pytest.raises(ValueError):
        Minecraft(conn).setEntityPose(HANDLE, "overworld", *values)
    assert conn.calls == []


@pytest.mark.parametrize("result", [None, {**POSE, "dimension": "the_end"}, {**POSE, "pos": [1, 2]}, {**POSE, "yaw": 180}, {**POSE, "pitch": -90.01}, {**POSE, "yaw": True}, {**POSE, "pitch": math.nan}, {**POSE, "extra": 1}])
def test_entity_pose_malformed_results_raise(result):
    with pytest.raises(McRemoteError):
        Minecraft(FakeConn(result)).getEntityPose(HANDLE)


def test_entity_remove_requires_null_and_opaque_strings_go_to_server():
    conn = FakeConn(None)
    assert Minecraft(conn).removeEntity("invalid-or-stale") is None
    assert conn.calls == [("entity.remove", ["invalid-or-stale"])]
    with pytest.raises(McRemoteError):
        Minecraft(FakeConn(True)).removeEntity(HANDLE)
    for call in (lambda mc: mc.getEntityPose(123), lambda mc: mc.setEntityPose(123, "overworld", 0, 0, 0, 0, 0), lambda mc: mc.removeEntity(123)):
        conn = FakeConn(None)
        with pytest.raises(TypeError):
            call(Minecraft(conn))
        assert conn.calls == []


@pytest.mark.parametrize("spec", ["minecraft:flame", {"particle_id": "minecraft:flame"}, DUST, BLOCK, {"particle_id": "minecraft:dust", "data": None}])
@pytest.mark.parametrize("force", [None, True, False])
def test_particle_specs_preserve_omission_null_force_and_request_mode(spec, force):
    conn = FakeConn(1)
    mc = Minecraft(conn, build_mode=BuildMode.FAST)
    args = [*PARTICLE_PREFIX, spec, 0, 1]
    if force is not None:
        args.append(force)
    assert mc.spawnParticle(*args) == 1
    assert conn.calls == [("world.spawnParticle", args)]
    if isinstance(spec, dict):
        assert conn.calls[0][1][6] is not spec


def test_particle_mapping_states_are_copied_to_json_and_inputs_are_unchanged():
    state = MappingProxyType({"axis": "y"})
    spec = {"particle_id": "minecraft:block", "data": {"block_id": "oak_log", "state": state}}
    conn = FakeConn(1)
    Minecraft(conn).spawnParticle(*PARTICLE_PREFIX, spec, 0, 1)
    assert conn.calls[0][1][6] == BLOCK
    assert conn.calls[0][1][6]["data"]["state"] is not state


@pytest.mark.parametrize("method,params,invoke", [
    ("world.getNearbyEntities", [0, 0, 0, 16, 8], lambda mc: mc.getNearbyEntities(0, 0, 0, 16, 8)),
    ("entity.getPose", [HANDLE], lambda mc: mc.getEntityPose(HANDLE)),
    ("entity.setPose", [HANDLE, "the_end", 0, 0, 0, 540, 0], lambda mc: mc.setEntityPose(HANDLE, "the_end", 0, 0, 0, 540, 0)),
    ("entity.remove", [HANDLE], lambda mc: mc.removeEntity(HANDLE)),
    ("world.spawnParticle", [*PARTICLE_PREFIX, DUST, 0, 1], lambda mc: mc.spawnParticle(*PARTICLE_PREFIX, DUST, 0, 1)),
])
@pytest.mark.parametrize("reason", ["auth_required", "permission_denied", "build_denied", "entity_not_found", "entity_unavailable", "entity_dimension_changed", "entity_capacity_exhausted", "teleport_failed", "particle_data_required", "particle_data_unsupported", "invalid_params", "backpressure", "work_limit_exceeded", "internal_error"])
def test_b8_server_errors_are_preserved_without_retry(method, params, invoke, reason):
    error = McRpcError(-32000, reason, {"reason": reason, "detail": "server fact"})
    conn = FakeConn(error)
    with pytest.raises(McRpcError) as caught:
        invoke(Minecraft(conn))
    assert caught.value is error
    assert conn.calls == [(method, params)]


def test_particle_compound_errors_are_left_for_server_priority():
    # Unknown ID + bad data + self remains a single request. No client auth gate.
    spec = {"particle_id": "minecraft:no_such_particle", "data": None, "receiver": "self"}
    error = McRpcError(-32602, "unknown_particle", {"reason": "unknown_particle"})
    conn = FakeConn(error)
    with pytest.raises(McRpcError) as caught:
        Minecraft(conn).spawnParticle(*PARTICLE_PREFIX, spec, 0, 1)
    assert caught.value.reason == "unknown_particle"
    assert conn.calls == [("world.spawnParticle", [*PARTICLE_PREFIX, spec, 0, 1])]


def observer_source():
    frames = []
    source = PythonObserverSource(frames.append, alias_factory=lambda: "MIND-STORM-000028")
    source.observe_request("hello", {"protocol": PROTOCOL, "auth": {"token": "secret-token"}}, 1)
    source.observe_result("hello", {
        "protocol": PROTOCOL, "mc_version": "1.21.11", "supported_mc_versions": ["1.21.11"],
        "catalogHash": None, "dimension": "minecraft:overworld", "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
    }, 1)
    frames.clear()
    return source, frames


def test_b8_observer_method_shapes_and_particle_data_in_snapshot():
    source, frames = observer_source()
    exchanges = [
        ("world.getNearbyEntities", [0, 0, 0, 64, 64], NEARBY),
        ("entity.getPose", [HANDLE], POSE),
        ("entity.setPose", [HANDLE, "the_end", 1.23456, 2, 3, 540, -90], POSE),
        ("entity.remove", [HANDLE], None),
        ("world.spawnParticle", [*PARTICLE_PREFIX, DUST, 0, 1, False], 1),
        ("world.spawnParticle", [*PARTICLE_PREFIX, BLOCK, 0, 1], 1),
        ("world.spawnParticle", [*PARTICLE_PREFIX, {"particle_id": "minecraft:flame"}, 0, 1], 1),
    ]
    for request_id, (method, params, result) in enumerate(exchanges, start=2):
        source.observe_request(method, params, request_id)
        source.observe_result(method, result, request_id)
    parsed = validate_snapshot(source.snapshot(frames))["streams"][0]["frames"]
    assert [(frame["method"], frame["payload"]) for frame in parsed] == [
        item for method, params, result in exchanges
        for item in ((method, {"params": params}), (method, {"result": result}))
    ]


@pytest.mark.parametrize("data", [
    {"color": [0, 255, 0], "size": 0.01},
    {"color": [255, 0, 255], "size": 4},
])
def test_observer_dust_range_endpoints(data):
    source, frames = observer_source()
    spec = {"particle_id": "minecraft:dust", "data": data}
    source.observe_request("world.spawnParticle", [*PARTICLE_PREFIX, spec, 0, 1], 2)
    assert frames[0]["payload"]["params"][6] == spec


@pytest.mark.parametrize("data", [None, {"color": [256, 0, 0], "size": 1}, {"color": [True, 0, 0], "size": 1}, {"color": [0, 0, 0], "size": 0}, {"color": [0, 0, 0], "size": 4.01}, {"color": [0, 0, 0], "size": 1, "token": "secret"}])
def test_observer_drops_invalid_particle_data_and_keeps_server_error(data):
    source, frames = observer_source()
    spec = {"particle_id": "minecraft:dust", "receiver": "self", "data": data}
    source.observe_request("world.spawnParticle", [*PARTICLE_PREFIX, spec, 0, 1], 2)
    assert frames == []
    source.observe_error("world.spawnParticle", McRpcError(-32602, "invalid_params", {"reason": "invalid_params", "token": "secret"}), 2)
    assert frames[0]["payload"]["error"]["data"] == {"reason": "invalid_params"}


def test_observer_drops_unapproved_fields_in_nested_b8_objects():
    source, frames = observer_source()
    for spec in ({**DUST, "token": "secret"}, {**BLOCK, "data": {**BLOCK["data"], "token": "secret"}}):
        source.observe_request("world.spawnParticle", [*PARTICLE_PREFIX, spec, 0, 1], 2)
    source.observe_result("world.getNearbyEntities", [{**NEARBY[0], "uuid": "private"}], 3)
    assert frames == []
    source.observe_result("entity.getPose", {**POSE, "uuid": "private"}, 4)
    assert frames[0]["payload"]["result"] == POSE


def test_particle_graph_is_bounded_self_only_and_does_not_change_world_blocks():
    path = Path(__file__).parents[1] / "examples" / "particle_graph.py"
    spec = importlib.util.spec_from_file_location("b8_particle_graph", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = FakeConn(1)
    module.draw_graph(Minecraft(conn))
    assert len(conn.calls) == 81
    for method, params in conn.calls:
        assert method == "world.spawnParticle"
        assert -4 <= params[0] <= 4 and 1 <= params[1] <= 5 and -4 <= params[2] <= 4
        assert params[6] == {**DUST, "data": {"color": [64, 160, 255], "size": 1.0}}
