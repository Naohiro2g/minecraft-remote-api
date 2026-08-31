"""Deterministic conformance tests for the Python WireScope adapter slice."""

import copy
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote.connection import Connection, McRpcError  # noqa: E402
from mc_remote.minecraft import Minecraft  # noqa: E402
import mc_remote.minecraft as minecraft_mod  # noqa: E402
import mc_remote.observer as observer_mod  # noqa: E402
from mc_remote.observer import (  # noqa: E402
    ObserverValidationError,
    PythonObserverSource,
    serialize_snapshot,
    validate_snapshot,
)


FIXTURE = Path(__file__).parent / "fixtures" / "python-main-lifecycle.json"
ALIAS_FIXTURE = Path(__file__).parent / "fixtures" / "display-alias-v1.json"
ALIAS_SOURCE = (
    Path(__file__).parent / "fixtures" / "display-alias-v1.source.json"
)

HELLO = {
    "protocol": "22.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "world_constants": {"y_sea": 62, "future_secret": "never-project"},
    "dimension": "minecraft:overworld",
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
    aliases = iter(aliases or ["MIND-STORM-000027"])
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
            "protocol": "22.0.0",
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
    assert observer_mod.OBSERVER_SCHEMA_VERSION == 1
    assert observer_mod.OBSERVER_COMPATIBILITY_SET_REVISION == "v1.1"
    assert {snapshot["schema_version"] for snapshot in parsed} == {1}
    assert parsed[0]["target"] == parsed[1]["target"]
    assert parsed[0]["streams"][0]["hello"] == parsed[1]["streams"][0]["hello"]
    assert parsed[0]["streams"][0]["frames"] == []
    frames = parsed[1]["streams"][0]["frames"]
    assert len(frames) == 23
    observed = [
        (frame["direction"], frame["request_id"], frame["method"])
        for frame in frames
    ]
    assert observed == [
        ("send", 2, "build.setDimension"),
        ("receive", 2, "build.setDimension"),
        ("send", None, "world.setBlock"),
        ("send", 3, "connection.flush"),
        ("receive", 3, "connection.flush"),
        ("send", 4, "world.getHeight"),
        ("receive", 4, "world.getHeight"),
        ("send", 5, "world.spawnParticle"),
        ("receive", 5, "world.spawnParticle"),
        ("send", 6, "world.spawnEntity"),
        ("receive", 6, "world.spawnEntity"),
        ("send", 7, "events.poll"),
        ("receive", 7, "events.poll"),
        ("send", 8, "player.getDirection"),
        ("receive", 8, "player.getDirection"),
        ("send", 9, "player.setDirection"),
        ("receive", 9, "player.setDirection"),
        ("send", 10, "entity.getDirection"),
        ("receive", 10, "entity.getDirection"),
        ("send", 11, "entity.setDirection"),
        ("receive", 11, "entity.setDirection"),
        ("send", 12, "world.strikeLightning"),
        ("receive", 12, "world.strikeLightning"),
    ]


def test_schema_v1_rejects_non_integer_and_compatibility_wire_versions():
    observer = source()
    activate(observer)
    snapshot = observer.snapshot([], emitted_at=1786118400050)
    for invalid_version in (True, 1.0, 1.1):
        snapshot["schema_version"] = invalid_version
        try:
            validate_snapshot(snapshot)
        except ObserverValidationError as exc:
            assert "unsupported observer schema version" in str(exc)
        else:
            raise AssertionError(
                f"invalid schema version was accepted: {invalid_version!r}"
            )


def test_b5_python_source_emits_exactly_one_main_stream():
    observer = source()
    activate(observer)

    snapshot = observer.snapshot([], emitted_at=1786118400050)

    assert [stream["id"] for stream in snapshot["streams"]] == ["main"]
    assert [stream["kind"] for stream in snapshot["streams"]] == ["main"]


def test_default_display_alias_generator_conforms_to_scratch_fixture(monkeypatch):
    contract = json.loads(ALIAS_FIXTURE.read_text(encoding="utf-8"))
    source_metadata = json.loads(ALIAS_SOURCE.read_text(encoding="utf-8"))
    assert source_metadata == {
        "repository": "Naohiro2g/scratch-editor",
        "branch": "develop",
        "commit": "3b3d1f1c8a0dd66d265c5c6ea515cc5ac291209b",
        "path": "mc-remote/live/test/fixtures/display-alias-v1.json",
        "sha256": (
            "85c8159a8b74788c0cf978078094d23a"
            "3cdae83c0be5e9aa9552bb820c8389ca"
        ),
        "knowledge_commit": "83f44dc5c3d309e080e3007a0d86a0c180b9fdb8",
        "decision_id": "2026-08-12-03",
    }
    assert hashlib.sha256(ALIAS_FIXTURE.read_bytes()).hexdigest() == (
        source_metadata["sha256"]
    )
    assert tuple(contract["words"]) == observer_mod._DISPLAY_ALIAS_WORDS
    assert contract["separator"] == observer_mod._DISPLAY_ALIAS_SEPARATOR
    assert contract["suffix_digits"] == observer_mod._DISPLAY_ALIAS_SUFFIX_DIGITS

    words = iter(("MIND", "STORM"))
    limits = []
    monkeypatch.setattr(observer_mod.secrets, "choice", lambda _words: next(words))
    monkeypatch.setattr(
        observer_mod.secrets,
        "randbelow",
        lambda limit: limits.append(limit) or 27,
    )
    observer = PythonObserverSource(
        target_id_factory=lambda: "target-python-alias-contract",
    )
    activate(observer)
    assert observer.display_alias == contract["example"]
    assert limits == [1_000_000]
    observer.connection_closed()


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
    for forbidden in ("token", "credential", "pair_code", '"player":', "auth."):
        assert forbidden not in first.stdout


def test_strict_validator_rejects_unknown_fields_and_shared_ids():
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    legacy_alias = copy.deepcopy(snapshot)
    legacy_alias["target"]["display_alias"] = "5A17C0DE"
    assert validate_snapshot(legacy_alias)["target"]["display_alias"] == "5A17C0DE"

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
            "block_id": "minecraft:stone",
            "property": "axis",
            "value": "w",
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
        "block_id": "minecraft:stone",
        "property": "axis",
        "value": "w",
        "allowed": ["overworld", 100, True],
        "bounds": [0, 0, 0, 99, 255, 99],
        "violating": [100, 64, 100],
    }
    assert "must-not-project" not in serialize_snapshot(snapshot)


def test_protocol22_block_values_remain_structured_and_observable():
    frames = []
    observer = source(frames)
    activate(observer)
    observer.observe_request(
        "world.setBlock",
        [1, 2, 3, {"block_id": "stone", "state": {}}],
        2,
    )
    observer.observe_request(
        "world.setBlocks",
        [0, 0, 0, 2, 2, 2, {"block_id": "oak_log", "state": {"axis": "z"}}],
        3,
    )
    observer.observe_result(
        "world.getBlock",
        {
            "block_id": "minecraft:oak_stairs",
            "state": {"waterlogged": False, "facing": "north"},
        },
        4,
    )
    payloads = [frame["payload"] for frame in frames[-3:]]
    assert payloads == [
        {"params": [1, 2, 3, {"block_id": "stone", "state": {}}]},
        {
            "params": [
                0,
                0,
                0,
                2,
                2,
                2,
                {"block_id": "oak_log", "state": {"axis": "z"}},
            ]
        },
        {
            "result": {
                "block_id": "minecraft:oak_stairs",
                "state": {"facing": "north", "waterlogged": False},
            }
        },
    ]

    before = len(frames)
    observer.observe_request("world.setBlock", [1, 2, 3, "minecraft:stone"], 5)
    observer.observe_result("world.getBlock", "minecraft:stone", 6)
    observer.observe_request(
        "world.setBlock",
        [True, 2, 3, {"block_id": "stone", "state": {}}],
        7,
    )
    observer.observe_request(
        "world.setBlock",
        [1, 2, 3, {"block_id": "stone", "state": None}],
        8,
    )
    assert len(frames) == before


def test_pose_methods_are_observed_with_method_specific_result_shape():
    frames = []
    observer = source(frames)
    activate(observer)
    observer.observe_request("player.getPose", [], 2)
    observer.observe_result(
        "player.getPose",
        {
            "dimension": "minecraft:overworld",
            "pos": [1.25, 64.5, -3.75],
            "yaw": 90.0,
            "pitch": -12.5,
            "player_uuid": "must-not-project",
        },
        2,
    )
    observer.observe_request(
        "player.setPose", ["the_end", 2.5, 70.25, 4.75, 725.0, 45.5], 3
    )
    observer.observe_result(
        "player.setPose",
        {
            "dimension": "minecraft:the_end",
            "pos": [2.5, 70.25, 4.75],
            "yaw": 5.0,
            "pitch": 45.5,
        },
        3,
    )

    snapshot = observer.snapshot(frames, emitted_at=1786118400250)
    pose_frames = snapshot["streams"][0]["frames"][-4:]
    assert [frame["method"] for frame in pose_frames] == [
        "player.getPose",
        "player.getPose",
        "player.setPose",
        "player.setPose",
    ]
    assert pose_frames[1]["payload"]["result"] == {
        "dimension": "minecraft:overworld",
        "pos": [1.25, 64.5, -3.75],
        "yaw": 90.0,
        "pitch": -12.5,
    }
    assert pose_frames[3]["payload"]["result"]["yaw"] == 5.0
    assert "must-not-project" not in serialize_snapshot(snapshot)


def test_pose_observer_drops_non_finite_results_and_projects_failure_reason():
    frames = []
    observer = source(frames)
    activate(observer)
    before = len(frames)
    observer.observe_result(
        "player.getPose",
        {
            "dimension": "minecraft:overworld",
            "pos": [0.0, 64.0, 0.0],
            "yaw": float("nan"),
            "pitch": 0.0,
        },
        2,
    )
    assert len(frames) == before

    observer.observe_error(
        "player.setPose",
        McRpcError(-32000, "teleport failed", {"reason": "teleport_failed"}),
        3,
    )
    error = frames[-1]["payload"]["error"]
    assert error["data"] == {"reason": "teleport_failed"}


def test_hello_is_immutable_across_build_state_frames():
    frames = []
    observer = source(frames)
    activate(observer)
    observer.observe_request("build.setDimension", ["the_nether"], 2)
    observer.observe_result(
        "build.setDimension",
        {"dimension": "minecraft:the_nether", "origin": [200, 0, 200]},
        2,
    )
    observer.observe_request("build.setOrigin", [10, 20, 30], 3)
    observer.observe_result(
        "build.setOrigin",
        {"dimension": "minecraft:the_nether", "origin": [10, 20, 30]},
        3,
    )
    snapshot = observer.snapshot(frames, emitted_at=1786118400300)
    hello = snapshot["streams"][0]["hello"]
    assert hello["dimension"] == "minecraft:overworld"
    assert hello["origin"] == [200, 0, 200]
    assert "current_build_state" not in snapshot["streams"][0]


def test_dimension_refs_are_observed_raw_and_server_outputs_require_keys():
    frames = []
    observer = source(frames, aliases=["MIND-STORM-000037"])
    activate(observer)

    observer.observe_request("build.setDimension", ["the_nether"], 2)
    observer.observe_request("build.setDimension", ["myworld:world"], 3)
    assert [frame["payload"]["params"] for frame in frames[-2:]] == [
        ["the_nether"],
        ["myworld:world"],
    ]

    before = len(frames)
    for invalid in (" MINECRAFT:OVERWORLD", "minecraft:", "a:b:c", True):
        observer.observe_request("build.setDimension", [invalid], 4)
    assert len(frames) == before

    observer.observe_result(
        "build.setDimension",
        {"dimension": "myworld:world", "origin": [200, 0, 200]},
        5,
    )
    assert frames[-1]["payload"]["result"] == {
        "dimension": "myworld:world",
        "origin": [200, 0, 200],
    }

    before = len(frames)
    for invalid in (
        {"dimension": "overworld", "origin": [200, 0, 200]},
        {"world": "world", "origin": [200, 0, 200]},
        {"dimension": "minecraft:overworld", "origin": [200.0, 0, 200]},
    ):
        observer.observe_result("build.setDimension", invalid, 6)
    observer.observe_result(
        "player.getPos",
        {"dimension": "overworld", "pos": [1.0, 2.0, 3.0]},
        7,
    )
    assert len(frames) == before


def test_hello_build_origin_rejects_fractional_coordinates():
    frames = []
    observer = source(frames, aliases=["MIND-STORM-000038"])
    observer.observe_request(
        "hello",
        {
            "protocol": "22.0.0",
            "build": {
                "dimension": "overworld",
                "origin": [200.5, 0, 200],
            },
        },
        1,
    )
    observer.observe_result("hello", HELLO, 1)
    assert observer.active
    assert len(frames) == 1
    assert frames[0]["direction"] == "receive"


def test_legacy_world_identity_does_not_activate_observer():
    observer = source([], aliases=["MIND-STORM-000039"])
    legacy = copy.deepcopy(HELLO)
    legacy["world"] = legacy.pop("dimension")
    observer.observe_request("hello", {"protocol": "22.0.0"}, 1)
    observer.observe_result("hello", legacy, 1)
    assert not observer.active


def test_reconnect_creates_a_new_target_and_alias():
    frames = []
    observer = source(
        frames,
        ids=["target-python-01", "target-python-02"],
        aliases=["MIND-STORM-000027", "LIFE-DNA-000028"],
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
    first = source(
        ids=["target-python-01"], aliases=["MIND-STORM-000027"]
    )
    second = source(
        ids=["target-python-02"],
        aliases=["MIND-STORM-000027", "LIFE-DNA-000028"],
    )
    activate(first)
    activate(second)
    assert first.display_alias == "MIND-STORM-000027"
    assert second.display_alias == "LIFE-DNA-000028"
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
        "hello", {"protocol": "22.0.0", "auth": {"token": "mcrs_secret"}}
    ) == HELLO
    assert conn.rpc(
        "world.setBlock",
        [1, 2, 3, {"block_id": "minecraft:stone", "state": {}}],
    ) is None
    assert [frame["request_id"] for frame in frames] == [1, 1, 2, 2]
    assert "mcrs_secret" not in serialize_snapshot(observer.snapshot(frames))

    observer.set_frame_consumer(
        lambda _frame: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    conn.reader = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {"block_id": "minecraft:stone", "state": {}},
            }
        )
        + "\n"
    )
    assert conn.rpc("world.getBlock", [1, 2, 3]) == {
        "block_id": "minecraft:stone",
        "state": {},
    }
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
