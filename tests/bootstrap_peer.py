"""Controllable TCP peer and clock; no client requests or reconnects are synthesized."""
import copy
import json
import queue
import threading
import time
from fractions import Fraction


class Clock:
    def __init__(self):
        self.now = Fraction(0)
        self.condition = threading.Condition()
        self.stopped = False

    def __call__(self):
        with self.condition:
            return float(self.now)

    def advance(self, seconds):
        with self.condition:
            self.now += Fraction(seconds)
            self.condition.notify_all()

    def sleep(self, seconds):
        with self.condition:
            until = self.now + Fraction(seconds)
            self.condition.wait_for(lambda: self.now >= until or self.stopped)

    def wait_until(self, until):
        with self.condition:
            self.condition.wait_for(lambda: self.now >= until or self.stopped)

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()


def eventually(predicate, message='client did not reach expected state'):
    deadline = time.perf_counter() + 3
    while time.perf_counter() < deadline:
        if predicate():
            return
        time.sleep(.002)
    assert predicate(), message


class PeerSocket:
    def __init__(self, harness):
        self.harness = harness
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self.sent = []
        self.closed = False
        self.connected = False
        self.ready = threading.Event()
        self.dial_error = None
        self.timeout = .02
        self.name = None
        self.replies = []
        self.options = []

    def setsockopt(self, *values):
        self.options.append(values)

    def settimeout(self, value):
        self.timeout = value

    def connect(self, endpoint):
        self.harness.dials.put(self)
        assert self.ready.wait(3), 'fixture did not release dial'
        if self.dial_error:
            raise self.dial_error
        self.connected = True

    def sendall(self, data):
        if self.closed:
            raise OSError('fixture peer closed')
        msg = json.loads(data)
        self.sent.append(msg)
        self.outgoing.put(msg)

    def recv(self, size):
        try:
            value = self.incoming.get(timeout=.02)
        except queue.Empty:
            raise TimeoutError
        if isinstance(value, Exception):
            raise value
        return value

    def makefile(self, *args, **kwargs):
        peer = self
        class Reader:
            def readline(self):
                while True:
                    try:
                        return peer.recv(65536).decode()
                    except TimeoutError:
                        pass
            def close(self):
                pass
        return Reader()

    def shutdown(self, how):
        self.incoming.put(b'')

    def close(self):
        self.closed = True
        self.ready.set()
        self.incoming.put(b'')


class Harness:
    def __init__(self, monkeypatch, *, options=None):
        import mc_remote.connection as transport
        import mc_remote.minecraft as minecraft
        from mc_remote.connection_options import ConnectionOptions, ReconnectOptions
        self.clock = Clock()
        self.dials = queue.Queue()
        self.peers = {}
        self.calls = {}
        self.threads = []
        self.mc = None
        self.events = []
        self.options = options or ConnectionOptions(response_idle_timeout=8, reconnect=ReconnectOptions(budget=8))
        self.store = {'fixture': 'mcrs_fixture_only_not_a_real_credential'}
        monkeypatch.setattr(transport.socket, 'socket', lambda *args: PeerSocket(self))
        monkeypatch.setattr(transport.Connection, 'is_connected', lambda c: not c.socket.closed and c._failure is None and not c._closed)
        original = transport.Connection.__init__
        def initialize(conn, *args, **kwargs):
            conn._clock = self.clock
            conn._pair_sleep = self.clock.sleep
            conn._pair_wait_until = self.clock.wait_until
            self.transport = conn
            original(conn, *args, **kwargs)
        monkeypatch.setattr(transport.Connection, '__init__', initialize)
        import mc_remote.auth as auth
        monkeypatch.setattr(auth, '_default_client', lambda:{'name':'fixture-client','version':'2321.1.0','locale':'ja'})
        monkeypatch.setattr(minecraft, 'load_token', lambda key: self.store.get(key))
        monkeypatch.setattr(minecraft, 'save_token', lambda key, value: self.store.update({key:value}))
        monkeypatch.setattr(minecraft, 'clear_token', lambda key: self.store.pop(key, None))

    def start(self, call, fn):
        row = self.calls[call] = {'done':False}
        def run():
            try:
                row['value'] = fn()
            except Exception as exc:
                row['error'] = exc
            finally:
                row['done'] = True
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()

    def connect(self):
        from mc_remote.minecraft import Minecraft
        self.mc = Minecraft.create('fixture-only', 0, token_key='fixture', sync_catalog=False,
                                   connection_options=self.options, on_reconnect=self.events.append,
                                   build={'dimension':'minecraft:overworld','origin':[0,0,0]})
        return self.mc

    def expect_connect(self, name):
        peer = self.dials.get(timeout=3)
        peer.name = name
        self.peers[name] = peer
        return peer

    def expect_send(self, name, expected):
        peer = self.peers[name]
        peer.ready.set()
        actual = peer.outgoing.get(timeout=3)
        if actual['method']=='hello':
            # Client identity is optional metadata, normalized only for equality.
            actual = copy.deepcopy(actual)
            actual['params']['client'] = expected['params']['client']
        assert actual == expected

    def send(self, name, message):
        peer = self.peers[name]
        peer.replies.append(message)
        peer.incoming.put((json.dumps(message)+'\n').encode())
        request_id = message.get('id')
        eventually(lambda: request_id not in getattr(self.transport, '_pending', {}))

    def invoke(self, method, params, mode='DEBUG'):
        from mc_remote.minecraft import BuildMode
        mc = self.mc
        if method=='world.getBlock':
            return mc.getBlock(*params)
        if method=='world.setBlock':
            # Avoid a mode-transition flush; setup chooses execution policy.
            with mc._build_mode_lock:
                mc._build_mode = BuildMode(mode)
            value=params[-1]
            if isinstance(value,dict):
                return mc.setBlock(*params[:-1],value['block_id'],state=value.get('state',{}))
            return mc.setBlock(*params)
        return {'build.setDimension':mc.setDimension, 'build.setOrigin':mc.setBuildOrigin,
                'connection.flush':mc.flush}[method](*params)

    def finish(self):
        self.clock.stop()
        for peer in self.peers.values():
            peer.close()
        for thread in self.threads:
            thread.join(1)
        if self.mc is not None:
            self.mc.conn._close_epoch(flush=False)
