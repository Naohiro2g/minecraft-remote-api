import os
import math

from .connection import (
    Connection,
    McRemoteError,
    McRpcError,
    ConnectionLostError,
    RequestFailedError,
)
from .auth import (
    pair as run_pairing,
    is_auth_discard,
    load_token,
    save_token,
    clear_token,
)
from .vec3 import Vec3
from .util import flatten

__all__ = [
    "Minecraft",
    "McRemoteError",
    "McRpcError",
    "ConnectionLostError",
    "RequestFailedError",
    "mcpy",
]


# Wire protocol version this client speaks (sent in the hello handshake and
# checked by the server). Distinct from the PyPI/distribution version.
PROTOCOL = "21.0.0"


def intFloor(*args):
    return [int(math.floor(x)) for x in flatten(args)]


def _env_first(*names):
    for name in names:
        if name in os.environ:
            return os.environ[name]
    return None


class Minecraft:
    """Client for a running Minecraft server speaking protocol 21.x.

    protocol 21.0.0 b2 surface: ``hello`` handshake (now carrying an optional
    ``auth`` token, §6.1) plus ``setBlock`` / ``getBlock`` / ``setBlocks`` over
    block_state_ref strings, ``postToChat`` (wire ``chat.post``), paired-player
    position helpers (``getPos`` / ``setPos``), and the connection-scoped build
    state (``setWorld`` / ``setBuildOrigin``). Tokens are obtained by pairing
    (``auth.pairBegin`` / ``auth.pairPoll``, §6.5);
    :meth:`create` drives the unified connect flow (hello first, pair only on
    ``auth_required``). Every call is an id-bearing JSON-RPC request
    (synchronous result/error); the default send-only notification form for
    setBlock / setBlocks / chat.post arrives in bN/debug integration. The
    legacy MCPI methods (entity / player / camera / events / sign /
    checkpoint / particle ...) were removed in the payload flip and will be
    re-introduced per protocol bump as they are ported to JSON-RPC."""

    def __init__(self, connection):
        self.conn = connection

        # Build state, scoped to this connection/stream (one instance = one
        # stream = one build state). Kept as a local record of what this stream
        # last set; the server is authoritative and applies the origin.
        self._world = "overworld"
        self._origin = Vec3(200, 0, 200)

        # Populated by hello(); the server is the source of truth.
        self.protocol = None
        self.mc_version = None
        self.supported_mc_versions = []
        self.y_sea = None
        self.catalog_hash = None
        self.session = None
        self.player = None
        self.permissions = None

    def hello(self, auth_token=None):
        """Handshake. Declares this client's protocol (and, if held, its auth
        token) and caches the server's hello response on this instance.

        The request sends the client protocol in an object param
        (``{"protocol": ...}``, the §6.1 canonical form); the server rejects a
        missing protocol (``protocol_required``) or a mismatch
        (``protocol_mismatch``). When ``auth_token`` is given it is sent as
        ``auth: {token}`` (§6.1); it is omitted otherwise, so a token-less
        hello stays ``{protocol}``-only and succeeds against a server running
        enforcement OFF. Under enforcement ON a missing/invalid token yields
        ``auth_required`` / ``token_invalid`` (§6.3) -- :meth:`create` catches
        these and pairs.

        The response carries ``protocol``, ``mc_version``,
        ``supported_mc_versions``, ``catalogHash`` (a scalar; ``null`` until a
        catalog lands -> a cache miss), ``world_constants`` (an object bundling
        informational world constants; ``world_constants.y_sea`` as
        ``number | null``, knowledge DECISIONS 2026-07-02-02), the current
        build state (``world`` / ``origin``), and the authenticated
        ``session`` / ``player`` / ``permissions`` (§6.2, the single source for
        identity and permissions). ``y_sea`` is informational only; the
        coordinate formula stays ``absolute_y = origin.y + dy``."""
        params = {"protocol": PROTOCOL}
        if auth_token:
            params["auth"] = {"token": auth_token}
        resp = self.conn.rpc("hello", params)
        if isinstance(resp, dict):
            self.protocol = resp.get("protocol")
            self.mc_version = resp.get("mc_version")
            self.supported_mc_versions = resp.get("supported_mc_versions", [])
            # y_sea lives under world_constants (DECISIONS 2026-07-02-02); no
            # top-level fallback -> an un-flipped server surfaces as None.
            self.y_sea = (resp.get("world_constants") or {}).get("y_sea")
            self.catalog_hash = resp.get("catalogHash")
            self.session = resp.get("session")
            self.player = resp.get("player")
            self.permissions = resp.get("permissions")
            if resp.get("world"):
                self._world = resp["world"]
            origin = resp.get("origin")
            if isinstance(origin, (list, tuple)) and len(origin) == 3:
                self._origin = Vec3(*origin)
        return resp

    def setBlock(self, x, y, z, block):
        """Set one block at (x, y, z) to a block_state_ref string, e.g.
        ``"minecraft:oak_log[axis=y]"``. The namespace is required; the input
        may omit/reorder state properties (the server canonicalises)."""
        coords = intFloor(x, y, z)
        return self.conn.rpc("world.setBlock", coords + [block])

    def getBlock(self, x, y, z):
        """Get the block at (x, y, z) as a canonical full block_state_ref
        string (all properties, names alphabetical) => round-trips with
        setBlock by string equality."""
        coords = intFloor(x, y, z)
        return self.conn.rpc("world.getBlock", coords)

    def setBlocks(self, x0, y0, z0, x1, y1, z1, block):
        """Set a cuboid (x0,y0,z0)-(x1,y1,z1) to a block_state_ref string.
        Validation is all-or-nothing: a single invalid ref rejects the whole
        request."""
        coords = intFloor(x0, y0, z0, x1, y1, z1)
        return self.conn.rpc("world.setBlocks", coords + [block])

    def setWorld(self, dimension):
        """Set the build world/dimension (overworld, nether, end, or an exact
        world name). Build state is scoped to this connection/stream."""
        result = self.conn.rpc("build.setWorld", [dimension])
        self._world = dimension
        return result

    def setBuildOrigin(self, x, y, z):
        """Set the build origin (x, y, z). Default is (200, 0, 200).
        Coordinates are absolute; no implicit Y offset is applied (abs y =
        origin y + dy)."""
        coords = intFloor(x, y, z)
        result = self.conn.rpc("build.setOrigin", coords)
        self._origin = Vec3(*coords)
        return result

    def postToChat(self, message):
        """Post a chat message to the server (wire method ``chat.post``)."""
        return self.conn.rpc("chat.post", [message])

    def getPos(self):
        """Get the paired player's current world and position.

        Returns ``{"world": ..., "pos": [x, y, z]}``, with ``pos`` expressed
        relative to this stream's build origin. The target player is the
        authenticated/pair-bound player; the client never sends a player name.
        """
        return self.conn.rpc("player.getPos", [])

    def setPos(self, world, x, y, z):
        """Move the paired player to a world and origin-relative position.

        ``world`` is explicit and does not depend on this stream's build world.
        The server applies ``absolute = stream.origin + [x, y, z]`` and returns
        the same shape as :meth:`getPos`.
        """
        coords = intFloor(x, y, z)
        return self.conn.rpc("player.setPos", [world] + coords)

    def close(self):
        """Close the connection to the Minecraft server"""
        self.conn.close()
        return True

    def authenticate(self, server_key, token_type="session", pair=True):
        """Run the unified b2 auth flow (§6.5) and return the hello response.

        Tries ``hello`` first, reusing a stored token for ``server_key`` if one
        exists. Under enforcement OFF a token-less hello just succeeds and
        pairing never runs. Under ON (or when the stored token is stale) the
        server answers with an auth-family reason (§6.3); we discard the bad
        token, pair once (printing the pair code to stdout and blocking until
        the player approves), persist the fresh token, and retry hello exactly
        once. Non-auth errors (``permission_denied``, ``protocol_mismatch``)
        propagate. ``pair=False`` disables the interactive pairing fallback."""
        token = load_token(server_key)
        try:
            return self.hello(token)
        except McRpcError as e:
            if not (pair and is_auth_discard(e)):
                raise
            # Auth-family failure: drop the bad token and pair. The server
            # drops the stream after auth_required (hello is once per
            # connection), so reconnect before pairing and again for the
            # authenticated hello.
            clear_token(server_key)
            self.conn.reconnect()
            token = run_pairing(self.conn, token_type=token_type)
            save_token(server_key, token)
            self.conn.reconnect()
            return self.hello(token)

    @staticmethod
    def create(
        address="localhost",
        port=25575,
        debug=False,
        handshake=True,
        sandbox=None,
        token_type="session",
        pair=True,
        token_key=None,
    ):
        """Connect and run the unified b2 auth flow (§6.5).

        Tries ``hello`` first, reusing a stored token if one exists for this
        server. Under enforcement OFF a token-less hello just succeeds and
        pairing never runs. Under ON (or when the stored token is stale) the
        server answers with an auth-family reason; we discard the bad token,
        pair once (printing the pair code to stdout and blocking until the
        player approves), persist the fresh token, and retry hello. Non-auth
        errors (``permission_denied``, ``protocol_mismatch``) propagate. Set
        ``pair=False`` to disable the interactive pairing fallback.

        ``token_key`` controls the local token-store entry. By default it is
        ``"{address}:{port}"``. ``sandbox`` is kept as a compatibility alias for
        this local key only; it is never sent in ``hello.params`` (§6.1)."""
        env_host = _env_first("MCREMOTE_API_HOST", "JRP_API_HOST")
        if env_host is not None:
            address = env_host
        env_port = _env_first("MCREMOTE_API_PORT", "JRP_API_PORT")
        if env_port is not None:
            try:
                port = int(env_port)
            except ValueError:
                pass
        mc = Minecraft(Connection(address, port, debug))
        if handshake:
            server_key = token_key or sandbox or f"{address}:{port}"
            mc.authenticate(server_key, token_type=token_type, pair=pair)
        return mc


def mcpy(func):
    # these will be created as global variable in module, so not good idea
    # func.__globals__['mc'] = Minecraft.create()
    func.__doc__ = ("_mcpy :" + func.__doc__) if func.__doc__ else "_mcpy "
    return func


if __name__ == "__main__":
    mc = Minecraft.create()
    mc.setBlock(0, 0, 0, "minecraft:stone")
    print(mc.getBlock(0, 0, 0))
