"""Conformance to the shared WireScope station attach v1 fixture."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mc_remote import _wirescope_station_contract as station
from mc_remote._wirescope_session import end_envelope
from mc_remote.wirescope import _AttachCode, _LoopbackRequestPolicy


FIXTURES = Path(__file__).parent / "fixtures"
CONTRACT_FIXTURE = FIXTURES / "station-attach-v1.json"
CONTRACT_SOURCE = FIXTURES / "station-attach-v1.source.json"
SESSION_FIXTURE = FIXTURES / "observer-session-lifecycle.ndjson"


class MutableClock:
    def __init__(self, value=1000):
        self.value = value

    def __call__(self):
        return self.value


def contract_fixture():
    return json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))


def test_station_fixture_has_fixed_scratch_and_knowledge_provenance():
    source = json.loads(CONTRACT_SOURCE.read_text(encoding="utf-8"))
    assert source == {
        "repository": "Naohiro2g/scratch-editor",
        "branch": "agent/wirescope-session-artifact",
        "commit": "192d1e3ccd213fb5012b92655e51b779270e15be",
        "path": "mc-remote/live/test/fixtures/station-attach-v1.json",
        "sha256": (
            "b50ce8e0cb8a6bb06f75d9bdad59b830"
            "06c92683bd73ced84a18223dde21fa81"
        ),
        "knowledge_commit": "367e1cf5ee936cf9ffef53fa9a3a910501fb927f",
        "decision_id": "2026-08-12-01",
    }
    assert hashlib.sha256(CONTRACT_FIXTURE.read_bytes()).hexdigest() == source[
        "sha256"
    ]


def test_transport_constants_headers_and_limits_match_shared_fixture():
    fixture = contract_fixture()
    assert fixture["protocol_version"] == station.STATION_ATTACH_PROTOCOL_VERSION
    assert fixture["paths"] == {
        "bootstrap": station.STATION_BOOTSTRAP_PATH,
        "attach": station.STATION_ATTACH_PATH,
    }
    assert fixture["content_types"] == {
        "json": station.STATION_JSON_CONTENT_TYPE,
        "ndjson": station.STATION_NDJSON_CONTENT_TYPE,
    }
    assert fixture["limits"] == {
        "bootstrap_response_max_bytes": station.STATION_BOOTSTRAP_MAX_BYTES,
        "error_response_max_bytes": station.STATION_ERROR_MAX_BYTES,
        "attach_request_max_bytes": station.STATION_ATTACH_REQUEST_MAX_BYTES,
        "ndjson_line_max_bytes": station.STATION_NDJSON_LINE_MAX_BYTES,
    }
    assert fixture["required_response_headers"] == dict(
        station.STATION_REQUIRED_RESPONSE_HEADERS
    )
    assert _LoopbackRequestPolicy(43123).response_headers == fixture[
        "required_response_headers"
    ]


def test_ready_and_not_ready_bootstrap_shapes_round_trip_strictly():
    fixture = contract_fixture()
    for key, readiness in (
        ("bootstrap_ready", True),
        ("bootstrap_not_ready", False),
    ):
        expected = fixture[key]
        assert station.validate_bootstrap(expected) == expected
        encoded = station.encode_bootstrap(
            manifest_sha256=expected["artifact"]["manifest_sha256"],
            station_ready=readiness,
        )
        assert len(encoded) <= station.STATION_BOOTSTRAP_MAX_BYTES
        assert station.parse_bootstrap(encoded) == expected
        assert b"target" not in encoded
        assert b"attach_code" not in encoded


@pytest.mark.parametrize(
    "change, message",
    [
        (
            lambda value: value.update({"target_id": "secret"}),
            "unknown field: target_id",
        ),
        (
            lambda value: value["artifact"].update(
                {"manifest_sha256": "A" * 64}
            ),
            "64 lowercase hexadecimal",
        ),
        (
            lambda value: value.update({"station_ready": 1}),
            "station_ready must be a boolean",
        ),
        (
            lambda value: value.update(
                {"station_attach_protocol_version": True}
            ),
            "station attach protocol version is unsupported",
        ),
        (
            lambda value: value["observer_schema"].update({"version": True}),
            "observer schema is unsupported",
        ),
    ],
)
def test_bootstrap_rejects_unknown_or_ambiguous_values(change, message):
    value = copy.deepcopy(contract_fixture()["bootstrap_ready"])
    change(value)
    with pytest.raises(station.StationContractError, match=message):
        station.validate_bootstrap(value)


def test_bootstrap_parser_enforces_strict_json_and_response_byte_limit():
    fixture = contract_fixture()["bootstrap_ready"]
    encoded = json.dumps(fixture, separators=(",", ":")).encode("utf-8")
    assert station.parse_bootstrap(encoded) == fixture
    with pytest.raises(station.StationContractError, match="duplicate key"):
        station.parse_bootstrap(
            b'{"station_ready":true,"station_ready":false}'
        )
    oversized = b'{' + (b" " * station.STATION_BOOTSTRAP_MAX_BYTES) + b'}'
    with pytest.raises(station.StationContractError, match="byte limit"):
        station.parse_bootstrap(oversized)


def test_attach_request_parser_accepts_only_the_exact_json_shape():
    request = contract_fixture()["attach_request"]
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    assert station.parse_attach_request(payload) == request["attach_code"]

    invalid = (
        b'{}',
        b'{"attach_code":0}',
        b'{"attach_code":"00000000","target":"secret"}',
        b'{"attach_code":"00000000","attach_code":"11111111"}',
        b'{"attach_code":"00000000"} trailing',
        b'\xef\xbb\xbf{"attach_code":"00000000"}',
        b'{"attach_code":"\xff"}',
    )
    for candidate in invalid:
        with pytest.raises(station.StationContractError):
            station.parse_attach_request(candidate)

    oversized = b'{"attach_code":"' + (
        b"0" * station.STATION_ATTACH_REQUEST_MAX_BYTES
    ) + b'"}'
    with pytest.raises(station.StationContractError, match="byte limit"):
        station.parse_attach_request(oversized)


def test_attach_error_status_body_and_attempt_accounting_match_fixture():
    fixture_errors = contract_fixture()["attach_errors"]
    actual = []
    for expected in fixture_errors:
        code = expected["body"]["error"]
        error = station.attach_error(code)
        actual.append(
            {
                "status": error.status,
                "body": error.body(),
                "consumes_attempt": error.consumes_attempt,
            }
        )
        encoded = station.encode_attach_error(code)
        assert station.parse_attach_error(encoded) == expected["body"]
        assert len(encoded) <= station.STATION_ERROR_MAX_BYTES
    assert actual == fixture_errors
    with pytest.raises(station.StationContractError, match="code is invalid"):
        station.attach_error("transport-lost")

    for invalid in (
        b'{"error":"target-not-ready","retry_after":1}',
        b'{"error":"transport-lost"}',
        b'{"error":1}',
        b'{"error":"target-not-ready","error":"invalid-code"}',
    ):
        with pytest.raises(station.StationContractError):
            station.parse_attach_error(invalid)


def test_attach_capability_results_map_without_changing_attempt_semantics():
    clock = MutableClock()
    values = iter([0, 1])
    capability = _AttachCode(
        clock=clock,
        random_bits=lambda _bits: next(values),
    )
    result = capability.redeem("00000000")
    assert result == "target-not-ready"
    assert station.attach_error(result).consumes_attempt is False

    capability.activate("target-1")
    result = capability.redeem("not-a-code")
    assert result == "malformed-code"
    assert station.attach_error(result).consumes_attempt is False

    for _attempt in range(4):
        result = capability.redeem("00000001")
        assert result == "invalid-code"
        assert station.attach_error(result).consumes_attempt is True
    result = capability.redeem("00000001")
    assert result == "attempts-exhausted"
    assert station.attach_error(result).consumes_attempt is True


def test_shared_session_fixture_uses_valid_strict_ndjson_lines():
    lines = SESSION_FIXTURE.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    parsed = [station.validate_ndjson_line(line) for line in lines]
    assert parsed[0]["type"] == "mcremote.wirescope.snapshot"
    assert parsed[1] == end_envelope("target-ended")


def json_line_of_size(size):
    prefix = b'{"value":"'
    suffix = b'"}'
    return prefix + (b"x" * (size - len(prefix) - len(suffix))) + suffix + b"\n"


def test_ndjson_line_accepts_the_exact_byte_boundary():
    line = json_line_of_size(station.STATION_NDJSON_LINE_MAX_BYTES)
    assert len(line) == station.STATION_NDJSON_LINE_MAX_BYTES + 1
    assert station.validate_ndjson_line(line)["value"].startswith("x")


@pytest.mark.parametrize(
    "payload, message",
    [
        (b'{}', "end with LF"),
        (b'{}\r\n', "one LF delimiter"),
        (b'\xef\xbb\xbf{}\n', "UTF-8 BOM"),
        (b'\n', "must not be empty"),
        (b'{}\n\n', "one LF delimiter"),
        (b'{"value":"\xff"}\n', "strict UTF-8"),
        (b'{"key":1,"key":2}\n', "duplicate key"),
        (b'[]\n', "JSON object"),
    ],
)
def test_ndjson_line_rejects_invalid_framing_or_json(payload, message):
    with pytest.raises(station.StationContractError, match=message):
        station.validate_ndjson_line(payload)


def test_ndjson_line_rejects_one_byte_over_the_limit():
    line = json_line_of_size(station.STATION_NDJSON_LINE_MAX_BYTES + 1)
    with pytest.raises(station.StationContractError, match="byte limit"):
        station.validate_ndjson_line(line)
