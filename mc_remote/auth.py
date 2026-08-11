"""b2 authentication: pairing flow, token storage, and auth reason sets.

protocol 21.0.0 b2 introduces token auth on the ``hello`` handshake. A token is
obtained out of band by *pairing*: ``auth.pairBegin`` returns a short human
``pair_code`` that the player types in Minecraft (``/mcremote pair <code>``),
and ``auth.pairPoll`` is polled until the server hands back the token
(wire-format §6.5, DECISIONS 2026-07-04-06).

The client contract (§6.5) is a single path: try ``hello`` first (with a stored
token if we have one) and only pair when the server answers ``auth_required``.
This unifies enforcement OFF (token-less hello succeeds, pairing auto-skipped)
and ON (missing/invalid token -> ``auth_required``/``token_invalid`` -> pair).
The orchestration lives in ``minecraft.create()``; this module provides the
pieces it composes: token persistence, the ``pair()`` poll loop, and the reason
classification that decides discard-vs-keep.
"""
import json
import locale
import os
import sys
import time

from .connection import McRemoteError, McRpcError


class PairingRequiredError(McRemoteError):
    """Authentication cannot continue because interactive pairing is off."""

    def __init__(self, reason=None):
        self.reason = reason
        suffix = f" (server reason: {reason})" if reason else ""
        super().__init__(
            "Minecraft pairing is required but pair=False disables it"
            f"{suffix}. Retry with pair=True in an interactive session, "
            "or provide a credential before running this non-interactively."
        )


# §6.3 authentication family: any of these means the token (if any) is no good
# -> discard it and re-pair. ``permission_denied`` is deliberately excluded: it
# is authorization (keep the token, the operation alone was refused). Version
# mismatch stays isolated as ``protocol_mismatch`` (§8), not an auth reason.
AUTH_DISCARD_REASONS = frozenset(
    {
        "token_expired",
        "token_revoked",
        "token_not_found",
        "token_invalid",
        "auth_required",
    }
)


def is_auth_discard(err):
    """True if ``err`` (an :class:`McRpcError`) is an auth-family failure whose
    remedy is to discard the current token and re-pair (§6.3)."""
    return isinstance(err, McRpcError) and err.reason in AUTH_DISCARD_REASONS


# --- token storage -------------------------------------------------------

def config_dir():
    """The mcremote config directory. ``MCREMOTE_CONFIG_DIR`` overrides;
    otherwise ``$XDG_CONFIG_HOME/mcremote`` then ``~/.config/mcremote``."""
    override = os.environ.get("MCREMOTE_CONFIG_DIR")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "mcremote")


def _token_file():
    return os.path.join(config_dir(), "token.json")


def _read_all():
    """Load the whole token map; tolerate a missing or corrupt file."""
    try:
        with open(_token_file(), "r", encoding="utf8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_token(server_key):
    """Return the stored token for ``server_key``, or ``None``."""
    token = _read_all().get(server_key)
    return token if isinstance(token, str) and token else None


def save_token(server_key, token):
    """Persist ``token`` for ``server_key`` (file mode 0600, dir 0700).

    Written via a temp file + atomic replace so a crash can't truncate the
    store, and chmod'd before the token lands so it is never briefly world
    readable."""
    directory = config_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    data = _read_all()
    data[server_key] = token
    tmp = _token_file() + ".tmp"
    # Create the temp file with 0600 from the start (umask-independent).
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as fh:
            json.dump(data, fh)
    except Exception:
        try:
            os.unlink(tmp)
        finally:
            raise
    os.replace(tmp, _token_file())


def clear_token(server_key):
    """Remove the stored token for ``server_key`` (no-op if absent)."""
    data = _read_all()
    if server_key in data:
        del data[server_key]
        if data:
            tmp = _token_file() + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf8") as fh:
                json.dump(data, fh)
            os.replace(tmp, _token_file())
        else:
            try:
                os.unlink(_token_file())
            except OSError:
                pass


# --- pairing -------------------------------------------------------------

def _dist_version():
    try:
        from importlib.metadata import version, PackageNotFoundError

        try:
            return version("minecraft-remote-api")
        except PackageNotFoundError:
            return "unknown"
    except Exception:
        return "unknown"


def _default_client():
    try:
        loc = locale.getlocale()[0] or "en"
    except Exception:
        loc = "en"
    return {"name": "mc_remote", "version": _dist_version(), "locale": loc}


def _display_pair_code(pair_code):
    pair_code = str(pair_code)
    if len(pair_code) == 6 and pair_code.isascii() and pair_code.isdigit():
        return f"{pair_code[:3]}-{pair_code[3:]}"
    return pair_code


def pair(conn, *, token_type="session", client=None, interval=1.5, stream=None):
    """Run the pairing flow and return a fresh token (§6.5).

    ``auth.pairBegin`` yields a 6-digit ``pair_code`` which is printed with
    instructions to ``stream`` (stdout by default); the player runs the shown
    ``/mcremote pair NNN-NNN`` command in Minecraft. We then poll
    ``auth.pairPoll`` at
    ``interval`` seconds until ``result.status == "ok"`` (``"pending"`` is not
    an error). ``pair_expired`` / ``pair_not_found`` surface as
    :class:`McRpcError`; exceeding ``expires_in`` is treated as ``pair_expired``.

    Only the token is returned -- ``player`` / ``permissions`` / ``world`` /
    ``origin`` come from the subsequent ``hello`` result, the single source
    (§6.2)."""
    if stream is None:
        stream = sys.stdout
    begin = conn.rpc(
        "auth.pairBegin",
        {"token_type": token_type, "client": client or _default_client()},
    )
    pairing_id = begin["pairing_id"]
    pair_code = begin["pair_code"]
    display_code = _display_pair_code(pair_code)
    expires_in = begin.get("expires_in")

    stream.write(
        "\nMinecraft pairing required.\n"
        f"  Run this in Minecraft:  /mcremote pair {display_code}\n"
    )
    if expires_in:
        stream.write(f"  (code expires in {expires_in}s)\n")
    stream.write("Waiting for approval...\n")
    stream.flush()

    deadline = time.monotonic() + expires_in if expires_in else None
    while True:
        poll = conn.rpc("auth.pairPoll", {"pairing_id": pairing_id})
        status = poll.get("status")
        if status == "ok":
            return poll["token"]
        # status == "pending" (or anything non-terminal): keep waiting.
        if deadline is not None and time.monotonic() >= deadline:
            raise McRpcError(-32000, "pairing code expired", {"reason": "pair_expired"})
        time.sleep(interval)
