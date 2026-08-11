"""Detached WireScope artifact parsing and integrity primitives.

The shared Scratch generator owns the versioned manifest field names.  This
module therefore implements only the consumer boundaries that are already
stable across profiles: strict detached-JSON parsing, an externally pinned
manifest digest, and archive-byte verification against the digest supplied by
the versioned manifest adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import string
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class WireScopeArtifactError(ValueError):
    """The detached artifact cannot be trusted or parsed."""


@dataclass(frozen=True, slots=True)
class DetachedManifest:
    """A strictly parsed manifest and the digest of its exact input bytes."""

    document: Mapping[str, Any]
    sha256: str


def _normalize_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise WireScopeArtifactError(f"{label} SHA-256 must be a string")
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in string.hexdigits for character in normalized
    ):
        raise WireScopeArtifactError(
            f"{label} SHA-256 must contain exactly 64 hexadecimal characters"
        )
    return normalized


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_sha256(payload: bytes, expected_sha256: str, *, label: str) -> str:
    """Verify exact bytes and return their normalized SHA-256 digest."""

    if not isinstance(payload, bytes):
        raise TypeError("artifact payload must be bytes")
    expected = _normalize_sha256(expected_sha256, label=label)
    actual = _sha256(payload)
    if not hmac.compare_digest(actual, expected):
        raise WireScopeArtifactError(f"{label} SHA-256 mismatch")
    return actual


def _reject_duplicate_object_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise WireScopeArtifactError(
                f"detached manifest contains duplicate key: {key}"
            )
        value[key] = item
    return value


def parse_detached_manifest(
    payload: bytes,
    *,
    expected_sha256: str,
) -> DetachedManifest:
    """Verify and strictly parse a detached manifest.

    ``expected_sha256`` comes from the distribution's outer trust boundary
    (wheel ``RECORD`` or deployment lock), not from the manifest itself.
    """

    digest = verify_sha256(payload, expected_sha256, label="manifest")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WireScopeArtifactError(
            "detached manifest must be valid UTF-8"
        ) from exc
    try:
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=lambda value: (_raise_json_constant(value)),
        )
    except WireScopeArtifactError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise WireScopeArtifactError(
            "detached manifest must be one complete JSON document"
        ) from exc
    if not isinstance(document, dict):
        raise WireScopeArtifactError(
            "detached manifest top level must be a JSON object"
        )
    return DetachedManifest(MappingProxyType(document), digest)


def _raise_json_constant(value):
    raise WireScopeArtifactError(
        f"detached manifest contains non-JSON numeric constant: {value}"
    )


def verify_archive(payload: bytes, *, expected_sha256: str) -> str:
    """Verify archive bytes against the digest read by a versioned adapter."""

    return verify_sha256(payload, expected_sha256, label="archive")
