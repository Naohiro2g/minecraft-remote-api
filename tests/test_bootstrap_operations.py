"""Execute every pinned v2 operation against the public Python entry point."""
import json
from fractions import Fraction
from pathlib import Path

import pytest

from bootstrap_peer import Harness, eventually
from mc_remote.auth import PairingExpiredError
from mc_remote.connection import McRpcError, RequestNotSentError

CASES = json.loads((Path(__file__).parent/'fixtures/client-bootstrap-operations-v23.2.1.json').read_text())['cases']


def epoch_name(h, epoch):
    # All epoch changes are actual dials made by the library, not harness calls.
    return list(h.peers)[epoch-1]


def observation(h):
    rows = []
    for name, call in h.calls.items():
        row = {'call':name}
        if not call['done']:
            row.update(outcome='pending', source='client')
        elif 'error' in call:
            exc = call['error']
            if isinstance(exc, McRpcError):
                row.update(outcome='server_error', source='server',
                           error={'code':exc.code,'message':exc.message,'data':exc.data})
            else:
                assert not hasattr(exc, 'code') and not hasattr(exc, 'reason')
                if isinstance(exc, PairingExpiredError):
                    row.update(outcome='pairing_expired', source='client', equivalent_to='pair_expired')
                elif isinstance(exc, RequestNotSentError):
                    row.update(outcome='not_sent', source='client', cause=exc.cause)
                elif getattr(exc, 'completion_unknown', False):
                    row.update(outcome='completion_unknown', source='client')
                else:
                    raise exc
        else:
            row.update(outcome='queued' if call.get('fast') else 'success',
                       source='client' if name=='open' or call.get('fast') else 'server')
            if name!='open' and not call.get('fast'):
                row['connection'] = call['connection']
        rows.append(row)
    connections = []
    conn = getattr(h, 'transport', None)
    for name, peer in h.peers.items():
        current = conn is not None and conn.socket is peer
        with conn._state_lock if hasattr(conn, '_state_lock') else __import__('contextlib').nullcontext():
            pending = [i for i,p in conn._pending.items() if p.sent] if current else []
        connections.append({'connection':name,'state':'failed' if peer.dial_error else 'closed' if peer.closed else 'open',
                            'sent_count':len(peer.sent),'pending_ids':pending})
    events = []
    for info in h.events:
        base = {'connection':epoch_name(h,info.epoch),'previous_connection':epoch_name(h,info.previous_epoch)}
        events.append(dict(base,kind='reconnected'))
        if info.events_lost: events.append(dict(base,kind='events_lost'))
        if info.server_changed: events.append(dict(base,kind='server_changed'))
        if info.session_changed: events.append(dict(base,kind='session_changed'))
    flushes = []
    for call, row in h.calls.items():
        info = row.get('flush_info')
        if info is not None:
            flushes.append({'call':call,'connection':epoch_name(h,info.epoch),
                            'reconnected_since_previous_flush':info.reconnected_since_previous_flush,
                            'excluded_connections':[n for i,n in enumerate(h.peers,1) if i<info.epoch] if info.excludes_previous_epochs else []})
    negotiations = []
    for name, peer in h.peers.items():
        hello = next((r for r in peer.replies if r.get('id')==1 and 'result' in r and isinstance(r['result'],dict) and 'protocol' in r['result']), None)
        if hello:
            incompatible = any(isinstance(r.get('error'), RequestNotSentError) and r['error'].cause=='incompatible_protocol'
                               for r in h.calls.values()) and peer is conn.socket
            negotiations.append({'connection':name,'compatible':not incompatible})
    states, catalogs = [], []
    if h.mc:
        current = epoch_name(h,h.mc.connection_epoch)
        invalid_handles = [v for v,e in h.mc._handle_epochs.items() if e!=h.mc.connection_epoch]
        invalid_cursors = h.seed_cursors if getattr(h, 'seed_epoch', h.mc.connection_epoch)!=h.mc.connection_epoch and h.mc._event_cursor==0 else []
        states.append({'connection':current,'invalidated_handles':invalid_handles,'invalidated_cursors':invalid_cursors})
        if getattr(h, 'seed_hash', None):
            catalogs.append({'connection':current,'hello_hash':h.mc.catalog_hash,
                             'cached_hash':h.seed_hash,'cache_matches':h.mc.catalog_cache_matches})
    return dict(calls=rows,connections=connections,events=events,flushes=flushes,negotiations=negotiations,
                epoch_states=states,catalogs=catalogs,connect_attempts=len(h.peers))


def compare(actual, expected):
    keys={'calls':('call',), 'connections':('connection',), 'flushes':('call','connection'),
          'negotiations':('connection',), 'epoch_states':('connection',), 'catalogs':('connection','cached_hash')}
    for section, value in expected.items():
        if section=='connect_attempts':
            assert actual[section] == value
            continue
        used = set()
        for row in value:
            matched = None
            for index, candidate in enumerate(actual[section]):
                if index in used: continue
                if section=='events':
                    if all(candidate.get(k)==v for k,v in row.items()): matched=(index,candidate);break
                elif all(candidate.get(k)==row.get(k) for k in keys[section]):
                    matched=(index,candidate);break
            assert matched is not None, (section,row,actual[section])
            used.add(matched[0]);candidate=matched[1]
            for k,v in row.items():
                assert k in candidate, (section,k,candidate)
                if k=='pending_ids':
                    assert set(candidate[k])==set(v)
                elif k in ('invalidated_handles','invalidated_cursors','excluded_connections'):
                    assert set(candidate[k])>=set(v)
                else:
                    assert type(candidate[k]) is type(v) and candidate[k]==v, (section,k,v,candidate[k])


def check(h, expected):
    def matches():
        try:
            compare(observation(h), expected)
            return True
        except AssertionError:
            return False
    eventually(matches, repr(expected)+'\n'+repr(observation(h)))
    compare(observation(h),expected)


@pytest.mark.parametrize('case', CASES, ids=lambda c:c['id'])
def test_operations(case, monkeypatch):
    h=Harness(monkeypatch)
    if case['id']=='F1-OP-08': h.store.clear()
    try:
        for step in case['steps']:
            op=step['op'];name=step.get('connection')
            if op=='app_connect':
                h.start(step['call'],h.connect)
            elif op=='app_call':
                call=step['call'];method=step['method'];params=step.get('params',[]);mode=step.get('mode','DEBUG')
                def run(method=method,params=params,mode=mode,call=call):
                    result=h.invoke(method,params,mode)
                    h.calls[call]['connection']=epoch_name(h,h.mc.connection_epoch)
                    if method=='connection.flush': h.calls[call]['flush_info']=h.mc.last_flush
                    return result
                h.start(call,run)
                h.calls[call]['fast']=mode=='FAST'
                h.calls[call]['flush']=method=='connection.flush'
            elif op=='expect_connect':
                h.expect_connect(name)
            elif op=='expect_send':
                h.expect_send(name,step['message'])
            elif op=='peer_send':
                h.send(name,step['message'])
            elif op in ('peer_eof','socket_error','liveness_lost'):
                h.peers[name].incoming.put(b'' if op=='peer_eof' else OSError('fixture transport failed'))
                eventually(lambda:h.peers[name].closed)
            elif op=='connect_error':
                peer=h.peers[name];peer.dial_error=OSError('fixture dial failed')
                h.clock.advance(h.options.reconnect.budget+1);peer.ready.set()
            elif op=='advance_clock':
                ratio=Fraction(step['fraction']['numerator'],step['fraction']['denominator'])
                if step['timer']=='receive_idle': budget=h.options.response_idle_timeout
                else:
                    budget=next(r['result']['expires_in'] for r in h.peers[name].replies if 'expires_in' in r.get('result',{}))
                h.clock.advance(ratio*budget)
                # Process timers at this time without advancing to a future event.
                if hasattr(h.transport,'_check_response_timeout'): h.transport._check_response_timeout()
            elif op=='observe':
                check(h,step['expected'])
            elif op=='seed_epoch_state':
                h.seed_epoch=h.mc.connection_epoch
                for handle in step['entity_handles']:
                    h.mc._handle_epochs[handle]=h.seed_epoch
                h.seed_cursors=step['event_cursors'];h.mc._event_cursor=h.seed_cursors[-1]
                h.seed_hash=step['catalog_hash'];h.mc._catalog_cache_hash=h.seed_hash
            else:
                raise AssertionError(op)
        check(h,case['expected'])
    finally:
        h.finish()


def test_v2_schema_and_inventory():
    root=Path(__file__).parent/'fixtures'
    suite=json.loads((root/'client-bootstrap-operations-v23.2.1.json').read_text())
    schema=json.loads((root/'client-bootstrap-v2.schema.json').read_text())
    assert set(schema['required'])<=suite.keys()
    assert suite['schema']==schema['properties']['schema']['const']
    ids=[case['id'] for case in suite['cases']]
    assert len(ids)==len(set(ids))==12
    assert set(ids)=={f'F1-OP-{i:02}' for i in range(1,13)}
