"""b3 catalog: fetch/cache the live block/entity/particle registry (wire
method ``catalog.get``, wire-format-design §7.2.1, DECISIONS 2026-07-29-04).

The server publishes a single ``catalogHash`` on ``hello`` (an informational
cache key; ``null`` until the server actually has a catalog to offer). When
authenticated and a catalog is advertised, the client can call
``catalog.get`` to fetch ``{catalogHash, block, entity, particle}`` in one
shot (v1 has no paging or version-switching -- current registry only).

This module owns the parts of that story that do not need a live connection:
hashing/validating the fetched body, a local disk cache keyed by
``catalogHash`` so a repeat connect to the same registry skips the network
round trip, and the input-side "kwargs sugar" for block state
(wire-format-design §7.1/§7.2 keeps that convenience client-side, not on the
wire). :mod:`mc_remote.minecraft` wires the fetch/cache pair to the live
connection (``Minecraft.getCatalog`` / ``Minecraft.sync_constants``).
"""
import hashlib
import json
import os

from .connection import McRemoteError

CATALOG_KEYS = ("block", "entity", "particle")


class CatalogError(McRemoteError):
    """Raised when a fetched catalog fails structural or hash validation."""


def compute_catalog_hash(body):
    """Recompute ``catalogHash`` from a catalog body.

    ``body`` must contain exactly the ``block``/``entity``/``particle`` keys
    (no ``catalogHash`` field -- the hash is computed over the rest of the
    catalog and would otherwise depend on itself). Algorithm (DECISIONS
    2026-07-29-04): recursively key-sorted, separator-minimised (compact)
    JSON serialisation of ``body``, encoded UTF-8, SHA-256 hex digest. Any
    change to registry content -- including a different mod set at the same
    ``mc_version`` -- changes the digest."""
    payload = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_catalog(data):
    """Validate a ``catalog.get`` result's shape and integrity.

    Checks: ``data`` is an object carrying a non-empty string
    ``catalogHash`` plus the ``block``/``entity``/``particle`` keys (each an
    object); every ``block`` entry carries ``states``/``default_state``
    (§7.2.1: JSON-native types matching the §7.1 canonical block_state_ref
    output); the declared ``catalogHash`` matches the digest recomputed from
    the returned body. Raises :class:`CatalogError` on any mismatch;
    returns ``None`` on success."""
    if not isinstance(data, dict):
        raise CatalogError(
            f"catalog.get result must be an object, got {type(data).__name__}"
        )
    declared_hash = data.get("catalogHash")
    if not isinstance(declared_hash, str) or not declared_hash:
        raise CatalogError("catalog.get result is missing a string catalogHash")
    body = {}
    for key in CATALOG_KEYS:
        value = data.get(key)
        if not isinstance(value, dict):
            raise CatalogError(f"catalog.get result.{key} must be an object")
        body[key] = value
    for block_id, entry in body["block"].items():
        if not isinstance(entry, dict) or "states" not in entry or "default_state" not in entry:
            raise CatalogError(
                f"catalog.get result.block[{block_id!r}] must carry "
                "'states' and 'default_state'"
            )
    recomputed = compute_catalog_hash(body)
    if recomputed != declared_hash:
        raise CatalogError(
            f"catalogHash mismatch: server declared {declared_hash!r}, "
            f"recomputed {recomputed!r} from the returned body"
        )


# --- disk cache -------------------------------------------------------------

def cache_dir():
    """The mcremote cache directory. ``MCREMOTE_CACHE_DIR`` overrides;
    otherwise ``$XDG_CACHE_HOME/mcremote`` then ``~/.cache/mcremote`` --
    matching :func:`mc_remote.auth.config_dir`'s ``mcremote`` naming (the
    ``/mcremote pair`` CLI command, the ``~/.config/mcremote`` token store).

    Deliberately a separate directory (and env var) from ``config_dir``:
    catalog entries are public game/mod data, not credentials, and clearing
    one store should never touch the other."""
    override = os.environ.get("MCREMOTE_CACHE_DIR")
    if override:
        return override
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(base, "mcremote")


def _catalog_cache_file(catalog_hash):
    return os.path.join(cache_dir(), "catalogs", f"{catalog_hash}.json")


def load_cached_catalog(catalog_hash):
    """Return the cached ``catalog.get`` result for ``catalog_hash``, or
    ``None`` if not cached (a missing/corrupt file is a cache miss, not an
    error -- the caller re-fetches)."""
    try:
        with open(_catalog_cache_file(catalog_hash), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_cached_catalog(catalog_hash, data):
    """Persist ``data`` (an already-validated ``catalog.get`` result) under
    ``catalog_hash``. Written via temp file + atomic replace so a crash
    mid-write cannot leave a corrupt cache entry."""
    path = _catalog_cache_file(catalog_hash)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, separators=(",", ":"))
    except Exception:
        try:
            os.unlink(tmp)
        finally:
            raise
    os.replace(tmp, path)


# --- kwargs sugar for block_state_ref input ---------------------------------

def _format_state_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def block_ref(name, **state):
    """Build a ``block_state_ref`` string from a bare/namespaced block id and
    optional state kwargs.

    This is the input-side convenience wire-format-design §7.1/§7.2 keeps
    off the wire: the server tolerates a missing namespace and
    partial/out-of-order state and canonicalises the rest from the block's
    ``default_state``, so this helper only assembles what the caller already
    knows -- it does not need to see the live catalog to run.

    >>> block_ref("oak_log", axis="y")
    'minecraft:oak_log[axis=y]'
    >>> block_ref("minecraft:water", level=0)
    'minecraft:water[level=0]'
    >>> block_ref("stone")
    'minecraft:stone'
    """
    ref = name if ":" in name else f"minecraft:{name}"
    if not state:
        return ref
    props = ",".join(
        f"{key}={_format_state_value(value)}" for key, value in state.items()
    )
    return f"{ref}[{props}]"
