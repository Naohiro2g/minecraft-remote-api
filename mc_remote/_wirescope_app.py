"""Verified, in-memory view of the immutable WireScope browser artifact."""

from __future__ import annotations

import base64
import io
import mimetypes
import zipfile
from dataclasses import dataclass
from importlib import metadata, resources
from types import MappingProxyType

from ._wirescope_artifact import (
    WireScopeArtifactError,
    parse_detached_manifest,
    verify_artifact_archive,
)


_ARTIFACT_ROOT = "_wirescope_app"
_ARCHIVE_NAME = "wirescope-app.zip"
_MANIFEST_NAME = "wirescope-app.manifest.json"
_MANIFEST_PACKAGE_PATH = f"mc_remote/{_ARTIFACT_ROOT}/{_MANIFEST_NAME}"


@dataclass(frozen=True, slots=True)
class WireScopeAsset:
    body: bytes
    content_type: str


class WireScopeApp:
    """A fully verified artifact with no runtime secrets or filesystem writes."""

    def __init__(self, *, manifest_sha256, assets):
        self.manifest_sha256 = manifest_sha256
        self._assets = MappingProxyType(dict(assets))
        if "index.html" not in self._assets:
            raise WireScopeArtifactError("artifact does not contain index.html")

    @classmethod
    def from_bytes(cls, manifest_bytes, archive_bytes, *, manifest_sha256):
        manifest = parse_detached_manifest(
            manifest_bytes,
            expected_sha256=manifest_sha256,
        )
        verify_artifact_archive(archive_bytes, manifest)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assets = {
                asset.path: WireScopeAsset(
                    archive.read(asset.path),
                    _asset_content_type(asset.path),
                )
                for asset in manifest.assets
            }
        return cls(manifest_sha256=manifest.sha256, assets=assets)

    def get(self, request_path):
        """Resolve only exact artifact paths; never normalize traversal."""

        if request_path == "/":
            path = "index.html"
        elif request_path.startswith("/"):
            path = request_path[1:]
        else:
            return None
        if not path or "\\" in path or any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            return None
        return self._assets.get(path)


def _asset_content_type(path):
    overrides = {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json",
        ".mjs": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".wasm": "application/wasm",
    }
    for suffix, content_type in overrides.items():
        if path.endswith(suffix):
            return content_type
    guessed, _encoding = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _record_manifest_sha256():
    """Read the manifest's SHA-256 pin from the installed wheel RECORD."""

    try:
        distribution = metadata.distribution("minecraft-remote-api")
    except metadata.PackageNotFoundError as exc:
        raise WireScopeArtifactError(
            "the installed distribution RECORD is unavailable"
        ) from exc
    matches = [
        item
        for item in (distribution.files or ())
        if item.as_posix() == _MANIFEST_PACKAGE_PATH
    ]
    if len(matches) != 1 or matches[0].hash is None:
        raise WireScopeArtifactError(
            "the artifact manifest is not pinned by wheel RECORD"
        )
    file_hash = matches[0].hash
    if file_hash.mode != "sha256":
        raise WireScopeArtifactError(
            "the artifact manifest RECORD pin must use SHA-256"
        )
    encoded = file_hash.value
    try:
        digest = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError) as exc:
        raise WireScopeArtifactError(
            "the artifact manifest RECORD pin is malformed"
        ) from exc
    if len(digest) != 32:
        raise WireScopeArtifactError(
            "the artifact manifest RECORD pin is malformed"
        )
    return digest.hex()


def load_bundled_wirescope_app():
    """Load and verify the distribution-owned detached artifact pair."""

    root = resources.files("mc_remote").joinpath(_ARTIFACT_ROOT)
    try:
        manifest_bytes = root.joinpath(_MANIFEST_NAME).read_bytes()
        archive_bytes = root.joinpath(_ARCHIVE_NAME).read_bytes()
    except (FileNotFoundError, IsADirectoryError, OSError) as exc:
        raise WireScopeArtifactError(
            "the immutable @mc-remote/live artifact is not installed"
        ) from exc
    return WireScopeApp.from_bytes(
        manifest_bytes,
        archive_bytes,
        manifest_sha256=_record_manifest_sha256(),
    )
