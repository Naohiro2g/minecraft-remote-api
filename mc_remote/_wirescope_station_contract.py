"""WireScope same-origin station attach protocol v1 primitives.

The constants and shapes in this module conform to the shared Scratch fixture
``mc-remote/live/test/fixtures/station-attach-v1.json``.  This is a transport
contract layer; it does not start an HTTP server or synthesize the browser's
local ``transport-lost`` state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType

from ._wirescope_session import (
    OBSERVER_SESSION_PROTOCOL_VERSION,
)
from .observer import OBSERVER_SCHEMA, OBSERVER_SCHEMA_VERSION


STATION_ATTACH_PROTOCOL_VERSION = 1
STATION_BOOTSTRAP_PATH = "/__mcremote/wirescope/bootstrap/v1"
STATION_ATTACH_PATH = "/__mcremote/wirescope/attach/v1"

STATION_JSON_CONTENT_TYPE = "application/json"
STATION_NDJSON_CONTENT_TYPE = "application/x-ndjson"

STATION_BOOTSTRAP_MAX_BYTES = 4 * 1024
STATION_ERROR_MAX_BYTES = 4 * 1024
STATION_ATTACH_REQUEST_MAX_BYTES = 1024
STATION_NDJSON_LINE_MAX_BYTES = 512 * 1024

STATION_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)

STATION_REQUIRED_RESPONSE_HEADERS = MappingProxyType(
    {
        "Cache-Control": "no-store",
        "Content-Security-Policy": STATION_CONTENT_SECURITY_POLICY,
        "Cross-Origin-Opener-Policy": "same-origin",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
)


@dataclass(frozen=True, slots=True)
class StationAttachError:
    status: int
    code: str
    consumes_attempt: bool

    def body(self):
        return {"error": self.code}


_ATTACH_ERRORS = {
    error.code: error
    for error in (
        StationAttachError(409, "target-not-ready", False),
        StationAttachError(400, "malformed-code", False),
        StationAttachError(403, "invalid-code", True),
        StationAttachError(429, "attempts-exhausted", True),
        StationAttachError(410, "code-expired", False),
        StationAttachError(409, "already-redeemed", False),
        StationAttachError(400, "invalid-request", False),
    )
}
STATION_ATTACH_ERRORS = MappingProxyType(_ATTACH_ERRORS)


class StationContractError(ValueError):
    """A station request or response violates attach protocol v1."""


def _reject_duplicate_object_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise StationContractError(f"JSON contains duplicate key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value):
    raise StationContractError(f"JSON contains invalid numeric constant: {value}")


def parse_strict_json(payload, *, max_bytes, context):
    """Decode one bounded, strict UTF-8 JSON document."""

    if not isinstance(payload, bytes):
        raise TypeError(f"{context} payload must be bytes")
    if len(payload) > max_bytes:
        raise StationContractError(f"{context} exceeds its byte limit")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise StationContractError(f"{context} must be strict UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_json_constant,
        )
    except StationContractError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise StationContractError(
            f"{context} must be one complete JSON document"
        ) from exc


def _exact_object(value, fields, *, context):
    if not isinstance(value, dict):
        raise StationContractError(f"{context} must be a JSON object")
    actual = set(value)
    expected = set(fields)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise StationContractError(
            f"{context} missing field: {sorted(missing)[0]}"
        )
    if unknown:
        raise StationContractError(
            f"{context} unknown field: {sorted(unknown)[0]}"
        )
    return value


def _manifest_sha256(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StationContractError(
            "artifact.manifest_sha256 must be 64 lowercase hexadecimal characters"
        )
    return value


def validate_bootstrap(value):
    """Validate and normalize the exact bootstrap response shape."""

    bootstrap = _exact_object(
        value,
        (
            "station_attach_protocol_version",
            "observer_session_protocol_version",
            "observer_schema",
            "artifact",
            "station_ready",
        ),
        context="bootstrap response",
    )
    if (
        type(bootstrap["station_attach_protocol_version"]) is not int
        or bootstrap["station_attach_protocol_version"]
        != STATION_ATTACH_PROTOCOL_VERSION
    ):
        raise StationContractError("station attach protocol version is unsupported")
    if (
        type(bootstrap["observer_session_protocol_version"]) is not int
        or bootstrap["observer_session_protocol_version"]
        != OBSERVER_SESSION_PROTOCOL_VERSION
    ):
        raise StationContractError("observer session protocol version is unsupported")
    if not isinstance(bootstrap["station_ready"], bool):
        raise StationContractError("station_ready must be a boolean")
    observer_schema = _exact_object(
        bootstrap["observer_schema"],
        ("name", "version"),
        context="observer_schema",
    )
    if (
        observer_schema["name"] != OBSERVER_SCHEMA
        or isinstance(observer_schema["version"], bool)
        or not isinstance(observer_schema["version"], (int, float))
        or observer_schema["version"] != OBSERVER_SCHEMA_VERSION
    ):
        raise StationContractError("observer schema is unsupported")
    artifact = _exact_object(
        bootstrap["artifact"],
        ("manifest_sha256",),
        context="artifact",
    )
    manifest_sha256 = _manifest_sha256(artifact["manifest_sha256"])
    return {
        "station_attach_protocol_version": STATION_ATTACH_PROTOCOL_VERSION,
        "observer_session_protocol_version": OBSERVER_SESSION_PROTOCOL_VERSION,
        "observer_schema": {
            "name": OBSERVER_SCHEMA,
            "version": OBSERVER_SCHEMA_VERSION,
        },
        "artifact": {"manifest_sha256": manifest_sha256},
        "station_ready": bootstrap["station_ready"],
    }


def build_bootstrap(*, manifest_sha256, station_ready):
    """Build the exact bootstrap response without target information."""

    return validate_bootstrap(
        {
            "station_attach_protocol_version": STATION_ATTACH_PROTOCOL_VERSION,
            "observer_session_protocol_version": OBSERVER_SESSION_PROTOCOL_VERSION,
            "observer_schema": {
                "name": OBSERVER_SCHEMA,
                "version": OBSERVER_SCHEMA_VERSION,
            },
            "artifact": {"manifest_sha256": manifest_sha256},
            "station_ready": station_ready,
        }
    )


def parse_bootstrap(payload):
    return validate_bootstrap(
        parse_strict_json(
            payload,
            max_bytes=STATION_BOOTSTRAP_MAX_BYTES,
            context="bootstrap response",
        )
    )


def parse_attach_request(payload):
    """Parse the strict request shape, leaving code validity to redeem."""

    request = _exact_object(
        parse_strict_json(
            payload,
            max_bytes=STATION_ATTACH_REQUEST_MAX_BYTES,
            context="attach request",
        ),
        ("attach_code",),
        context="attach request",
    )
    if not isinstance(request["attach_code"], str):
        raise StationContractError("attach_code must be a string")
    return request["attach_code"]


def attach_error(code):
    try:
        return STATION_ATTACH_ERRORS[code]
    except (KeyError, TypeError) as exc:
        raise StationContractError("station attach error code is invalid") from exc


def validate_attach_error(value):
    body = _exact_object(value, ("error",), context="attach error response")
    error = attach_error(body["error"])
    return error.body()


def parse_attach_error(payload):
    return validate_attach_error(
        parse_strict_json(
            payload,
            max_bytes=STATION_ERROR_MAX_BYTES,
            context="attach error response",
        )
    )


def _compact_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def encode_bootstrap(*, manifest_sha256, station_ready):
    payload = _compact_json(
        build_bootstrap(
            manifest_sha256=manifest_sha256,
            station_ready=station_ready,
        )
    )
    if len(payload) > STATION_BOOTSTRAP_MAX_BYTES:
        raise StationContractError("bootstrap response exceeds its byte limit")
    return payload


def encode_attach_error(code):
    payload = _compact_json(validate_attach_error({"error": code}))
    if len(payload) > STATION_ERROR_MAX_BYTES:
        raise StationContractError("error response exceeds its byte limit")
    return payload


def validate_ndjson_line(payload):
    """Validate one complete outbound NDJSON line, including its final LF."""

    if not isinstance(payload, bytes):
        raise TypeError("NDJSON line must be bytes")
    if not payload.endswith(b"\n"):
        raise StationContractError("NDJSON line must end with LF")
    line = payload[:-1]
    if not line:
        raise StationContractError("NDJSON line must not be empty")
    if b"\n" in line or b"\r" in line:
        raise StationContractError("NDJSON must use one LF delimiter")
    if line.startswith(b"\xef\xbb\xbf"):
        raise StationContractError("NDJSON line must not contain a UTF-8 BOM")
    if len(line) > STATION_NDJSON_LINE_MAX_BYTES:
        raise StationContractError("NDJSON line exceeds its byte limit")
    value = parse_strict_json(
        line,
        max_bytes=STATION_NDJSON_LINE_MAX_BYTES,
        context="NDJSON line",
    )
    if not isinstance(value, dict):
        raise StationContractError("NDJSON line must contain a JSON object")
    return value
