#!/usr/bin/env python3
"""Verify the WireScope artifact and license boundary in a built wheel."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath


ARCHIVE_PATH = PurePosixPath("mc_remote/_wirescope_app/wirescope-app.zip")
MANIFEST_PATH = PurePosixPath(
    "mc_remote/_wirescope_app/wirescope-app.manifest.json"
)
EXPECTED_FILES = {
    ARCHIVE_PATH: (
        59340,
        "f3ffaa1c55122b21acaccf9467bbd39c775c44d7e982fa3b11658d10a14b0f49",
    ),
    MANIFEST_PATH: (
        2321,
        "b7565dd7f4883020737bbe5f5dfb28819862d0edc54bb4b4d5503d99c5d65780",
    ),
}
LICENSE_EXPRESSION = "MIT AND AGPL-3.0-only"
LICENSE_FILES = {
    "LICENSE",
    "LICENSES/AGPL-3.0-only.txt",
    "LICENSES/WireScope-NOTICE.txt",
}
SOURCE_URL = (
    "https://github.com/Naohiro2g/scratch-editor/tree/"
    "602ecdf809f87a7e33e50d7c465b7248429e26dc/mc-remote/live"
)


class WheelCheckError(RuntimeError):
    pass


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _record_digest(body: bytes) -> str:
    digest = hashlib.sha256(body).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _one_path(names: set[str], suffix: str) -> str:
    matches = sorted(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        raise WheelCheckError(f"expected exactly one {suffix}, got {matches!r}")
    return matches[0]


def check_wheel(path: Path) -> None:
    try:
        wheel = zipfile.ZipFile(path)
    except (FileNotFoundError, OSError, zipfile.BadZipFile) as exc:
        raise WheelCheckError(f"cannot open wheel: {path}") from exc

    with wheel:
        names = set(wheel.namelist())
        metadata_path = _one_path(names, ".dist-info/METADATA")
        record_path = _one_path(names, ".dist-info/RECORD")
        license_root = metadata_path.removesuffix("METADATA") + "licenses/"

        record_rows = {
            row[0]: row[1:]
            for row in csv.reader(
                io.StringIO(wheel.read(record_path).decode("utf-8"))
            )
        }
        for package_path, (expected_size, expected_sha256) in EXPECTED_FILES.items():
            name = package_path.as_posix()
            try:
                body = wheel.read(name)
            except KeyError as exc:
                raise WheelCheckError(f"wheel is missing {name}") from exc
            if len(body) != expected_size or _sha256(body) != expected_sha256:
                raise WheelCheckError(f"immutable artifact mismatch: {name}")
            expected_record = f"sha256={_record_digest(body)}"
            if record_rows.get(name) != [expected_record, str(expected_size)]:
                raise WheelCheckError(f"RECORD mismatch: {name}")

        metadata = BytesParser().parsebytes(wheel.read(metadata_path))
        if metadata.get("License-Expression") != LICENSE_EXPRESSION:
            raise WheelCheckError("distribution license expression mismatch")
        if set(metadata.get_all("License-File", ())) != LICENSE_FILES:
            raise WheelCheckError("distribution license inventory mismatch")
        source_urls = {
            value.removeprefix("WireScope Source, ")
            for value in metadata.get_all("Project-URL", ())
            if value.startswith("WireScope Source, ")
        }
        if source_urls != {SOURCE_URL}:
            raise WheelCheckError("WireScope corresponding source mismatch")

        archive_bytes = wheel.read(ARCHIVE_PATH.as_posix())
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            component_files = {
                "AGPL-3.0-only.txt": archive.read("LICENSE"),
                "WireScope-NOTICE.txt": archive.read("NOTICE"),
            }
        for filename, expected_body in component_files.items():
            wheel_path = license_root + "LICENSES/" + filename
            try:
                actual_body = wheel.read(wheel_path)
            except KeyError as exc:
                raise WheelCheckError(f"wheel is missing {wheel_path}") from exc
            if actual_body != expected_body:
                raise WheelCheckError(f"component license mismatch: {filename}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    try:
        check_wheel(args.wheel)
    except WheelCheckError as exc:
        print(f"WireScope wheel check failed: {exc}", file=sys.stderr)
        return 1
    print(f"WireScope wheel check passed: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
