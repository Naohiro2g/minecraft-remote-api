"""Project-local publication for the live catalog projection.

The projection is deliberately disposable: ``mc_constants.py`` and its
manifest are created only after an authenticated hello, are never bundled,
and must be ignored by Git.  The manifest is the commit marker; it is always
published after the Python artifact.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import time

from .connection import McRemoteError, McRpcError


ARTIFACT_NAME = "mc_constants.py"
MANIFEST_NAME = "mc_constants.manifest.json"
LOCK_NAME = ".mc_constants.lock"
GENERATOR_VERSION = "1"
PROJECTION_SCHEMA_VERSION = 1
IGNORE_RULES = (
    "/mc_constants.py",
    "/mc_constants.manifest.json",
    "/.mc_constants.*",
)


class CatalogProjectionError(McRemoteError):
    """A catalog-projection failure with a stable, user-actionable stage."""

    def __init__(self, stage, message, *, cause=None):
        self.stage = stage
        self.cause = cause
        super().__init__(message)


class CatalogProjectionWarning(UserWarning):
    """Non-fatal warning emitted by ``Minecraft.create()`` projection."""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def projection_key(catalog_hash):
    return _sha256(
        _canonical_json(
            {
                "catalogHash": catalog_hash,
                "generatorVersion": GENERATOR_VERSION,
                "projectionSchemaVersion": PROJECTION_SCHEMA_VERSION,
            }
        )
    )


def build_manifest(catalog_hash, source_bytes):
    return {
        "catalogHash": catalog_hash,
        "projectionKey": projection_key(catalog_hash),
        "generatorVersion": GENERATOR_VERSION,
        "projectionSchemaVersion": PROJECTION_SCHEMA_VERSION,
        "artifacts": {
            ARTIFACT_NAME: {"sha256": _sha256(source_bytes)},
        },
    }


def _run_git(target_dir, *args):
    try:
        return subprocess.run(
            ["git", "-C", target_dir, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise CatalogProjectionError(
            "ignore", "Git could not be inspected", cause=exc
        ) from exc


def _is_git_managed(target_dir):
    result = _run_git(target_dir, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_projection_allowed(target_dir):
    """Reject generation in Git projects whose disposable outputs can land.

    This function only checks policy; it never edits ``.gitignore``.  A user
    can opt in explicitly with ``mcremote init``.
    """
    target_dir = os.path.abspath(target_dir)
    if not _is_git_managed(target_dir):
        return
    for name in (
        ARTIFACT_NAME,
        MANIFEST_NAME,
        LOCK_NAME,
        ".mc_constants.py.probe",
        ".mc_constants.manifest.probe",
    ):
        tracked = _run_git(target_dir, "ls-files", "--error-unmatch", "--", name)
        ignored = _run_git(
            target_dir, "check-ignore", "--no-index", "--quiet", "--", name
        )
        if tracked.returncode == 0 or ignored.returncode != 0:
            raise CatalogProjectionError(
                "ignore",
                f"{name} is not safely ignored; run `mcremote init` in "
                "the project root, then retry",
            )


def init_project(target_dir=None):
    """Idempotently add projection rules to a project's ``.gitignore``."""
    target_dir = os.path.abspath(target_dir or os.getcwd())
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, ".gitignore")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            existing = fh.read()
    except FileNotFoundError:
        existing = ""

    present = set(existing.splitlines())
    missing = [rule for rule in IGNORE_RULES if rule not in present]
    if not missing:
        return path, False

    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = (
        prefix
        + "# mc_remote live catalog projection (generated after hello)\n"
        + "\n".join(missing)
        + "\n"
    )
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError as exc:
        raise CatalogProjectionError(
            "ignore", f"could not update {path}", cause=exc
        ) from exc
    return path, True


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def projection_is_current(target_dir, manifest, source_bytes):
    expected = build_manifest(manifest["catalogHash"], source_bytes)
    if manifest != expected:
        return False
    try:
        with open(os.path.join(target_dir, ARTIFACT_NAME), "rb") as fh:
            actual = fh.read()
    except OSError:
        return False
    return _sha256(actual) == expected["artifacts"][ARTIFACT_NAME]["sha256"]


class _ProjectLock:
    def __init__(self, target_dir, timeout=5.0):
        self.path = os.path.join(target_dir, LOCK_NAME)
        self.timeout = timeout
        self.acquired = False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="ascii") as fh:
                    fh.write(f"{os.getpid()}\n")
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                    if age > 60:
                        os.unlink(self.path)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise CatalogProjectionError(
                        "publish", "catalog projection is locked by another process"
                    )
                time.sleep(0.05)
            except OSError as exc:
                raise CatalogProjectionError(
                    "publish", "could not acquire the project projection lock", cause=exc
                ) from exc

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            try:
                os.unlink(self.path)
            except OSError:
                pass


def _write_staged(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _fsync_dir(path):
    """Persist rename ordering where directory fsync is supported."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _refresh_import(target_dir):
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)
    if "mc_constants" in sys.modules:
        try:
            importlib.invalidate_caches()
            importlib.reload(sys.modules["mc_constants"])
        except Exception:
            sys.modules.pop("mc_constants", None)


def publish_projection(source, catalog_hash, target_dir=None):
    """Atomically publish source then its manifest commit marker.

    Returns the absolute path of ``mc_constants.py``.  An unchanged, fully
    verified projection is not rewritten.
    """
    target_dir = os.path.abspath(target_dir or os.getcwd())
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        raise CatalogProjectionError(
            "publish", f"could not create projection directory {target_dir}", cause=exc
        ) from exc
    ensure_projection_allowed(target_dir)
    source_bytes = source.encode("utf-8")
    artifact_path = os.path.join(target_dir, ARTIFACT_NAME)
    manifest_path = os.path.join(target_dir, MANIFEST_NAME)

    with _ProjectLock(target_dir):
        current = _read_json(manifest_path)
        if current and current.get("catalogHash") == catalog_hash:
            try:
                if projection_is_current(target_dir, current, source_bytes):
                    _refresh_import(target_dir)
                    return artifact_path
            except (KeyError, TypeError):
                pass

        manifest = build_manifest(catalog_hash, source_bytes)
        manifest_bytes = _canonical_json(manifest) + b"\n"
        suffix = f".{os.getpid()}.{time.time_ns()}"
        staged_artifact = os.path.join(target_dir, ".mc_constants.py" + suffix)
        staged_manifest = os.path.join(target_dir, ".mc_constants.manifest" + suffix)
        old_artifact = None
        try:
            try:
                with open(artifact_path, "rb") as fh:
                    old_artifact = fh.read()
            except FileNotFoundError:
                pass
            _write_staged(staged_artifact, source_bytes)
            _write_staged(staged_manifest, manifest_bytes)
            os.replace(staged_artifact, artifact_path)
            _fsync_dir(target_dir)
            try:
                os.replace(staged_manifest, manifest_path)
                _fsync_dir(target_dir)
            except Exception:
                # Best-effort process-level rollback.  A crash is detected on
                # the next run because the old manifest checksum will differ.
                if old_artifact is None:
                    try:
                        os.unlink(artifact_path)
                    except FileNotFoundError:
                        pass
                else:
                    rollback = staged_artifact + ".rollback"
                    _write_staged(rollback, old_artifact)
                    os.replace(rollback, artifact_path)
                raise
        except CatalogProjectionError:
            raise
        except Exception as exc:
            raise CatalogProjectionError(
                "publish", "could not atomically publish the catalog projection", cause=exc
            ) from exc
        finally:
            for path in (staged_artifact, staged_manifest):
                try:
                    os.unlink(path)
                except OSError:
                    pass

        _refresh_import(target_dir)
        return artifact_path


def format_warning(error):
    """Return a redacted actionable warning for a non-fatal create sync."""
    cause = error.cause
    cause_summary = ""
    if isinstance(cause, McRpcError):
        cause_summary = f" (McRpcError: reason={cause.reason!r}, code={cause.code!r})"
    elif cause is not None:
        # Do not echo arbitrary exception text: third-party exceptions can
        # embed request params or credentials.  CatalogError and OS errors are
        # already explained by the stage and the retry guidance.
        cause_summary = f" ({type(cause).__name__})"
    return (
        f"Catalog completion was not updated (stage={error.stage}): "
        f"{str(error)}{cause_summary}. "
        "The Minecraft connection is ready and building can continue. "
        "Any existing completion may be stale. "
        "Fix the reported issue, then retry with mc.sync_constants(force=True)."
    )
