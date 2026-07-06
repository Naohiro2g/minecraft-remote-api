"""protocol 21.0.0 b2 auth tests (pairing, hello auth, connect orchestration).

Covers the b2 auth checklist:
  1. auth.pairBegin / auth.pairPoll poll loop (pending -> ok returns the token)
  2. pairBegin params carry ``client`` and NO ``protocol`` (§6.5)
  3. pairing errors (pair_expired / pair_not_found) surface as McRpcError
  4. hello sends ``auth:{token}`` only when a token is held (§6.1)
  5. hello caches session / player / permissions from the §6.2 result
  6. enforcement OFF: token-less hello succeeds, pairing is skipped
  7. enforcement ON: hello -> auth_required -> pair -> token saved -> re-hello
  8. §6.3 discipline: token_* / auth_required re-pair; permission_denied propagates
  9. token store: save/load/clear round-trip, file mode 0600, stored token reused

The Minecraft/auth layer is tested against a fake connection and a temp config
dir; no socket, server, or real filesystem config is touched.
"""
import contextlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote import auth  # noqa: E402
from mc_remote.auth import (  # noqa: E402
    pair,
    is_auth_discard,
    load_token,
    save_token,
    clear_token,
    AUTH_DISCARD_REASONS,
)
from mc_remote.connection import McRpcError  # noqa: E402
from mc_remote.minecraft import Minecraft, PROTOCOL  # noqa: E402


class FakeConn:
    """Records rpc calls and returns canned results (or raises).

    A response may be a single value, an Exception (raised), a callable
    (called with params), or a **list** used as a queue -- one entry consumed
    per call, so a method can answer differently on successive calls (e.g.
    pairPoll pending then ok, or hello failing then succeeding)."""

    def __init__(self, responses):
        self.responses = {k: list(v) if isinstance(v, list) else v
                          for k, v in responses.items()}
        self.calls = []
        self.reconnects = 0

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        r = self.responses[method]
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(params)
        return r

    def reconnect(self):
        self.reconnects += 1

    def close(self):
        pass


@contextlib.contextmanager
def tmp_config():
    """Point token storage at a throwaway dir for the duration."""
    prev = os.environ.get("MCREMOTE_CONFIG_DIR")
    d = tempfile.mkdtemp(prefix="mcremote_test_")
    os.environ["MCREMOTE_CONFIG_DIR"] = d
    try:
        yield d
    finally:
        if prev is None:
            os.environ.pop("MCREMOTE_CONFIG_DIR", None)
        else:
            os.environ["MCREMOTE_CONFIG_DIR"] = prev


HELLO_OK = {
    "protocol": PROTOCOL,
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "world_constants": {"y_sea": 63},
    "session": "sess-1",
    "player": "00000000-0000-0000-0000-000000000001",
    "world": "overworld",
    "origin": [200, 0, 200],
    "permissions": {"online": True, "offline": False, "buildRange": 1000},
}


def _pair_responses(token="mcrs_new", poll=("pending", "ok")):
    """Build begin+poll responses for a pairing sequence."""
    polls = []
    for p in poll:
        polls.append({"status": "ok", "token": token} if p == "ok"
                     else {"status": "pending"})
    return {
        "auth.pairBegin": {"pairing_id": "pid-1", "pair_code": "827419",
                           "expires_in": 120},
        "auth.pairPoll": polls,
    }


# 1. poll loop: pending then ok returns the token
def test_pair_pending_then_ok():
    conn = FakeConn(_pair_responses(token="mcrs_abc", poll=("pending", "ok")))
    token = pair(conn, interval=0, stream=open(os.devnull, "w"))
    assert token == "mcrs_abc", token
    methods = [m for m, _ in conn.calls]
    assert methods == ["auth.pairBegin", "auth.pairPoll", "auth.pairPoll"], methods


# 2. pairBegin carries client, no protocol; token_type default session
def test_pairbegin_params():
    conn = FakeConn(_pair_responses(poll=("ok",)))
    pair(conn, interval=0, stream=open(os.devnull, "w"))
    method, params = conn.calls[0]
    assert method == "auth.pairBegin"
    assert params["token_type"] == "session", params
    assert "protocol" not in params, params
    assert set(params["client"]) == {"name", "version", "locale"}, params["client"]
    # pairPoll correlates by pairing_id only
    assert conn.calls[1] == ("auth.pairPoll", {"pairing_id": "pid-1"}), conn.calls[1]


# 3a. pair_expired surfaces as McRpcError
def test_pair_expired_raises():
    resp = _pair_responses(poll=("pending",))
    resp["auth.pairPoll"] = McRpcError(-32000, "expired", {"reason": "pair_expired"})
    conn = FakeConn(resp)
    try:
        pair(conn, interval=0, stream=open(os.devnull, "w"))
    except McRpcError as e:
        assert e.reason == "pair_expired", e.reason
    else:
        raise AssertionError("expected McRpcError(pair_expired)")


# 3b. pair_not_found surfaces as McRpcError
def test_pair_not_found_raises():
    resp = _pair_responses(poll=("pending",))
    resp["auth.pairPoll"] = McRpcError(-32000, "no", {"reason": "pair_not_found"})
    conn = FakeConn(resp)
    try:
        pair(conn, interval=0, stream=open(os.devnull, "w"))
    except McRpcError as e:
        assert e.reason == "pair_not_found", e.reason
    else:
        raise AssertionError("expected McRpcError(pair_not_found)")


# 4a. hello sends auth:{token} when a token is held
def test_hello_sends_auth_when_token():
    mc = Minecraft(FakeConn({"hello": HELLO_OK}))
    mc.hello("mcrs_xyz")
    method, params = mc.conn.calls[-1]
    assert method == "hello"
    assert params == {"protocol": PROTOCOL, "auth": {"token": "mcrs_xyz"}}, params


# 4b. hello stays {protocol}-only when token-less (enforcement OFF path)
def test_hello_omits_auth_when_none():
    mc = Minecraft(FakeConn({"hello": HELLO_OK}))
    mc.hello()
    assert mc.conn.calls[-1] == ("hello", {"protocol": PROTOCOL}), mc.conn.calls[-1]


# 5. hello caches identity/permissions from the §6.2 result
def test_hello_caches_identity():
    mc = Minecraft(FakeConn({"hello": HELLO_OK}))
    mc.hello()
    assert mc.session == "sess-1"
    assert mc.player == "00000000-0000-0000-0000-000000000001"
    assert mc.permissions == {"online": True, "offline": False, "buildRange": 1000}
    assert mc.y_sea == 63


# 6. enforcement OFF: token-less hello succeeds, pairing never runs
def test_enforcement_off_skips_pairing():
    with tmp_config():
        mc = Minecraft(FakeConn({"hello": HELLO_OK}))  # no auth.* responses
        mc.authenticate("srv:1")
        methods = [m for m, _ in mc.conn.calls]
        assert methods == ["hello"], methods  # would KeyError if pairing ran
        assert mc.conn.calls[0][1] == {"protocol": PROTOCOL}  # no token sent


# 7. enforcement ON: hello -> auth_required -> pair -> save -> re-hello
def test_enforcement_on_pairs_and_retries():
    with tmp_config():
        auth_required = McRpcError(-32000, "auth", {"reason": "auth_required"})
        resp = _pair_responses(token="mcrs_fresh", poll=("ok",))
        resp["hello"] = [auth_required, HELLO_OK]
        mc = Minecraft(FakeConn(resp))
        mc.authenticate("srv:1")
        methods = [m for m, _ in mc.conn.calls]
        assert methods == ["hello", "auth.pairBegin", "auth.pairPoll", "hello"], methods
        # first hello token-less, retry carries the freshly paired token
        assert mc.conn.calls[0][1] == {"protocol": PROTOCOL}
        assert mc.conn.calls[-1][1] == {"protocol": PROTOCOL,
                                        "auth": {"token": "mcrs_fresh"}}
        assert load_token("srv:1") == "mcrs_fresh"  # persisted
        # server drops the stream after auth_required -> reconnect before
        # pairing and before the authenticated hello (two reconnects).
        assert mc.conn.reconnects == 2, mc.conn.reconnects


# 8a. every auth-family reason triggers re-pair
def test_discard_reasons_repair():
    for reason in AUTH_DISCARD_REASONS:
        with tmp_config():
            err = McRpcError(-32000, reason, {"reason": reason})
            resp = _pair_responses(token="mcrs_r", poll=("ok",))
            resp["hello"] = [err, HELLO_OK]
            mc = Minecraft(FakeConn(resp))
            mc.authenticate("srv:1")
            methods = [m for m, _ in mc.conn.calls]
            assert methods == ["hello", "auth.pairBegin", "auth.pairPoll", "hello"], \
                (reason, methods)
            assert is_auth_discard(err), reason


# 8b. permission_denied is authorization, not auth: propagate, no pairing
def test_permission_denied_propagates():
    with tmp_config():
        denied = McRpcError(-32000, "denied", {"reason": "permission_denied"})
        mc = Minecraft(FakeConn({"hello": denied}))
        try:
            mc.authenticate("srv:1")
        except McRpcError as e:
            assert e.reason == "permission_denied", e.reason
        else:
            raise AssertionError("expected permission_denied to propagate")
        methods = [m for m, _ in mc.conn.calls]
        assert methods == ["hello"], methods  # no pairing attempted
        assert not is_auth_discard(denied)


# 8c. protocol_mismatch is not an auth reason -> propagates
def test_protocol_mismatch_propagates():
    with tmp_config():
        mm = McRpcError(-32600, "mismatch", {"reason": "protocol_mismatch"})
        mc = Minecraft(FakeConn({"hello": mm}))
        try:
            mc.authenticate("srv:1")
        except McRpcError as e:
            assert e.reason == "protocol_mismatch", e.reason
        else:
            raise AssertionError("expected protocol_mismatch to propagate")


# 9a. token store round-trip + 0600 file mode
def test_token_store_roundtrip_and_mode():
    with tmp_config():
        assert load_token("srv:1") is None
        save_token("srv:1", "mcrs_stored")
        assert load_token("srv:1") == "mcrs_stored"
        mode = os.stat(auth._token_file()).st_mode & 0o777
        assert mode == 0o600, oct(mode)
        clear_token("srv:1")
        assert load_token("srv:1") is None


# 9b. a stored token is reused: hello carries it, no pairing
def test_stored_token_reused():
    with tmp_config():
        save_token("srv:1", "mcrs_saved")
        mc = Minecraft(FakeConn({"hello": HELLO_OK}))
        mc.authenticate("srv:1")
        methods = [m for m, _ in mc.conn.calls]
        assert methods == ["hello"], methods
        assert mc.conn.calls[0][1] == {"protocol": PROTOCOL,
                                       "auth": {"token": "mcrs_saved"}}


# 9c. per-server keying: token for one server is not used for another
def test_token_keyed_per_server():
    with tmp_config():
        save_token("srv:1", "mcrs_one")
        assert load_token("srv:2") is None
        save_token("srv:2", "mcrs_two")
        assert load_token("srv:1") == "mcrs_one"
        assert load_token("srv:2") == "mcrs_two"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
