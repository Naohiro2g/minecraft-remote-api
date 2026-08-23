"""Observer session envelope v1 and protocol 22 candidate conformance."""

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
from mc_remote.observer import ObserverValidationError, PythonObserverSource


FIXTURES = Path(__file__).parent / "fixtures"
SESSION_FIXTURE = FIXTURES / "observer-session-lifecycle.ndjson"
SESSION_SOURCE = FIXTURES / "observer-session-lifecycle.source.json"
POLL_BOUNDARY_FIXTURE = FIXTURES / "python-events-poll-frame-boundary.json"


def fixture_lines():
    return SESSION_FIXTURE.read_bytes().splitlines(keepends=True)


def fixture_envelopes():
    return [json.loads(line) for line in fixture_lines()]


def test_protocol22_session_fixture_has_fixed_candidate_provenance():
    source = json.loads(SESSION_SOURCE.read_text(encoding="utf-8"))
    assert source == {
        "repository": "Naohiro2g/minecraft-remote-api",
        "base_commit": "af2b19dd4a4f0404c4bde439021ca7e017904a04",
        "path": "tests/fixtures/observer-session-lifecycle.ndjson",
        "sha256": (
            "e60001bdb04001490b3f21dcc97736055"
            "4a1ebd25d4540a15e27db0bf0db4ea9"
        ),
        "knowledge_commit": "f9d5dc7780ab2673b8872dc7481d230e10ca95d9",
        "decision_id": "2026-08-22-02",
        "status": "dimension-key-local-candidate-awaiting-common-artifact",
    }
    assert hashlib.sha256(SESSION_FIXTURE.read_bytes()).hexdigest() == source[
        "sha256"
    ]


def test_python_encoder_matches_protocol22_candidate_byte_for_byte():
    lines = fixture_lines()
    snapshot, terminal = fixture_envelopes()

    assert encode_snapshot(
        snapshot["snapshot"],
        dropped_frames=snapshot["history_window"]["dropped_frames"],
    ) == lines[0]
    assert encode_end(terminal["reason"]) == lines[1]


def test_candidate_fixture_has_atomic_history_and_terminal_line_order():
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


def test_snapshot_schema_v1_stays_strict_inside_v1_1_compatibility_set():
    snapshot = fixture_envelopes()[0]["snapshot"]
    snapshot["history_window"] = {"dropped_frames": 7}
    with pytest.raises(ObserverValidationError, match="unknown field"):
        snapshot_envelope(snapshot, dropped_frames=7)


def test_maximum_poll_response_fits_one_schema_v1_session_frame():
    fixture = json.loads(POLL_BOUNDARY_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["knowledge_commit"] == (
        "c9cf761453d67d120ec54a1b246e8f5e80a6160c"
    )
    assert fixture["decision_id"] == "2026-08-21-02"
    assert fixture["observer_schema_version"] == 1
    assert fixture["compatibility_set_revision"] == "v1.1"

    response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "events": [
                {
                    "sequence": 1,
                    "type": "chat_posted",
                    "dimension": "minecraft:overworld",
                    "origin": [200, 0, 200],
                    "message": "",
                }
            ],
            "through_sequence": 1,
            "latest_sequence": 1,
            "filtered_out": 0,
            "overflow_dropped_total": 0,
            "capacity_dropped_total": 0,
            "explicitly_discarded_total": 0,
        },
    }

    def compact_bytes(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    response_limit = fixture["compact_jsonrpc_response_max_bytes"]
    unit = "".join(
        chr(code_point)
        for code_point in fixture["message_pattern"]["unit_code_points"]
    )
    empty_size = len(compact_bytes(response))
    encoded_unit_size = len(compact_bytes(unit)) - len(compact_bytes(""))
    repetitions = (response_limit - empty_size) // encoded_unit_size
    assert repetitions >= fixture["message_pattern"]["minimum_repetitions"]
    message = unit * repetitions
    response["result"]["events"][0]["message"] = message
    remaining = response_limit - len(compact_bytes(response))
    response["result"]["events"][0]["message"] += "x" * remaining
    assert len(compact_bytes(response)) == response_limit

    frames = []
    observer = PythonObserverSource(
        frames.append,
        target_id_factory=lambda: "target-b5-poll-boundary",
        alias_factory=lambda: "MIND-STORM-000029",
        clock=lambda: 1786122000000,
    )
    hello = fixture_envelopes()[0]["snapshot"]["streams"][0]["hello"]
    observer.observe_request("hello", {"protocol": "22.0.0"}, 1)
    observer.observe_result("hello", hello, 1)
    frames.clear()
    observer.observe_request("events.poll", [0], 2)
    observer.observe_result("events.poll", response["result"], 2)
    assert len(frames) == 2

    encoded = encode_snapshot(
        observer.snapshot(frames, emitted_at=1786122000100),
        dropped_frames=0,
    )
    assert len(encoded) <= fixture["observer_session_frame_max_bytes"]
