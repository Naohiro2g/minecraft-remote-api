"""Python consumers of the pinned F1 scripted-peer fixtures."""
import io
import json
from pathlib import Path

import pytest

from mc_remote.connection import Connection, McRpcError
from mc_remote.minecraft import Minecraft

ROOT = Path(__file__).parent / 'fixtures'
SUITES = {name: json.loads((ROOT / f'client-bootstrap-{name}-v23.2.1.json').read_text()) for name in ('framing','hello','pairing','blocks','errors','close')}


class WireSocket:
    def __init__(self):
        self.sent = []
    def sendall(self, data):
        self.sent.append(json.loads(data))
    def close(self):
        pass
    def shutdown(self, how):
        pass


def wire_connection(messages):
    conn = Connection.__new__(Connection)
    conn.socket = WireSocket()
    conn.reader = io.StringIO(''.join(json.dumps(m, ensure_ascii=False) + '\n' if isinstance(m, dict) else m for m in messages))
    conn.debug = False
    conn._id = 0
    conn._observer = None
    conn.is_connected = lambda: True
    return conn


@pytest.mark.parametrize('case', SUITES['hello']['cases'], ids=lambda c:c['id'])
def test_f1_hello(case):
    request = next(s['message'] for s in case['steps'] if s['op']=='client_send')
    replies = [s['message'] for s in case['steps'] if s['op']=='peer_send']
    conn = ScriptedConnection(case) if case["id"] in ("F1-HE-11","F1-HE-12") else wire_connection(replies)
    mc = Minecraft(conn)
    expected = case['expected']
    if expected.get('compatible') is False or 'reason' in expected:
        with pytest.raises(McRpcError) as caught:
            mc.hello(request['params'].get('auth',{}).get('token'))
        if 'reason' in expected:
            assert caught.value.reason == expected['reason']
        if 'application_failure' in expected:
            assert conn.socket.closed and not conn._pending
        if 'error' in replies[0]:
            error = replies[0]['error']
            assert caught.value.code == error['code']
            assert caught.value.message == error['message']
            assert caught.value.data == error['data']
    else:
        reply = mc.hello(request['params'].get('auth',{}).get('token'))
        assert reply == replies[0]['result']
        assert mc.protocol == reply['protocol']
        if 'result' in expected:
            assert reply == expected['result']


def test_f1_framing_non_json_line():
    case = next(c for c in SUITES['framing']['cases'] if c['id']=='F1-FR-06')
    data = b''.join(bytes.fromhex(s['bytes_hex']) for s in case['steps'])
    conn = wire_connection([data.decode()])
    assert conn.rpc('hello', {'protocol':'23.2.1'}) == case['expected']['frames'][0]['result']


@pytest.mark.parametrize('case', SUITES['framing']['cases'], ids=lambda c:c['id'])
def test_f1_framing(case):
    from mc_remote.connection import _JsonRpcFrames
    decoder = _JsonRpcFrames()
    frames = []
    pending = {s['message']['id'] for s in case['steps'] if s['op']=='client_send'}
    matched, ignored = [], []
    for step in case['steps']:
        if step['op']=='peer_bytes':
            frames.extend(decoder.feed(bytes.fromhex(step['bytes_hex'])))
        elif step['op']=='peer_send':
            frame = step['message']
            if decoder.matches(frame, pending):
                matched.append(frame['id'])
                pending.remove(frame['id'])
                Connection._parse_response(json.dumps(frame), frame['id'])
            else:
                ignored.append(frame['id'])
        elif step['op']=='client_send':
            message = step['message']
            assert json.loads(Connection._build_request(message['method'], message.get('params'), message['id'])) == message
    expected = case['expected']
    if 'frames' in expected:
        assert frames == expected['frames']
        assert decoder.tail.hex() == expected['tail_hex']
    else:
        assert matched == expected['matched_ids']
        assert ignored == expected['ignored_ids']
        assert sorted(pending) == expected['pending_ids']


class ScriptedConnection(Connection):
    """Run the production sequencer against the fixture's in-memory peer streams."""
    def __init__(self, case):
        self.plans = []
        for step in case['steps']:
            if step['op']=='connect':
                self.plans.append({'requests': [], 'replies': [], 'eof': False})
            elif step['op']=='client_send':
                self.plans[-1]['requests'].append(step['message'])
            elif step['op']=='peer_send':
                self.plans[-1]['replies'].append(json.dumps(step['message'])+'\n')
            elif step['op']=='peer_bytes':
                self.plans[-1]['replies'].append(bytes.fromhex(step['bytes_hex']).decode())
            elif step['op']=='peer_eof':
                self.plans[-1]['eof'] = True
        self.streams = []
        super().__init__('fixture-only', 0)

    def _connect(self):
        plan = self.plans.pop(0)
        sock = WireSocket()
        sock.closed = False
        sock.close = lambda: setattr(sock, 'closed', True)
        self.socket = sock
        self.reader = io.StringIO(''.join(plan['replies']))
        self.streams.append((plan, sock))
        self._start_sequencer()

    def is_connected(self):
        if self.socket.closed or getattr(self, '_failure', None) is not None:
            return False
        plan, sock = self.streams[-1]
        eof = plan['eof'] and len(sock.sent)>=len(plan['requests']) and self.reader.tell()==len(self.reader.getvalue())
        return not eof

    def assert_requests(self):
        for plan, sock in self.streams:
            assert len(sock.sent) == len(plan['requests'])
            for actual, expected in zip(sock.sent, plan['requests']):
                assert actual['id'] == expected['id']
                assert actual['method'] == expected['method']
                if actual['method']=='hello':
                    # This wire-level consumer may omit optional client/build metadata.
                    assert actual['params'] in (expected['params'], {k:v for k,v in expected['params'].items() if k in ('protocol','auth')})
                else:
                    assert actual['params'] == expected['params']


def as_wire(value):
    from mc_remote.block_value import BlockValue
    if isinstance(value, BlockValue):
        return {'block_id':value.block_id, 'state':dict(value.state)}
    return value


@pytest.mark.parametrize('case', SUITES['blocks']['cases'] + SUITES['errors']['cases'], ids=lambda c:c['id'])
def test_f1_blocks_and_errors(case):
    conn = ScriptedConnection(case)
    mc = Minecraft(conn)
    last, errors = None, []
    try:
        for step in case['steps']:
            if step['op']!='client_send':
                continue
            msg = step['message']
            try:
                if msg['method']=='hello':
                    last = mc.hello(msg['params'].get('auth',{}).get('token'))
                elif msg['method']=='world.getBlock':
                    last = as_wire(mc.getBlock(*msg['params']))
                else:
                    # Malformed BlockSpecs must reach the wire error decoder, not a local builder.
                    last = conn.rpc(msg['method'], msg.get('params'))
            except McRpcError as exc:
                errors.append(exc)
        expected = case['expected']
        if 'result' in expected:
            assert last == expected['result']
        if 'reason' in expected:
            assert errors[-1].reason == expected['reason']
        if 'error' in expected:
            error = expected['error']
            assert (errors[-1].code, errors[-1].message, errors[-1].data) == (error['code'], error['message'], error['data'])
            assert expected['matched_ids'] == [next(s['message']['id'] for s in case['steps'] if s['op']=='peer_send' and 'error' in s['message'])]
        for ref in case.get('value_refs',[]):
            target = json.loads((ROOT/ref['file']).read_text())
            for key in ref['pointer'].split('/')[1:]:
                target = target[key.replace('~1','/').replace('~0','~')]
            assert target  # Resolve the actual shared catalog, preserving its numeric/default-state data.
        conn.assert_requests()
    finally:
        conn.close()


@pytest.mark.parametrize('case', SUITES['pairing']['cases'], ids=lambda c:c['id'])
def test_f1_pairing(case, monkeypatch):
    import mc_remote.minecraft as minecraft
    import mc_remote.auth as auth
    from mc_remote.auth import PairingRequiredError
    conn = ScriptedConnection(case)
    mc = Minecraft(conn)
    initial = next(s['message'] for s in case['steps'] if s['op']=='client_send')
    store = {'key':initial['params'].get('auth',{}).get('token')}
    discarded = []
    monkeypatch.setattr(minecraft, 'load_token', lambda key:store.get(key))
    monkeypatch.setattr(minecraft, 'save_token', lambda key,value:store.update({key:value}))
    def clear(key):
        discarded.append(key)
        store.pop(key, None)
    monkeypatch.setattr(minecraft, 'clear_token', clear)
    monkeypatch.setattr(auth.time, 'sleep', lambda seconds:None)
    begin = next((s['message'] for s in case['steps'] if s['op']=='client_send' and s['message']['method']=='auth.pairBegin'), None)
    if begin:
        monkeypatch.setattr(auth, '_default_client', lambda:begin['params']['client'])
    result, failure = None, None
    try:
        try:
            if case['id']=='F1-AU-03':
                # Deliberately unknown pairing_id is a wire-error case, not an
                # instruction for authenticate() to corrupt its issued ID.
                started = False
                for step in case['steps']:
                    if step['op']=='connect':
                        if started:
                            conn.reconnect()
                        started = True
                    elif step['op']=='client_send':
                        msg = step['message']
                        try:
                            conn.rpc(msg['method'], msg.get('params'))
                        except McRpcError as exc:
                            failure = exc
            elif case['id']=='F1-AU-12':
                for step in case['steps']:
                    if step['op']=='connect' and conn.socket.sent:
                        conn.reconnect()
                    elif step['op']=='client_send':
                        msg=step['message']
                        try:
                            conn.rpc(msg['method'], msg.get('params'))
                        except McRpcError:
                            pass
                        except Exception as exc:
                            assert exc.completion_unknown and not hasattr(exc,'reason')
                            assert msg['id']==case['expected']['unanswered_ids'][0]
                assert not conn._pending
            elif case['id']=='F1-AU-07':
                result = mc._hello_attempt('key',store['key'])
            elif initial['method']=='auth.pairBegin':
                auth.pair(conn, token_type=initial['params']['token_type'], stream=io.StringIO())
            else:
                result = mc.authenticate('key', pair=case['id']!='F1-AU-07')
                if case['id']=='F1-AU-06':
                    conn.reconnect()
                    result = mc.authenticate('key')
        except (McRpcError, PairingRequiredError) as exc:
            failure = exc
        expected = case['expected']
        if 'reason' in expected:
            assert failure is not None and failure.reason == expected['reason']
        else:
            assert failure is None
        if 'result' in expected:
            assert result == expected['result']
        if 'token' in expected:
            assert store['key'] == expected['token']
        if 'discard_token' in expected:
            assert bool(discarded) == expected['discard_token']
        attempts = sum(m['method']=='auth.pairBegin' for _,sock in conn.streams for m in sock.sent)
        if 'pairing_attempts' in expected:
            assert attempts == expected['pairing_attempts']
        if expected.get('pairing_required') is True:
            assert attempts > 0
        if 'error' in expected:
            error = expected['error']
            assert (failure.code, failure.message, failure.data)==(error['code'],error['message'],error['data'])
        if expected.get('pairing_required') is False:
            assert not any(m['method'].startswith('auth.pair') for _,sock in conn.streams for m in sock.sent)
        conn.assert_requests()
    finally:
        conn.close()


@pytest.mark.parametrize('case', SUITES['close']['cases'], ids=lambda c:c['id'])
def test_f1_close(case, monkeypatch):
    from mc_remote.connection import McRemoteError
    import mc_remote.minecraft as minecraft
    if case['steps'][0]['op']=='connect_error':
        def fail(*args, **kwargs):
            raise OSError('fixture connection failure')
        monkeypatch.setattr(minecraft, 'Connection', fail)
        with pytest.raises(OSError):
            Minecraft.create(sync_catalog=False, pair=False)
        assert case['expected']['completed_ids']==[]
        return
    if case['id']=='F1-CL-08':
        from bootstrap_peer import Harness, eventually
        h=Harness(monkeypatch)
        ids=[]
        try:
            for step in case['steps']:
                if step['op']=='connect':
                    h.start('open',h.connect)
                    h.expect_connect(step['connection'])
                elif step['op']=='client_send':
                    msg=step['message']
                    if msg['method']!='hello':
                        ids.append(msg['id'])
                        h.start(str(msg['id']),lambda:h.mc.getBlock(0,0,0))
                    h.expect_send('c1',msg)
                elif step['op']=='peer_send':
                    h.send('c1',step['message'])
                    eventually(lambda:h.calls['open']['done'])
                elif step['op']=='client_close':
                    h.mc.close()
            eventually(lambda:all(h.calls[str(i)]['done'] for i in ids))
            assert ids==case['expected']['unanswered_ids']
            assert [{'id':i,'outcome':'completion_unknown'} for i in ids if h.calls[str(i)]['error'].completion_unknown]==case['expected']['local_failures']
            assert not h.transport._pending and h.peers['c1'].closed
        finally:
            h.finish()
        return
    conn = ScriptedConnection(case)
    completed, unanswered, local_failures = [], [], []
    last = None
    try:
        for step in case['steps']:
            if step['op']=='client_send':
                msg = step['message']
                try:
                    last = conn.rpc(msg['method'],msg.get('params'))
                    completed.append(msg['id'])
                except McRemoteError as exc:
                    unanswered.append(msg['id'])
                    if getattr(exc, "completion_unknown", False):
                        assert not isinstance(exc, McRpcError) and not hasattr(exc, "reason")
                        local_failures.append({"id":msg["id"],"outcome":"completion_unknown"})
            elif step['op']=='client_close':
                conn.close()
            elif step['op']=='connect' and completed:
                conn.reconnect()
        expected = case['expected']
        if 'completed_ids' in expected:
            assert completed==expected['completed_ids']
        if 'unanswered_ids' in expected:
            assert unanswered==expected['unanswered_ids']
        if 'local_failures' in expected:
            assert local_failures==expected['local_failures']
            assert not conn._pending
        if 'pending_ids' in expected:
            assert completed or unanswered
            assert not getattr(conn, '_pending', {})
        if 'result' in expected:
            assert last==expected['result']
        assert conn.is_connected() == (expected['connection']=='open')
    finally:
        conn.close()


def test_f1_pinned_identity_schema_and_54_case_inventory():
    import hashlib
    source = json.loads((ROOT/'client-bootstrap.source.json').read_text())
    assert source['commit']=='335c604f859d6dfad04f0434bfa4eb6445761430'
    for file in source['files']:
        body = (ROOT/file['file']).read_bytes()
        assert len(body)==file['bytes']
        assert hashlib.sha256(body).hexdigest()==file['sha256']
    assert hashlib.sha256((ROOT/'LICENSE').read_bytes()).hexdigest()=='aa329a0bafc839b95124306141db13a381de45818bf629e983c44ea55ab5a7fb'
    schema = json.loads((ROOT/'client-bootstrap-v1.schema.json').read_text())
    ids = []
    for name, fixture in SUITES.items():
        assert set(schema['required'])<=fixture.keys()
        assert fixture['suite']==name
        assert fixture['schema']==schema['properties']['schema']['const']
        for case in fixture['cases']:
            assert set(schema['properties']['cases']['items']['required'])<=case.keys()
            ids.append(case['id'])
    assert len(ids)==len(set(ids))==54
    assert {name:len(f['cases']) for name,f in SUITES.items()}=={'framing':7,'hello':12,'pairing':12,'blocks':12,'errors':3,'close':8}


@pytest.mark.parametrize('case_id', ['F1-HE-04','F1-HE-05'])
def test_create_rejects_protocol_mismatch_without_discarding_token(case_id, monkeypatch):
    import mc_remote.minecraft as minecraft
    case = next(c for c in SUITES['hello']['cases'] if c['id']==case_id)
    conn = ScriptedConnection(case)
    monkeypatch.setattr(minecraft, 'Connection', lambda *args:conn)
    token = next(s['message']['params']['auth']['token'] for s in case['steps'] if s['op']=='client_send')
    monkeypatch.setattr(minecraft, 'load_token', lambda key:token)
    def forbidden(*args, **kwargs):
        pytest.fail('protocol mismatch must not discard, pair, or save a token')
    for name in ['clear_token','save_token','run_pairing']:
        monkeypatch.setattr(minecraft, name, forbidden)
    with pytest.raises(McRpcError) as caught:
        Minecraft.create(pair=True, sync_catalog=False)
    response = next(s['message']['result'] for s in case['steps'] if s['op']=='peer_send')
    assert caught.value.reason=='protocol_mismatch'
    assert caught.value.data['server']==response['protocol']
    assert caught.value.data['client_requires']=='23.2.1'
    assert conn.socket.closed


@pytest.mark.parametrize('code', [-32600,-32000])
def test_peer_protocol_mismatch_preserves_both_versions_for_either_code(code):
    error = {'code':code,'message':'protocol mismatch', 'data':{'reason':'protocol_mismatch','server':'23.1.0','client_requires':'23.2.1'}}
    conn = wire_connection([{'jsonrpc':'2.0','id':1,'error':error}])
    with pytest.raises(McRpcError) as caught:
        Minecraft(conn).hello()
    assert caught.value.reason=='protocol_mismatch'
    assert caught.value.code==code
    assert caught.value.data==error['data']


def test_sequenced_reader_ignores_non_json_and_unknown_id_before_response():
    case = json.loads(json.dumps(SUITES['hello']['cases'][0]))
    conn = ScriptedConnection(case)
    original = conn.reader.getvalue()
    conn.reader = io.StringIO('not-json\n'+json.dumps({'jsonrpc':'2.0','id':99,'error':{'code':-32602,'message':'unknown id'}})+'\n'+original)
    try:
        assert Minecraft(conn).hello()['protocol']=='23.2.1'
    finally:
        conn.close()


def test_tcp_reader_explicitly_uses_utf8(monkeypatch):
    import mc_remote.connection as connection
    recorded = {}
    class Socket(WireSocket):
        def setsockopt(self, *args):
            pass
        def settimeout(self, timeout):
            pass
        def connect(self, address):
            pass
        def makefile(self, mode, **kwargs):
            recorded.update(kwargs)
            return io.StringIO('')
    monkeypatch.setattr(connection.socket, 'socket', lambda *args:Socket())
    conn = Connection('fixture-only', 0)
    try:
        assert recorded.get('encoding')=='utf8'
    finally:
        conn.close()
