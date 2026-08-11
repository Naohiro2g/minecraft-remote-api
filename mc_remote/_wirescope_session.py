"""WireScope observer session envelope v1 encoding.

The serialized shape is shared with ``@mc-remote/live`` and is exercised
against its transport-neutral NDJSON lifecycle fixture.
"""

from __future__ import annotations

import json

from .observer import validate_snapshot


OBSERVER_SESSION_PROTOCOL_VERSION = 1
OBSERVER_SESSION_SNAPSHOT = "mcremote.wirescope.snapshot"
OBSERVER_SESSION_END = "mcremote.wirescope.end"
OBSERVER_SESSION_WIRE_END_REASONS = frozenset(
    {
        "target-ended",
        "source-closed",
        "backpressure",
        "capacity-exhausted",
    }
)
JAVASCRIPT_MAX_SAFE_INTEGER = (1 << 53) - 1


class WireScopeSessionError(ValueError):
    """A value cannot be represented by observer session protocol v1."""


def snapshot_envelope(snapshot, *, dropped_frames):
    """Build one atomic snapshot/history-window envelope."""

    if (
        isinstance(dropped_frames, bool)
        or not isinstance(dropped_frames, int)
        or dropped_frames < 0
        or dropped_frames > JAVASCRIPT_MAX_SAFE_INTEGER
    ):
        raise WireScopeSessionError(
            "history_window.dropped_frames must be a non-negative safe integer"
        )
    return {
        "type": OBSERVER_SESSION_SNAPSHOT,
        "protocol_version": OBSERVER_SESSION_PROTOCOL_VERSION,
        "snapshot": validate_snapshot(snapshot),
        "history_window": {"dropped_frames": dropped_frames},
    }


def end_envelope(reason):
    """Build one terminal wire envelope.

    ``transport-lost`` is deliberately excluded because only the browser may
    synthesize it after an incomplete transport.
    """

    if (
        not isinstance(reason, str)
        or reason not in OBSERVER_SESSION_WIRE_END_REASONS
    ):
        raise WireScopeSessionError("observer session end reason is invalid")
    return {
        "type": OBSERVER_SESSION_END,
        "protocol_version": OBSERVER_SESSION_PROTOCOL_VERSION,
        "reason": reason,
    }


def encode_envelope(envelope):
    """Encode one already constructed envelope as one UTF-8 NDJSON line."""

    return (
        json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def encode_snapshot(snapshot, *, dropped_frames):
    """Validate and encode one snapshot envelope as an NDJSON line."""

    return encode_envelope(
        snapshot_envelope(snapshot, dropped_frames=dropped_frames)
    )


def encode_end(reason):
    """Validate and encode one terminal envelope as an NDJSON line."""

    return encode_envelope(end_envelope(reason))
