"""Python-side primitives for the browser-loopback WireScope profile.

The browser application, its immutable artifact manifest, and the exact
observer-session envelope are shared contracts owned with ``@mc-remote/live``.
This module deliberately does not invent those wire shapes.  It provides the
public station descriptor and bounded runtime consumed by the internal
same-origin HTTP adapter.
"""

from __future__ import annotations

import json
import queue
import secrets
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass

from . import _wirescope_station_contract as _station_contract

__all__ = ["WireScopeStation", "WireScopeWarning"]


ATTACH_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ATTACH_CODE_LENGTH = 8
ATTACH_CODE_TTL_SECONDS = 120
ATTACH_CODE_MAX_ATTEMPTS = 5
ATTACH_CODE_MAX_REISSUES = 2
ATTACH_CODE_REISSUE_COOLDOWN_SECONDS = 5

FRAME_MAX_BYTES = 64 * 1024
HISTORY_MAX_FRAMES = 100
HISTORY_MAX_BYTES = 256 * 1024
INGRESS_MAX_EVENTS = 256
OUTBOUND_MAX_ENVELOPES = 16
OUTBOUND_MAX_BYTES = 1024 * 1024
ATTACH_REQUEST_MAX_BYTES = _station_contract.STATION_ATTACH_REQUEST_MAX_BYTES

BOOTSTRAP_PATH = _station_contract.STATION_BOOTSTRAP_PATH
ATTACH_PATH = _station_contract.STATION_ATTACH_PATH


class WireScopeWarning(RuntimeWarning):
    """A non-fatal failure limited to the WireScope observer path."""


class _WireScopeStartError(RuntimeError):
    pass


class _FrameCapacityError(ValueError):
    pass


class _RequestBoundaryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WireScopeStation:
    """Public descriptor selecting a WireScope station profile.

    Only the in-process browser-loopback profile is currently defined.  The
    descriptor is configuration; ``Minecraft.create`` owns the runtime.
    """

    _profile: str

    @classmethod
    def local(cls):
        """Select the in-process browser-loopback reference profile."""

        return cls("browser-loopback")

    def __repr__(self):
        return "WireScopeStation.local()"


def _coerce_station(value):
    if value is None or value is False:
        return None
    if value is True:
        return WireScopeStation.local()
    if not isinstance(value, WireScopeStation):
        raise TypeError(
            "wirescope must be None, a bool, or WireScopeStation.local()"
        )
    if value._profile != "browser-loopback":
        raise ValueError(f"unsupported WireScope station profile: {value._profile}")
    return value


def _compact_json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _encode_attach_code(value):
    chars = []
    for shift in range(35, -1, -5):
        chars.append(ATTACH_CODE_ALPHABET[(value >> shift) & 31])
    return "".join(chars)


def _normalize_attach_code(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if len(normalized) == ATTACH_CODE_LENGTH + 1 and normalized[4] == "-":
        normalized = normalized[:4] + normalized[5:]
    if len(normalized) != ATTACH_CODE_LENGTH:
        return None
    if any(char not in ATTACH_CODE_ALPHABET for char in normalized):
        return None
    return normalized


class _AttachCode:
    """Target-bound, expiring, one-time capability for a single browser."""

    def __init__(
        self,
        *,
        clock=time.monotonic,
        random_bits=secrets.randbits,
        ttl=ATTACH_CODE_TTL_SECONDS,
        max_attempts=ATTACH_CODE_MAX_ATTEMPTS,
        max_reissues=ATTACH_CODE_MAX_REISSUES,
        cooldown=ATTACH_CODE_REISSUE_COOLDOWN_SECONDS,
    ):
        self._clock = clock
        self._random_bits = random_bits
        self._ttl = ttl
        self._max_attempts = max_attempts
        self._max_reissues = max_reissues
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._target_id = None
        self._code = None
        self._expires_at = None
        self._attempts = 0
        self._reissues = 0
        self._cooldown_until = 0
        self._redeemed = False

    def activate(self, target_id):
        with self._lock:
            self._target_id = target_id
            self._reissues = 0
            self._cooldown_until = 0
            self._issue_locked()
            return self._code

    def _issue_locked(self):
        self._code = _encode_attach_code(self._random_bits(40))
        self._expires_at = self._clock() + self._ttl
        self._attempts = 0
        self._redeemed = False

    def display_code(self):
        with self._lock:
            if self._code is None:
                return None
            return f"{self._code[:4]}-{self._code[4:]}"

    def redeem(self, submitted):
        normalized = _normalize_attach_code(submitted)
        if normalized is None:
            return "malformed-code"
        with self._lock:
            now = self._clock()
            if self._redeemed:
                return "already-redeemed"
            if self._target_id is None or self._code is None:
                return "target-not-ready"
            if now >= self._expires_at:
                return "code-expired"
            if normalized != self._code:
                self._attempts += 1
                if self._attempts >= self._max_attempts:
                    self._expires_at = now
                    self._cooldown_until = now + self._cooldown
                    return "attempts-exhausted"
                return "invalid-code"
            self._redeemed = True
            self._code = None
            return "redeemed"

    def reissue(self):
        with self._lock:
            now = self._clock()
            if self._target_id is None:
                return "target-not-ready", None
            if self._redeemed:
                return "already-redeemed", None
            if now < self._expires_at:
                return "code-active", None
            self._cooldown_until = max(
                self._cooldown_until,
                self._expires_at + self._cooldown,
            )
            if self._reissues >= self._max_reissues:
                return "reissue-exhausted", None
            if now < self._cooldown_until:
                return "cooldown", None
            self._reissues += 1
            self._issue_locked()
            return "reissued", self._code

    def invalidate(self):
        with self._lock:
            self._target_id = None
            self._code = None
            self._expires_at = None
            self._redeemed = False


class _RollingHistory:
    """Finite frame window measured using the actual compact JSON bytes."""

    def __init__(
        self,
        *,
        max_frames=HISTORY_MAX_FRAMES,
        max_bytes=HISTORY_MAX_BYTES,
        frame_max_bytes=FRAME_MAX_BYTES,
    ):
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self.frame_max_bytes = frame_max_bytes
        self._items = deque()
        self.encoded_bytes = 0
        self.dropped_frames = 0

    def append(self, frame):
        encoded_size = len(_compact_json_bytes(frame))
        if encoded_size > self.frame_max_bytes:
            raise _FrameCapacityError("observer frame exceeds admission limit")
        self._items.append((frame, encoded_size))
        self.encoded_bytes += encoded_size
        while len(self._items) > self.max_frames or self.encoded_bytes > self.max_bytes:
            _frame, old_size = self._items.popleft()
            self.encoded_bytes -= old_size
            self.dropped_frames += 1

    def frames(self):
        return [frame for frame, _size in self._items]

    def metadata(self):
        return {
            "retained_frames": len(self._items),
            "retained_bytes": self.encoded_bytes,
            "dropped_frames": self.dropped_frames,
        }


class _LatestSnapshot:
    """One replaceable snapshot slot plus one non-replaceable terminal state."""

    def __init__(self):
        self._condition = threading.Condition()
        self._snapshot = None
        self._terminal = None

    def replace(self, snapshot, history_window):
        with self._condition:
            if self._terminal is None:
                self._snapshot = (snapshot, history_window)
                self._condition.notify_all()

    def end(self, reason):
        with self._condition:
            if self._terminal is None:
                self._terminal = reason
                self._condition.notify_all()

    def take_snapshot(self):
        with self._condition:
            value = self._snapshot
            self._snapshot = None
            return value

    def wait(self, timeout):
        with self._condition:
            if self._snapshot is None and self._terminal is None:
                self._condition.wait(timeout)
            value = self._snapshot
            self._snapshot = None
            return value, self._terminal

    @property
    def terminal(self):
        with self._condition:
            return self._terminal


class _EncodedOutboundQueue:
    """Bound pre-encoded output without knowing the shared envelope shape."""

    def __init__(
        self,
        *,
        max_envelopes=OUTBOUND_MAX_ENVELOPES,
        max_bytes=OUTBOUND_MAX_BYTES,
    ):
        self.max_envelopes = max_envelopes
        self.max_bytes = max_bytes
        self._items = deque()
        self.encoded_bytes = 0
        self._terminal = False

    def replace_snapshot(self, encoded):
        if self._terminal:
            return False
        encoded = bytes(encoded)
        retained = deque()
        retained_bytes = 0
        for kind, value in self._items:
            if kind != "snapshot":
                retained.append((kind, value))
                retained_bytes += len(value)
        if len(encoded) > self.max_bytes:
            return False
        retained.append(("snapshot", encoded))
        retained_bytes += len(encoded)
        if len(retained) > self.max_envelopes or retained_bytes > self.max_bytes:
            return False
        self._items = retained
        self.encoded_bytes = retained_bytes
        return True

    def append_end(self, encoded):
        if self._terminal:
            return False
        encoded = bytes(encoded)
        while self._items and (
            len(self._items) + 1 > self.max_envelopes
            or self.encoded_bytes + len(encoded) > self.max_bytes
        ):
            kind, value = self._items.popleft()
            self.encoded_bytes -= len(value)
            if kind != "snapshot":
                return False
        if len(encoded) > self.max_bytes:
            return False
        self._items.append(("end", encoded))
        self.encoded_bytes += len(encoded)
        self._terminal = True
        return True

    def pop(self):
        if not self._items:
            return None
        item = self._items.popleft()
        self.encoded_bytes -= len(item[1])
        return item


class _LoopbackRequestPolicy:
    """Exact-origin checks shared by the future loopback HTTP handler."""

    def __init__(self, port, *, request_max_bytes=ATTACH_REQUEST_MAX_BYTES):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
            raise ValueError("loopback station port must be an integer")
        self.authority = f"127.0.0.1:{port}"
        self.origin = f"http://{self.authority}"
        self.request_max_bytes = request_max_bytes

    @property
    def response_headers(self):
        return dict(_station_contract.STATION_REQUIRED_RESPONSE_HEADERS)

    def validate_bootstrap(self, *, host, origin=None):
        self._validate_host(host)
        if origin is not None and origin != self.origin:
            raise _RequestBoundaryError("origin mismatch")

    def validate_attach(self, *, host, origin, content_type, content_length):
        self._validate_host(host)
        if origin != self.origin:
            raise _RequestBoundaryError("origin mismatch")
        if content_type != _station_contract.STATION_JSON_CONTENT_TYPE:
            raise _RequestBoundaryError("content type must be application/json")
        if (
            isinstance(content_length, bool)
            or not isinstance(content_length, int)
            or content_length < 0
            or content_length > self.request_max_bytes
        ):
            raise _RequestBoundaryError("request body exceeds the attach limit")

    def _validate_host(self, host):
        if host != self.authority:
            raise _RequestBoundaryError("authority mismatch")


class _ObserverPipeline:
    """Non-blocking observer ingress and worker-owned history state."""

    def __init__(
        self,
        *,
        code_renderer,
        clock=time.monotonic,
        random_bits=secrets.randbits,
        ingress_max=INGRESS_MAX_EVENTS,
        history=None,
    ):
        self._queue = queue.Queue(maxsize=ingress_max)
        self._history = history or _RollingHistory()
        self._latest = _LatestSnapshot()
        self._code = _AttachCode(clock=clock, random_bits=random_bits)
        self._code_renderer = code_renderer
        self._source = None
        self._pre_attach_hello = []
        self._attached = False
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="mcremote-wirescope",
            daemon=True,
        )

    def start(self):
        self._thread.start()
        return self

    def accept_frame(self, frame):
        self._put(("frame", frame))

    def accept_lifecycle(self, event, source):
        self._put((event, source))

    def _put(self, item):
        if self._closed.is_set() or self._latest.terminal is not None:
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._code.invalidate()
            self._latest.end("backpressure")

    def attach(self, submitted):
        result = self._code.redeem(submitted)
        if result == "redeemed":
            self._put(("attached", None))
        return result

    def reissue_code(self):
        result, code = self._code.reissue()
        if code is not None:
            self._render_code(code)
        return result

    def _run(self):
        while not self._closed.is_set():
            try:
                event, value = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if self._latest.terminal is not None:
                continue
            if event == "frame":
                self._handle_frame(value)
            elif event == "target-activated":
                self._source = value
                code = self._code.activate(value.target_id)
                self._render_code(code)
            elif event == "attached":
                self._attached = True
                for frame in self._pre_attach_hello:
                    if not self._append(frame):
                        break
                self._pre_attach_hello.clear()
                self._publish()
            elif event == "target-ended":
                self._end("target-ended")
            elif event == "source-closed":
                self._end("source-closed")

    def _handle_frame(self, frame):
        if not self._attached:
            if frame.get("method") == "hello":
                self._pre_attach_hello = (self._pre_attach_hello + [frame])[-2:]
            return
        if self._append(frame):
            self._publish()

    def _append(self, frame):
        try:
            self._history.append(frame)
            return True
        except _FrameCapacityError:
            self._end("capacity-exhausted")
            return False

    def _publish(self):
        if self._source is None or not self._source.active:
            return
        try:
            snapshot = self._source.snapshot(self._history.frames())
        except Exception:
            self._end("source-closed")
            return
        self._latest.replace(snapshot, self._history.metadata())

    def _render_code(self, code):
        try:
            self._code_renderer(f"{code[:4]}-{code[4:]}")
        except Exception:
            self._end("source-closed")

    def _end(self, reason):
        self._code.invalidate()
        self._latest.end(reason)

    def take_snapshot(self):
        return self._latest.take_snapshot()

    def wait_output(self, timeout):
        return self._latest.wait(timeout)

    def new_outbound_queue(self):
        return _EncodedOutboundQueue()

    def end_backpressure(self):
        self._end("backpressure")

    @property
    def terminal_reason(self):
        return self._latest.terminal

    @property
    def attach_code(self):
        return self._code.display_code()

    @property
    def station_ready(self):
        return self.attach_code is not None and self.terminal_reason is None

    def close(self, *, source_closed=True):
        if source_closed:
            self._end("source-closed")
        self._closed.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1)


class _RuntimeHandle:
    """Internal interface consumed by ``Minecraft.create``."""

    def __init__(self, pipeline, http_station=None):
        self.pipeline = pipeline
        self.http_station = http_station
        self.source = None

    @property
    def url(self):
        return None if self.http_station is None else self.http_station.url

    def observer(self):
        from .observer import PythonObserverSource

        source = PythonObserverSource(
            self.pipeline.accept_frame,
            lifecycle_consumer=self.pipeline.accept_lifecycle,
        )
        self.source = source
        return source

    def close(self):
        if self.http_station is None:
            self.pipeline.close()
        else:
            self.http_station.close()


def _start_loopback_station(
    *,
    app,
    terminal,
    clock=time.monotonic,
    random_bits=secrets.randbits,
):
    """Start the internal HTTP profile around an already verified app."""

    from ._wirescope_app import WireScopeApp
    from ._wirescope_http import LoopbackHTTPStation

    if not isinstance(app, WireScopeApp):
        raise TypeError("app must be a verified WireScopeApp")
    pipeline = _ObserverPipeline(
        code_renderer=_terminal_renderer(terminal),
        clock=clock,
        random_bits=random_bits,
    ).start()
    try:
        http_station = LoopbackHTTPStation(
            app=app,
            pipeline=pipeline,
            policy_factory=_LoopbackRequestPolicy,
        )
    except Exception:
        pipeline.close()
        raise
    return _RuntimeHandle(pipeline, http_station)


def _terminal_renderer(stream):
    def render(code):
        stream.write(f"WireScope attach code: {code}\n")
        stream.flush()

    return render


def _start_station(
    station,
    *,
    terminal=None,
    _app_loader=None,
    _browser_launcher=None,
):
    """Preflight and launch the browser-loopback reference profile."""

    if station._profile != "browser-loopback":
        raise _WireScopeStartError("unsupported WireScope station profile")
    stream = terminal if terminal is not None else sys.stderr
    if not getattr(stream, "isatty", lambda: False)():
        raise _WireScopeStartError(
            "an interactive TTY is required to display the attach code"
        )
    from ._wirescope_app import load_bundled_wirescope_app
    from ._wirescope_artifact import WireScopeArtifactError

    app_loader = _app_loader or load_bundled_wirescope_app
    browser_launcher = _browser_launcher or webbrowser.open
    try:
        app = app_loader()
    except WireScopeArtifactError as exc:
        raise _WireScopeStartError(str(exc)) from exc
    try:
        runtime = _start_loopback_station(app=app, terminal=stream)
    except Exception as exc:
        raise _WireScopeStartError("the loopback station could not start") from exc
    try:
        launched = browser_launcher(runtime.url, new=2, autoraise=True)
    except Exception as exc:
        runtime.close()
        raise _WireScopeStartError("the WireScope browser could not open") from exc
    if not launched:
        runtime.close()
        raise _WireScopeStartError("the WireScope browser could not open")
    return runtime
