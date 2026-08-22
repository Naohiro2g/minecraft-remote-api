import socket
import select
import sys
import json
import queue
import threading


DEFAULT_SEND_QUEUE_CAPACITY = 1024
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
_STOP = object()


class _PendingResult:
    """One caller-owned completion for a queued JSON-RPC request."""

    def __init__(self):
        self._event = threading.Event()
        self._result = None
        self._error = None

    def set_result(self, result):
        self._result = result
        self._event.set()

    def set_error(self, error):
        self._error = error
        self._event.set()

    def result(self):
        self._event.wait()
        if self._error is not None:
            raise self._error
        return self._result


class _QueuedCall:
    """A frozen wire command registered in the connection FIFO."""

    def __init__(
        self,
        method,
        params,
        request_id,
        payload,
        pending=None,
        flush_target=None,
    ):
        self.method = method
        self.params = params
        self.request_id = request_id
        self.payload = payload
        self.pending = pending
        self.flush_target = flush_target


class McRemoteError(Exception):
    """Base class for mc_remote client errors."""


class ConnectionLostError(McRemoteError):
    """Raised when the connection to the server is lost.

    Replaces the old ``sys.exit(1)`` so that one failed stream does not take
    down the whole process (build state is scoped per stream)."""


class RequestTimeoutError(ConnectionLostError):
    """A request timed out after transmission; its completion is unknown."""

    completion_unknown = True

    def __init__(self, method):
        self.method = method
        super().__init__(
            f"{method} timed out; completion is unknown and the request "
            "was not retried"
        )


class RequestFailedError(McRemoteError):
    """Kept for backward compatibility. Server failures are now reported as
    :class:`McRpcError` (JSON-RPC error object)."""


class McRpcError(RequestFailedError):
    """A JSON-RPC error object returned by the server.

    The machine-readable discriminator is ``reason`` (carried in
    ``error.data.reason``); ``code`` follows the JSON-RPC numbering
    (structured block/params validation = -32602, world-state = -32000 band).
    UI / AI / tests should branch on ``reason``, not ``code``."""

    def __init__(self, code, message, data=None):
        self.code = code
        self.message = message
        self.data = data or {}
        self.reason = self.data.get("reason")
        super().__init__(self._format(message))

    def _format(self, message):
        head = self.reason if self.reason is not None else self.code
        parts = [f"[{head}]"]
        if message:
            parts.append(str(message))
        for key in (
            "block_id",
            "dimension",
            "pos",
            "property",
            "value",
            "allowed",
            "bounds",
            "violating",
        ):
            if key in self.data:
                parts.append(f"{key}={self.data[key]!r}")
        return " ".join(parts)


class Connection:
    """JSON-RPC 2.0 connection to a Minecraft server (protocol 22.x).

    One instance == one stream == one build state. The wire is line-delimited
    JSON-RPC: one JSON object per line in each direction. Requests and
    notifications share one bounded, thread-safe FIFO so that
    ``connection.flush`` can be a precise barrier."""

    def __init__(
        self,
        address,
        port,
        debug=False,
        *,
        send_queue_capacity=DEFAULT_SEND_QUEUE_CAPACITY,
    ):
        if (
            isinstance(send_queue_capacity, bool)
            or not isinstance(send_queue_capacity, int)
            or send_queue_capacity <= 0
        ):
            raise ValueError("send_queue_capacity must be a positive integer")
        self.address = address
        self.port = port
        self.debug = debug
        self.send_queue_capacity = send_queue_capacity
        self.request_timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS
        self.lastSent = b""
        self._observer = None
        self._close_lock = threading.Lock()
        self._connect()

    def _notify_observer(self, method, *args):
        """Call the optional read-only observer without affecting the wire."""
        observer = self._observer
        callback = getattr(observer, method, None) if observer is not None else None
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            # Observation must never break authentication or building.  Do not
            # include callback values here: they may originate in raw frames.
            if self.debug:
                sys.stderr.write("WireScope observer dropped an event\n")

    def set_observer(self, observer):
        """Attach a transport-neutral observer to the current connection epoch."""
        if self._observer is observer:
            return
        if self._observer is not None:
            self._notify_observer("connection_closed")
        self._observer = observer
        self._notify_observer("connection_opened")

    def _connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10)
        self.socket.connect((self.address, self.port))
        self.socket.settimeout(self.request_timeout)
        self.reader = self.socket.makefile("r")
        self._start_sequencer()

    def _start_sequencer(self):
        """Start a fresh connection-epoch FIFO around the current transport."""

        self.epoch = getattr(self, "epoch", 0) + 1
        self._id = 0
        self._send_queue = queue.Queue(maxsize=self.send_queue_capacity)
        self._enqueue_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._accepting = True
        self._closing = False
        self._closed = False
        self._failure = None
        self._hello_completed = False
        self._notification_serial = 0
        self._flushed_serial = 0
        self._observer_closed = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name=f"mcremote-wire-{self.address}:{self.port}",
            daemon=True,
        )
        self._worker.start()

    def reconnect(self):
        """Open a fresh stream to the same server, resetting the id counter.

        Needed by the b2 auth flow: the server drops the TCP stream after
        rejecting an unauthenticated hello with ``auth_required``, and ``hello``
        is once per connection -- so the client reconnects before pairing and
        again for the authenticated hello."""
        self._close_epoch(flush=False)
        self._connect()
        self._notify_observer("connection_opened")

    def close(self):
        """Flush pending notifications, then close all connection resources.

        Resource reclamation always runs. If the automatic flush cannot prove
        completion, its exception is re-raised after the socket and worker are
        closed.
        """

        self._close_epoch(flush=True)

    def _close_epoch(self, *, flush):
        # A few transport-focused tests construct Connection via __new__ and
        # intentionally exercise the old direct path without a worker.
        if not hasattr(self, "_send_queue"):
            self._close_resources()
            return

        with self._close_lock:
            if self._closed:
                return
            if self.debug:
                sys.stderr.write("Closing connection... ")

            flush_pending = None
            flush_error = None
            with self._enqueue_lock:
                needs_flush = (
                    flush and self._notification_serial > self._flushed_serial
                )
                if needs_flush and self._failure is not None:
                    flush_error = self._copy_failure(self._failure)
                if self._accepting:
                    if needs_flush:
                        if not self._hello_completed:
                            flush_error = McRemoteError(
                                "cannot flush before a successful hello"
                            )
                        else:
                            try:
                                flush_pending = self._enqueue_request_locked(
                                    "connection.flush",
                                    [],
                                    flush_target=self._notification_serial,
                                )
                            except Exception as exc:
                                flush_error = exc
                    self._accepting = False
                    self._closing = True

            if flush_pending is not None:
                try:
                    result = flush_pending.result()
                    if result is not None:
                        raise McRemoteError(
                            "connection.flush success result must be null"
                        )
                except Exception as exc:  # completion failure is reported later
                    flush_error = exc

            self._stop_worker()
            self._close_resources()
            self._closed = True
            if self.debug:
                sys.stderr.write("Connection closed\n")
            if flush_error is not None:
                raise flush_error

    def _stop_worker(self):
        worker = getattr(self, "_worker", None)
        if worker is None or not worker.is_alive():
            return
        self._send_queue.put(_STOP)
        if threading.current_thread() is not worker:
            worker.join()

    def _close_resources(self):
        reader = getattr(self, "reader", None)
        sock = getattr(self, "socket", None)
        if reader is not None:
            try:
                reader.close()
            except Exception as exc:
                if self.debug:
                    sys.stderr.write(f"Failed to close reader: {exc}\n")
        if sock is not None:
            try:
                sock.close()
            except Exception as exc:
                if self.debug:
                    sys.stderr.write(f"Failed to close socket: {exc}\n")
        self._notify_connection_closed_once()

    def _notify_connection_closed_once(self):
        if getattr(self, "_observer_closed", False):
            return
        self._observer_closed = True
        self._notify_observer("connection_closed")

    def is_connected(self):
        """Checks if the connection to the server is still active"""
        if getattr(self, "_failure", None) is not None or getattr(
            self, "_closed", False
        ):
            return False
        try:
            readable, _, _ = select.select([self.socket], [], [], 0)
            if readable:
                data = self.socket.recv(1, socket.MSG_PEEK)
                if not data:
                    return False
            return True
        except (OSError, ValueError):
            return False

    def rpc(self, method, params=None):
        """Send a JSON-RPC request and return its ``result``.

        Raises :class:`McRpcError` if the server returns an error object, or
        :class:`ConnectionLostError` if the stream drops."""
        if not hasattr(self, "_send_queue"):
            return self._rpc_direct(method, params)
        return self._enqueue_request(method, params).result()

    def notify(self, method, params=None):
        """Register an id-less JSON-RPC notification in the connection FIFO.

        The call returns after bounded registration, not after server-side
        execution. Local serialization/queue errors can raise immediately;
        later transport failure is surfaced by the next request or flush.
        """

        if not hasattr(self, "_send_queue"):
            raise McRemoteError("notification requires the connection sequencer")
        with self._enqueue_lock:
            self._ensure_accepting_locked()
            payload, frozen_params = self._freeze_payload(method, params, None)
            self._notification_serial += 1
            call = _QueuedCall(
                method,
                frozen_params,
                None,
                payload,
            )
            try:
                self._put_call_locked(call)
            except Exception:
                self._notification_serial -= 1
                raise
        return None

    def flush(self):
        """Wait for all preceding commands in this connection epoch.

        This is a barrier only. It does not recover individual notification
        results or errors.
        """

        try:
            if not hasattr(self, "_send_queue"):
                result = self._rpc_direct("connection.flush", [])
                if result is not None:
                    raise McRemoteError(
                        "connection.flush success result must be null"
                    )
                return None
            with self._enqueue_lock:
                self._ensure_accepting_locked()
                if not self._hello_completed:
                    raise McRemoteError(
                        "connection.flush requires a successful hello"
                    )
                pending = self._enqueue_request_locked(
                    "connection.flush",
                    [],
                    flush_target=self._notification_serial,
                )
            result = pending.result()
            if result is not None:
                raise McRemoteError(
                    "connection.flush success result must be null"
                )
            return None
        except RequestTimeoutError:
            self._close_epoch(flush=False)
            raise

    def _enqueue_request(self, method, params=None):
        with self._enqueue_lock:
            self._ensure_accepting_locked()
            return self._enqueue_request_locked(method, params)

    def _enqueue_request_locked(self, method, params, *, flush_target=None):
        self._id += 1
        request_id = self._id
        try:
            payload, frozen_params = self._freeze_payload(
                method, params, request_id
            )
        except Exception:
            self._id -= 1
            raise
        pending = _PendingResult()
        call = _QueuedCall(
            method,
            frozen_params,
            request_id,
            payload,
            pending=pending,
            flush_target=flush_target,
        )
        try:
            self._put_call_locked(call)
        except Exception:
            self._id -= 1
            raise
        return pending

    def _put_call_locked(self, call):
        # Timed retries are deliberate. If the worker fails while a producer
        # is applying backpressure, it records failure before taking the
        # enqueue lock; the producer then wakes and releases the lock so the
        # failed queue can be drained without deadlock.
        while True:
            self._ensure_accepting_locked()
            try:
                self._send_queue.put(call, timeout=0.1)
                return
            except queue.Full:
                continue

    def _ensure_accepting_locked(self):
        if self._failure is not None:
            raise self._copy_failure(self._failure)
        if not self._accepting:
            raise ConnectionLostError("Connection is closing or closed")

    @classmethod
    def _freeze_payload(cls, method, params, request_id):
        payload = (
            cls._build_notification(method, params)
            if request_id is None
            else cls._build_request(method, params, request_id)
        )
        request = json.loads(payload.decode("utf8"))
        return payload, request.get("params")

    def _worker_loop(self):
        while True:
            call = self._send_queue.get()
            try:
                if call is _STOP:
                    return
                self._execute_queued_call(call)
                if self._failure is not None:
                    return
            finally:
                self._send_queue.task_done()

    def _execute_queued_call(self, call):
        try:
            if not self.is_connected():
                raise ConnectionLostError("Connection to the server is lost")
            self._notify_observer(
                "observe_request", call.method, call.params, call.request_id
            )
            if self.debug:
                sys.stderr.write(f"-> {call.payload!r}\n")
            self.lastSent = call.payload
            try:
                self.socket.sendall(call.payload)
            except OSError as exc:
                raise ConnectionLostError(
                    f"Failed to send to the server: {exc}"
                ) from exc

            if call.pending is None:
                return

            try:
                line = self.reader.readline()
            except TimeoutError as exc:
                raise RequestTimeoutError(call.method) from exc
            except OSError as exc:
                raise ConnectionLostError(
                    f"Failed to receive from the server: {exc}"
                ) from exc
            if line == "":
                raise ConnectionLostError("Connection closed by server")
            if self.debug:
                sys.stderr.write(f"<- {line!r}")
            try:
                result = self._parse_response(
                    line.rstrip("\n"), call.request_id
                )
            except McRpcError as exc:
                self._notify_observer(
                    "observe_error", call.method, exc, call.request_id
                )
                call.pending.set_error(exc)
                return

            self._notify_observer(
                "observe_result", call.method, result, call.request_id
            )
            if call.method == "hello":
                self._hello_completed = True
            if call.flush_target is not None and result is None:
                with self._state_lock:
                    self._flushed_serial = max(
                        self._flushed_serial, call.flush_target
                    )
            call.pending.set_result(result)
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, McRemoteError)
                else ConnectionLostError(f"Connection failed: {exc}")
            )
            if call.pending is not None:
                call.pending.set_error(failure)
            self._fail_connection(failure)

    def _fail_connection(self, failure):
        with self._state_lock:
            if self._failure is None:
                self._failure = failure
            self._accepting = False
        with self._enqueue_lock:
            while True:
                try:
                    queued = self._send_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if queued is not _STOP and queued.pending is not None:
                        queued.pending.set_error(self._copy_failure(failure))
                finally:
                    self._send_queue.task_done()
        self._notify_connection_closed_once()

    @staticmethod
    def _copy_failure(failure):
        if isinstance(failure, RequestTimeoutError):
            return RequestTimeoutError(failure.method)
        if isinstance(failure, ConnectionLostError):
            return ConnectionLostError(str(failure))
        if isinstance(failure, McRemoteError):
            return McRemoteError(str(failure))
        return ConnectionLostError(str(failure))

    def _rpc_direct(self, method, params=None):
        """Synchronous compatibility path for transport-focused test doubles."""

        if not self.is_connected():
            self._notify_connection_closed_once()
            raise ConnectionLostError("Connection to the server is lost")
        self._id += 1
        req_id = self._id
        payload = self._build_request(method, params, req_id)
        self._notify_observer("observe_request", method, params, req_id)
        if self.debug:
            sys.stderr.write(f"-> {payload!r}\n")
        self.lastSent = payload
        try:
            self.socket.sendall(payload)
            line = self.reader.readline()
        except TimeoutError as exc:
            self._notify_connection_closed_once()
            raise RequestTimeoutError(method) from exc
        except OSError as exc:
            self._notify_connection_closed_once()
            raise ConnectionLostError(f"Failed to talk to the server: {exc}") from exc
        if line == "":
            self._notify_connection_closed_once()
            raise ConnectionLostError("Connection closed by server")
        if self.debug:
            sys.stderr.write(f"<- {line!r}")
        try:
            result = self._parse_response(line.rstrip("\n"), req_id)
        except McRpcError as exc:
            self._notify_observer("observe_error", method, exc, req_id)
            raise
        self._notify_observer("observe_result", method, result, req_id)
        return result

    @staticmethod
    def _build_request(method, params, req_id):
        request = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            request["params"] = params
        return (json.dumps(request, separators=(",", ":")) + "\n").encode("utf8")

    @staticmethod
    def _build_notification(method, params):
        request = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        return (json.dumps(request, separators=(",", ":")) + "\n").encode("utf8")

    @staticmethod
    def _parse_response(line, expected_id):
        try:
            msg = json.loads(line)
        except (ValueError, TypeError) as e:
            raise McRemoteError(f"Invalid JSON-RPC response: {line!r}") from e
        # Surface errors even when id is null (JSON-RPC allows a null id for
        # some server-side failures).
        if "error" in msg:
            err = msg.get("error") or {}
            raise McRpcError(err.get("code"), err.get("message"), err.get("data"))
        if msg.get("id") != expected_id:
            raise McRemoteError(
                f"JSON-RPC id mismatch: expected {expected_id}, got {msg.get('id')}"
            )
        return msg.get("result")
