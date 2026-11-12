import pytest
from bootstrap_peer import Harness, eventually

HELLO = {'jsonrpc':'2.0','id':1,'result':{
    'protocol':'23.2.1','mc_version':'1.21.11','supported_mc_versions':['1.21.11'],
    'catalogHash':None,'world_constants':{},'session':'fixture-session','server':'fixture-server',
    'dimension':'minecraft:overworld','origin':[0,0,0]}}


def opened(monkeypatch):
    h = Harness(monkeypatch)
    h.start('open', h.connect)
    p = h.expect_connect('c1')
    p.ready.set()
    assert p.outgoing.get(timeout=3)['method']=='hello'
    h.send('c1', HELLO)
    eventually(lambda:h.calls['open']['done'])
    if 'error' in h.calls['open']:
        raise h.calls['open']['error']
    return h


def test_requests_can_overlap_and_all_sent_calls_settle_on_disconnect(monkeypatch):
    h = opened(monkeypatch)
    try:
        for name in ['a','b']:
            h.start(name, lambda:h.mc.getBlock(0,0,0))
            assert h.peers['c1'].outgoing.get(timeout=1)['method']=='world.getBlock'
        h.peers['c1'].incoming.put(OSError('fixture socket error'))
        eventually(lambda:all(h.calls[n]['done'] for n in ['a','b']))
        assert all(h.calls[n]['error'].completion_unknown for n in ['a','b'])
    finally:
        h.finish()


@pytest.mark.parametrize("dial_failure", [False, True])
def test_real_thread_barrier_shares_one_recovery(monkeypatch, dial_failure):
    import threading
    h=opened(monkeypatch)
    try:
        h.peers['c1'].incoming.put(b'')
        eventually(lambda:h.peers['c1'].closed)
        gate=threading.Barrier(9)
        def read():
            gate.wait(3)
            return h.mc.getBlock(0,0,0)
        for i in range(8): h.start(str(i),read)
        gate.wait(3)
        p=h.expect_connect('c2')
        eventually(lambda:len(h.mc._recovery_condition._waiters)==7)
        if dial_failure:
            from mc_remote.connection import RequestNotSentError
            p.dial_error=OSError('fixture terminal dial error')
            h.clock.advance(h.options.reconnect.budget+1);p.ready.set()
            eventually(lambda:all(h.calls[str(i)]['done'] for i in range(8)))
            assert all(isinstance(h.calls[str(i)]['error'],RequestNotSentError) for i in range(8))
            assert h.dials.empty() and len(h.peers)==2
            return
        p.ready.set()
        hello=p.outgoing.get(timeout=3)
        assert hello['method']=='hello'
        h.send('c2',HELLO)
        requests=[p.outgoing.get(timeout=3) for _ in range(8)]
        assert [r['id'] for r in requests]==list(range(2,10))
        for request in requests:
            h.send('c2',{'jsonrpc':'2.0','id':request['id'],'result':{'block_id':'minecraft:stone','state':{}}})
        eventually(lambda:all(h.calls[str(i)]['done'] for i in range(8)))
        assert all('error' not in h.calls[str(i)] for i in range(8))
        assert h.dials.empty() and len(h.peers)==2 and len(h.events)==1
    finally:
        h.finish()


def test_call_options_extends_connection_idle_budget(monkeypatch):
    from mc_remote.connection import CompletionUnknownError, RequestTimeoutError
    h=opened(monkeypatch)
    try:
        def long_read():
            with h.mc.call_options(response_idle_timeout=16):
                return h.mc.getBlock(0,0,0)
        h.start('long',long_read)
        p=h.peers['c1'];req=p.outgoing.get(timeout=3)
        h.clock.advance(10);h.transport._check_response_timeout()
        assert not h.calls['long']['done']
        h.clock.advance(7);h.transport._check_response_timeout()
        eventually(lambda:h.calls['long']['done'])
        error=h.calls['long']['error']
        assert isinstance(error,RequestTimeoutError) and isinstance(error,CompletionUnknownError)
        assert p.closed and not h.transport._pending
        assert len(p.sent)==2 and req['id']==2
    finally:
        h.finish()


def test_auto_reconnect_can_be_disabled_and_explicit_close_is_terminal(monkeypatch):
    from mc_remote.connection_options import ConnectionOptions, ReconnectOptions
    from mc_remote.connection import RequestNotSentError
    h=Harness(monkeypatch,options=ConnectionOptions(reconnect=ReconnectOptions(enabled=False)))
    try:
        h.start('open',h.connect);p=h.expect_connect('c1');p.ready.set();p.outgoing.get(timeout=3)
        h.send('c1',HELLO);eventually(lambda:h.calls['open']['done'])
        p.incoming.put(b'');eventually(lambda:p.closed)
        with pytest.raises(RequestNotSentError) as error: h.mc.getBlock(0,0,0)
        assert error.value.cause=='reconnect_disabled' and h.dials.empty()
        h.mc.close()
        with pytest.raises(RequestNotSentError): h.mc.getBlock(0,0,0)
        assert h.dials.empty()
    finally:
        h.finish()


def test_pairing_continues_after_lost_poll_then_uses_token_hello(monkeypatch):
    import mc_remote.auth as auth
    h=Harness(monkeypatch);h.store.clear()
    # Absolute clock waits prevent fixture scheduling from moving a sleep later.
    waits=[]
    original=h.clock.wait_until
    def waiting(until):
        waits.append(until)
        original(until)
    h.clock.wait_until=waiting
    try:
        h.start('open',h.connect)
        p1=h.expect_connect('c1');p1.ready.set();assert p1.outgoing.get(timeout=3)['method']=='hello'
        h.send('c1',{'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':'auth required','data':{'reason':'auth_required'}}})
        p1.incoming.put(b'')
        p2=h.expect_connect('c2');p2.ready.set();assert p2.outgoing.get(timeout=3)['method']=='auth.pairBegin'
        h.send('c2',{'jsonrpc':'2.0','id':1,'result':{'pairing_id':'fixture-pairing','pair_code':'123456','expires_in':120}})
        first=p2.outgoing.get(timeout=3)
        h.send('c2',{'jsonrpc':'2.0','id':first['id'],'result':{'status':'pending'}})
        eventually(lambda:len(waits)==1);h.clock.advance(2)
        lost=p2.outgoing.get(timeout=3);assert lost['params']==first['params']
        p2.incoming.put(b'');eventually(lambda:p2.closed and len(waits)==2);h.clock.advance(2)
        p3=h.expect_connect('c3');p3.ready.set();following=p3.outgoing.get(timeout=3)
        assert following['id']==1 and following['method']=='auth.pairPoll' and following['params']==lost['params']
        h.send('c3',{'jsonrpc':'2.0','id':1,'result':{'status':'ok','token':'mcrs_fixture_only_not_a_real_credential'}})
        p4=h.expect_connect('c4');p4.ready.set();hello=p4.outgoing.get(timeout=3)
        assert hello['params']['auth']['token']==h.store['fixture']
        h.send('c4',HELLO);eventually(lambda:h.calls['open']['done'])
        assert 'error' not in h.calls['open']
        assert sum(m['method']=='auth.pairBegin' for p in h.peers.values() for m in p.sent)==1
    finally:
        h.finish()


def test_recovery_invalidates_public_handle_before_entity_command(monkeypatch):
    from mc_remote.minecraft import EntityHandle, StaleEpochError
    h=opened(monkeypatch)
    try:
        handle=h.mc._bind_handle(EntityHandle('mcr_eh_fixture'))
        h.mc._event_cursor=7
        h.peers['c1'].incoming.put(b'');eventually(lambda:h.peers['c1'].closed)
        h.start('pose',lambda:h.mc.getEntityPose(handle))
        p=h.expect_connect('c2');p.ready.set();assert p.outgoing.get(timeout=3)['method']=='hello'
        h.send('c2',HELLO);eventually(lambda:h.calls['pose']['done'])
        assert isinstance(h.calls['pose']['error'],StaleEpochError)
        assert len(p.sent)==1 and h.mc._event_cursor==0
    finally:
        h.finish()


def test_tcp_keepalive_is_configured_separately_from_response_budget(monkeypatch):
    import socket
    h=opened(monkeypatch)
    try:
        applied=h.transport.keepalive_applied
        assert applied['enabled'] is True
        assert (socket.SOL_SOCKET,socket.SO_KEEPALIVE,1) in h.peers['c1'].options
        if hasattr(socket,'TCP_KEEPIDLE'): assert applied['TCP_KEEPIDLE']==60
        if hasattr(socket,'TCP_KEEPCNT'): assert applied['TCP_KEEPCNT']==10
        h.clock.advance(1000);h.transport._check_response_timeout()
        assert not h.peers['c1'].closed and len(h.peers['c1'].sent)==1
    finally:
        h.finish()


@pytest.mark.parametrize('value',[0,-1,True,float('nan'),float('inf')])
def test_connection_options_reject_invalid_idle_budgets(value):
    from mc_remote.connection_options import ConnectionOptions
    with pytest.raises(ValueError): ConnectionOptions(response_idle_timeout=value)


def test_reconnect_backoff_has_jitter_grows_and_stops_at_budget(monkeypatch):
    from dataclasses import replace
    from mc_remote.connection_options import ReconnectOptions
    from mc_remote.connection import RequestNotSentError
    h=opened(monkeypatch)
    try:
        h.transport.options=replace(h.transport.options,reconnect=ReconnectOptions(initial_delay=.5,max_delay=1,budget=1.5))
        factors=iter([.5,1.5]);intervals=[]
        def sample(low,high):
            assert (low,high)==(.5,1.5)
            return next(factors)
        h.mc._backoff_random=sample
        def wait(delay):
            intervals.append(delay);h.clock.advance(delay)
            return False
        h.mc._reconnect_wait=wait
        h.peers['c1'].incoming.put(b'');eventually(lambda:h.peers['c1'].closed)
        h.start('read',lambda:h.mc.getBlock(0,0,0))
        for name in ['c2','c3','c4']:
            p=h.expect_connect(name);p.dial_error=OSError('fixture dial error');p.ready.set()
        eventually(lambda:h.calls['read']['done'])
        assert intervals==[.25,1.25]
        assert isinstance(h.calls['read']['error'],RequestNotSentError)
        assert all(not p.sent for name,p in h.peers.items() if name!='c1')
    finally:
        h.finish()


def test_sender_does_not_inherit_short_receiver_poll_timeout(monkeypatch):
    h=opened(monkeypatch)
    try:
        assert h.peers['c1'].timeout == h.options.response_idle_timeout
    finally:
        h.finish()
