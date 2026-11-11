"""E2 decisions which need native tests in addition to F1."""
import io
import threading

import pytest

from mc_remote import auth
from mc_remote.connection import Connection, McRemoteError, McRpcError, RequestTimeoutError
from mc_remote.minecraft import Minecraft, PairingExpiredError
from test_client_bootstrap_fixture import SUITES, ScriptedConnection, WireSocket


def test_client_pairing_expiry_is_local_not_a_synthetic_rpc_error(monkeypatch):
    class Peer:
        def rpc(self, method, params):
            if method == 'auth.pairBegin':
                return {'pairing_id': 'fixture-only', 'pair_code': '000000', 'expires_in': 1}
            return {'status': 'pending'}

    clock = iter([0, 2])
    monkeypatch.setattr(auth.time, 'monotonic', lambda: next(clock))
    with pytest.raises(PairingExpiredError) as caught:
        auth.pair(Peer(), stream=io.StringIO())
    assert not isinstance(caught.value, McRpcError)
    assert not hasattr(caught.value, 'reason') and not hasattr(caught.value, 'code')
    assert caught.value.origin == 'client'


@pytest.mark.parametrize('case_id', ['F1-HE-04', 'F1-HE-05'])
def test_direct_hello_mismatch_closes_before_another_request(case_id):
    case = next(c for c in SUITES['hello']['cases'] if c['id'] == case_id)
    conn = ScriptedConnection(case)
    mc = Minecraft(conn)
    try:
        with pytest.raises(McRpcError):
            mc.hello()
        assert conn.socket.closed
        assert mc._closed
        with pytest.raises(McRemoteError):
            mc.getBlock(0, 0, 0)
        assert [m['method'] for _, sock in conn.streams for m in sock.sent] == ['hello']
    finally:
        conn.close()


@pytest.mark.parametrize('backpressure', [False, True])
def test_close_settles_outstanding_calls_without_waiting_for_peer(backpressure):
    entered = threading.Event()
    release = threading.Event()

    class Reader:
        def readline(self):
            entered.set()
            release.wait(5)
            return ''

        def close(self):
            release.set()

    class Socket(WireSocket):
        def shutdown(self, how):
            release.set()

    conn = Connection.__new__(Connection)
    conn.socket = Socket()
    conn.reader = Reader()
    conn.debug = False
    conn._observer = None
    conn.address = 'fixture-only'
    conn.port = 0
    conn.send_queue_capacity = 1
    conn.request_timeout = 60
    conn._close_lock = threading.Lock()
    conn.is_connected = lambda: True
    conn._start_sequencer()
    first = conn._enqueue_request('fixture.wait', [])
    assert entered.wait(2)
    second = conn._enqueue_request('fixture.queued', [])
    producer = None
    producer_done = threading.Event()
    if backpressure:
        putting = threading.Event()
        put = conn._send_queue.put

        def observed_put(*args, **kwargs):
            putting.set()
            return put(*args, **kwargs)

        conn._send_queue.put = observed_put

        def enqueue_third():
            try:
                conn._enqueue_request('fixture.unsent', [])
            except McRemoteError:
                pass
            finally:
                producer_done.set()

        producer = threading.Thread(target=enqueue_third, daemon=True)
        producer.start()
        assert putting.wait(2)
    closer = threading.Thread(target=conn.close, daemon=True)
    closer.start()
    try:
        assert first._event.wait(1), 'close left the transmitted request hanging'
        assert second._event.wait(1), 'close left the queued call hanging'
        with pytest.raises(McRemoteError) as caught:
            first.result()
        assert caught.value.completion_unknown is True
        assert not isinstance(caught.value, McRpcError)
        assert not hasattr(caught.value, 'reason')
        with pytest.raises(McRemoteError) as queued:
            second.result()
        assert queued.value.completion_unknown is False
        if producer is not None:
            assert producer_done.wait(1), 'close left a queue producer blocked'
    finally:
        release.set()
        closer.join(3)
        if producer is not None:
            producer.join(3)


def test_call_after_failure_is_not_mislabeled_as_completion_unknown():
    conn = Connection.__new__(Connection)
    conn._failure = RequestTimeoutError('previous.call')
    conn._accepting = False
    with pytest.raises(McRemoteError) as caught:
        conn._ensure_accepting_locked()
    assert caught.value.completion_unknown is False
    assert not hasattr(caught.value, 'reason')
