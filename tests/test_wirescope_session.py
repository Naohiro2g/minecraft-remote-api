"""Cross-adapter conformance for observer session envelope v1."""

import hashlib
import json
from pathlib import Path

import pytest

from mc_remote._wirescope_session import (
    JAVASCRIPT_MAX_SAFE_INTEGER,
    OBSERVER_SESSION_END,
    OBSERVER_SESSION_PROTOCOL_VERSION,
    OBSERVER_SESSION_SNAPSHOT,
    WireScopeSessionError,
    encode_end,
    encode_snapshot,
    end_envelope,
    snapshot_envelope,
)
from mc_remote.observer import ObserverValidationError


FIXTURES = Path(__file__).parent / "fixtures"
SESSION_FIXTURE = FIXTURES / "observer-session-lifecycle.ndjson"
SESSION_SOURCE = FIXTURES / "observer-session-lifecycle.source.json"


def fixture_lines():
    return SESSION_FIXTURE.read_bytes().splitlines(keepends=True)


def fixture_envelopes():
    return [json.loads(line) for line in fixture_lines()]


def test_scratch_session_fixture_has_fixed_remote_provenance():
    source = json.loads(SESSION_SOURCE.read_text(encoding="utf-8"))
    assert source == {
        "repository": "Naohiro2g/scratch-editor",
        "commit": "e0794c1d09ecc99efceec786fe9d46c23a250db3",
        "path": (
            "mc-remote/live/test/fixtures/"
            "observer-session-lifecycle.ndjson"
        ),
        "sha256": (
            "3c95e11cceb00318fdf1fc09a8dad335"
            "7466a31a855846df18d7c1d28bce986c"
        ),
    }
    assert hashlib.sha256(SESSION_FIXTURE.read_bytes()).hexdigest() == source[
        "sha256"
    ]


def test_python_encoder_matches_scratch_ndjson_fixture_byte_for_byte():
    lines = fixture_lines()
    snapshot, terminal = fixture_envelopes()

    assert encode_snapshot(
        snapshot["snapshot"],
        dropped_frames=snapshot["history_window"]["dropped_frames"],
    ) == lines[0]
    assert encode_end(terminal["reason"]) == lines[1]


def test_scratch_fixture_has_atomic_history_and_terminal_line_order():
    snapshot, terminal = fixture_envelopes()
    assert snapshot == snapshot_envelope(
        snapshot["snapshot"],
        dropped_frames=7,
    )
    assert snapshot["type"] == OBSERVER_SESSION_SNAPSHOT
    assert snapshot["protocol_version"] == OBSERVER_SESSION_PROTOCOL_VERSION
    assert snapshot["history_window"] == {"dropped_frames": 7}
    assert terminal == end_envelope("target-ended")
    assert terminal["type"] == OBSERVER_SESSION_END


@pytest.mark.parametrize(
    "dropped_frames",
    [-1, True, 1.5, JAVASCRIPT_MAX_SAFE_INTEGER + 1],
)
def test_history_window_uses_scratch_safe_integer_boundary(dropped_frames):
    snapshot = fixture_envelopes()[0]["snapshot"]
    with pytest.raises(WireScopeSessionError, match="non-negative safe integer"):
        snapshot_envelope(snapshot, dropped_frames=dropped_frames)


@pytest.mark.parametrize(
    "reason",
    ["target-ended", "source-closed", "backpressure", "capacity-exhausted"],
)
def test_all_wire_end_reasons_are_encodable(reason):
    assert end_envelope(reason)["reason"] == reason


@pytest.mark.parametrize("reason", ["transport-lost", None, []])
def test_non_wire_values_are_not_end_reasons(reason):
    with pytest.raises(WireScopeSessionError, match="end reason is invalid"):
        end_envelope(reason)


def test_snapshot_schema_v1_stays_strict_inside_session_envelope():
    snapshot = fixture_envelopes()[0]["snapshot"]
    snapshot["history_window"] = {"dropped_frames": 7}
    with pytest.raises(ObserverValidationError, match="unknown field"):
        snapshot_envelope(snapshot, dropped_frames=7)
