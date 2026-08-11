"""Deterministic tests for the Python browser-loopback station primitives."""

import io
import json
import time
import warnings
from pathlib import Path

import mc_remote.minecraft as minecraft_mod
from mc_remote.minecraft import Minecraft
from mc_remote.observer import PythonObserverSource
from mc_remote.wirescope import WireScopeStation, WireScopeWarning
import mc_remote.wirescope as wirescope_mod


FIXTURE = Path(__file__).parent / "fixtures" / "python-wirescope-local.json"

HELLO = {
    "protocol": "21.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "world_constants": {"y_sea": 62},
    "world": "overworld",
    "origin": [200, 0, 200],
    "permissions": {"online": True, "offline": False, "buildRange": 100},
}


class Terminal(io.StringIO):
    def isatty(self):
        return True


class MutableClock:
    def __init__(self, value=1000):
        self.value = value

    def __call__(self):
        return self.value


def wait_for(predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("timed out waiting for WireScope worker")


def test_local_profile_fixture_matches_implementation_constants():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    code = fixture["attach_code"]
    buffers = fixture["buffers"]
    assert code == {
        "alphabet": wirescope_mod.ATTACH_CODE_ALPHABET,
        "symbols": wirescope_mod.ATTACH_CODE_LENGTH,
        "entropy_bits": 40,
        "ttl_seconds": wirescope_mod.ATTACH_CODE_TTL_SECONDS,
        "max_invalid_attempts": wirescope_mod.ATTACH_CODE_MAX_ATTEMPTS,
        "max_reissues": wirescope_mod.ATTACH_CODE_MAX_REISSUES,
        "reissue_cooldown_seconds": (
            wirescope_mod.ATTACH_CODE_REISSUE_COOLDOWN_SECONDS
        ),
    }
    assert buffers == {
        "frame_max_bytes": wirescope_mod.FRAME_MAX_BYTES,
        "history_max_frames": wirescope_mod.HISTORY_MAX_FRAMES,
        "history_max_bytes": wirescope_mod.HISTORY_MAX_BYTES,
        "ingress_max_events": wirescope_mod.INGRESS_MAX_EVENTS,
        "outbound_max_envelopes": wirescope_mod.OUTBOUND_MAX_ENVELOPES,
        "outbound_max_bytes": wirescope_mod.OUTBOUND_MAX_BYTES,
        "attach_request_max_bytes": wirescope_mod.ATTACH_REQUEST_MAX_BYTES,
    }


def test_public_station_descriptor_and_boolean_alias_are_stable():
    explicit = WireScopeStation.local()
    assert repr(explicit) == "WireScopeStation.local()"
    assert wirescope_mod._coerce_station(None) is None
    assert wirescope_mod._coerce_station(False) is None
    assert wirescope_mod._coerce_station(True) == explicit
    assert wirescope_mod._coerce_station(explicit) is explicit
    try:
        wirescope_mod._coerce_station("http://127.0.0.1:1234")
    except TypeError:
        pass
    else:
        raise AssertionError("arbitrary station URLs must not be accepted")


def test_attach_code_is_target_bound_expiring_atomic_and_attempt_limited():
    clock = MutableClock()
    values = iter([0, 1, 2])
    capability = wirescope_mod._AttachCode(
        clock=clock,
        random_bits=lambda _bits: next(values),
    )
    assert capability.redeem("0000-0000") == "target-not-ready"
    assert capability.activate("target-1") == "00000000"
    assert capability.display_code() == "0000-0000"
    assert capability.redeem("not-a-code") == "malformed-code"
    for _attempt in range(4):
        assert capability.redeem("00000001") == "invalid-code"
    assert capability.redeem("00000001") == "attempts-exhausted"
    assert capability.reissue() == ("cooldown", None)
    clock.value += wirescope_mod.ATTACH_CODE_REISSUE_COOLDOWN_SECONDS
    assert capability.reissue() == ("reissued", "00000001")
    assert capability.redeem("0000-0001") == "redeemed"
    assert capability.redeem("00000001") == "already-redeemed"


def test_expired_code_requires_cooldown_and_reissue_is_bounded():
    clock = MutableClock()
    values = iter([3, 4, 5])
    capability = wirescope_mod._AttachCode(
        clock=clock,
        random_bits=lambda _bits: next(values),
    )
    capability.activate("target-1")
    assert capability.reissue() == ("code-active", None)
    clock.value += wirescope_mod.ATTACH_CODE_TTL_SECONDS
    assert capability.redeem("00000003") == "code-expired"
    assert capability.reissue() == ("cooldown", None)
    clock.value += wirescope_mod.ATTACH_CODE_REISSUE_COOLDOWN_SECONDS
    assert capability.reissue()[0] == "reissued"
    clock.value += wirescope_mod.ATTACH_CODE_TTL_SECONDS
    clock.value += wirescope_mod.ATTACH_CODE_REISSUE_COOLDOWN_SECONDS
    assert capability.reissue()[0] == "reissued"
    clock.value += wirescope_mod.ATTACH_CODE_TTL_SECONDS
    clock.value += wirescope_mod.ATTACH_CODE_REISSUE_COOLDOWN_SECONDS
    assert capability.reissue() == ("reissue-exhausted", None)


def test_rolling_history_evicts_old_frames_and_rejects_oversized_frame():
    history = wirescope_mod._RollingHistory(
        max_frames=2,
        max_bytes=10000,
        frame_max_bytes=1000,
    )
    history.append({"sequence": 1})
    history.append({"sequence": 2})
    history.append({"sequence": 3})
    assert history.frames() == [{"sequence": 2}, {"sequence": 3}]
    assert history.metadata()["dropped_frames"] == 1
    try:
        history.append({"payload": "x" * 1000})
    except wirescope_mod._FrameCapacityError:
        pass
    else:
        raise AssertionError("oversized frames must end the observer path")


def test_pipeline_retains_only_hello_before_attach_and_coalesces_snapshots():
    rendered = []
    history = wirescope_mod._RollingHistory(max_frames=3, max_bytes=10000)
    pipeline = wirescope_mod._ObserverPipeline(
        code_renderer=rendered.append,
        random_bits=lambda _bits: 1,
        history=history,
    ).start()
    observer = PythonObserverSource(
        pipeline.accept_frame,
        lifecycle_consumer=pipeline.accept_lifecycle,
        target_id_factory=lambda: "target-python-01",
        alias_factory=lambda: "5A17C0DE",
    )
    try:
        observer.observe_request("hello", {"protocol": "21.0.0"}, 1)
        observer.observe_result("hello", HELLO, 1)
        wait_for(lambda: pipeline.attach_code)
        assert rendered == ["0000-0001"]

        observer.observe_request("world.setBlock", [1, 2, 3, "stone"], 2)
        observer.observe_result("world.setBlock", None, 2)
        assert pipeline.attach("0000-0001") == "redeemed"
        first = wait_for(pipeline.take_snapshot)
        assert [frame["method"] for frame in first[0]["streams"][0]["frames"]] == [
            "hello",
            "hello",
        ]

        observer.observe_request("build.setWorld", ["nether"], 3)
        observer.observe_result("build.setWorld", None, 3)
        latest = wait_for(pipeline.take_snapshot)
        frames = latest[0]["streams"][0]["frames"]
        assert [frame["method"] for frame in frames][-2:] == [
            "build.setWorld",
            "build.setWorld",
        ]
        assert latest[1]["dropped_frames"] == 1
        observer.connection_closed()
        wait_for(lambda: pipeline.terminal_reason == "target-ended")
    finally:
        pipeline.close()


def test_ingress_overflow_is_nonblocking_and_terminal():
    pipeline = wirescope_mod._ObserverPipeline(
        code_renderer=lambda _code: None,
        ingress_max=1,
    )
    pipeline.accept_frame({"sequence": 1})
    pipeline.accept_frame({"sequence": 2})
    assert pipeline.terminal_reason == "backpressure"
    pipeline.close()


def test_encoded_outbound_queue_replaces_snapshot_and_preserves_terminal():
    outbound = wirescope_mod._EncodedOutboundQueue(max_envelopes=2, max_bytes=10)
    assert outbound.replace_snapshot(b"old")
    assert outbound.replace_snapshot(b"latest")
    assert outbound.append_end(b"end")
    assert outbound.pop() == ("snapshot", b"latest")
    assert outbound.pop() == ("end", b"end")
    assert not outbound.replace_snapshot(b"after-end")


def test_loopback_request_policy_requires_exact_authority_and_origin():
    policy = wirescope_mod._LoopbackRequestPolicy(43123)
    assert policy.authority == "127.0.0.1:43123"
    assert policy.origin == "http://127.0.0.1:43123"
    policy.validate_bootstrap(host=policy.authority)
    policy.validate_bootstrap(host=policy.authority, origin=policy.origin)
    policy.validate_attach(
        host=policy.authority,
        origin=policy.origin,
        content_type="application/json",
        content_length=32,
    )
    for kwargs in (
        {"host": "localhost:43123"},
        {"host": policy.authority, "origin": "http://example.invalid"},
    ):
        try:
            policy.validate_bootstrap(**kwargs)
        except wirescope_mod._RequestBoundaryError:
            pass
        else:
            raise AssertionError("bootstrap must reject authority/origin mismatch")
    try:
        policy.validate_attach(
            host=policy.authority,
            origin=policy.origin,
            content_type="text/plain",
            content_length=1,
        )
    except wirescope_mod._RequestBoundaryError:
        pass
    else:
        raise AssertionError("attach must reject the wrong content type")


class FakeConnection:
    def __init__(self, address, port, debug=False):
        self.address = address
        self.port = port
        self.debug = debug
        self.observer = None
        self.closed = False
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
        self.closed = True
        if self.observer is not None:
            self.observer.connection_closed()


class FakeRuntime:
    def __init__(self):
        self.closed = False
        self.events = []
        self.source = None

    def observer(self):
        self.source = PythonObserverSource(
            lambda frame: self.events.append(("frame", frame)),
            lifecycle_consumer=lambda event, _source: self.events.append(
                ("lifecycle", event)
            ),
        )
        return self.source

    def close(self):
        self.closed = True


def test_minecraft_create_is_opt_in_and_local_descriptor_attaches_before_hello():
    previous_connection = minecraft_mod.Connection
    previous_load_token = minecraft_mod.load_token
    previous_start = wirescope_mod._start_station
    runtimes = []
    minecraft_mod.Connection = FakeConnection
    minecraft_mod.load_token = lambda _server_key: None
    wirescope_mod._start_station = (
        lambda _station: runtimes.append(FakeRuntime()) or runtimes[-1]
    )
    try:
        plain = Minecraft.create(sync_catalog=False, pair=False)
        assert plain.conn.observer is None
        assert plain._observer is None
        plain.close()

        observed = Minecraft.create(
            sync_catalog=False,
            pair=False,
            wirescope=WireScopeStation.local(),
        )
        assert observed.conn.observer is runtimes[0].source
        assert runtimes[0].events[-1] == ("lifecycle", "target-activated")
        observed.close()
        assert runtimes[0].closed
    finally:
        minecraft_mod.Connection = previous_connection
        minecraft_mod.load_token = previous_load_token
        wirescope_mod._start_station = previous_start


def test_wirescope_preflight_failure_warns_and_minecraft_continues():
    previous_connection = minecraft_mod.Connection
    previous_load_token = minecraft_mod.load_token
    previous_start = wirescope_mod._start_station
    minecraft_mod.Connection = FakeConnection
    minecraft_mod.load_token = lambda _server_key: None
    wirescope_mod._start_station = lambda _station: (_ for _ in ()).throw(
        wirescope_mod._WireScopeStartError("fixture unavailable")
    )
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mc = Minecraft.create(sync_catalog=False, pair=False, wirescope=True)
        assert mc.conn.observer is None
        assert len(caught) == 1
        assert caught[0].category is WireScopeWarning
        assert "fixture unavailable" in str(caught[0].message)
        mc.close()
    finally:
        minecraft_mod.Connection = previous_connection
        minecraft_mod.load_token = previous_load_token
        wirescope_mod._start_station = previous_start


def test_station_preflight_starts_loopback_then_opens_secret_free_url():
    class Runtime:
        url = "http://127.0.0.1:43123/"

        def close(self):
            raise AssertionError("successful launch must keep the runtime open")

    runtime = Runtime()
    calls = []
    previous_loopback_start = wirescope_mod._start_loopback_station
    wirescope_mod._start_loopback_station = lambda **_kwargs: runtime
    try:
        result = wirescope_mod._start_station(
            WireScopeStation.local(),
            terminal=Terminal(),
            _app_loader=lambda: object(),
            _browser_launcher=lambda url, **options: calls.append(
                (url, options)
            )
            or True,
        )
        assert result is runtime
        assert calls == [
            (
                "http://127.0.0.1:43123/",
                {"new": 2, "autoraise": True},
            )
        ]
        assert "attach" not in calls[0][0]
        assert "code" not in calls[0][0]
    finally:
        wirescope_mod._start_loopback_station = previous_loopback_start


def test_browser_launch_failure_closes_station_and_remains_fail_open():
    class Runtime:
        url = "http://127.0.0.1:43123/"

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    runtime = Runtime()
    previous_loopback_start = wirescope_mod._start_loopback_station
    wirescope_mod._start_loopback_station = lambda **_kwargs: runtime
    try:
        try:
            wirescope_mod._start_station(
                WireScopeStation.local(),
                terminal=Terminal(),
                _app_loader=lambda: object(),
                _browser_launcher=lambda _url, **_options: False,
            )
        except wirescope_mod._WireScopeStartError as exc:
            assert "browser could not open" in str(exc)
        else:
            raise AssertionError("browser launch failure must fail WireScope")
        assert runtime.closed
    finally:
        wirescope_mod._start_loopback_station = previous_loopback_start


def test_create_failure_closes_wirescope_runtime():
    class FailingConnection:
        def __init__(self, _address, _port, _debug=False):
            raise OSError("connection failed")

    runtime = FakeRuntime()
    previous_connection = minecraft_mod.Connection
    previous_start = wirescope_mod._start_station
    minecraft_mod.Connection = FailingConnection
    wirescope_mod._start_station = lambda _station: runtime
    try:
        try:
            Minecraft.create(wirescope=True)
        except OSError:
            pass
        else:
            raise AssertionError("connection failure must propagate")
        assert runtime.closed
    finally:
        minecraft_mod.Connection = previous_connection
        wirescope_mod._start_station = previous_start
