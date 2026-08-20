"""b3 catalog: fetch/cache the live block/entity/particle registry (wire
method ``catalog.get``, wire-format-design §7.2.1, DECISIONS 2026-07-29-04).

The server publishes a single ``catalogHash`` on ``hello`` (an informational
cache key; ``null`` until the server actually has a catalog to offer). When
authenticated and a catalog is advertised, the client can call
``catalog.get`` to fetch ``{catalogHash, block, entity, particle}`` in one
shot (v1 has no paging or version-switching -- current registry only).

This module owns the parts of that story that do not need a live connection:
hashing/validating the fetched body and a local disk cache keyed by
``catalogHash`` so a repeat connect to the same registry skips the network
round trip. :mod:`mc_remote.minecraft` wires the fetch/cache pair to the live
connection (``Minecraft.getCatalog`` / ``Minecraft.sync_constants``).
"""
import hashlib
import json
import math
import os
import re
import time

from .connection import McRemoteError

CATALOG_KEYS = ("block", "entity", "particle")
_BLOCK_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")


class CatalogError(McRemoteError):
    """Raised when a fetched catalog fails structural or hash validation."""


def _json_scalar_type(value):
    """Return the strict JSON scalar type used by the state schema.

    Python's ``bool`` subclasses ``int``; checking exact types here preserves
    the wire distinction required by DECISION 2026-08-02-04.
    """
    if type(value) is bool:
        return "boolean"
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            return None
        return "number"
    if type(value) is str:
        return "string"
    return None


def _state_entry_parts(block_id, entry):
    """Validate one block entry and return ``(states, default_state)``."""
    where = f"catalog.get result.block[{block_id!r}]"
    if not isinstance(block_id, str) or not _BLOCK_ID.fullmatch(block_id):
        raise CatalogError(
            f"{where} key must be a fully-qualified namespace:path block id"
        )
    if not isinstance(entry, dict):
        raise CatalogError(f"{where} must be an object")
    states = entry.get("states")
    default_state = entry.get("default_state")
    if not isinstance(states, dict) or not isinstance(default_state, dict):
        raise CatalogError(f"{where}.states and .default_state must be objects")
    if not all(isinstance(name, str) and name for name in states):
        raise CatalogError(f"{where}.states property names must be non-empty strings")
    if not all(isinstance(name, str) and name for name in default_state):
        raise CatalogError(
            f"{where}.default_state property names must be non-empty strings"
        )
    if set(states) != set(default_state):
        raise CatalogError(
            f"{where}.states and .default_state must have identical properties"
        )

    for property_name, allowed in states.items():
        prop_where = f"{where}.states[{property_name!r}]"
        if not isinstance(allowed, list) or not allowed:
            raise CatalogError(f"{prop_where} must be a non-empty array")
        value_types = [_json_scalar_type(value) for value in allowed]
        if any(value_type is None for value_type in value_types):
            raise CatalogError(
                f"{prop_where} values must be finite JSON scalars "
                "(boolean, number, or string)"
            )
        if len(set(value_types)) != 1:
            raise CatalogError(
                f"{prop_where} values must all have the same JSON type; "
                "boolean and number are distinct"
            )
        for index, value in enumerate(allowed):
            if any(value == previous for previous in allowed[:index]):
                raise CatalogError(f"{prop_where} must not contain duplicate values")

        default = default_state[property_name]
        default_type = _json_scalar_type(default)
        if default_type != value_types[0]:
            raise CatalogError(
                f"{where}.default_state[{property_name!r}] must have the "
                f"same JSON type as {prop_where}"
            )
        if not any(default == value for value in allowed):
            raise CatalogError(
                f"{where}.default_state[{property_name!r}] must be one of "
                f"the values in {prop_where}"
            )
    return states, default_state


def state_signature(entry, block_id="signature-input:block"):
    """Derive the canonical client-side state signature for a block entry.

    The signature contains sorted property names, strict JSON types, and
    canonical allowed-value sets. ``default_state`` is validated but excluded
    from the result because it does not change which keyword/value inputs are
    accepted. No signature field is added to the wire catalog.
    """
    states, _ = _state_entry_parts(block_id, entry)
    signature = []
    for property_name in sorted(states):
        allowed = states[property_name]
        value_type = _json_scalar_type(allowed[0])
        if value_type == "boolean":
            canonical_values = tuple(sorted(allowed))
        elif value_type == "number":
            canonical_values = tuple(sorted(allowed))
        else:
            canonical_values = tuple(sorted(allowed))
        signature.append((property_name, value_type, canonical_values))
    return tuple(signature)


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


def validate_catalog(data, expected_hash=None):
    """Validate a ``catalog.get`` result's shape and integrity.

    Checks: ``data`` is an object carrying a non-empty string
    ``catalogHash`` plus the ``block``/``entity``/``particle`` keys (each an
    object); every ``block`` entry carries ``states``/``default_state``
    (§7.2.1: JSON-native types matching protocol 22 structured block state);
    the declared ``catalogHash`` matches the digest recomputed from
    the returned body. Raises :class:`CatalogError` on any mismatch;
    returns ``None`` on success."""
    if not isinstance(data, dict):
        raise CatalogError(
            f"catalog.get result must be an object, got {type(data).__name__}"
        )
    declared_hash = data.get("catalogHash")
    if not isinstance(declared_hash, str) or not declared_hash:
        raise CatalogError("catalog.get result is missing a string catalogHash")
    if expected_hash is not None and declared_hash != expected_hash:
        raise CatalogError(
            f"catalogHash differs from authenticated hello: expected "
            f"{expected_hash!r}, got {declared_hash!r}"
        )
    body = {}
    for key in CATALOG_KEYS:
        value = data.get(key)
        if not isinstance(value, dict):
            raise CatalogError(f"catalog.get result.{key} must be an object")
        body[key] = value
    for block_id, entry in body["block"].items():
        _state_entry_parts(block_id, entry)
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
    try:
        validate_catalog(data, expected_hash=catalog_hash)
    except CatalogError:
        return None
    return data


def save_cached_catalog(catalog_hash, data):
    """Persist ``data`` (an already-validated ``catalog.get`` result) under
    ``catalog_hash``. Written via temp file + atomic replace so a crash
    mid-write cannot leave a corrupt cache entry."""
    validate_catalog(data, expected_hash=catalog_hash)
    path = _catalog_cache_file(catalog_hash)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
