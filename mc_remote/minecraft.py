import os
import math
import re
import time
import threading
import warnings
from collections.abc import Mapping
from enum import Enum
from typing import TypeVar, overload

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
from . import wirescope as _wirescope
from .vec3 import Vec3
from .util import flatten
from .block_value import (
    BlockId,
    BlockValue,
    StateScalar,
    block_spec,
    decode_block_value,
)
from .b5_values import (
    BlockRightClickEvent,
    BlockTarget,
    ChatPostedEvent,
    EntityHandle,
    EntityTarget,
    EventBatch,
    EventValue,
    PlayerTarget,
    ProjectileHitEvent,
    ProjectileTarget,
    decode_event_batch,
)

_StateT = TypeVar("_StateT")
_TRACE_DELAY_UNSET = object()
_FORCE_UNSET = object()
_CANONICAL_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")


class BuildMode(str, Enum):
    """Connection-scoped execution policy for block-setting commands."""

    DEBUG = "DEBUG"
    TRACE = "TRACE"
    FAST = "FAST"


DEFAULT_TRACE_DELAY: float = 0.25


def _validate_build_mode(value):
    if not isinstance(value, BuildMode):
        raise TypeError("build_mode must be a BuildMode")
    return value


def _validate_trace_delay(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("trace_delay must be a finite non-negative number")
    return float(value)

__all__ = [
    "Minecraft",
    "McRemoteError",
    "McRpcError",
    "ConnectionLostError",
    "RequestFailedError",
    "PairingRequiredError",
    "BuildMode",
    "BlockValue",
    "BlockRightClickEvent",
    "BlockTarget",
    "ChatPostedEvent",
    "EntityHandle",
    "EntityTarget",
    "EventBatch",
    "EventValue",
    "PlayerTarget",
    "ProjectileHitEvent",
    "ProjectileTarget",
    "CatalogProjectionError",
    "CatalogProjectionWarning",
    "WireScopeWarning",
    "mcpy",
]


# Wire protocol version this client speaks (sent in the hello handshake and
# checked by the server). Distinct from the PyPI/distribution version.
PROTOCOL = "22.0.0"

CatalogProjectionError = _projection.CatalogProjectionError
CatalogProjectionWarning = _projection.CatalogProjectionWarning
WireScopeWarning = _wirescope.WireScopeWarning


def _integer_values(where, *values):
    parsed = []
    for index, value in enumerate(flatten(values)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or int(value) != value
        ):
            raise ValueError(f"{where}[{index}] must be an integer")
        parsed.append(int(value))
    return parsed


def _finite_values(where, *values):
    parsed = []
    for index, value in enumerate(flatten(values)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{where}[{index}] must be a finite number")
        parsed.append(value)
    return parsed


def _canonical_id(value, where):
    if not isinstance(value, str) or _CANONICAL_ID.fullmatch(value) is None:
        raise ValueError(f"{where} must be a canonical namespace ID")
    return value


def _env_first(*names):
    for name in names:
        if name in os.environ:
            return os.environ[name]
    return None


class Minecraft:
    """Client for a running Minecraft server speaking protocol 22.x.

    protocol 22.0.0 b5 surface: ``hello`` handshake (carrying an optional
    ``auth`` token, §6.1) plus ``setBlock`` / ``getBlock`` / ``setBlocks`` over
    structured block values, ``postToChat`` (wire ``chat.post``), paired-player
    position and pose helpers (``getPos`` / ``setPos`` / ``getPose`` /
    ``setPose``), the connection-scoped build
    state (``setWorld`` / ``setBuildOrigin``), and the live block/entity/
    particle catalog (``getCatalog`` / ``sync_constants``, wire ``catalog.get``,
    §7.2.1). Tokens are obtained by pairing (``auth.pairBegin`` /
    ``auth.pairPoll``, §6.5); :meth:`create` drives the unified connect flow
    (hello first, pair only on ``auth_required``, then sync the catalog if one
    is advertised). ``setBlock`` and ``setBlocks`` use connection-scoped
    DEBUG, TRACE, or FAST execution while retaining one public setter API;
    all other calls remain id-bearing requests. The legacy MCPI
    methods (entity / player / camera / events / sign / checkpoint / particle
    ...) were removed in the payload flip and will be re-introduced per
    protocol bump as they are ported to JSON-RPC."""

    def __init__(
        self,
        connection,
        *,
        build_mode=BuildMode.DEBUG,
        trace_delay=DEFAULT_TRACE_DELAY,
        _sleeper=None,
    ):
        self.conn = connection
        self._build_mode_lock = threading.RLock()
        self._build_mode = _validate_build_mode(build_mode)
        self._trace_delay = _validate_trace_delay(trace_delay)
        self._sleeper = _sleeper or time.sleep
        self._closed = False
        self._observer = None
        self._wirescope_runtime = None
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
        self._event_cursor = 0
        self._event_epoch = getattr(connection, "epoch", None)

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

    @overload
    def setBlock(
        self, x, y, z, block_id: BlockId[_StateT], *, state: _StateT | None = None
    ) -> None: ...

    @overload
    def setBlock(
        self,
        x,
        y,
        z,
        block_id: str,
        *,
        state: Mapping[str, StateScalar] | None = None,
    ) -> None: ...

    def setBlock(self, x, y, z, block_id, *, state=None):
        """Set one block using a protocol 22 structured ``BlockSpec``.

        Vanilla ``block_id`` values may omit ``minecraft:``. ``state`` may be
        partial; ``None`` is normalized to an empty object. The server fills
        omitted properties from Minecraft defaults rather than merging with
        the block currently in the world.
        """
        coords = _integer_values("world.setBlock coordinates", x, y, z)
        self._execute_set(
            "world.setBlock", coords + [block_spec(block_id, state)]
        )
        return None

    def getBlock(self, x, y, z) -> BlockValue:
        """Return an immutable canonical :class:`BlockValue` snapshot."""
        coords = _integer_values("world.getBlock coordinates", x, y, z)
        return decode_block_value(self.conn.rpc("world.getBlock", coords))

    def getBlocks(self, x0, y0, z0, x1, y1, z1) -> tuple[BlockValue, ...]:
        """Return canonical block snapshots in protocol-defined z-fastest order.

        The server normalizes each axis to inclusive min/max bounds and owns
        the per-axis and total work limits. The tuple and every BlockValue it
        contains are immutable observations.
        """

        coords = _integer_values(
            "world.getBlocks coordinates", x0, y0, z0, x1, y1, z1
        )
        result = self.conn.rpc("world.getBlocks", coords)
        if not isinstance(result, list):
            raise McRemoteError("world.getBlocks result must be an array")
        return tuple(decode_block_value(value) for value in result)

    @overload
    def getHeight(self, x, z) -> int: ...

    @overload
    def getHeight(self, x, z, max_y) -> int: ...

    def getHeight(self, x, z, max_y=None):
        """Return the highest exposed block at ``x,z`` up to inclusive max_y."""

        params = _integer_values("world.getHeight coordinates", x, z)
        if max_y is not None:
            params.extend(_integer_values("world.getHeight max_y", max_y))
        result = self.conn.rpc("world.getHeight", params)
        if isinstance(result, bool) or not isinstance(result, int):
            raise McRemoteError("world.getHeight result must be an integer")
        return result

    @overload
    def spawnParticle(
        self,
        x,
        y,
        z,
        offset_x,
        offset_y,
        offset_z,
        particle,
        speed,
        count,
    ) -> int: ...

    @overload
    def spawnParticle(
        self,
        x,
        y,
        z,
        offset_x,
        offset_y,
        offset_z,
        particle,
        speed,
        count,
        force: bool,
    ) -> int: ...

    def spawnParticle(
        self,
        x,
        y,
        z,
        offset_x,
        offset_y,
        offset_z,
        particle,
        speed,
        count,
        force=_FORCE_UNSET,
    ):
        """Spawn a b5 data-free particle without pre-rounding its position."""

        position = _finite_values("world.spawnParticle position", x, y, z)
        offsets = _finite_values(
            "world.spawnParticle offsets", offset_x, offset_y, offset_z
        )
        speed_value = _finite_values("world.spawnParticle speed", speed)[0]
        if any(value < 0 for value in offsets) or speed_value < 0:
            raise ValueError("particle offsets and speed must be non-negative")
        count_value = _integer_values("world.spawnParticle count", count)[0]
        if count_value < 0:
            raise ValueError("particle count must be non-negative")
        params = position + offsets + [
            _canonical_id(particle, "particle"),
            speed_value,
            count_value,
        ]
        if force is not _FORCE_UNSET:
            if not isinstance(force, bool):
                raise TypeError("force must be a boolean")
            params.append(force)
        result = self.conn.rpc("world.spawnParticle", params)
        if isinstance(result, bool) or not isinstance(result, int) or result < 0:
            raise McRemoteError(
                "world.spawnParticle result must be a non-negative integer"
            )
        return result

    def spawnEntity(self, x, y, z, entity) -> EntityHandle:
        """Spawn an entity and return its opaque connection-epoch handle."""

        params = _finite_values("world.spawnEntity position", x, y, z)
        params.append(_canonical_id(entity, "entity"))
        result = self.conn.rpc("world.spawnEntity", params)
        try:
            return EntityHandle(result)
        except ValueError as exc:
            raise McRemoteError(f"invalid world.spawnEntity result: {exc}") from exc

    def pollEvents(self, limit=100) -> EventBatch:
        """Poll this connection epoch without destructively dequeuing events.

        The cursor advances only after a complete, valid response. A lost
        response therefore retries from the same ``after_sequence``.
        """

        limit_value = _integer_values("events.poll limit", limit)[0]
        if limit_value < 1:
            raise ValueError("events.poll limit must be positive")
        epoch = getattr(self.conn, "epoch", None)
        if epoch != self._event_epoch:
            self._event_cursor = 0
            self._event_epoch = epoch
        after_sequence = self._event_cursor
        result = self.conn.rpc("events.poll", [after_sequence, limit_value])
        batch = decode_event_batch(result, after_sequence=after_sequence)
        self._event_cursor = batch.through_sequence
        return batch

    @overload
    def setBlocks(
        self,
        x0,
        y0,
        z0,
        x1,
        y1,
        z1,
        block_id: BlockId[_StateT],
        *,
        state: _StateT | None = None,
    ) -> None: ...

    @overload
    def setBlocks(
        self,
        x0,
        y0,
        z0,
        x1,
        y1,
        z1,
        block_id: str,
        *,
        state: Mapping[str, StateScalar] | None = None,
    ) -> None: ...

    def setBlocks(self, x0, y0, z0, x1, y1, z1, block_id, *, state=None):
        """Fill a cuboid using one protocol 22 structured ``BlockSpec``."""
        coords = _integer_values(
            "world.setBlocks coordinates", x0, y0, z0, x1, y1, z1
        )
        self._execute_set(
            "world.setBlocks", coords + [block_spec(block_id, state)]
        )
        return None

    @property
    def build_mode(self) -> BuildMode:
        """The current read-only connection execution mode."""

        with self._build_mode_lock:
            return self._build_mode

    @property
    def trace_delay(self) -> float:
        """The read-only TRACE delay in seconds for future setters."""

        with self._build_mode_lock:
            return self._trace_delay

    def _execute_set(self, method, params):
        pending = None
        result = None
        with self._build_mode_lock:
            mode = self._build_mode
            delay = self._trace_delay
            if mode is BuildMode.FAST:
                notify = getattr(self.conn, "notify", None)
                if notify is None:
                    raise McRemoteError(
                        "FAST mode requires notification-capable connection"
                    )
                notify(method, params)
            else:
                enqueue = getattr(self.conn, "_enqueue_request", None)
                if enqueue is None:
                    # Synchronous test doubles use the call itself as their
                    # registration point for transition ordering.
                    result = self.conn.rpc(method, params)
                else:
                    pending = enqueue(method, params)

        if mode is BuildMode.FAST:
            return None
        if pending is not None:
            result = pending.result()
        if result is not None:
            raise McRemoteError(f"{method} success result must be null")
        if mode is BuildMode.TRACE:
            self._sleeper(delay)
        return None

    @overload
    def setBuildMode(self, mode: BuildMode) -> None: ...

    @overload
    def setBuildMode(self, mode: BuildMode, *, trace_delay: float) -> None: ...

    def setBuildMode(self, mode, *, trace_delay=_TRACE_DELAY_UNSET):
        """Flush earlier commands, then atomically install a new build mode."""

        mode = _validate_build_mode(mode)
        with self._build_mode_lock:
            delay = (
                self._trace_delay
                if trace_delay is _TRACE_DELAY_UNSET
                else _validate_trace_delay(trace_delay)
            )
            if mode is self._build_mode and delay == self._trace_delay:
                return None
            self.flush()
            self._build_mode = mode
            self._trace_delay = delay
        return None

    def flush(self) -> None:
        """Wait for preceding commands without reading world state."""

        flush = getattr(self.conn, "flush", None)
        if flush is None:
            raise McRemoteError("connection does not support connection.flush")
        result = flush()
        if result is not None:
            raise McRemoteError("connection.flush success result must be null")
        return None

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
        coords = _integer_values("build.setOrigin coordinates", x, y, z)
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
        coords = _finite_values("player.setPos coordinates", x, y, z)
        return self.conn.rpc("player.setPos", [world] + coords)

    def getPose(self):
        """Get the paired player's current position and orientation.

        Returns ``{"world": ..., "pos": [x, y, z], "yaw": ..., "pitch": ...}``.
        Position is relative to this stream's build origin.  The target is the
        authenticated/pair-bound player; no player identity is sent.
        """
        return self.conn.rpc("player.getPose", [])

    def setPose(self, world, x, y, z, yaw, pitch):
        """Move and orient the paired player with one atomic server operation.

        ``world`` is explicit, position is relative to this stream's build
        origin, and all five numeric values retain their fractional precision.
        The server validates finite values and the pitch range, normalizes yaw,
        and returns the resulting pose in the same shape as :meth:`getPose`.
        """
        return self.conn.rpc("player.setPose", [world, x, y, z, yaw, pitch])

    def _get_catalog_on_current_stream(self):
        """Fetch on this instance's stream (auxiliary instances only)."""
        return self.conn.rpc("catalog.get", [])

    def _catalog_stream(self):
        factory = self._catalog_connection_factory
        address, port, debug = self._catalog_endpoint
        if (
            factory is None
            or address is None
            or port is None
            or self._server_key is None
        ):
            raise _projection.CatalogProjectionError(
                "fetch",
                "catalog sync needs connection endpoint metadata; "
                "use Minecraft.create()",
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
            source, stub = _constants_codegen.generate_projection(
                data, self.mc_version, self.catalog_hash, world_info=world_info
            )
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "generate", "could not generate mc_constants projection", cause=exc
            ) from exc
        try:
            return _projection.publish_projection(
                source, stub, self.catalog_hash, target_dir=target_dir
            )
        except _projection.CatalogProjectionError:
            raise
        except Exception as exc:
            raise _projection.CatalogProjectionError(
                "publish", "catalog projection publication failed", cause=exc
            ) from exc

    def close(self):
        """Flush pending FAST commands and close the Minecraft connection."""
        if self._closed:
            return True
        try:
            self.conn.close()
        finally:
            self._closed = True
            if self._wirescope_runtime is not None:
                try:
                    self._wirescope_runtime.close()
                except Exception:
                    warnings.warn(
                        "WireScope cleanup failed; Minecraft is already closed",
                        _wirescope.WireScopeWarning,
                        stacklevel=2,
                    )
                self._wirescope_runtime = None
        return True

    def __enter__(self) -> "Minecraft":
        if self._closed:
            raise McRemoteError("Minecraft connection is already closed")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except Exception:
                # Preserve the learner's original exception while still making
                # the completion-guarantee failure visible.
                warnings.warn(
                    "Minecraft close/flush also failed; preserving the "
                    "active exception",
                    RuntimeWarning,
                    stacklevel=2,
                )
        return False

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
        wirescope=None,
        build_mode=BuildMode.DEBUG,
        trace_delay=DEFAULT_TRACE_DELAY,
    ) -> "Minecraft":
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
        ``False`` to skip catalog cache/projection work entirely.

        ``wirescope`` accepts ``None``/``False`` (fully disabled), ``True``
        (the permanent low-floor alias for ``WireScopeStation.local()``), or
        an explicit ``WireScopeStation.local()`` descriptor.  WireScope
        preflight and observer failures warn but never block Minecraft.

        ``build_mode`` defaults to :attr:`BuildMode.DEBUG`. ``trace_delay`` is
        the connection-local TRACE pause in seconds and defaults to ``0.25``.
        Neither value is sent in hello or method params."""
        build_mode = _validate_build_mode(build_mode)
        trace_delay = _validate_trace_delay(trace_delay)
        env_host = _env_first("MCREMOTE_API_HOST", "JRP_API_HOST")
        if env_host is not None:
            address = env_host
        env_port = _env_first("MCREMOTE_API_PORT", "JRP_API_PORT")
        if env_port is not None:
            try:
                port = int(env_port)
            except ValueError:
                pass
        station = _wirescope._coerce_station(wirescope)
        runtime = None
        if station is not None:
            try:
                runtime = _wirescope._start_station(station)
            except _wirescope._WireScopeStartError as exc:
                warnings.warn(
                    f"WireScope was not started: {exc}; Minecraft will continue",
                    _wirescope.WireScopeWarning,
                    stacklevel=2,
                )
            except Exception:
                warnings.warn(
                    "WireScope station preflight failed; Minecraft will continue",
                    _wirescope.WireScopeWarning,
                    stacklevel=2,
                )
        connection_factory = Connection
        mc = None
        try:
            mc = Minecraft(
                connection_factory(address, port, debug),
                build_mode=build_mode,
                trace_delay=trace_delay,
            )
            mc._wirescope_runtime = runtime
            if runtime is not None:
                attach_observer = getattr(mc.conn, "set_observer", None)
                try:
                    mc._observer = runtime.observer()
                    if attach_observer is None:
                        raise RuntimeError("connection has no observer hook")
                    attach_observer(mc._observer)
                except Exception:
                    if attach_observer is not None:
                        try:
                            attach_observer(None)
                        except Exception:
                            pass
                    try:
                        runtime.close()
                    except Exception:
                        pass
                    runtime = None
                    mc._wirescope_runtime = None
                    mc._observer = None
                    warnings.warn(
                        "WireScope observer hook failed; Minecraft will continue",
                        _wirescope.WireScopeWarning,
                        stacklevel=2,
                    )
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
        except Exception:
            if mc is not None:
                try:
                    mc.close()
                except Exception:
                    pass
            elif runtime is not None:
                runtime.close()
            raise


def mcpy(func):
    # these will be created as global variable in module, so not good idea
    # func.__globals__['mc'] = Minecraft.create()
    func.__doc__ = ("_mcpy :" + func.__doc__) if func.__doc__ else "_mcpy "
    return func


if __name__ == "__main__":
    mc = Minecraft.create()
    mc.setBlock(0, 0, 0, "minecraft:stone")
    print(mc.getBlock(0, 0, 0))
