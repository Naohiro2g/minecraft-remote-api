"""Protocol 22.0.0 b5 structured block value tests."""
import json
import math
import queue
import threading
import warnings
from pathlib import Path

from mc_remote.block_value import BlockValue
from mc_remote.b5_values import (
    BlockRightClickEvent,
    ChatPostedEvent,
    EntityHandle,
    EventContextMismatchError,
    ProjectileHitEvent,
)
from mc_remote.connection import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SEND_QUEUE_CAPACITY,
    Connection,
    ConnectionLostError,
    McRemoteError,
    RequestTimeoutError,
)
from mc_remote.minecraft import (
    DEFAULT_TRACE_DELAY,
    MAX_TRACE_DELAY,
    BuildMode,
    Minecraft,
    PROTOCOL,
)
from mc_remote.observer import PythonObserverSource


EVENT_CONTEXT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "python-event-context-guard.json"
)
RUNTIME_POLICY_FIXTURE = (
    Path(__file__).parent / "fixtures" / "python-b5-runtime-policy.json"
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


class ImmediateResult:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def result(self):
        if self.error is not None:
            raise self.error
        return self.value


class ModeConn:
    def __init__(self):
        self.calls = []
        self.flush_count = 0
        self.closed = False
        self.next_result = None
        self.next_error = None

    def _enqueue_request(self, method, params=None):
        self.calls.append(("request", method, params))
        result = ImmediateResult(self.next_result, self.next_error)
        self.next_result = None
        self.next_error = None
        return result

    def notify(self, method, params=None):
        self.calls.append(("notification", method, params))

    def flush(self):
        self.flush_count += 1

    def close(self):
        self.closed = True


class ScriptedReader:
    def __init__(self):
        self.lines = queue.Queue()
        self.closed = False

    def push(self, response):
        self.lines.put(json.dumps(response, separators=(",", ":")) + "\n")

    def readline(self):
        return self.lines.get(timeout=2)

    def close(self):
        self.closed = True


class TimeoutReader:
    def __init__(self):
        self.closed = False

    def push(self, _response):
        pass

    def readline(self):
        raise TimeoutError("scripted request timeout")

    def close(self):
        self.closed = True


class ScriptedSocket:
    def __init__(self, reader):
        self.reader = reader
        self.messages = []
        self.closed = False
        self.fail_method = None
        self.failed = threading.Event()
        self.error_method = None
        self.block_method = None
        self.block_once = False
        self.block_entered = threading.Event()
        self.block_release = threading.Event()

    def sendall(self, payload):
        message = json.loads(payload.decode("utf8"))
        self.messages.append(message)
        if message.get("method") == self.fail_method:
            self.failed.set()
            raise OSError("scripted send failure")
        if message.get("method") == self.block_method and not self.block_once:
            self.block_once = True
            self.block_entered.set()
            self.block_release.wait(timeout=2)
        if "id" in message:
            if message["method"] == self.error_method:
                self.reader.push(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {
                            "code": -32602,
                            "message": "invalid params",
                            "data": {"reason": "invalid_params"},
                        },
                    }
                )
                return
            result = (
                {"protocol": "22.0.0"}
                if message["method"] == "hello"
                else None
            )
            self.reader.push(
                {"jsonrpc": "2.0", "id": message["id"], "result": result}
            )

    def close(self):
        self.closed = True


def scripted_connection(capacity=4):
    conn = object.__new__(Connection)
    conn.address = "example.invalid"
    conn.port = 25575
    conn.debug = False
    conn.send_queue_capacity = capacity
    conn.lastSent = b""
    conn._observer = None
    conn._close_lock = threading.Lock()
    conn.reader = ScriptedReader()
    conn.socket = ScriptedSocket(conn.reader)
    conn._start_sequencer()
    conn.is_connected = lambda: True
    return conn


def test_protocol_and_structured_setblock_payload():
    conn = FakeConn({"world.setBlock": None})
    mc = Minecraft(conn)

    mc.setBlock(0, 1, 2, "gold_block")
    mc.setBlock(3, 4, 5, "minecraft:oak_log", state={"axis": "z"})

    assert PROTOCOL == "22.0.0"
    assert conn.calls == [
        (
            "world.setBlock",
            [0, 1, 2, {"block_id": "gold_block", "state": {}}],
        ),
        (
            "world.setBlock",
            [
                3,
                4,
                5,
                {"block_id": "minecraft:oak_log", "state": {"axis": "z"}},
            ],
        ),
    ]


def test_debug_trace_and_fast_keep_one_setter_surface_and_return_none():
    conn = ModeConn()
    delays = []
    mc = Minecraft(conn, _sleeper=delays.append)

    assert mc.build_mode is BuildMode.DEBUG
    assert mc.trace_delay == 0.25
    assert mc.setBlock(1, 2, 3, "stone") is None
    assert conn.calls[-1][0:2] == ("request", "world.setBlock")
    assert delays == []

    assert mc.setBuildMode(BuildMode.TRACE) is None
    assert conn.flush_count == 1
    assert mc.setBlocks(0, 0, 0, 1, 1, 1, "stone") is None
    assert conn.calls[-1][0:2] == ("request", "world.setBlocks")
    assert delays == [0.25]

    assert mc.setBuildMode(BuildMode.FAST) is None
    assert conn.flush_count == 2
    assert mc.setBlock(4, 5, 6, "gold_block") is None
    assert conn.calls[-1][0:2] == ("notification", "world.setBlock")
    assert delays == [0.25]


def test_trace_does_not_delay_on_error_or_accept_non_null_set_result():
    conn = ModeConn()
    delays = []
    mc = Minecraft(conn, build_mode=BuildMode.TRACE, _sleeper=delays.append)
    conn.next_error = McRemoteError("rejected")
    try:
        mc.setBlock(0, 0, 0, "stone")
    except McRemoteError:
        pass
    else:
        raise AssertionError("TRACE must surface the request error")
    assert delays == []

    conn.next_result = {"applied": 1}
    try:
        mc.setBlock(0, 0, 0, "stone")
    except McRemoteError as exc:
        assert "must be null" in str(exc)
    else:
        raise AssertionError("setter accepted a non-null success result")
    assert delays == []


def test_trace_setter_keeps_registered_delay_during_later_mode_change():
    conn = ModeConn()
    delay_entered = threading.Event()
    delay_release = threading.Event()
    seen = []

    def sleeper(delay):
        seen.append(delay)
        delay_entered.set()
        delay_release.wait(timeout=2)

    mc = Minecraft(
        conn,
        build_mode=BuildMode.TRACE,
        trace_delay=0.25,
        _sleeper=sleeper,
    )
    setter = threading.Thread(target=lambda: mc.setBlock(0, 0, 0, "stone"))
    setter.start()
    assert delay_entered.wait(timeout=2)

    mc.setBuildMode(BuildMode.TRACE, trace_delay=1.0)
    assert mc.trace_delay == 1.0
    assert seen == [0.25]
    delay_release.set()
    setter.join(timeout=2)
    assert not setter.is_alive()


def test_mode_transition_fences_later_setter_until_flush_succeeds():
    class BlockingFlushConn(ModeConn):
        def __init__(self):
            super().__init__()
            self.flush_entered = threading.Event()
            self.flush_release = threading.Event()

        def flush(self):
            self.flush_count += 1
            self.flush_entered.set()
            self.flush_release.wait(timeout=2)

    conn = BlockingFlushConn()
    mc = Minecraft(conn)
    transition = threading.Thread(
        target=lambda: mc.setBuildMode(BuildMode.FAST)
    )
    transition.start()
    assert conn.flush_entered.wait(timeout=2)

    setter = threading.Thread(target=lambda: mc.setBlock(0, 0, 0, "stone"))
    setter.start()
    assert not any(call[0] == "notification" for call in conn.calls)
    conn.flush_release.set()
    transition.join(timeout=2)
    setter.join(timeout=2)
    assert not transition.is_alive() and not setter.is_alive()
    assert conn.calls[-1][0:2] == ("notification", "world.setBlock")


def test_failed_mode_transition_keeps_old_mode_and_delay():
    class FailedFlushConn(ModeConn):
        def flush(self):
            raise ConnectionLostError("flush failed")

    mc = Minecraft(FailedFlushConn())
    try:
        mc.setBuildMode(BuildMode.TRACE, trace_delay=1.0)
    except ConnectionLostError:
        pass
    else:
        raise AssertionError("mode transition must surface flush failure")
    assert mc.build_mode is BuildMode.DEBUG
    assert mc.trace_delay == 0.25


def test_invalid_mode_and_delay_are_rejected_before_transition():
    conn = ModeConn()
    mc = Minecraft(conn)
    for invalid in (-1, 2.0001, math.inf, math.nan, True, "0.25"):
        try:
            mc.setBuildMode(BuildMode.TRACE, trace_delay=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid TRACE delay: {invalid!r}")
    try:
        mc.setBuildMode("FAST")
    except TypeError:
        pass
    else:
        raise AssertionError("accepted a string instead of BuildMode")
    assert conn.flush_count == 0


def test_trace_delay_accepts_both_contract_boundaries_without_clamping():
    conn = ModeConn()
    mc = Minecraft(conn)
    mc.setBuildMode(BuildMode.TRACE, trace_delay=0)
    assert mc.trace_delay == 0.0
    mc.setBuildMode(BuildMode.TRACE, trace_delay=2.0)
    assert mc.trace_delay == 2.0
    assert conn.flush_count == 2


def test_b5_runtime_policy_fixture_locks_python_candidate_values():
    fixture = json.loads(RUNTIME_POLICY_FIXTURE.read_text(encoding="utf-8"))
    assert fixture == {
        "knowledge_commit": "5b12a4360b969db9ad899b868cae993ce65cfa44",
        "decision_id": "2026-08-21-02",
        "send_queue": {
            "capacity": DEFAULT_SEND_QUEUE_CAPACITY,
            "overflow": "backpressure",
            "silent_drop": False,
        },
        "request_timeout": {
            "seconds": DEFAULT_REQUEST_TIMEOUT_SECONDS,
            "completion": "unknown",
            "automatic_retry": False,
            "reclaim_connection": True,
        },
        "trace_delay": {
            "default": DEFAULT_TRACE_DELAY,
            "minimum": 0.0,
            "maximum": MAX_TRACE_DELAY,
        },
        "events_poll": {
            "omitted": "server-default",
            "option": "max_events",
        },
        "status": "b5-finite-candidate-pending-b6-calibration",
    }


def test_connection_notification_and_flush_share_fifo_and_wire_shape():
    conn = scripted_connection()
    assert conn.rpc("hello", {"protocol": "22.0.0"}) == {
        "protocol": "22.0.0"
    }
    conn.notify("world.setBlock", [0, 0, 0, {"block_id": "stone", "state": {}}])
    conn.notify("world.setBlock", [0, 0, 0, {"block_id": "gold_block", "state": {}}])
    assert conn.flush() is None

    messages = conn.socket.messages
    assert [message["method"] for message in messages] == [
        "hello",
        "world.setBlock",
        "world.setBlock",
        "connection.flush",
    ]
    assert [message.get("id") for message in messages] == [1, None, None, 2]
    assert "id" not in messages[1] and "id" not in messages[2]
    assert messages[3]["params"] == []
    conn.close()
    assert len(conn.socket.messages) == 4  # explicit flush covered both notifications


def test_normal_close_automatically_flushes_pending_notification():
    conn = scripted_connection()
    conn.rpc("hello", {"protocol": "22.0.0"})
    conn.notify("world.setBlock", [0, 0, 0, {"block_id": "stone", "state": {}}])
    conn.close()
    assert [message["method"] for message in conn.socket.messages] == [
        "hello",
        "world.setBlock",
        "connection.flush",
    ]
    assert conn.reader.closed and conn.socket.closed


def test_rejected_request_is_terminal_without_poisoning_later_fifo_work():
    conn = scripted_connection()
    conn.rpc("hello", {"protocol": "22.0.0"})
    conn.socket.error_method = "world.setBlock"
    try:
        conn.rpc(
            "world.setBlock",
            [0, 0, 0, {"block_id": "unknown", "state": {}}],
        )
    except McRemoteError as exc:
        assert "invalid_params" in str(exc)
    else:
        raise AssertionError("request rejection was not surfaced")
    assert conn.flush() is None
    conn.close()


def test_finite_fifo_applies_backpressure_without_dropping_notifications():
    conn = scripted_connection(capacity=1)
    conn.rpc("hello", {"protocol": "22.0.0"})
    conn.socket.block_method = "world.setBlock"
    params = [0, 0, 0, {"block_id": "stone", "state": {}}]
    conn.notify("world.setBlock", params)
    assert conn.socket.block_entered.wait(timeout=2)
    conn.notify("world.setBlock", params)

    third_done = threading.Event()
    third = threading.Thread(
        target=lambda: (conn.notify("world.setBlock", params), third_done.set())
    )
    third.start()
    assert not third_done.wait(timeout=0.1)
    conn.socket.block_release.set()
    assert third_done.wait(timeout=2)
    third.join(timeout=2)
    conn.flush()
    conn.close()
    assert [
        message["method"] for message in conn.socket.messages
    ].count("world.setBlock") == 3


def test_notification_transport_failure_makes_later_flush_fail():
    conn = scripted_connection()
    conn.rpc("hello", {"protocol": "22.0.0"})
    conn.socket.fail_method = "world.setBlock"
    conn.notify("world.setBlock", [0, 0, 0, {"block_id": "stone", "state": {}}])
    assert conn.socket.failed.wait(timeout=2)
    try:
        conn.flush()
    except ConnectionLostError:
        pass
    else:
        raise AssertionError("flush must fail after notification transport failure")
    try:
        conn.close()
    except ConnectionLostError:
        pass
    else:
        raise AssertionError("close must report the failed completion guarantee")
    assert conn.socket.closed


def test_context_manager_auto_closes_and_preserves_body_exception():
    conn = ModeConn()
    with Minecraft(conn) as mc:
        assert mc is not None
    assert conn.closed

    class FailedCloseConn(ModeConn):
        def close(self):
            self.closed = True
            raise ConnectionLostError("close failed")

    failed = FailedCloseConn()
    body_error = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            with Minecraft(failed):
                raise ValueError("body failed")
        except ValueError as exc:
            body_error = exc
            assert str(exc) == "body failed"
            if hasattr(exc, "__notes__"):
                assert any(
                    "close/flush also failed" in note
                    and "ConnectionLostError" in note
                    for note in exc.__notes__
                )
        else:
            raise AssertionError("context manager masked the body exception")
    assert failed.closed
    if hasattr(ValueError(), "add_note"):
        assert caught == []
    else:
        assert body_error.__context__ is not None
        assert isinstance(body_error.__context__, ConnectionLostError)


def test_flush_timeout_reclaims_connection_and_is_never_retried():
    conn = scripted_connection()
    assert conn.rpc("hello", {"protocol": "22.0.0"}) == {
        "protocol": "22.0.0"
    }
    timeout_reader = TimeoutReader()
    conn.reader = timeout_reader
    conn.socket.reader = timeout_reader
    mc = Minecraft(conn)

    try:
        mc.flush()
    except RequestTimeoutError as exc:
        assert exc.method == "connection.flush"
        assert exc.completion_unknown is True
        assert "completion is unknown" in str(exc)
        assert "not retried" in str(exc)
    else:
        raise AssertionError("flush timeout was not surfaced")

    assert mc._closed is True
    assert conn.socket.closed is True
    assert timeout_reader.closed is True
    assert [
        message["method"] for message in conn.socket.messages
    ] == ["hello", "connection.flush"]


def test_mode_transition_timeout_keeps_old_mode_and_reclaims_connection():
    conn = scripted_connection()
    conn.rpc("hello", {"protocol": "22.0.0"})
    timeout_reader = TimeoutReader()
    conn.reader = timeout_reader
    conn.socket.reader = timeout_reader
    mc = Minecraft(conn)

    try:
        mc.setBuildMode(BuildMode.FAST)
    except RequestTimeoutError:
        pass
    else:
        raise AssertionError("mode transition accepted an unknown flush outcome")

    assert mc.build_mode is BuildMode.DEBUG
    assert mc.trace_delay == DEFAULT_TRACE_DELAY
    assert mc._closed is True
    assert conn.socket.closed is True


def test_observer_distinguishes_notification_null_result_and_flush():
    frames = []
    observer = PythonObserverSource(
        frames.append,
        target_id_factory=lambda: "target-b5-mode",
        alias_factory=lambda: "MIND-STORM-000025",
    )
    hello = {
        "protocol": "22.0.0",
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalog_hash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": {
            "online": True,
            "offline": False,
            "build_range": 100,
        },
    }
    observer.observe_request("hello", {"protocol": "22.0.0"}, 1)
    observer.observe_result("hello", hello, 1)
    frames.clear()

    params = [0, 0, 0, {"block_id": "stone", "state": {}}]
    observer.observe_request("world.setBlock", params, None)
    observer.observe_request("connection.flush", [], 2)
    observer.observe_result("connection.flush", None, 2)

    observed = [
        (frame["direction"], frame["request_id"], frame["method"])
        for frame in frames
    ]
    assert observed == [
        ("send", None, "world.setBlock"),
        ("send", 2, "connection.flush"),
        ("receive", 2, "connection.flush"),
    ]
    assert frames[2]["payload"] == {"result": None}

    before = len(frames)
    observer.observe_result("world.setBlock", {"applied": 1}, 3)
    observer.observe_request("connection.flush", [1], 4)
    assert len(frames) == before


def test_observer_accepts_new_poll_options_and_rejects_old_flat_limit():
    frames = []
    observer = PythonObserverSource(
        frames.append,
        target_id_factory=lambda: "target-b5-poll-options",
        alias_factory=lambda: "MIND-STORM-000028",
    )
    hello = {
        "protocol": "22.0.0",
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalog_hash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": {
            "online": True,
            "offline": False,
            "build_range": 100,
        },
    }
    observer.observe_request("hello", {"protocol": "22.0.0"}, 1)
    observer.observe_result("hello", hello, 1)
    frames.clear()

    observer.observe_request("events.poll", [0], 2)
    observer.observe_request(
        "events.poll", [0, {"max_events": 9999}], 3
    )
    assert [frame["payload"]["params"] for frame in frames] == [
        [0],
        [0, {"max_events": 9999}],
    ]

    for request_id, invalid in enumerate(
        (
            [0, 64],
            [0, {}],
            [0, {"max_events": 0}],
            [0, {"max_events": -1}],
            [0, {"max_events": 1.5}],
            [0, {"max_events": True}],
            [0, {"max_events": 1, "unknown": 2}],
        ),
        start=4,
    ):
        before = len(frames)
        observer.observe_request("events.poll", invalid, request_id)
        assert len(frames) == before


def test_observer_projects_getblocks_as_canonical_blockvalue_array():
    frames = []
    observer = PythonObserverSource(
        frames.append,
        target_id_factory=lambda: "target-b5-getblocks",
        alias_factory=lambda: "MIND-STORM-000026",
    )
    hello = {
        "protocol": "22.0.0",
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalog_hash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": {
            "online": True,
            "offline": False,
            "build_range": 100,
        },
    }
    observer.observe_request("hello", {"protocol": "22.0.0"}, 1)
    observer.observe_result("hello", hello, 1)
    frames.clear()

    values = [
        {"block_id": "minecraft:stone", "state": {}},
        {"block_id": "minecraft:oak_log", "state": {"axis": "z"}},
    ]
    observer.observe_request("world.getBlocks", [0, 0, 0, 1, 0, 0], 2)
    observer.observe_result("world.getBlocks", values, 2)

    assert frames == [
        {
            "sequence": frames[0]["sequence"],
            "observed_at": frames[0]["observed_at"],
            "direction": "send",
            "request_id": 2,
            "method": "world.getBlocks",
            "payload": {"params": [0, 0, 0, 1, 0, 0]},
        },
        {
            "sequence": frames[1]["sequence"],
            "observed_at": frames[1]["observed_at"],
            "direction": "receive",
            "request_id": 2,
            "method": "world.getBlocks",
            "payload": {"result": values},
        },
    ]

    before = len(frames)
    observer.observe_request("world.getBlocks", [0, 0, 0], 3)
    observer.observe_result(
        "world.getBlocks",
        [{"block_id": "stone", "state": {}}],
        4,
    )
    observer.observe_result("world.getBlocks", {"blocks": values}, 5)
    assert len(frames) == before


def test_setblocks_uses_same_blockspec_and_snapshots_input():
    conn = FakeConn({"world.setBlocks": None})
    mc = Minecraft(conn)
    state = {"waterlogged": False, "facing": "north"}

    mc.setBlocks(0, 0, 0, 2, 2, 2, "oak_stairs", state=state)
    state["facing"] = "south"

    assert conn.calls == [
        (
            "world.setBlocks",
            [
                0,
                0,
                0,
                2,
                2,
                2,
                {
                    "block_id": "oak_stairs",
                    "state": {"facing": "north", "waterlogged": False},
                },
            ],
        )
    ]


def test_getblock_returns_immutable_blockvalue():
    conn = FakeConn(
        {
            "world.getBlock": {
                "block_id": "minecraft:oak_log",
                "state": {"axis": "z"},
            }
        }
    )
    value = Minecraft(conn).getBlock(1, 2, 3)

    assert value == BlockValue("minecraft:oak_log", {"axis": "z"})
    assert value.block_id == "minecraft:oak_log"
    assert value.state == {"axis": "z"}
    assert repr(value.state) == "{'axis': 'z'}"
    try:
        value.state["axis"] = "x"
    except TypeError:
        pass
    else:
        raise AssertionError("BlockValue.state must be immutable")
    try:
        value.state._values["axis"] = "x"
    except TypeError:
        pass
    else:
        raise AssertionError("BlockValue private storage must also be immutable")


def test_getblock_no_state_is_still_an_empty_mapping():
    conn = FakeConn(
        {"world.getBlock": {"block_id": "minecraft:gold_block", "state": {}}}
    )
    value = Minecraft(conn).getBlock(0, 0, 0)
    assert value.state == {}


def test_getblocks_returns_immutable_tuple_in_wire_order():
    result = [
        {"block_id": "minecraft:stone", "state": {}},
        {"block_id": "minecraft:oak_log", "state": {"axis": "z"}},
    ]
    conn = FakeConn({"world.getBlocks": result})

    values = Minecraft(conn).getBlocks(0, 1, 2, 3, 4, 5)

    assert values == (
        BlockValue("minecraft:stone", {}),
        BlockValue("minecraft:oak_log", {"axis": "z"}),
    )
    assert conn.calls == [("world.getBlocks", [0, 1, 2, 3, 4, 5])]
    try:
        values[0] = values[1]
    except TypeError:
        pass
    else:
        raise AssertionError("world.getBlocks result must be immutable")


def test_getblocks_rejects_non_array_or_malformed_items():
    invalid_results = [
        {"blocks": []},
        ["minecraft:stone"],
        [{"block_id": "stone", "state": {}}],
        [{"block_id": "minecraft:stone", "state": None}],
    ]
    for result in invalid_results:
        try:
            Minecraft(FakeConn({"world.getBlocks": result})).getBlocks(
                0, 0, 0, 1, 1, 1
            )
        except McRemoteError:
            pass
        else:
            raise AssertionError(f"accepted malformed BlockValue array: {result!r}")


def test_getblock_rejects_non_exact_or_noncanonical_results():
    invalid_results = [
        "minecraft:stone",
        {"block_id": "minecraft:stone"},
        {"block_id": "minecraft:stone", "state": {}, "legacy": True},
        {"block_id": "stone", "state": {}},
        {"block_id": "minecraft:stone", "state": None},
        {"block_id": "minecraft:water", "state": {"level": None}},
    ]
    for result in invalid_results:
        try:
            Minecraft(FakeConn({"world.getBlock": result})).getBlock(0, 0, 0)
        except McRemoteError:
            pass
        else:
            raise AssertionError(f"accepted malformed BlockValue: {result!r}")


def test_input_rejects_protocol21_ref_and_non_json_state_values():
    mc = Minecraft(FakeConn({"world.setBlock": None}))
    invalid = [
        ("oak_log[axis=z]", {}),
        ("oak_log", {"axis": None}),
        ("oak_log", {"axis": ["z"]}),
        ("oak_log", {"axis": math.inf}),
        ("oak_log", {1: "z"}),
    ]
    for block_id, state in invalid:
        try:
            mc.setBlock(0, 0, 0, block_id, state=state)
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError(f"accepted invalid BlockSpec: {block_id!r}, {state!r}")


def test_block_coordinates_reject_fractional_values_without_sending():
    conn = FakeConn(
        {
            "world.setBlock": None,
            "world.setBlocks": None,
            "world.getBlock": {"block_id": "minecraft:air", "state": {}},
            "world.getBlocks": [],
            "build.setOrigin": None,
        }
    )
    mc = Minecraft(conn)
    calls = [
        lambda: mc.setBlock(0.5, 0, 0, "stone"),
        lambda: mc.setBlocks(0, 0, 0, 1, 1.5, 1, "stone"),
        lambda: mc.getBlock(0, 0.25, 0),
        lambda: mc.getBlocks(0, 0, 0, 1, 1, 1.5),
        lambda: mc.setBuildOrigin(0, 0.5, 0),
    ]
    for call in calls:
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("fractional block coordinate was accepted")
    assert conn.calls == []


def test_integral_json_numbers_are_sent_as_integer_coordinates():
    conn = FakeConn(
        {"world.getBlock": {"block_id": "minecraft:air", "state": {}}}
    )
    Minecraft(conn).getBlock(1.0, -2.0, 3)
    assert conn.calls == [("world.getBlock", [1, -2, 3])]


def test_height_particle_and_entity_use_protocol22_exact_wire_order():
    handle = "mceh_" + "A" * 22
    conn = FakeConn(
        {
            "world.getHeight": 71,
            "world.spawnParticle": 8,
            "world.spawnEntity": handle,
        }
    )
    mc = Minecraft(conn)
    assert mc.getHeight(1, 2, 90) == 71
    assert (
        mc.spawnParticle(
            1.25,
            2.5,
            3.75,
            0.1,
            0.2,
            0.3,
            "minecraft:dust",
            0.4,
            8,
        )
        == 8
    )
    assert mc.spawnEntity(4.25, 5.5, 6.75, "minecraft:pig") == handle
    assert isinstance(mc.spawnEntity(1, 2, 3, "minecraft:cow"), EntityHandle)
    assert conn.calls == [
        ("world.getHeight", [1, 2, 90]),
        (
            "world.spawnParticle",
            [
                1.25,
                2.5,
                3.75,
                0.1,
                0.2,
                0.3,
                "minecraft:dust",
                0.4,
                8,
            ],
        ),
        ("world.spawnEntity", [4.25, 5.5, 6.75, "minecraft:pig"]),
        ("world.spawnEntity", [1, 2, 3, "minecraft:cow"]),
    ]


def test_poll_events_advances_cursor_only_after_a_valid_response():
    handle = "mceh_" + "B" * 22
    valid = {
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
    assert isinstance(batch.events[0], BlockRightClickEvent)
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


def test_poll_events_default_delegates_to_server_runtime_policy():
    result = {
        "events": [],
        "through_sequence": 0,
        "latest_sequence": 0,
        "filtered_out": 0,
        "overflow_dropped_total": 0,
        "capacity_dropped_total": 0,
        "explicitly_discarded_total": 0,
    }
    conn = FakeConn({"events.poll": result})
    Minecraft(conn).pollEvents()
    assert conn.calls == [("events.poll", [0])]


def test_poll_events_rejects_invalid_client_max_before_sending():
    conn = FakeConn({"events.poll": None})
    mc = Minecraft(conn)
    for invalid in (0, -1, 1.5, True, "16"):
        try:
            mc.pollEvents(max_events=invalid)
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError(f"accepted invalid max_events: {invalid!r}")
    assert conn.calls == []


def test_assert_event_context_guards_use_without_mutating_or_discarding_event():
    fixture = json.loads(EVENT_CONTEXT_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["knowledge_commit"] == (
        "f9d5dc7780ab2673b8872dc7481d230e10ca95d9"
    )
    assert fixture["decision_id"] == "2026-08-22-02"
    assert fixture["helper"] == "Minecraft.assertEventContext"
    assert fixture["error"] == "EventContextMismatchError"
    assert fixture["reason"] == "event_context_mismatch"
    state = {
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
    }

    def set_dimension(params):
        state["dimension"] = params[0]
        return {"dimension": state["dimension"], "origin": list(state["origin"])}

    def set_origin(params):
        state["origin"] = list(params)
        return {"dimension": state["dimension"], "origin": list(state["origin"])}

    conn = FakeConn(
        {"build.setDimension": set_dimension, "build.setOrigin": set_origin}
    )
    mc = Minecraft(conn)
    event_value = fixture["event"]
    event = ChatPostedEvent(
        sequence=event_value["sequence"],
        dimension=event_value["dimension"],
        origin=tuple(event_value["origin"]),
        message=event_value["message"],
    )
    matching, wrong_dimension, wrong_origin = fixture["cases"]
    assert matching["outcome"] == "match"
    mc.setDimension(matching["current_dimension"])
    assert mc.assertEventContext(event) is None

    mc.setDimension(wrong_dimension["current_dimension"])
    try:
        mc.assertEventContext(event)
    except EventContextMismatchError as exc:
        assert exc.reason == "event_context_mismatch"
        assert exc.event_dimension == "myworld:world"
        assert exc.current_dimension == "minecraft:the_nether"
        assert "setDimension(event.dimension)" in str(exc)
    else:
        raise AssertionError("changed dimension was not guarded")

    mc.setDimension(wrong_origin["current_dimension"])
    mc.setBuildOrigin(*wrong_origin["current_origin"])
    try:
        mc.assertEventContext(event)
    except EventContextMismatchError as exc:
        assert exc.event_origin == (200, 0, 200)
        assert exc.current_origin == (10, 20, 30)
        assert "setBuildOrigin(*event.origin)" in str(exc)
    else:
        raise AssertionError("changed origin was not guarded")

    mc.setBuildOrigin(*event.origin)
    assert mc.assertEventContext(event) is None
    assert event == ChatPostedEvent(
        sequence=1,
        dimension="myworld:world",
        origin=(200, 0, 200),
        message="hello",
    )


def test_assert_event_context_rejects_non_event_values():
    try:
        Minecraft(FakeConn({})).assertEventContext(
            {"dimension": "minecraft:overworld"}
        )
    except TypeError as exc:
        assert "protocol 22 event" in str(exc)
    else:
        raise AssertionError("non-event value was accepted")


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
