"""Local projection checks for knowledge 16668c5e; successor fixture pending."""

import importlib
import math
import subprocess
import sys
from types import MappingProxyType

import pytest

from mc_remote.connection import McRemoteError, McRpcError
from mc_remote.minecraft import BuildMode, Minecraft
from mc_remote.observer import PythonObserverSource, validate_snapshot
from test_b8 import FakeConn, PARTICLE_PREFIX, observer_source


@pytest.fixture(autouse=True)
def release_observer_aliases():
    before = set(PythonObserverSource._active_aliases)
    yield
    for alias in set(PythonObserverSource._active_aliases) - before:
        PythonObserverSource._active_aliases[alias].connection_closed()


@pytest.mark.parametrize("mode", list(BuildMode))
@pytest.mark.parametrize("options", [{}, {"volume": None, "pitch": None, "note": None}, {"receiver": None}, {"volume": 0, "pitch": 0.5}, {"volume": 1, "pitch": 2}, {"note": 0, "receiver": "self"}, {"note": 12}, {"note": 24}])
@pytest.mark.parametrize("method,identifier,position", [("playSound", "entity.cow.ambient", [1.23456, -2.34567, 3.45678]), ("playBlockSound", "hit", [1, -2, 3])])
def test_sound_keywords_preserve_defaults_numbers_and_omit_none(mode, options, method, identifier, position):
    conn = FakeConn(None)
    args = [*position, identifier]
    controls = {"receiver": "world", **options}
    controls = {key: value for key, value in controls.items() if value is not None}
    assert getattr(Minecraft(conn, build_mode=mode), method)(*args, **options) is None
    if controls:
        args.append(controls)
    assert conn.calls == [("world." + method, args)]


@pytest.mark.parametrize("kind", ["place", "hit", "break", "step", "fall"])
def test_block_sound_kind_is_sent_without_scene_pitch_correction(kind):
    conn = FakeConn(None)
    Minecraft(conn).playBlockSound(1.0, 2, 3, kind, note=12)
    assert conn.calls == [("world.playBlockSound", [1, 2, 3, kind, {"note": 12, "receiver": "world"}])]


@pytest.mark.parametrize("method", ["playSound", "playBlockSound"])
@pytest.mark.parametrize("pitch,note", [(1, 12), (0.5, 0), (0, 0)])
def test_sound_rejects_both_pitch_and_note_before_rpc(method, pitch, note):
    conn = FakeConn(None)
    with pytest.raises(ValueError, match="pitch and note"):
        getattr(Minecraft(conn), method)(0, 0, 0, "hit", pitch=pitch, note=note)
    assert conn.calls == []


@pytest.mark.parametrize("method", ["playSound", "playBlockSound"])
def test_sound_controls_require_keyword_arguments(method):
    conn = FakeConn(None)
    with pytest.raises(TypeError):
        getattr(Minecraft(conn), method)(0, 0, 0, "hit", {"pitch": 1})
    assert conn.calls == []


@pytest.mark.parametrize("method,position", [("playSound", [math.nan, 0, 0]), ("playSound", [True, 0, 0]), ("playBlockSound", [0.1, 0, 0]), ("playBlockSound", [math.inf, 0, 0])])
def test_sound_invalid_position_is_not_rounded_or_sent(method, position):
    conn = FakeConn(None)
    with pytest.raises(ValueError):
        getattr(Minecraft(conn), method)(*position, "hit")
    assert conn.calls == []


@pytest.mark.parametrize("method,identifier", [("playSound", "missing"), ("playBlockSound", "hit")])
@pytest.mark.parametrize("reason", ["invalid_params", "unknown_sound", "no_block", "auth_required", "player_offline", "permission_denied", "build_denied", "backpressure", "work_limit_exceeded", "internal_error"])
def test_sound_server_error_propagates_once_without_retry(method, identifier, reason):
    error = McRpcError(-32000, reason, {"reason": reason})
    conn = FakeConn(error)
    options = {"receiver": "self", "note": 12}
    with pytest.raises(McRpcError) as caught:
        getattr(Minecraft(conn), method)(0, 0, 0, identifier, **options)
    assert caught.value is error
    assert conn.calls == [("world." + method, [0, 0, 0, identifier, options])]


@pytest.mark.parametrize("method,identifier", [("playSound", "entity.cow.ambient"), ("playBlockSound", "hit")])
def test_sound_projects_keywords_and_rejects_non_null_success(method, identifier):
    conn = FakeConn(True)
    options = MappingProxyType({"note": 12})
    with pytest.raises(McRemoteError):
        getattr(Minecraft(conn), method)(0, 0, 0, identifier, **options)
    assert type(conn.calls[0][1][-1]) is dict


@pytest.mark.parametrize("particle", ["flame", "minecraft:flame", "example:flame", {"particle_id": "dust", "data": {"color": [0, 255, 0], "size": 1}}, {"particle_id": "block", "data": {"block_id": "stone", "state": {}}}])
def test_resource_ids_particle_client_and_observer_preserve_namespace_omission(particle):
    conn = FakeConn(1)
    args = [*PARTICLE_PREFIX, particle, 0, 1]
    Minecraft(conn).spawnParticle(*args)
    source, frames = observer_source()
    source.observe_request("world.spawnParticle", args, 2)
    assert conn.calls == [("world.spawnParticle", args)]
    assert frames[0]["payload"]["params"] == args
    validate_snapshot(source.snapshot(frames))


@pytest.mark.parametrize("entity", ["pig", "minecraft:pig", "example:pig"])
def test_resource_ids_entity_client_and_observer_preserve_namespace_omission(entity):
    conn = FakeConn("mcr_eh_test")
    Minecraft(conn).spawnEntity(0, 0, 0, entity)
    source, frames = observer_source()
    source.observe_request("world.spawnEntity", [0, 0, 0, entity], 2)
    assert conn.calls == [("world.spawnEntity", [0, 0, 0, entity])]
    assert frames[0]["payload"]["params"][-1] == entity


@pytest.mark.parametrize("identifier", ["", ":pig", "minecraft:", "mc:pig:bad", "Pig", " minecraft:pig", "mc:Bad"])
def test_resource_ids_noncanonical_inputs_are_not_silently_repaired(identifier):
    for method, params in [("spawnEntity", [0, 0, 0, identifier]), ("spawnParticle", [*PARTICLE_PREFIX, identifier, 0, 1]), ("playSound", [0, 0, 0, identifier])]:
        conn = FakeConn(None)
        with pytest.raises(ValueError):
            getattr(Minecraft(conn), method)(*params)
        assert conn.calls == []
        source, frames = observer_source()
        source.observe_request("world." + method, params, 2)
        assert frames == []
        source.connection_closed()


@pytest.mark.parametrize("method,identifier", [("world.playSound", "entity.cow.ambient"), ("world.playSound", "minecraft:entity.cow.ambient"), ("world.playBlockSound", "hit")])
@pytest.mark.parametrize("options", ["omitted", {}, {"volume": 0, "pitch": 0.5}, {"volume": 1, "pitch": 2}, {"note": 0}, {"note": 24, "receiver": "self"}])
def test_observer_sound_request_result_and_snapshot(method, identifier, options):
    source, frames = observer_source()
    params = [0, 1, 2, identifier]
    if options != "omitted":
        params.append(options)
    source.observe_request(method, params, 2)
    source.observe_result(method, None, 2)
    assert [frame["payload"] for frame in frames] == [{"params": params}, {"result": None}]
    validate_snapshot(source.snapshot(frames))


@pytest.mark.parametrize("options", [None, [], {"token": "secret"}, {"volume": -0.01}, {"volume": 1.01}, {"volume": True}, {"pitch": 0.49}, {"pitch": 2.01}, {"pitch": math.nan}, {"pitch": 1, "note": 12}, {"note": -1}, {"note": 25}, {"note": 1.5}, {"note": True}, {"receiver": "all"}, {"receiver": {"token": "secret"}}])
@pytest.mark.parametrize("method", ["world.playSound", "world.playBlockSound"])
def test_observer_drops_invalid_sound_controls_and_sanitizes_server_error(method, options):
    source, frames = observer_source()
    identifier = "entity.cow.ambient" if method == "world.playSound" else "hit"
    source.observe_request(method, [0, 0, 0, identifier, options], 2)
    assert frames == []
    source.observe_error(method, McRpcError(-32602, "invalid_params", {"reason": "invalid_params", "token": "secret"}), 2)
    assert frames[0]["payload"]["error"]["data"] == {"reason": "invalid_params"}
    validate_snapshot(source.snapshot(frames))


def test_short_import_follows_reload_and_is_discoverable():
    # Keep reload separate from the main pytest process's imported class objects.
    subprocess.run([sys.executable, "-c", """
import importlib
import mc_remote
from mc_remote import Minecraft
from mc_remote.minecraft import Minecraft as direct
assert Minecraft is direct
assert 'Minecraft' in dir(mc_remote)
assert 'Minecraft' not in vars(mc_remote)
importlib.reload(mc_remote.minecraft)
from mc_remote import Minecraft as new
from mc_remote.minecraft import Minecraft as new_direct
assert new is new_direct and new is not Minecraft
try:
    mc_remote.not_an_export
except AttributeError:
    pass
else:
    raise AssertionError('unknown name accepted')
"""], check=True)


def test_pygame_is_only_an_optional_extra():
    # Python 3.10 is supported, so do not require tomllib for this check.
    from importlib.metadata import metadata
    package = metadata("minecraft-remote-api")
    assert "pygame" in package.get_all("Provides-Extra", [])
    requirements = package.get_all("Requires-Dist", [])
    assert requirements and all('extra == "pygame"' in item.replace("'", '"') for item in requirements)
    assert any("pygame-ce>=2.5" in item for item in requirements)
