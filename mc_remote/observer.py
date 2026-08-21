"""Transport-neutral Python projection for ``mcremote.observer`` schema v1.1.

This module deliberately does not launch WireScope, retain frame history, or
choose a browser/relay transport.  It only projects the main connection through
a generation-side allowlist and validates snapshots against the shared schema.
"""

from __future__ import annotations

import json
import math
import re
import secrets
import threading
import time
import weakref
from collections.abc import Callable, Iterable, Mapping

from .connection import McRemoteError
from .b5_values import decode_event_batch


OBSERVER_SCHEMA = "mcremote.observer"
OBSERVER_SCHEMA_VERSION = 1.1
MAIN_STREAM_ID = "main"

_DISPLAY_ALIAS_WORDS = (
    "MIND",
    "STORM",
    "SOCIETY",
    "PAPERT",
    "RESNICK",
    "PIAGET",
    "MINSKY",
    "LIFE",
    "DNA",
    "MUSIC",
    "WAVE",
    "BRAIN",
    "SELF",
    "APPLE",
    "ORANGE",
    "LEMON",
)
_DISPLAY_ALIAS_SEPARATOR = "-"
_DISPLAY_ALIAS_SUFFIX_DIGITS = 6

OBSERVED_METHODS = frozenset(
    {
        "hello",
        "build.setWorld",
        "build.setOrigin",
        "chat.post",
        "world.setBlock",
        "world.setBlocks",
        "world.getBlock",
        "world.getBlocks",
        "world.getHeight",
        "world.spawnParticle",
        "world.spawnEntity",
        "events.poll",
        "connection.flush",
        "player.getPos",
        "player.setPos",
        "player.getPose",
        "player.setPose",
    }
)
_QUALIFIED_BLOCK_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")
_SHORT_BLOCK_ID = re.compile(r"^[a-z0-9/._-]+$")


class ObserverValidationError(ValueError):
    """Raised when a snapshot does not conform to observer schema v1.1."""


def _generate_display_alias():
    """Generate a non-secret, human-readable display alias contract v1."""

    first = secrets.choice(_DISPLAY_ALIAS_WORDS)
    second = secrets.choice(_DISPLAY_ALIAS_WORDS)
    suffix = secrets.randbelow(10**_DISPLAY_ALIAS_SUFFIX_DIGITS)
    return _DISPLAY_ALIAS_SEPARATOR.join(
        (first, second, f"{suffix:0{_DISPLAY_ALIAS_SUFFIX_DIGITS}d}")
    )


def _object(value, context):
    if not isinstance(value, Mapping):
        raise ObserverValidationError(f"{context} must be an object")
    return value


def _exact_fields(value, allowed, context):
    unknown = set(value) - set(allowed)
    if unknown:
        field = sorted(unknown, key=str)[0]
        raise ObserverValidationError(f"{context} unknown field: {field}")


def _required_string(value, context):
    if not isinstance(value, str) or not value:
        raise ObserverValidationError(f"{context} must be a non-empty string")
    return value


def _finite_number(value, context):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObserverValidationError(f"{context} must be a finite number")
    if not math.isfinite(value):
        raise ObserverValidationError(f"{context} must be a finite number")
    return value


def _integer(value, context, *, non_negative=False):
    value = _finite_number(value, context)
    if int(value) != value or (non_negative and value < 0):
        qualifier = "non-negative " if non_negative else ""
        raise ObserverValidationError(f"{context} must be a {qualifier}integer")
    return int(value)


def _canonical_id(value, context):
    value = _required_string(value, context)
    if _QUALIFIED_BLOCK_ID.fullmatch(value) is None:
        raise ObserverValidationError(f"{context} must be a canonical namespace ID")
    return value


def _parse_event_batch(value):
    try:
        normalized = json.loads(json.dumps(value, allow_nan=False))
        decode_event_batch(normalized, after_sequence=0)
    except (McRemoteError, TypeError, ValueError) as exc:
        raise ObserverValidationError(f"invalid events.poll result: {exc}") from exc
    return normalized


def _json_scalar(value, context):
    if value is None or isinstance(value, (str, bool)):
        return value
    return _finite_number(value, context)


def _string_array(value, context):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ObserverValidationError(f"{context} must be a string array")
    return list(value)


def _number_tuple(value, context):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ObserverValidationError(f"{context} must be a three-number tuple")
    return [
        _finite_number(value[0], f"{context}[0]"),
        _finite_number(value[1], f"{context}[1]"),
        _finite_number(value[2], f"{context}[2]"),
    ]


def _parse_block_value(value, context, *, require_namespace):
    block = _object(value, context)
    _exact_fields(block, {"block_id", "state"}, context)
    if set(block) != {"block_id", "state"}:
        raise ObserverValidationError(
            f"{context} must contain exactly block_id and state"
        )
    block_id = _required_string(block["block_id"], f"{context}.block_id")
    valid_id = (
        _QUALIFIED_BLOCK_ID.fullmatch(block_id)
        if require_namespace
        else (
            _QUALIFIED_BLOCK_ID.fullmatch(block_id)
            or _SHORT_BLOCK_ID.fullmatch(block_id)
        )
    )
    if valid_id is None:
        raise ObserverValidationError(
            f"{context}.block_id has an invalid block ID shape"
        )
    state = _object(block["state"], f"{context}.state")
    property_names = list(state)
    if any(not isinstance(name, str) or not name for name in property_names):
        raise ObserverValidationError(
            f"{context}.state property names must be non-empty strings"
        )
    parsed_state = {}
    for property_name in sorted(property_names):
        item = state[property_name]
        if item is None:
            raise ObserverValidationError(
                f"{context}.state.{property_name} must be a JSON scalar"
            )
        parsed_state[property_name] = _json_scalar(
            item, f"{context}.state.{property_name}"
        )
    return {"block_id": block_id, "state": parsed_state}


def _parse_permissions(value):
    permissions = _object(value, "permissions")
    _exact_fields(permissions, {"online", "offline", "build_range"}, "permissions")
    parsed = {}
    for key in ("online", "offline"):
        if key in permissions:
            if not isinstance(permissions[key], bool):
                raise ObserverValidationError(f"permissions.{key} must be a boolean")
            parsed[key] = permissions[key]
    if "build_range" in permissions:
        build_range = permissions["build_range"]
        if isinstance(build_range, bool) or not isinstance(
            build_range, (str, int, float)
        ):
            raise ObserverValidationError(
                "permissions.build_range must be a number or string"
            )
        if not isinstance(build_range, str):
            _finite_number(build_range, "permissions.build_range")
        parsed["build_range"] = build_range
    return parsed


def _parse_hello(value):
    hello = _object(value, "hello")
    _exact_fields(
        hello,
        {
            "protocol",
            "mc_version",
            "supported_mc_versions",
            "catalog_hash",
            "world",
            "origin",
            "world_constants",
            "permissions",
        },
        "hello",
    )
    if "catalog_hash" not in hello:
        raise ObserverValidationError("hello.catalog_hash is required")
    catalog_hash = hello.get("catalog_hash")
    if catalog_hash is not None and not isinstance(catalog_hash, str):
        raise ObserverValidationError("hello.catalog_hash must be a string or null")
    constants = _object(hello.get("world_constants"), "hello.world_constants")
    _exact_fields(constants, {"y_sea"}, "hello.world_constants")
    if "y_sea" not in constants:
        raise ObserverValidationError("hello.world_constants.y_sea is required")
    y_sea = constants["y_sea"]
    if y_sea is not None:
        y_sea = _finite_number(y_sea, "hello.world_constants.y_sea")
    parsed = {
        "protocol": _required_string(hello.get("protocol"), "hello.protocol"),
        "mc_version": _required_string(hello.get("mc_version"), "hello.mc_version"),
        "supported_mc_versions": _string_array(
            hello.get("supported_mc_versions"), "hello.supported_mc_versions"
        ),
        "catalog_hash": catalog_hash,
    }
    if "world" in hello:
        parsed["world"] = _required_string(hello["world"], "hello.world")
    if "origin" in hello:
        parsed["origin"] = _number_tuple(hello["origin"], "hello.origin")
    parsed["world_constants"] = {"y_sea": y_sea}
    if "permissions" in hello:
        parsed["permissions"] = _parse_permissions(hello["permissions"])
    return parsed


def _parse_error_data(value):
    data = _object(value, "frame.payload.error.data")
    _exact_fields(
        data,
        {
            "reason",
            "block_id",
            "property",
            "value",
            "allowed",
            "bounds",
            "violating",
        },
        "frame.payload.error.data",
    )
    parsed = {}
    for key in ("reason", "block_id", "property"):
        if key in data:
            if not isinstance(data[key], str):
                raise ObserverValidationError(
                    f"frame.payload.error.data.{key} must be a string"
                )
            parsed[key] = data[key]
    if "value" in data:
        if data["value"] is None:
            raise ObserverValidationError(
                "frame.payload.error.data.value must be a JSON scalar"
            )
        parsed["value"] = _json_scalar(
            data["value"], "frame.payload.error.data.value"
        )
    if "allowed" in data:
        allowed = data["allowed"]
        if not isinstance(allowed, list):
            raise ObserverValidationError(
                "frame.payload.error.data.allowed must be an array"
            )
        parsed_allowed = []
        for index, item in enumerate(allowed):
            if item is None:
                raise ObserverValidationError(
                    f"frame.payload.error.data.allowed[{index}] must be a JSON scalar"
                )
            parsed_allowed.append(
                _json_scalar(item, f"frame.payload.error.data.allowed[{index}]")
            )
        parsed["allowed"] = parsed_allowed
    for key in ("bounds", "violating"):
        if key in data:
            values = data[key]
            if not isinstance(values, list):
                raise ObserverValidationError(
                    f"frame.payload.error.data.{key} must be a number array"
                )
            parsed[key] = [
                _finite_number(item, f"frame.payload.error.data.{key}[{index}]")
                for index, item in enumerate(values)
            ]
    return parsed


def _parse_error(value):
    error = _object(value, "frame.payload.error")
    _exact_fields(error, {"code", "message", "data"}, "frame.payload.error")
    if "code" not in error:
        raise ObserverValidationError("frame.payload.error.code is required")
    code = error.get("code")
    if code is not None and not isinstance(code, str):
        code = _finite_number(code, "frame.payload.error.code")
    parsed = {
        "code": code,
        "message": _required_string(
            error.get("message"), "frame.payload.error.message"
        ),
    }
    if "data" in error:
        parsed["data"] = _parse_error_data(error["data"])
    return parsed


def _parse_params(method, value):
    if method == "hello":
        params = _object(value, "frame.payload.params")
        _exact_fields(params, {"protocol", "client", "build"}, "frame.payload.params")
        parsed = {
            "protocol": _required_string(
                params.get("protocol"), "frame.payload.params.protocol"
            )
        }
        if "client" in params:
            client = _object(params["client"], "frame.payload.params.client")
            _exact_fields(
                client,
                {"name", "version", "locale"},
                "frame.payload.params.client",
            )
            parsed_client = {
                "name": _required_string(
                    client.get("name"), "frame.payload.params.client.name"
                ),
                "version": _required_string(
                    client.get("version"), "frame.payload.params.client.version"
                ),
            }
            if isinstance(client.get("locale"), str):
                parsed_client["locale"] = client["locale"]
            parsed["client"] = parsed_client
        if "build" in params:
            build = _object(params["build"], "frame.payload.params.build")
            _exact_fields(build, {"world", "origin"}, "frame.payload.params.build")
            parsed_build = {}
            if isinstance(build.get("world"), str):
                parsed_build["world"] = build["world"]
            if "origin" in build:
                parsed_build["origin"] = _number_tuple(
                    build["origin"], "frame.payload.params.build.origin"
                )
            parsed["build"] = parsed_build
        return parsed
    if not isinstance(value, list):
        raise ObserverValidationError("frame.payload.params must be an array")
    block_index = None
    if method == "world.setBlock":
        if len(value) != 4:
            raise ObserverValidationError(
                "world.setBlock params must contain x, y, z, and BlockSpec"
            )
        block_index = 3
    elif method == "world.setBlocks":
        if len(value) != 7:
            raise ObserverValidationError(
                "world.setBlocks params must contain two coordinates and BlockSpec"
            )
        block_index = 6
    elif method == "world.getBlock" and len(value) != 3:
        raise ObserverValidationError(
            "world.getBlock params must contain x, y, and z"
        )
    elif method == "world.getBlocks" and len(value) != 6:
        raise ObserverValidationError(
            "world.getBlocks params must contain two coordinates"
        )
    elif method == "world.getHeight" and len(value) not in {2, 3}:
        raise ObserverValidationError(
            "world.getHeight params must contain x, z, and optional max_y"
        )
    elif method == "world.spawnParticle" and len(value) not in {9, 10}:
        raise ObserverValidationError(
            "world.spawnParticle params must contain 9 or 10 values"
        )
    elif method == "world.spawnEntity" and len(value) != 4:
        raise ObserverValidationError(
            "world.spawnEntity params must contain x, y, z, and entity"
        )
    elif method == "events.poll" and len(value) != 2:
        raise ObserverValidationError(
            "events.poll params must contain after_sequence and limit"
        )
    elif method == "connection.flush" and value != []:
        raise ObserverValidationError("connection.flush params must be an empty array")
    if block_index is not None:
        parsed = [
            _integer(item, f"frame.payload.params[{index}]")
            for index, item in enumerate(value[:block_index])
        ]
        parsed.append(
            _parse_block_value(
                value[block_index],
                f"frame.payload.params[{block_index}]",
                require_namespace=False,
            )
        )
        return parsed
    if method in {"world.getBlock", "world.getBlocks", "world.getHeight"}:
        return [
            _integer(item, f"frame.payload.params[{index}]")
            for index, item in enumerate(value)
        ]
    if method == "build.setOrigin":
        if len(value) != 3:
            raise ObserverValidationError(
                "build.setOrigin params must contain x, y, and z"
            )
        return [
            _integer(item, f"frame.payload.params[{index}]")
            for index, item in enumerate(value)
        ]
    if method == "events.poll":
        return [
            _integer(item, f"frame.payload.params[{index}]", non_negative=True)
            for index, item in enumerate(value)
        ]
    if method == "world.spawnEntity":
        return [
            *[
                _finite_number(item, f"frame.payload.params[{index}]")
                for index, item in enumerate(value[:3])
            ],
            _canonical_id(value[3], "frame.payload.params[3]"),
        ]
    if method == "world.spawnParticle":
        parsed = [
            _finite_number(item, f"frame.payload.params[{index}]")
            for index, item in enumerate(value[:6])
        ]
        if any(item < 0 for item in parsed[3:6]):
            raise ObserverValidationError("particle offsets must be non-negative")
        parsed.extend(
            [
                _canonical_id(value[6], "frame.payload.params[6]"),
                _finite_number(value[7], "frame.payload.params[7]"),
                _integer(
                    value[8], "frame.payload.params[8]", non_negative=True
                ),
            ]
        )
        if parsed[7] < 0:
            raise ObserverValidationError("particle speed must be non-negative")
        if len(value) == 10:
            if not isinstance(value[9], bool):
                raise ObserverValidationError(
                    "frame.payload.params[9] must be a boolean"
                )
            parsed.append(value[9])
        return parsed
    return [
        _json_scalar(item, f"frame.payload.params[{index}]")
        for index, item in enumerate(value)
    ]


def _parse_result(method, value):
    if method == "hello":
        return _parse_hello(value)
    if method in {"player.getPos", "player.setPos"}:
        position = _object(value, "frame.payload.result")
        _exact_fields(position, {"world", "pos"}, "frame.payload.result")
        return {
            "world": _required_string(
                position.get("world"), "frame.payload.result.world"
            ),
            "pos": _number_tuple(position.get("pos"), "frame.payload.result.pos"),
        }
    if method in {"player.getPose", "player.setPose"}:
        pose = _object(value, "frame.payload.result")
        _exact_fields(
            pose,
            {"world", "pos", "yaw", "pitch"},
            "frame.payload.result",
        )
        return {
            "world": _required_string(
                pose.get("world"), "frame.payload.result.world"
            ),
            "pos": _number_tuple(pose.get("pos"), "frame.payload.result.pos"),
            "yaw": _finite_number(pose.get("yaw"), "frame.payload.result.yaw"),
            "pitch": _finite_number(pose.get("pitch"), "frame.payload.result.pitch"),
        }
    if method == "world.getBlock":
        return _parse_block_value(
            value, "frame.payload.result", require_namespace=True
        )
    if method == "world.getBlocks":
        if not isinstance(value, list):
            raise ObserverValidationError(
                "world.getBlocks success result must be an array"
            )
        return [
            _parse_block_value(
                item,
                f"frame.payload.result[{index}]",
                require_namespace=True,
            )
            for index, item in enumerate(value)
        ]
    if method == "events.poll":
        return _parse_event_batch(value)
    if method == "world.getHeight":
        return _integer(value, "frame.payload.result")
    if method == "world.spawnParticle":
        return _integer(value, "frame.payload.result", non_negative=True)
    if method == "world.spawnEntity":
        if not isinstance(value, str) or re.fullmatch(
            r"mceh_[A-Za-z0-9_-]{22,}", value
        ) is None:
            raise ObserverValidationError(
                "world.spawnEntity success result must be an entity handle"
            )
        return value
    if method in {"world.setBlock", "world.setBlocks", "connection.flush"}:
        if value is not None:
            raise ObserverValidationError(
                f"{method} success result must be null"
            )
        return None
    return _json_scalar(value, "frame.payload.result")


def _parse_payload(method, value):
    payload = _object(value, "frame.payload")
    _exact_fields(payload, {"params", "result", "error"}, "frame.payload")
    present = [key for key in ("params", "result", "error") if key in payload]
    if len(present) != 1:
        raise ObserverValidationError(
            "frame.payload must contain exactly one payload kind"
        )
    kind = present[0]
    if kind == "params":
        return {"params": _parse_params(method, payload[kind])}
    if kind == "result":
        return {"result": _parse_result(method, payload[kind])}
    return {"error": _parse_error(payload[kind])}


def _parse_frame(value):
    frame = _object(value, "frame")
    _exact_fields(
        frame,
        {"sequence", "observed_at", "direction", "request_id", "method", "payload"},
        "frame",
    )
    direction = frame.get("direction")
    if direction not in {"send", "receive"}:
        raise ObserverValidationError("frame.direction must be send or receive")
    method = frame.get("method")
    if method not in OBSERVED_METHODS:
        raise ObserverValidationError(f"frame.method is not observable: {method}")
    request_id = frame.get("request_id")
    if "request_id" not in frame:
        raise ObserverValidationError("frame.request_id is required")
    if request_id is not None and not isinstance(request_id, str):
        request_id = _finite_number(request_id, "frame.request_id")
    return {
        "sequence": _finite_number(frame.get("sequence"), "frame.sequence"),
        "observed_at": _finite_number(frame.get("observed_at"), "frame.observed_at"),
        "direction": direction,
        "request_id": request_id,
        "method": method,
        "payload": _parse_payload(method, frame.get("payload")),
    }


def _parse_stream(value):
    stream = _object(value, "stream")
    _exact_fields(stream, {"id", "kind", "status", "hello", "frames"}, "stream")
    if stream.get("kind") not in {"main", "substream"}:
        raise ObserverValidationError("stream.kind must be main or substream")
    if stream.get("status") not in {"connected", "error"}:
        raise ObserverValidationError("stream.status must be connected or error")
    frames = stream.get("frames")
    if not isinstance(frames, list):
        raise ObserverValidationError("stream.frames must be an array")
    return {
        "id": _required_string(stream.get("id"), "stream.id"),
        "kind": stream["kind"],
        "status": stream["status"],
        "hello": _parse_hello(stream.get("hello")),
        "frames": [_parse_frame(frame) for frame in frames],
    }


def validate_snapshot(value):
    """Validate and return a JSON-safe copy of an observer schema v1 snapshot."""

    snapshot = _object(value, "snapshot")
    _exact_fields(
        snapshot,
        {"schema", "schema_version", "emitted_at", "target", "streams"},
        "snapshot",
    )
    if snapshot.get("schema") != OBSERVER_SCHEMA:
        raise ObserverValidationError(
            f"unsupported observer schema: {snapshot.get('schema')}"
        )
    version = snapshot.get("schema_version")
    if isinstance(version, bool) or version != OBSERVER_SCHEMA_VERSION:
        raise ObserverValidationError(f"unsupported observer schema version: {version}")
    target = _object(snapshot.get("target"), "target")
    _exact_fields(target, {"id", "display_alias", "source_kind"}, "target")
    if target.get("source_kind") not in {"scratch", "python"}:
        raise ObserverValidationError("target.source_kind must be scratch or python")
    streams = snapshot.get("streams")
    if not isinstance(streams, list) or not streams:
        raise ObserverValidationError("snapshot.streams must be a non-empty array")
    parsed_target = {
        "id": _required_string(target.get("id"), "target.id"),
        "display_alias": _required_string(
            target.get("display_alias"), "target.display_alias"
        ),
        "source_kind": target["source_kind"],
    }
    parsed_streams = [_parse_stream(stream) for stream in streams]
    stream_ids = [stream["id"] for stream in parsed_streams]
    if parsed_target["id"] in stream_ids:
        raise ObserverValidationError("target id must not be used as a stream id")
    if len(set(stream_ids)) != len(stream_ids):
        raise ObserverValidationError("stream ids must be unique within a target")
    return {
        "schema": OBSERVER_SCHEMA,
        "schema_version": OBSERVER_SCHEMA_VERSION,
        "emitted_at": _finite_number(snapshot.get("emitted_at"), "snapshot.emitted_at"),
        "target": parsed_target,
        "streams": parsed_streams,
    }


def serialize_snapshot(value):
    """Validate and encode one snapshot without non-standard JSON numbers."""

    return json.dumps(
        validate_snapshot(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _allowed_string(value):
    return value if isinstance(value, str) and value else None


def _allowed_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _allowed_tuple(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    items = [_allowed_number(item) for item in value]
    return items if all(item is not None for item in items) else None


def _allowed_scalar(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    return _allowed_number(value)


def _project_hello(value):
    if not isinstance(value, Mapping):
        return None
    protocol = _allowed_string(value.get("protocol"))
    mc_version = _allowed_string(value.get("mc_version"))
    if not protocol or not mc_version:
        return None
    versions = value.get("supported_mc_versions")
    versions = (
        [item for item in versions if isinstance(item, str)]
        if isinstance(versions, list)
        else []
    )
    catalog_hash = value.get("catalogHash", value.get("catalog_hash"))
    catalog_hash = catalog_hash.lower() if isinstance(catalog_hash, str) else None
    constants = value.get("world_constants")
    constants = constants if isinstance(constants, Mapping) else {}
    y_sea = constants.get("y_sea")
    if y_sea is not None:
        y_sea = _allowed_number(y_sea)
    projected = {
        "protocol": protocol,
        "mc_version": mc_version,
        "supported_mc_versions": versions,
        "catalog_hash": catalog_hash,
        "world_constants": {"y_sea": y_sea},
    }
    world = _allowed_string(value.get("world"))
    origin = _allowed_tuple(value.get("origin"))
    if world:
        projected["world"] = world
    if origin:
        projected["origin"] = origin
    permissions = value.get("permissions")
    if isinstance(permissions, Mapping):
        allowed_permissions = {}
        for key in ("online", "offline"):
            if isinstance(permissions.get(key), bool):
                allowed_permissions[key] = permissions[key]
        build_range = permissions.get("buildRange", permissions.get("build_range"))
        if isinstance(build_range, str) or _allowed_number(build_range) is not None:
            allowed_permissions["build_range"] = build_range
        if allowed_permissions:
            projected["permissions"] = allowed_permissions
    return projected


def _project_hello_params(value):
    if not isinstance(value, Mapping):
        return None
    protocol = _allowed_string(value.get("protocol"))
    if not protocol:
        return None
    projected = {"protocol": protocol}
    client = value.get("client")
    if isinstance(client, Mapping):
        name = _allowed_string(client.get("name"))
        version = _allowed_string(client.get("version"))
        if name and version:
            projected_client = {"name": name, "version": version}
            if isinstance(client.get("locale"), str):
                projected_client["locale"] = client["locale"]
            projected["client"] = projected_client
    build = value.get("build")
    if isinstance(build, Mapping):
        projected_build = {}
        world = _allowed_string(build.get("world"))
        origin = _allowed_tuple(build.get("origin"))
        if world:
            projected_build["world"] = world
        if origin:
            projected_build["origin"] = origin
        if projected_build:
            projected["build"] = projected_build
    return projected


def _project_array(value):
    if not isinstance(value, list):
        return None
    projected = [_allowed_scalar(item) for item in value]
    for original, allowed in zip(value, projected):
        if allowed is None and original is not None:
            return None
    return projected


def _project_block_value(value, *, require_namespace):
    try:
        return _parse_block_value(
            value, "projected block value", require_namespace=require_namespace
        )
    except ObserverValidationError:
        return None


def _project_block_values(value):
    if not isinstance(value, list):
        return None
    projected = [
        _project_block_value(item, require_namespace=True) for item in value
    ]
    return projected if all(item is not None for item in projected) else None


def _project_params(method, value):
    try:
        return _parse_params(method, value)
    except ObserverValidationError:
        return None


def _project_position(value):
    if not isinstance(value, Mapping):
        return None
    world = _allowed_string(value.get("world"))
    pos = _allowed_tuple(value.get("pos"))
    return {"world": world, "pos": pos} if world and pos else None


def _project_pose(value):
    if not isinstance(value, Mapping):
        return None
    world = _allowed_string(value.get("world"))
    pos = _allowed_tuple(value.get("pos"))
    yaw = _allowed_number(value.get("yaw"))
    pitch = _allowed_number(value.get("pitch"))
    if not world or pos is None or yaw is None or pitch is None:
        return None
    return {"world": world, "pos": pos, "yaw": yaw, "pitch": pitch}


def _project_error(value):
    if isinstance(value, Mapping):
        code = value.get("code")
        message = value.get("message")
        data = value.get("data")
    else:
        code = getattr(value, "code", None)
        message = getattr(value, "message", None) or str(value)
        data = getattr(value, "data", None)
    if not isinstance(code, str) and _allowed_number(code) is None:
        code = None
    message = _allowed_string(message) or "McRemote error"
    projected = {"code": code, "message": message}
    if isinstance(data, Mapping):
        projected_data = {}
        for key in ("reason", "block_id", "property"):
            if isinstance(data.get(key), str):
                projected_data[key] = data[key]
        if data.get("value") is not None:
            value = _allowed_scalar(data["value"])
            if value is not None:
                projected_data["value"] = value
        allowed = data.get("allowed")
        if isinstance(allowed, list):
            projected_allowed = [_allowed_scalar(item) for item in allowed]
            if all(item is not None for item in projected_allowed):
                projected_data["allowed"] = projected_allowed
        for key in ("bounds", "violating"):
            values = data.get(key)
            if isinstance(values, list):
                projected_values = [_allowed_number(item) for item in values]
                if all(item is not None for item in projected_values):
                    projected_data[key] = projected_values
        if projected_data:
            projected["data"] = projected_data
    return projected


class PythonObserverSource:
    """Project one ``Minecraft.create()`` main connection without retention.

    Sanitized frames are delivered to ``frame_consumer`` and immediately
    forgotten.  A later relay may retain a bounded sequence and pass it to
    :meth:`snapshot`; this source does not choose that retention policy.
    """

    _alias_lock = threading.Lock()
    _active_aliases = weakref.WeakValueDictionary()

    def __init__(
        self,
        frame_consumer: Callable[[dict], None] | None = None,
        *,
        lifecycle_consumer: Callable[[str, "PythonObserverSource"], None]
        | None = None,
        clock: Callable[[], int | float] | None = None,
        target_id_factory: Callable[[], str] | None = None,
        alias_factory: Callable[[], str] | None = None,
    ):
        self._frame_consumer = frame_consumer
        self._lifecycle_consumer = lifecycle_consumer
        self._clock = clock or (lambda: time.time_ns() // 1_000_000)
        self._target_id_factory = target_id_factory or (
            lambda: f"target-{secrets.token_hex(16)}"
        )
        self._alias_factory = alias_factory or _generate_display_alias
        self.connection_opened()

    def set_frame_consumer(self, consumer: Callable[[dict], None] | None):
        """Set an in-process sink for already-sanitized frames."""

        self._frame_consumer = consumer

    def set_lifecycle_consumer(self, consumer):
        """Set an in-process sink for target lifecycle events."""

        self._lifecycle_consumer = consumer

    def _emit_lifecycle(self, event):
        if self._lifecycle_consumer is not None:
            self._lifecycle_consumer(event, self)

    def connection_opened(self):
        self._release_alias()
        self.active = False
        self.target_id = None
        self.display_alias = None
        self.hello = None
        self.status = "connected"
        self._sequence = 0
        self._pending_hello = []

    def connection_closed(self):
        was_active = self.active
        self._release_alias()
        self.active = False
        self._pending_hello = []
        if was_active:
            self._emit_lifecycle("target-ended")

    def _release_alias(self):
        alias = getattr(self, "display_alias", None)
        if not alias:
            return
        with self._alias_lock:
            if self._active_aliases.get(alias) is self:
                self._active_aliases.pop(alias, None)

    def _reserve_alias(self):
        for _attempt in range(32):
            alias = _required_string(self._alias_factory(), "target.display_alias")
            with self._alias_lock:
                if alias not in self._active_aliases:
                    self._active_aliases[alias] = self
                    return alias
        raise ObserverValidationError(
            "could not allocate a unique active display alias"
        )

    def _next_frame(self, direction, request_id, method, payload):
        if method not in OBSERVED_METHODS or method.startswith("auth."):
            return None
        if request_id is not None and not isinstance(request_id, str):
            if _allowed_number(request_id) is None:
                request_id = None
        self._sequence += 1
        frame = {
            "sequence": self._sequence,
            "observed_at": self._clock(),
            "direction": direction,
            "request_id": request_id,
            "method": method,
            "payload": payload,
        }
        try:
            return _parse_frame(frame)
        except ObserverValidationError:
            return None

    def _emit(self, frame):
        if frame is not None and self._frame_consumer is not None:
            self._frame_consumer(frame)

    def observe_request(self, method, params, request_id):
        if method == "hello":
            allowed = _project_hello_params(params)
        else:
            allowed = _project_params(method, params)
        if allowed is None:
            return
        frame = self._next_frame("send", request_id, method, {"params": allowed})
        if method == "hello" and not self.active:
            self._pending_hello = [frame] if frame is not None else []
        elif self.active:
            self._emit(frame)

    def observe_result(self, method, result, request_id):
        valid_null = False
        if method == "hello":
            allowed = _project_hello(result)
        elif method in {"player.getPos", "player.setPos"}:
            allowed = _project_position(result)
        elif method in {"player.getPose", "player.setPose"}:
            allowed = _project_pose(result)
        elif method == "world.getBlock":
            allowed = _project_block_value(result, require_namespace=True)
        elif method == "world.getBlocks":
            allowed = _project_block_values(result)
        elif method == "events.poll":
            try:
                allowed = _parse_event_batch(result)
            except ObserverValidationError:
                allowed = None
        elif method in {
            "world.getHeight",
            "world.spawnParticle",
            "world.spawnEntity",
        }:
            try:
                allowed = _parse_result(method, result)
            except ObserverValidationError:
                allowed = None
        elif method in {"world.setBlock", "world.setBlocks", "connection.flush"}:
            allowed = None
            valid_null = result is None
        else:
            allowed = _allowed_scalar(result)
            valid_null = result is None
            if allowed is None and not valid_null:
                return
        if allowed is None and not valid_null:
            return
        frame = self._next_frame("receive", request_id, method, {"result": allowed})
        if method == "hello" and not self.active:
            target_id = _required_string(self._target_id_factory(), "target.id")
            if target_id == MAIN_STREAM_ID:
                raise ObserverValidationError(
                    "target id must not be used as a stream id"
                )
            self.target_id = target_id
            self.display_alias = self._reserve_alias()
            self.hello = _parse_hello(allowed)
            self.active = True
            for pending in self._pending_hello:
                self._emit(pending)
            self._pending_hello = []
            self._emit(frame)
            self._emit_lifecycle("target-activated")
            return
        if self.active:
            self.status = "connected"
            self._emit(frame)

    def observe_error(self, method, error, request_id):
        frame = self._next_frame(
            "receive", request_id, method, {"error": _project_error(error)}
        )
        if self.active:
            self.status = "error"
            self._emit(frame)

    def snapshot(self, frames: Iterable[Mapping] = (), *, emitted_at=None):
        """Build a snapshot from a caller-owned, bounded sanitized frame list."""

        if not self.active or self.hello is None:
            raise ObserverValidationError("observer target is not active")
        value = {
            "schema": OBSERVER_SCHEMA,
            "schema_version": OBSERVER_SCHEMA_VERSION,
            "emitted_at": self._clock() if emitted_at is None else emitted_at,
            "target": {
                "id": self.target_id,
                "display_alias": self.display_alias,
                "source_kind": "python",
            },
            "streams": [
                {
                    "id": MAIN_STREAM_ID,
                    "kind": "main",
                    "status": self.status,
                    "hello": self.hello,
                    "frames": list(frames),
                }
            ],
        }
        return validate_snapshot(value)
