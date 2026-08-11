"""Tests for detached WireScope artifact integrity boundaries."""

import hashlib

import pytest

from mc_remote._wirescope_artifact import (
    WireScopeArtifactError,
    parse_detached_manifest,
    verify_archive,
)


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def test_detached_manifest_is_pinned_by_its_exact_outer_bytes():
    payload = b'{"fixture":"scratch-generator"}\n'
    parsed = parse_detached_manifest(
        payload,
        expected_sha256=sha256(payload).upper(),
    )
    assert parsed.document == {"fixture": "scratch-generator"}
    assert parsed.sha256 == sha256(payload)

    changed = b'{"fixture":"scratch-generator"} '
    with pytest.raises(WireScopeArtifactError, match="manifest SHA-256 mismatch"):
        parse_detached_manifest(changed, expected_sha256=sha256(payload))


@pytest.mark.parametrize(
    "payload, message",
    [
        (b'{"key":1,"key":2}', "duplicate key"),
        (b"[]", "top level must be a JSON object"),
        (b'{"value":NaN}', "non-JSON numeric constant"),
        (b'{"value":1} trailing', "one complete JSON document"),
        (b'\xff', "valid UTF-8"),
    ],
)
def test_detached_manifest_parser_rejects_ambiguous_or_invalid_json(
    payload,
    message,
):
    with pytest.raises(WireScopeArtifactError, match=message):
        parse_detached_manifest(payload, expected_sha256=sha256(payload))


def test_archive_hash_is_checked_against_manifest_adapter_output():
    archive = b"deterministic ZIP fixture bytes"
    assert verify_archive(archive, expected_sha256=sha256(archive)) == sha256(
        archive
    )
    with pytest.raises(WireScopeArtifactError, match="archive SHA-256 mismatch"):
        verify_archive(archive + b"changed", expected_sha256=sha256(archive))


@pytest.mark.parametrize("expected", ["", "0" * 63, "g" * 64, None])
def test_hash_verifier_rejects_malformed_expected_digest(expected):
    with pytest.raises(WireScopeArtifactError, match="SHA-256"):
        verify_archive(b"archive", expected_sha256=expected)


def test_hash_verifier_requires_exact_bytes():
    with pytest.raises(TypeError, match="payload must be bytes"):
        verify_archive(bytearray(b"archive"), expected_sha256="0" * 64)
