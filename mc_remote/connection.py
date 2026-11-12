import socket
import select
import sys
import json
import queue
import threading
import time

from .connection_options import ConnectionOptions, _response_budget


DEFAULT_SEND_QUEUE_CAPACITY = 1024
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900.0
_STOP = object()


class _PendingResult:
    """One caller-owned completion for a queued JSON-RPC request."""

    def __init__(self):
        self._event = threading.Event()
        self._settle_lock = threading.Lock()
        self.sent = False
        self._result = None
        self._error = None

    def set_result(self, result):
        with self._settle_lock:
            if not self._event.is_set():
                self._result = result
                self._event.set()

    def set_error(self, error):
        with self._settle_lock:
            if not self._event.is_set():
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

    def __init__(self, message, *, completion_unknown=False):
        self.completion_unknown = completion_unknown
        super().__init__(message)


class CompletionUnknownError(ConnectionLostError):
    """A transmitted request may have completed; no server reason is invented."""

    def __init__(self, message='Request completion is unknown'):
        super().__init__(message, completion_unknown=True)


class RequestNotSentError(ConnectionLostError):
    """This call was never transmitted to the server."""

    def __init__(self, message='Request was not sent', *, cause='connection_failed'):
        self.cause = cause
        super().__init__(message)


class RequestTimeoutError(CompletionUnknownError):
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


class _JsonRpcFrames:
    """Incremental LF framing shared by the TCP reader and fixture consumers."""

    def __init__(self):
        self.tail = b""

    def feed(self, data):
        lines = (self.tail + data).split(b"\n")
        self.tail = lines.pop()
        frames = []
        for line in lines:
            try:
                frame = json.loads(line.decode("utf8"))
            except (ValueError, UnicodeError):
                continue
            if isinstance(frame, dict):
                frames.append(frame)
        return frames

    @staticmethod
    def matches(frame, pending_ids):
        try:
            return frame.get("id") in pending_ids or (
                frame.get("id") is None and "error" in frame
            )
        except TypeError:
            return False


class Connection:
    """JSON-RPC 2.0 connection to a Minecraft server (protocol 23.x).

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
        connection_options=None,
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
        self.options = ConnectionOptions() if connection_options is None else connection_options
        if not isinstance(self.options, ConnectionOptions):
            raise TypeError('connection_options must be ConnectionOptions')
        self._clock = getattr(self, '_clock', time.monotonic)
        self.request_timeout = self.options.response_idle_timeout
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
        self.socket.settimeout(self.options.connect_timeout)
        try:
            self.socket.connect((self.address, self.port))
            self._configure_keepalive()
            # Receive polling uses select; never impose its short interval on writes.
            self.socket.settimeout(self.request_timeout)
        except BaseException:
            self.socket.close()
            raise
        self.reader = self.socket.makefile("r", encoding="utf8", newline="")
        self._start_sequencer()

    def _start_sequencer(self):
        """Start a fresh connection-epoch FIFO around the current transport."""

        self.epoch = getattr(self, "epoch", 0) + 1
        self._id = 0
        self._send_queue = queue.Queue(maxsize=self.send_queue_capacity)
        self._enqueue_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending = {}
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
        self._multiplexed = callable(getattr(self.socket, 'recv', None))
        self._last_received = getattr(self, '_clock', time.monotonic)()
        self._waiting_since = self._last_received
        self._worker.start()
        if self._multiplexed:
            self._receiver = threading.Thread(
                target=self._receive_loop, args=(self.epoch,),
                name='mcremote-receive', daemon=True,
            )
            self._receiver.start()

    def _configure_keepalive(self):
        policy = self.options.liveness
        self.keepalive_applied = {}
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, int(policy.enabled))
        self.keepalive_applied['enabled'] = policy.enabled
        if not policy.enabled:
            return
        for names, value in ((('TCP_KEEPIDLE', 'TCP_KEEPALIVE'), policy.idle),
                             (('TCP_KEEPINTVL',), policy.interval),
                             (('TCP_KEEPCNT',), policy.probes)):
            name = next((name for name in names if hasattr(socket, name)), None)
            if name is not None:
                try:
                    self.socket.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)
                    self.keepalive_applied[name] = value
                except OSError:
                    pass
        if hasattr(socket, 'SIO_KEEPALIVE_VALS'):
            try:
                self.socket.ioctl(socket.SIO_KEEPALIVE_VALS, (1, policy.idle * 1000, policy.interval * 1000))
                self.keepalive_applied['SIO_KEEPALIVE_VALS'] = True
            except (OSError, AttributeError):
                pass

    def _receive_loop(self, epoch):
        frames = _JsonRpcFrames()
        while epoch == self.epoch and self._failure is None and not self._closed:
            try:
                if hasattr(self.socket, 'fileno'):
                    readable, _, _ = select.select([self.socket], [], [], 0.1)
                    if not readable:
                        self._check_response_timeout()
                        continue
                data = self.socket.recv(65536)
                if not data:
                    self._fail_connection(CompletionUnknownError('Connection closed by server'))
                    return
                self._last_received = self._clock()
                for frame in frames.feed(data):
                    self._dispatch_response(frame)
            except TimeoutError:
                self._check_response_timeout()
            except OSError:
                if epoch == self.epoch:
                    self._fail_connection(CompletionUnknownError('Socket no longer receives data'))
                return
            except Exception:
                if epoch == self.epoch:
                    self._fail_connection(CompletionUnknownError('Invalid response stream'))
                return

    def _check_response_timeout(self):
        with self._state_lock:
            waiting = [p for p in self._pending.values() if p.sent]
            if not waiting or self._failure is not None:
                return
            budget = max(p.response_timeout for p in waiting)
            expired = self._clock() - max(self._last_received, self._waiting_since) > budget
            method = waiting[0].method
        if expired:
            self._fail_connection(RequestTimeoutError(method))

    def _dispatch_response(self, frame):
        request_id = frame.get('id')
        with self._state_lock:
            try:
                pending = self._pending.get(request_id)
            except TypeError:
                return
            if pending is None and request_id is None and 'error' in frame:
                pending = next((p for p in self._pending.values() if p.sent), None)
                request_id = next((i for i, p in self._pending.items() if p is pending), None)
            if pending is None or not pending.sent:
                return
        try:
            result = self._parse_response(json.dumps(frame), request_id)
        except McRpcError as exc:
            self._notify_observer('observe_error', pending.method, exc, request_id)
            pending.set_error(exc)
            with self._state_lock:
                self._pending.pop(request_id, None)
            return
        self._notify_observer('observe_result', pending.method, result, request_id)
        if pending.method == 'hello':
            self._hello_completed = True
        if pending.flush_target is not None and result is None:
            with self._state_lock:
                self._flushed_serial = max(self._flushed_serial, pending.flush_target)
        callback = getattr(self, '_result_callback', None)
        try:
            if callback is not None:
                callback(pending.method, result)
        except Exception as exc:
            pending.set_error(exc)
        else:
            pending.set_result(result)
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)

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

            # Stop producers before taking the enqueue lock: a producer may
            # hold it while waiting for queue space behind a blocked reply.
            with self._state_lock:
                outstanding = any(
                    not item._event.is_set() for item in self._pending.values()
                )
                was_accepting = self._accepting
                self._accepting = False
                self._closing = True
            if outstanding or not flush:
                failure = ConnectionLostError(
                    "Connection closed; completion is unknown", completion_unknown=True
                )
                self._fail_connection(failure)
                self._shutdown_socket()
                self._stop_worker()
                self._close_resources()
                self._closed = True
                if flush and self._notification_serial > self._flushed_serial:
                    raise failure
                return

            flush_pending = None
            flush_error = None
            with self._enqueue_lock:
                needs_flush = (
                    flush and self._notification_serial > self._flushed_serial
                )
                if needs_flush and self._failure is not None:
                    flush_error = self._copy_failure(self._failure)
                if was_accepting:
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
                                    allow_closing=True,
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
        worker = getattr(self, '_worker', None)
        if worker is not None and worker.is_alive():
            try:
                self._send_queue.put_nowait(_STOP)
            except queue.Full:
                pass
            if threading.current_thread() is not worker:
                worker.join()
        # Graceful close reaches this point only after its flush. Release an
        # idle recv before joining it, including when the sender already died.
        self._shutdown_socket()
        receiver = getattr(self, '_receiver', None)
        if receiver is not None and threading.current_thread() is not receiver:
            receiver.join()

    def _shutdown_socket(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass

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
            if getattr(self, '_multiplexed', False) and not hasattr(socket, 'MSG_DONTWAIT'):
                # The receiver owns reads. Avoid a blocking peek racing it on
                # platforms without a per-call nonblocking recv flag.
                return True
            readable, _, _ = select.select([self.socket], [], [], 0)
            if readable:
                flags = socket.MSG_PEEK | getattr(socket, 'MSG_DONTWAIT', 0)
                try:
                    data = self.socket.recv(1, flags)
                except BlockingIOError:
                    return True
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

    def _enqueue_request_locked(
        self, method, params, *, flush_target=None, allow_closing=False
    ):
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
        pending.method = method
        pending.flush_target = flush_target
        default = getattr(self, 'request_timeout', DEFAULT_REQUEST_TIMEOUT_SECONDS)
        pending.response_timeout = max(default, _response_budget.get() or default)
        call = _QueuedCall(
            method,
            frozen_params,
            request_id,
            payload,
            pending=pending,
            flush_target=flush_target,
        )
        with self._state_lock:
            self._pending[request_id] = pending
        try:
            self._put_call_locked(call, allow_closing=allow_closing)
        except Exception:
            with self._state_lock:
                self._pending.pop(request_id, None)
            self._id -= 1
            raise
        return pending

    def _put_call_locked(self, call, *, allow_closing=False):
        # Timed retries are deliberate. If the worker fails while a producer
        # is applying backpressure, it records failure before taking the
        # enqueue lock; the producer then wakes and releases the lock so the
        # failed queue can be drained without deadlock.
        while True:
            self._ensure_accepting_locked(allow_closing=allow_closing)
            try:
                self._send_queue.put(call, timeout=0.1)
                return
            except queue.Full:
                continue

    def _ensure_accepting_locked(self, *, allow_closing=False):
        if self._failure is not None:
            raise RequestNotSentError(
                "Connection failed before transmission"
            ) from self._failure
        if not self._accepting and not allow_closing:
            raise RequestNotSentError("Connection is closing or closed")

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
                if not self._multiplexed and call is not _STOP and call.pending is not None:
                    with self._state_lock:
                        self._pending.pop(call.request_id, None)
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
            with self._state_lock:
                if self._failure is not None:
                    raise ConnectionLostError("Connection was closed before transmission")
                if call.pending is not None:
                    if not any(item.sent for item in self._pending.values()):
                        self._waiting_since = getattr(self, '_clock', time.monotonic)()
                    call.pending.sent = True
            try:
                self.socket.sendall(call.payload)
            except OSError as exc:
                raise ConnectionLostError(
                    f"Failed to send to the server: {exc}"
                ) from exc

            if call.pending is None or self._multiplexed:
                return

            try:
                result = self._read_response(call.request_id, call.method)
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
            callback = getattr(self, '_result_callback', None)
            if callback is not None:
                callback(call.method, result)
            call.pending.set_result(result)
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, McRemoteError)
                else ConnectionLostError(f"Connection failed: {exc}")
            )
            if isinstance(failure, ConnectionLostError) and call.pending is not None:
                failure.completion_unknown = call.pending.sent
            self._fail_connection(failure)
            if call.pending is not None:
                call.pending.set_error(failure)

    def _fail_connection(self, failure):
        with self._state_lock:
            if self._failure is not None:
                return
            self._failure = failure
            self._accepting = False
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            if item.sent:
                error = self._copy_failure(failure)
                if not isinstance(error, ConnectionLostError):
                    error = CompletionUnknownError("Connection closed; completion is unknown")
                if not isinstance(error, CompletionUnknownError):
                    error = CompletionUnknownError(str(error))
            else:
                error = RequestNotSentError("Connection closed before transmission")
            item.set_error(error)
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
        self._shutdown_socket()
        self._close_resources()
        # Wake an idle sender too; failures discovered while idle must not leak it.
        try:
            self._send_queue.put_nowait(_STOP)
        except queue.Full:
            pass

    @staticmethod
    def _copy_failure(failure):
        if isinstance(failure, RequestTimeoutError):
            return RequestTimeoutError(failure.method)
        if isinstance(failure, CompletionUnknownError):
            return CompletionUnknownError(str(failure))
        if isinstance(failure, RequestNotSentError):
            return RequestNotSentError(str(failure), cause=failure.cause)
        if isinstance(failure, ConnectionLostError):
            return ConnectionLostError(
                str(failure), completion_unknown=failure.completion_unknown
            )
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
        except TimeoutError as exc:
            self._notify_connection_closed_once()
            raise RequestTimeoutError(method) from exc
        except OSError as exc:
            self._notify_connection_closed_once()
            raise ConnectionLostError(f"Failed to talk to the server: {exc}") from exc
        try:
            result = self._read_response(req_id, method)
        except McRpcError as exc:
            self._notify_observer("observe_error", method, exc, req_id)
            raise
        self._notify_observer("observe_result", method, result, req_id)
        return result

    def _read_response(self, request_id, method):
        frames = _JsonRpcFrames()
        while True:
            try:
                line = self.reader.readline()
            except TimeoutError as exc:
                raise RequestTimeoutError(method) from exc
            except OSError as exc:
                raise CompletionUnknownError("Failed to receive from the server") from exc
            if not line:
                raise CompletionUnknownError("Connection closed by server")
            if self.debug:
                sys.stderr.write(f"<- {line!r}")
            for frame in frames.feed(line.encode("utf8")):
                if frames.matches(frame, {request_id}):
                    return self._parse_response(json.dumps(frame), request_id)

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
