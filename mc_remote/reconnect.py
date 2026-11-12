"""Minecraft-side recovery of authenticated build state, never RPC replay."""
import copy
import random
import threading
import warnings

from .connection import (ConnectionLostError, RequestNotSentError, McRemoteError,
                         McRpcError)
from .auth import PairingRequiredError
from .connection_options import ReconnectInfo, FlushInfo, call_options


class StaleEpochError(McRemoteError):
    """A handle belongs to an earlier connection epoch."""


class RecoveryMixin:
    def _init_recovery(self):
        self._recovery_condition = threading.Condition()
        self._recovery_running = False
        self._recovery_error = None
        self._recovery_cancel = threading.Event()
        self._reconnect_active = False
        self._on_reconnect = None
        self._hello_build = None
        self._last_hello = {}
        self.last_reconnect = None
        self.last_flush = None
        self._last_flush_epoch = None
        self._handle_epochs = {}
        self._catalog_cache_hash = None
        self._event_lock = threading.RLock()
        self._call_local = threading.local()
        self._backoff_random = random.uniform

    def _bind_handle(self, value):
        epoch = getattr(self._call_local, 'epoch', self.connection_epoch)
        if hasattr(value, '__dict__'):
            value._connection_epoch = epoch
            value._connection_owner = self
        self._handle_epochs[str(value)] = epoch
        return value

    def _check_handle(self, handle):
        epoch = getattr(handle, '_connection_epoch', self._handle_epochs.get(str(handle)))
        owner = getattr(handle, '_connection_owner', self)
        if owner is not self or (epoch is not None and epoch != self.connection_epoch):
            raise StaleEpochError('Entity handle belongs to an earlier connection epoch')

    def _rpc(self, method, params=None):
        if method != 'hello' and not method.startswith('auth.'):
            self._ensure_ready()
        if method.startswith('entity.') and params:
            self._check_handle(params[0])
        self._deliver_reconnect()
        if method == 'events.poll':
            params = [self._event_cursor, *params[1:]]
            self._call_local.after_sequence = self._event_cursor
        epoch = self.connection_epoch
        result = self.conn.rpc(method, params)
        self._call_local.epoch = epoch
        if not hasattr(self.conn, '_send_queue'):
            self._connection_result(method, result)
        return result

    def _connection_result(self, method, result):
        if method in ('build.setDimension', 'build.setOrigin'):
            from .dimension import decode_build_context
            from .vec3 import Vec3
            dimension, origin = decode_build_context(result, method + ' result')
            with self._context_lock:
                self._dimension = dimension
                self._origin = Vec3(*origin)

    def _ensure_ready(self):
        if not self._reconnect_active:
            return
        with self._recovery_condition:
            if self._closed:
                raise RequestNotSentError('Minecraft connection was explicitly closed')
            if self._recovery_running:
                self._recovery_condition.wait_for(lambda: not self._recovery_running)
                if self._recovery_error is not None:
                    raise RequestNotSentError(str(self._recovery_error), cause=self._recovery_error.cause) from self._recovery_error
                return
            if self.conn.is_connected() and self.conn._hello_completed:
                return
            if not self.conn.options.reconnect.enabled:
                raise RequestNotSentError('Automatic reconnection is disabled', cause='reconnect_disabled')
            self._recovery_running = True
            self._recovery_error = None
        error = None
        try:
            self._recover_transport()
        except RequestNotSentError as exc:
            error = exc
            raise
        except Exception as exc:
            error = RequestNotSentError('Recovery failed before transmission')
            raise error from exc
        finally:
            with self._recovery_condition:
                self._recovery_error = error
                self._recovery_running = False
                self._recovery_condition.notify_all()

    def _reconnect_wait(self, delay):
        return self._recovery_cancel.wait(delay)

    def _recover_transport(self):
        policy = self.conn.options.reconnect
        clock = self.conn._clock
        started = clock()
        delay = policy.initial_delay
        old_epoch = self.connection_epoch
        old_hello = copy.deepcopy(self._last_hello)
        old_fast_unknown = self.conn._notification_serial > self.conn._flushed_serial
        with self._context_lock:
            build = {'dimension':self._dimension, 'origin':list(self._origin)}
        while True:
            if self._recovery_cancel.is_set():
                raise RequestNotSentError('Recovery cancelled by close')
            try:
                self.conn.reconnect()
                if self._recovery_cancel.is_set():
                    self.conn._close_epoch(flush=False)
                    raise RequestNotSentError('Recovery cancelled by close')
                self._hello_build = build
                response = self.authenticate(self._server_key, pair=False)
                break
            except PairingRequiredError as exc:
                self.conn._close_epoch(flush=False)
                raise RequestNotSentError('Pairing is required; reconnect did not start pairing', cause='pairing_required') from exc
            except McRpcError as exc:
                self.conn._close_epoch(flush=False)
                cause = 'incompatible_protocol' if exc.reason == 'protocol_mismatch' else 'connection_failed'
                raise RequestNotSentError('Reconnect hello was rejected', cause=cause) from exc
            except (OSError, ConnectionLostError) as exc:
                remaining = policy.budget - (clock() - started)
                if remaining <= 0:
                    raise RequestNotSentError('Reconnect budget exhausted') from exc
                wait = min(remaining, self._backoff_random(.5, 1.5) * delay)
                if self._reconnect_wait(wait):
                    raise RequestNotSentError('Recovery cancelled by close') from exc
                delay = min(policy.max_delay, delay * 2)
            except McRemoteError as exc:
                self.conn._close_epoch(flush=False)
                raise RequestNotSentError('Reconnect hello was invalid') from exc
        self._event_cursor = 0
        self._last_event_batch = None
        self._event_epoch = self.connection_epoch
        info = ReconnectInfo(old_epoch, self.connection_epoch, old_hello, copy.deepcopy(response),
                             old_hello.get('server') != response.get('server'),
                             old_hello.get('session') != response.get('session'),
                             old_hello.get('catalogHash') != response.get('catalogHash'),
                             previous_fast_completion_unknown=old_fast_unknown)
        self.last_reconnect = info
        # Callbacks run after the single-flight gate opens, never under its lock.
        self._pending_reconnect_info = info

    def _deliver_reconnect(self):
        with self._recovery_condition:
            info = getattr(self, '_pending_reconnect_info', None)
            self._pending_reconnect_info = None
        if info is not None and self._on_reconnect is not None:
            try:
                self._on_reconnect(info)
            except Exception:
                warnings.warn('Reconnect observer failed; Minecraft connection is ready', RuntimeWarning, stacklevel=3)

    def _record_flush(self):
        previous = self._last_flush_epoch
        self.last_flush = FlushInfo(self.connection_epoch, previous,
                                    previous is not None and previous != self.connection_epoch)
        self._last_flush_epoch = self.connection_epoch
