"""Deterministic conformance tests for the Python WireScope adapter slice."""

import copy
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote.connection import Connection, McRpcError  # noqa: E402
from mc_remote.minecraft import Minecraft  # noqa: E402
import mc_remote.minecraft as minecraft_mod  # noqa: E402
from mc_remote.observer import (  # noqa: E402
    ObserverValidationError,
    PythonObserverSource,
    serialize_snapshot,
    validate_snapshot,
)


FIXTURE = Path(__file__).parent / "fixtures" / "python-main-lifecycle.json"

HELLO = {
    "protocol": "21.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "world_constants": {"y_sea": 62, "future_secret": "never-project"},
    "world": "overworld",
    "origin": [200, 0, 200],
    "session": "internal-session",
    "player": "00000000-0000-0000-0000-000000000001",
    "permissions": {
        "online": True,
        "offline": False,
        "buildRange": 100,
        "credential_id": "credential-1",
    },
}


class Clock:
    def __init__(self, start=1786118400000):
        self.value = start

    def __call__(self):
        value = self.value
        self.value += 1
        return value


def source(frames=None, ids=None, aliases=None):
    ids = iter(ids or ["target-python-01"])
    aliases = iter(aliases or ["5A17C0DE"])
    return PythonObserverSource(
        None if frames is None else frames.append,
        clock=Clock(),
        target_id_factory=lambda: next(ids),
        alias_factory=lambda: next(aliases),
    )


def activate(observer, request_id=1):
    observer.observe_request(
        "hello",
        {
            "protocol": "21.0.0",
            "auth": {"token": "mcrs_secret"},
            "device_label": "classroom laptop",
        },
        request_id,
    )
    observer.observe_result("hello", HELLO, request_id)


def test_python_lifecycle_fixture_conforms():
    snapshots = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = [validate_snapshot(snapshot) for snapshot in snapshots]
    assert parsed == snapshots
    assert parsed[0]["target"] == parsed[1]["target"]
    assert parsed[0]["streams"][0]["hello"] == parsed[1]["streams"][0]["hello"]
    assert parsed[0]["streams"][0]["frames"] == []
    assert len(parsed[1]["streams"][0]["frames"]) == 1


def test_fixture_dump_command_is_deterministic_and_matches_committed_fixture():
    command = [
        sys.executable,
        "-m",
        "mc_remote.observer_fixture",
        "--dump-observer-fixture",
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout) == json.loads(FIXTURE.read_text(encoding="utf-8"))
    for forbidden in ("token", "credential", "pair_code", "player", "auth."):
        assert forbidden not in first.stdout


def test_strict_validator_rejects_unknown_fields_and_shared_ids():
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    unknown = copy.deepcopy(snapshot)
    unknown["streams"][0]["hello"]["player"] = "uuid"
    try:
        validate_snapshot(unknown)
    except ObserverValidationError as exc:
        assert "unknown field: player" in str(exc)
    else:
        raise AssertionError("unknown hello fields must fail closed")

    shared_id = copy.deepcopy(snapshot)
    shared_id["target"]["id"] = "main"
    try:
        validate_snapshot(shared_id)
    except ObserverValidationError as exc:
        assert "target id" in str(exc)
    else:
        raise AssertionError("target and stream ids must be distinct")


def test_generation_allowlist_never_serializes_secrets():
    frames = []
    observer = source(frames)
    activate(observer)
    observer.observe_request(
        "auth.pairPoll", {"pairing_id": "pair-secret", "token": "mcrs_secret"}, 2
    )
    observer.observe_result(
        "auth.pairPoll", {"token": "mcrs_secret", "player": HELLO["player"]}, 2
    )
    serialized = serialize_snapshot(observer.snapshot(frames, emitted_at=1786118400100))
    assert '"source_kind":"python"' in serialized
    for forbidden in (
        "mcrs_secret",
        "pair-secret",
        "device_label",
        "classroom laptop",
        "internal-session",
        HELLO["player"],
        "credential_id",
        "credential-1",
        "future_secret",
        "auth.pairPoll",
        '"auth"',
    ):
        assert forbidden not in serialized


def test_error_allowlist_includes_schema_fields_only():
    frames = []
    observer = source(frames)
    activate(observer)
    error = McRpcError(
        -32000,
        "outside build range",
        {
            "reason": "build_denied",
            "ref": "minecraft:stone",
            "allowed": ["overworld", 100, True],
            "bounds": [0, 0, 0, 99, 255, 99],
            "violating": [100, 64, 100],
            "credential": "must-not-project",
        },
    )
    observer.observe_error("world.setBlock", error, 2)
    snapshot = observer.snapshot(frames, emitted_at=1786118400200)
    error_data = snapshot["streams"][0]["frames"][-1]["payload"]["error"]["data"]
    assert error_data == {
        "reason": "build_denied",
        "ref": "minecraft:stone",
        "allowed": ["overworld", 100, True],
        "bounds": [0, 0, 0, 99, 255, 99],
        "violating": [100, 64, 100],
    }
    assert "must-not-project" not in serialize_snapshot(snapshot)


def test_hello_is_immutable_across_build_state_frames():
    frames = []
    observer = source(frames)
    activate(observer)
    observer.observe_request("build.setWorld", ["nether"], 2)
    observer.observe_result("build.setWorld", None, 2)
    observer.observe_request("build.setOrigin", [10, 20, 30], 3)
    observer.observe_result("build.setOrigin", None, 3)
    snapshot = observer.snapshot(frames, emitted_at=1786118400300)
    hello = snapshot["streams"][0]["hello"]
    assert hello["world"] == "overworld"
    assert hello["origin"] == [200, 0, 200]
    assert "current_build_state" not in snapshot["streams"][0]


def test_reconnect_creates_a_new_target_and_alias():
    frames = []
    observer = source(
        frames,
        ids=["target-python-01", "target-python-02"],
        aliases=["5A17C0DE", "A11CE002"],
    )
    activate(observer)
    first = (observer.target_id, observer.display_alias)
    observer.connection_closed()
    assert not observer.active
    observer.connection_opened()
    activate(observer)
    second = (observer.target_id, observer.display_alias)
    assert first != second


def test_active_alias_collision_is_regenerated():
    first = source(ids=["target-python-01"], aliases=["COLLIDE"])
    second = source(
        ids=["target-python-02"],
        aliases=["COLLIDE", "UNIQUE01"],
    )
    activate(first)
    activate(second)
    assert first.display_alias == "COLLIDE"
    assert second.display_alias == "UNIQUE01"
    first.connection_closed()
    second.connection_closed()


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendall(self, payload):
        self.sent.append(payload)

    def close(self):
        pass


def test_minecraft_create_without_wirescope_does_not_attach_observer():
    class CreateConnection:
        def __init__(self, address, port, debug=False):
            self.address = address
            self.port = port
            self.debug = debug
            self.observer = None
            self.request_id = 0

        def set_observer(self, observer):
            self.observer = observer
            observer.connection_opened()

        def rpc(self, method, params=None):
            self.request_id += 1
            if self.observer is not None:
                self.observer.observe_request(method, params, self.request_id)
            result = HELLO if method == "hello" else None
            if self.observer is not None:
                self.observer.observe_result(method, result, self.request_id)
            return result

        def close(self):
            if self.observer is not None:
                self.observer.connection_closed()

    previous_connection = minecraft_mod.Connection
    previous_load_token = minecraft_mod.load_token
    minecraft_mod.Connection = CreateConnection
    minecraft_mod.load_token = lambda _server_key: None
    try:
        mc = Minecraft.create(sync_catalog=False, pair=False)
        assert mc.conn.observer is None
        assert mc._observer is None
        mc.close()
    finally:
        minecraft_mod.Connection = previous_connection
        minecraft_mod.load_token = previous_load_token


def test_connection_hook_uses_wire_request_ids_and_cannot_break_rpc():
    frames = []
    observer = source(frames)
    conn = object.__new__(Connection)
    conn.address = "example.invalid"
    conn.port = 25575
    conn.debug = False
    conn.lastSent = b""
    conn._id = 0
    conn._observer = observer
    conn.socket = FakeSocket()
    conn.reader = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": HELLO}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "result": None})
        + "\n"
    )
    conn.is_connected = lambda: True

    assert conn.rpc(
        "hello", {"protocol": "21.0.0", "auth": {"token": "mcrs_secret"}}
    ) == HELLO
    assert conn.rpc("world.setBlock", [1, 2, 3, "minecraft:stone"]) is None
    assert [frame["request_id"] for frame in frames] == [1, 1, 2, 2]
    assert "mcrs_secret" not in serialize_snapshot(observer.snapshot(frames))

    observer.set_frame_consumer(
        lambda _frame: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    conn.reader = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 3, "result": "minecraft:stone"}) + "\n"
    )
    assert conn.rpc("world.getBlock", [1, 2, 3]) == "minecraft:stone"
    conn.close()
    assert not observer.active


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
            print(f"FAIL {test.__name__}: {exc}")
    raise SystemExit(1 if failed else 0)
