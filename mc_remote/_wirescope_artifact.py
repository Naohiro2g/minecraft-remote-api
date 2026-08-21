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
import io
import json
import string
import zipfile
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


MANIFEST_SCHEMA = "mcremote.wirescope.app-manifest"
MANIFEST_VERSION = 1
ARCHIVE_FILENAME = "wirescope-app.zip"
ARCHIVE_FORMAT = "zip"
ARCHIVE_FORMAT_VERSION = 1
SOURCE_REPOSITORY = "https://github.com/Naohiro2g/scratch-editor"
SOURCE_SUBDIRECTORY = "mc-remote/live"
LICENSE_EXPRESSION = "AGPL-3.0-only"
JAVASCRIPT_MAX_SAFE_INTEGER = (1 << 53) - 1


class WireScopeArtifactError(ValueError):
    """The detached artifact cannot be trusted or parsed."""


@dataclass(frozen=True, slots=True)
class ArtifactAsset:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DetachedManifest:
    """A strictly parsed manifest and the digest of its exact input bytes."""

    document: Mapping[str, Any]
    sha256: str
    archive_sha256: str
    assets: tuple[ArtifactAsset, ...]


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


def _object(value, *, fields, context):
    if not isinstance(value, dict):
        raise WireScopeArtifactError(f"{context} must be a JSON object")
    actual = set(value)
    missing = fields - actual
    unknown = actual - fields
    if missing:
        raise WireScopeArtifactError(
            f"{context} missing field: {sorted(missing)[0]}"
        )
    if unknown:
        raise WireScopeArtifactError(
            f"{context} unknown field: {sorted(unknown)[0]}"
        )
    return value


def _required_string(value, *, context):
    if not isinstance(value, str) or not value:
        raise WireScopeArtifactError(f"{context} must be a non-empty string")
    return value


def _required_integer(value, *, context, minimum=0):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > JAVASCRIPT_MAX_SAFE_INTEGER
    ):
        raise WireScopeArtifactError(f"{context} must be a safe integer")
    return value


def _exact(value, expected, *, context):
    if value != expected or type(value) is not type(expected):
        raise WireScopeArtifactError(f"{context} is unsupported")
    return value


def _sha256_field(value, *, context):
    normalized = _normalize_sha256(value, label=context)
    if value != normalized:
        raise WireScopeArtifactError(f"{context} SHA-256 must be lowercase")
    return normalized


def _string_record(value, *, required, context):
    if not isinstance(value, dict):
        raise WireScopeArtifactError(f"{context} must be a JSON object")
    missing = required - set(value)
    if missing:
        raise WireScopeArtifactError(
            f"{context} missing field: {sorted(missing)[0]}"
        )
    for key, item in value.items():
        _required_string(key, context=f"{context} key")
        _required_string(item, context=f"{context}.{key}")
    return value


def _validate_asset_path(value):
    path = _required_string(value, context="asset.path")
    components = path.split("/")
    if (
        path.startswith("/")
        or "\\" in path
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise WireScopeArtifactError("asset.path must be a safe relative ZIP path")
    return path


def _validate_manifest(document):
    manifest = _object(
        document,
        fields={
            "manifest_schema",
            "manifest_version",
            "archive",
            "source",
            "build",
            "protocols",
            "assets",
            "license_expression",
        },
        context="detached manifest",
    )
    _exact(
        manifest["manifest_schema"],
        MANIFEST_SCHEMA,
        context="manifest_schema",
    )
    _exact(
        manifest["manifest_version"],
        MANIFEST_VERSION,
        context="manifest_version",
    )

    archive = _object(
        manifest["archive"],
        fields={"file", "format", "format_version", "sha256"},
        context="archive",
    )
    _exact(archive["file"], ARCHIVE_FILENAME, context="archive.file")
    _exact(archive["format"], ARCHIVE_FORMAT, context="archive.format")
    _exact(
        archive["format_version"],
        ARCHIVE_FORMAT_VERSION,
        context="archive.format_version",
    )
    archive_sha256 = _sha256_field(archive["sha256"], context="archive")

    source = _object(
        manifest["source"],
        fields={
            "repository",
            "commit",
            "subdirectory",
            "corresponding_source_url",
        },
        context="source",
    )
    _exact(
        source["repository"],
        SOURCE_REPOSITORY,
        context="source.repository",
    )
    _exact(
        source["subdirectory"],
        SOURCE_SUBDIRECTORY,
        context="source.subdirectory",
    )
    source_commit = _required_string(source["commit"], context="source.commit")
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise WireScopeArtifactError(
            "source.commit must be a lowercase full Git commit SHA"
        )
    expected_source_url = (
        f"{SOURCE_REPOSITORY}/tree/{source_commit}/{SOURCE_SUBDIRECTORY}"
    )
    _exact(
        source["corresponding_source_url"],
        expected_source_url,
        context="source.corresponding_source_url",
    )

    build = _object(
        manifest["build"],
        fields={"recipe", "toolchain", "input_identity"},
        context="build",
    )
    _required_string(build["recipe"], context="build.recipe")
    _string_record(
        build["toolchain"],
        required={"node", "rolldown-vite", "typescript", "jszip"},
        context="build.toolchain",
    )
    inputs = _string_record(
        build["input_identity"],
        required={
            "source_commit",
            "package_json_sha256",
            "package_lock_sha256",
        },
        context="build.input_identity",
    )
    if inputs["source_commit"] != source_commit:
        raise WireScopeArtifactError(
            "build.input_identity.source_commit must match source.commit"
        )
    _sha256_field(
        inputs["package_json_sha256"],
        context="build.input_identity.package_json",
    )
    _sha256_field(
        inputs["package_lock_sha256"],
        context="build.input_identity.package_lock",
    )

    protocols = _object(
        manifest["protocols"],
        fields={
            "observer_schema",
            "observer_session",
            "scratch_handoff",
            "station_attach",
        },
        context="protocols",
    )
    observer_schema = _object(
        protocols["observer_schema"],
        fields={"name", "version"},
        context="protocols.observer_schema",
    )
    _exact(
        observer_schema["name"],
        "mcremote.observer",
        context="protocols.observer_schema.name",
    )
    _exact(
        observer_schema["version"],
        1.1,
        context="protocols.observer_schema.version",
    )
    for field in ("observer_session", "scratch_handoff", "station_attach"):
        _exact(protocols[field], 1, context=f"protocols.{field}")

    raw_assets = manifest["assets"]
    if not isinstance(raw_assets, list) or not raw_assets:
        raise WireScopeArtifactError("assets must be a non-empty array")
    assets = []
    for raw_asset in raw_assets:
        asset = _object(
            raw_asset,
            fields={"path", "bytes", "sha256"},
            context="asset",
        )
        assets.append(
            ArtifactAsset(
                path=_validate_asset_path(asset["path"]),
                bytes=_required_integer(
                    asset["bytes"], context="asset.bytes", minimum=0
                ),
                sha256=_sha256_field(asset["sha256"], context="asset"),
            )
        )
    paths = [asset.path for asset in assets]
    if len(paths) != len(set(paths)):
        raise WireScopeArtifactError("assets must not contain duplicate paths")
    if paths != sorted(paths, key=lambda path: path.encode("utf-8")):
        raise WireScopeArtifactError("assets must use deterministic UTF-8 path order")
    for required_path in ("LICENSE", "NOTICE", "index.html"):
        if required_path not in paths:
            raise WireScopeArtifactError(f"assets missing required path: {required_path}")
    if not any(path.startswith("assets/") for path in paths):
        raise WireScopeArtifactError("assets must contain a browser asset")

    _exact(
        manifest["license_expression"],
        LICENSE_EXPRESSION,
        context="license_expression",
    )
    return archive_sha256, tuple(assets)


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
    archive_sha256, assets = _validate_manifest(document)
    return DetachedManifest(
        MappingProxyType(document),
        digest,
        archive_sha256,
        assets,
    )


def _raise_json_constant(value):
    raise WireScopeArtifactError(
        f"detached manifest contains non-JSON numeric constant: {value}"
    )


def verify_archive(payload: bytes, *, expected_sha256: str) -> str:
    """Verify archive bytes against the digest read by a versioned adapter."""

    return verify_sha256(payload, expected_sha256, label="archive")


def verify_artifact_archive(payload: bytes, manifest: DetachedManifest) -> str:
    """Verify the ZIP itself and every asset declared by its manifest."""

    if not isinstance(manifest, DetachedManifest):
        raise TypeError("manifest must be a parsed DetachedManifest")
    digest = verify_archive(payload, expected_sha256=manifest.archive_sha256)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise WireScopeArtifactError(
                    "archive must not contain duplicate paths"
                )
            expected_names = [asset.path for asset in manifest.assets]
            if names != expected_names:
                raise WireScopeArtifactError(
                    "archive inventory does not match detached manifest"
                )
            for entry, asset in zip(entries, manifest.assets):
                if entry.is_dir():
                    raise WireScopeArtifactError(
                        "archive inventory must contain regular files only"
                    )
                contents = archive.read(entry)
                if len(contents) != asset.bytes:
                    raise WireScopeArtifactError(
                        f"archive asset byte count mismatch: {asset.path}"
                    )
                verify_sha256(
                    contents,
                    asset.sha256,
                    label=f"archive asset {asset.path}",
                )
    except WireScopeArtifactError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise WireScopeArtifactError("archive must be a readable ZIP") from exc
    return digest
