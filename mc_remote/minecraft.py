import os
import math
import warnings

from .connection import (
    Connection,
    McRemoteError,
    McRpcError,
    ConnectionLostError,
    RequestFailedError,
)
from .auth import (
    PairingRequiredError,
    pair as run_pairing,
    is_auth_discard,
    load_token,
    save_token,
    clear_token,
)
from . import catalog as _catalog
from . import _constants_codegen
from . import projection as _projection
from .observer import PythonObserverSource
from .vec3 import Vec3
from .util import flatten

__all__ = [
    "Minecraft",
    "McRemoteError",
    "McRpcError",
    "ConnectionLostError",
    "RequestFailedError",
    "PairingRequiredError",
    "CatalogProjectionError",
    "CatalogProjectionWarning",
    "mcpy",
]


# Wire protocol version this client speaks (sent in the hello handshake and
# checked by the server). Distinct from the PyPI/distribution version.
PROTOCOL = "21.0.0"

CatalogProjectionError = _projection.CatalogProjectionError
CatalogProjectionWarning = _projection.CatalogProjectionWarning


def intFloor(*args):
    return [int(math.floor(x)) for x in flatten(args)]


def _env_first(*names):
    for name in names:
        if name in os.environ:
            return os.environ[name]
    return None


class Minecraft:
    """Client for a running Minecraft server speaking protocol 21.x.

    protocol 21.0.0 b3 surface: ``hello`` handshake (carrying an optional
    ``auth`` token, §6.1) plus ``setBlock`` / ``getBlock`` / ``setBlocks`` over
    block_state_ref strings, ``postToChat`` (wire ``chat.post``), paired-player
    position helpers (``getPos`` / ``setPos``), the connection-scoped build
    state (``setWorld`` / ``setBuildOrigin``), and the live block/entity/
    particle catalog (``getCatalog`` / ``sync_constants``, wire ``catalog.get``,
    §7.2.1). Tokens are obtained by pairing (``auth.pairBegin`` /
    ``auth.pairPoll``, §6.5); :meth:`create` drives the unified connect flow
    (hello first, pair only on ``auth_required``, then sync the catalog if one
    is advertised). Every call is an id-bearing JSON-RPC request (synchronous
    result/error); the default send-only notification form for setBlock /
    setBlocks / chat.post arrives in bN/debug integration. The legacy MCPI
    methods (entity / player / camera / events / sign / checkpoint / particle
    ...) were removed in the payload flip and will be re-introduced per
    protocol bump as they are ported to JSON-RPC."""

    def __init__(self, connection):
        self.conn = connection
        self._observer = None
        self._server_key = None
        self._catalog_connection_factory = None
        self._catalog_endpoint = (
            getattr(connection, "address", None),
            getattr(connection, "port", None),
            getattr(connection, "debug", False),
        )

        # Build state, scoped to this connection/stream (one instance = one
        # stream = one build state). Kept as a local record of what this stream
        # last set; the server is authoritative and applies the origin.
        self._world = "overworld"
        self._origin = Vec3(200, 0, 200)

        # Populated by hello(); the server is the source of truth.
        self.protocol = None
        self.mc_version = None
        self.supported_mc_versions = []
        self.world_constants = {}
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
        informational world constants; currently just ``y_sea`` as
        ``number | null``, knowledge DECISIONS 2026-07-02-02, but a forward
        compatible bucket -- a future bN may add more dimension/generation
        facts such as ``y_ground``/``y_lava``/``y_cloud``/``steve_min_y``/
        ``steve_max_y`` without an envelope change; this client caches the
        whole object, not just ``y_sea``, so those show up in
        :meth:`sync_constants`'s generated ``world_info`` as soon as the
        server sends them), the current build state (``world`` / ``origin``),
        and the authenticated ``session`` / ``player`` / ``permissions``
        (§6.2, the single source for identity and permissions). World
        constants are informational only; the coordinate formula stays
        ``absolute_y = origin.y + dy``."""
        params = {"protocol": PROTOCOL}
        if auth_token:
            params["auth"] = {"token": auth_token}
        resp = self.conn.rpc("hello", params)
        if isinstance(resp, dict):
            self.protocol = resp.get("protocol")
            self.mc_version = resp.get("mc_version")
            self.supported_mc_versions = resp.get("supported_mc_versions", [])
            # No top-level fallback -> an un-flipped server surfaces {} / None.
            self.world_constants = resp.get("world_constants") or {}
            self.y_sea = self.world_constants.get("y_sea")
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

    def _get_catalog_on_current_stream(self):
        """Fetch on this instance's stream (auxiliary instances only)."""
        return self.conn.rpc("catalog.get", [])

    def _catalog_stream(self):
        factory = self._catalog_connection_factory
        address, port, debug = self._catalog_endpoint
        if factory is None or address is None or port is None or self._server_key is None:
            raise _projection.CatalogProjectionError(
                "fetch",
                "catalog sync needs connection endpoint metadata; use Minecraft.create()",
            )
        auxiliary = None
        try:
            auxiliary = Minecraft(factory(address, port, debug))
            auxiliary._server_key = self._server_key
            auxiliary._catalog_endpoint = self._catalog_endpoint
            auxiliary._catalog_connection_factory = factory
            auxiliary.authenticate(self._server_key, pair=False)
        except Exception as exc:
            if auxiliary is not None:
                try:
                    auxiliary.close()
                except Exception:
                    pass
            if isinstance(exc, _projection.CatalogProjectionError):
                raise
            raise _projection.CatalogProjectionError(
                "fetch", "could not open the short-lived catalog stream", cause=exc
            ) from exc
        return auxiliary

    def _fetch_catalog_separately(self):
        auxiliary = self._catalog_stream()
        try:
            if auxiliary.catalog_hash != self.catalog_hash:
                raise _catalog.CatalogError(
                    "catalogHash changed between the build-stream hello and "
                    "the catalog-stream hello; retry the sync"
                )
            return auxiliary._get_catalog_on_current_stream()
        except _catalog.CatalogError as exc:
            raise _projection.CatalogProjectionError(
                "validate", "catalog stream did not match the build hello", cause=exc
            ) from exc
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "fetch", "catalog.get failed on the short-lived stream", cause=exc
            ) from exc
        finally:
            try:
                auxiliary.close()
            except Exception:
                pass

    def getCatalog(self):
        """Fetch the live block/entity/particle catalog from the server
        (wire method ``catalog.get``, §7.2.1). Authenticated only
        (``auth_required`` otherwise); v1 has no paging or version
        switching -- the whole current registry comes back in one response
        as ``{catalogHash, block, entity, particle}``. The fetch always uses
        a separate short-lived authenticated stream, so it cannot reset or
        close this instance's connection-scoped build state. Most callers
        want :meth:`sync_constants` instead, which adds caching, integrity
        verification, and publishes the generated projection."""
        return self._fetch_catalog_separately()

    def sync_constants(self, target_dir=None, force=False):
        """Ensure the connected server's catalog is cached locally and
        publish the CWD ``mc_constants.py`` plus manifest projection from it
        (mc-constants-design_ja.md; DECISIONS 2026-08-02-05/06).

        No-ops (returns ``None``) if ``hello`` did not advertise a
        ``catalogHash`` -- the server has no catalog to offer yet, or this
        session is unauthenticated. Otherwise: reuse the local cache for
        this ``catalogHash`` if present, else fetch on a separate short-lived
        stream and validate + cache the result. Folds this
        session's whole ``world_constants`` (from ``hello``, currently just
        ``y_sea`` but forward compatible with a future bN sending more) into
        the generated file's ``world_info`` class alongside ``block`` /
        ``entity`` / ``particle``. ``force=True`` re-fetches even if a cache
        entry already exists for this ``catalogHash``. Returns the written
        file's path, or ``None`` if there was no catalog to sync. This explicit
        method is strict and raises :class:`CatalogProjectionError` with a
        stable ``stage``; it never closes the build stream. :meth:`create`
        calls it automatically unless ``sync_catalog=False``, but turns such
        failures into :class:`CatalogProjectionWarning` and still returns the
        connected client."""
        if not self.catalog_hash:
            return None

        try:
            target_dir = os.path.abspath(target_dir or os.getcwd())
            # Policy is checked before cache/network work.  In a Git project a
            # missing ignore rule means no projection files are created at all.
            _projection.ensure_projection_allowed(target_dir)
        except _projection.CatalogProjectionError:
            raise
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "ignore", "could not verify project ignore policy", cause=exc
            ) from exc

        try:
            data = None if force else _catalog.load_cached_catalog(self.catalog_hash)
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "cache", "could not inspect the raw catalog cache", cause=exc
            ) from exc
        if data is None:
            data = self._fetch_catalog_separately()
            try:
                _catalog.validate_catalog(data, expected_hash=self.catalog_hash)
            except Exception as exc:
                raise _projection.CatalogProjectionError(
                    "validate", "catalog validation failed", cause=exc
                ) from exc
            try:
                _catalog.save_cached_catalog(self.catalog_hash, data)
            except Exception as exc:
                raise _projection.CatalogProjectionError(
                    "cache", "could not save the validated raw catalog", cause=exc
                ) from exc
        try:
            world_info = {
                key.upper(): value
                for key, value in (self.world_constants or {}).items()
                if value is not None
            } or None
            source = _constants_codegen.generate_source(
                data, self.mc_version, self.catalog_hash, world_info=world_info
            )
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "generate", "could not generate mc_constants.py", cause=exc
            ) from exc
        try:
            return _projection.publish_projection(
                source, self.catalog_hash, target_dir=target_dir
            )
        except _projection.CatalogProjectionError:
            raise
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "publish", "catalog projection publication failed", cause=exc
            ) from exc

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
            if not is_auth_discard(e):
                raise
            # Token disposition is independent of whether this call is
            # allowed to launch pairing (DEC 2026-08-02-06).
            clear_token(server_key)
            if not pair:
                raise PairingRequiredError(e.reason) from e
            # Auth-family failure: pair. The server
            # drops the stream after auth_required (hello is once per
            # connection), so reconnect before pairing and again for the
            # authenticated hello.
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
        sync_catalog=True,
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
        this local key only; it is never sent in ``hello.params`` (§6.1).

        ``sync_catalog`` (default ``True``) additionally calls
        :meth:`sync_constants` after a successful handshake. Cache misses use
        a separate short-lived stream and publish ``mc_constants.py`` plus its
        manifest. Projection failures are non-fatal actionable warnings; pass
        ``False`` to skip catalog cache/projection work entirely."""
        env_host = _env_first("MCREMOTE_API_HOST", "JRP_API_HOST")
        if env_host is not None:
            address = env_host
        env_port = _env_first("MCREMOTE_API_PORT", "JRP_API_PORT")
        if env_port is not None:
            try:
                port = int(env_port)
            except ValueError:
                pass
        connection_factory = Connection
        mc = Minecraft(connection_factory(address, port, debug))
        mc._observer = PythonObserverSource()
        attach_observer = getattr(mc.conn, "set_observer", None)
        if attach_observer is not None:
            attach_observer(mc._observer)
        mc._catalog_endpoint = (address, port, debug)
        mc._catalog_connection_factory = connection_factory
        if handshake:
            server_key = token_key or sandbox or f"{address}:{port}"
            mc._server_key = server_key
            mc.authenticate(server_key, token_type=token_type, pair=pair)
            if sync_catalog:
                try:
                    mc.sync_constants()
                except _projection.CatalogProjectionError as exc:
                    warnings.warn(
                        _projection.format_warning(exc),
                        _projection.CatalogProjectionWarning,
                        stacklevel=2,
                    )
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
