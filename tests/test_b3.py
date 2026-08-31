"""Catalog tests carried forward through protocol 22 b5.

Covers the b3 checklist (versioning-design §10.11.1 item 14, DECISIONS
2026-07-29-04):
  1. compute_catalog_hash: recursive key-sort + compact serialisation is
     deterministic and insertion-order independent, and content-sensitive
  2. validate_catalog: accepts a well-formed catalog; rejects a non-object
     result, a missing/empty catalogHash, missing block/entity/particle
     keys, a block entry missing states/default_state, and a catalogHash
     that does not match the recomputed digest
  3. disk cache: save/load round-trip under MCREMOTE_CACHE_DIR; a missing or
     corrupt cache file is a miss (None), not an error
  4. codegen: runtime constants plus state builder and catalog-specific .pyi
  5. project projection: mc_constants.py/.pyi plus checksum manifest
  7. Minecraft.getCatalog / sync_constants: cache misses and force fetches use
     a separate short-lived authenticated stream; explicit sync stays strict
     without closing the build stream
  8. Minecraft.create(sync_catalog=...): automatic failures warn and still
     return a build-capable client; False skips all projection work
  9. project init / Git policy: ignore supply is explicit and idempotent;
     missing ignore blocks generation; status and clone stay artifact-free

The catalog/auth layers are tested against a fake connection, a temp cache
dir, and a temp CWD; no socket, server, or real filesystem config is
touched.
"""
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote.catalog import (  # noqa: E402
    CatalogError,
    cache_dir,
    compute_catalog_hash,
    load_cached_catalog,
    save_cached_catalog,
    state_signature,
    validate_catalog,
)
from mc_remote import _constants_codegen  # noqa: E402
from mc_remote.auth import save_token  # noqa: E402
from mc_remote.minecraft import (  # noqa: E402
    CatalogProjectionError,
    CatalogProjectionWarning,
    Minecraft,
    PROTOCOL,
)
from mc_remote.projection import (  # noqa: E402
    ARTIFACT_NAME,
    GENERATOR_VERSION,
    IGNORE_RULES,
    MANIFEST_NAME,
    PROJECTION_SCHEMA_VERSION,
    STUB_NAME,
    init_project,
)
import mc_remote.projection as projection_mod  # noqa: E402
import mc_remote.minecraft as minecraft_mod  # noqa: E402


class FakeConn:
    """Records rpc calls and returns canned results (or raises).

    A response may be a single value, an Exception (raised), a callable
    (called with params), or a **list** used as a queue -- one entry
    consumed per call."""

    def __init__(self, responses):
        self.responses = {
            k: list(v) if isinstance(v, list) else v for k, v in responses.items()
        }
        self.calls = []
        self.closed = False
        self.address = "localhost"
        self.port = 25575
        self.debug = False

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        r = self.responses[method]
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(params)
        return r

    def reconnect(self):
        pass

    def close(self):
        self.closed = True


@contextlib.contextmanager
def tmp_cache():
    """Point the catalog cache at a throwaway dir for the duration."""
    prev = os.environ.get("MCREMOTE_CACHE_DIR")
    d = tempfile.mkdtemp(prefix="mcremote_cache_test_")
    os.environ["MCREMOTE_CACHE_DIR"] = d
    try:
        yield d
    finally:
        if prev is None:
            os.environ.pop("MCREMOTE_CACHE_DIR", None)
        else:
            os.environ["MCREMOTE_CACHE_DIR"] = prev


@contextlib.contextmanager
def tmp_config():
    """Point token storage at a throwaway dir for the duration."""
    prev = os.environ.get("MCREMOTE_CONFIG_DIR")
    d = tempfile.mkdtemp(prefix="mcremote_test_")
    os.environ["MCREMOTE_CONFIG_DIR"] = d
    try:
        yield d
    finally:
        if prev is None:
            os.environ.pop("MCREMOTE_CONFIG_DIR", None)
        else:
            os.environ["MCREMOTE_CONFIG_DIR"] = prev


@contextlib.contextmanager
def tmp_chdir():
    """Run inside a throwaway CWD (mc_constants.py lands here)."""
    prev = os.getcwd()
    d = tempfile.mkdtemp(prefix="mcremote_cwd_test_")
    os.chdir(d)
    try:
        yield d
    finally:
        os.chdir(prev)
        sys.path[:] = [p for p in sys.path if p != d]
        sys.modules.pop("mc_constants", None)


@contextlib.contextmanager
def patched_connection(*connections):
    """Feed one fake per stream opened by Minecraft.create()."""
    prev = minecraft_mod.Connection
    pending = list(connections)
    connect_args = []
    for conn in connections:
        conn.connect_args = connect_args

    def fake_connection(address, port, debug=False):
        connect_args.append((address, port, debug))
        if not pending:
            raise AssertionError("unexpected extra connection")
        return pending.pop(0)

    minecraft_mod.Connection = fake_connection
    try:
        yield
    finally:
        minecraft_mod.Connection = prev


def configure_catalog_stream(mc, auxiliary, server_key="localhost:25575"):
    """Give a directly-created client the metadata create() normally sets."""
    mc._server_key = server_key
    mc._catalog_endpoint = ("localhost", 25575, False)
    used = False

    def factory(address, port, debug=False):
        nonlocal used
        if used:
            raise AssertionError("unexpected extra catalog stream")
        used = True
        return auxiliary

    mc._catalog_connection_factory = factory


@contextlib.contextmanager
def api_env(**values):
    """Temporarily control API host/port env vars."""
    names = ["MCREMOTE_API_HOST", "MCREMOTE_API_PORT", "JRP_API_HOST", "JRP_API_PORT"]
    prev = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    for name, value in values.items():
        os.environ[name] = value
    try:
        yield
    finally:
        for name in names:
            if prev[name] is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prev[name]


def _sample_body():
    return {
        "block": {
            "minecraft:oak_log": {
                "states": {"axis": ["x", "y", "z"]},
                "default_state": {"axis": "y"},
            },
            "minecraft:stone": {"states": {}, "default_state": {}},
        },
        "entity": {"minecraft:zombie": {}},
        "particle": {"minecraft:flame": {}},
    }


def _sample_catalog():
    body = _sample_body()
    return {"catalogHash": compute_catalog_hash(body), **body}


def _rehash(data):
    body = {key: data[key] for key in ("block", "entity", "particle")}
    data["catalogHash"] = compute_catalog_hash(body)
    return data


HELLO_WITH_CATALOG = {
    "protocol": PROTOCOL,
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,  # overwritten per-test with the sample catalog's hash
    "world_constants": {"y_sea": 63},
    "session": "sess-1",
    "player": "00000000-0000-0000-0000-000000000001",
    "dimension": "minecraft:overworld",
    "origin": [200, 0, 200],
    "permissions": {"online": True, "offline": False, "buildRange": 1000},
}


# 1a. hash is deterministic and independent of key insertion order
def test_compute_catalog_hash_order_independent():
    body_a = _sample_body()
    body_b = {"particle": body_a["particle"], "block": body_a["block"], "entity": body_a["entity"]}
    assert compute_catalog_hash(body_a) == compute_catalog_hash(body_b)


# 1b. hash changes when registry content changes (e.g. a mod block is added)
def test_compute_catalog_hash_content_sensitive():
    body = _sample_body()
    h1 = compute_catalog_hash(body)
    body["block"]["modid:thing"] = {"states": {}, "default_state": {}}
    h2 = compute_catalog_hash(body)
    assert h1 != h2


# 2a. a well-formed, correctly-hashed catalog validates cleanly
def test_validate_catalog_accepts_well_formed():
    validate_catalog(_sample_catalog())  # must not raise


# 2b. non-object result
def test_validate_catalog_rejects_non_object():
    try:
        validate_catalog(["not", "an", "object"])
    except CatalogError:
        pass
    else:
        raise AssertionError("expected CatalogError")


# 2c. missing catalogHash
def test_validate_catalog_rejects_missing_hash():
    data = _sample_catalog()
    del data["catalogHash"]
    try:
        validate_catalog(data)
    except CatalogError:
        pass
    else:
        raise AssertionError("expected CatalogError")


# 2d. missing block/entity/particle key
def test_validate_catalog_rejects_missing_category():
    data = _sample_catalog()
    del data["entity"]
    try:
        validate_catalog(data)
    except CatalogError:
        pass
    else:
        raise AssertionError("expected CatalogError")


# 2e. block entry missing states/default_state
def test_validate_catalog_rejects_incomplete_block_entry():
    data = _sample_catalog()
    data["block"]["minecraft:stone"] = "not-an-object-with-states"
    try:
        validate_catalog(data)
    except CatalogError:
        pass
    else:
        raise AssertionError("expected CatalogError")


# 2f. block ids must be fully-qualified namespace:path identifiers
def test_validate_catalog_rejects_unqualified_block_id():
    data = _sample_catalog()
    data["block"]["stone"] = data["block"].pop("minecraft:stone")
    _rehash(data)
    try:
        validate_catalog(data)
    except CatalogError as exc:
        assert "fully-qualified" in str(exc)
    else:
        raise AssertionError("expected CatalogError")


# 2g. states/default_state must be objects with the same property set
def test_validate_catalog_rejects_invalid_state_objects_and_property_sets():
    invalid_entries = [
        {"states": [], "default_state": {}},
        {"states": {"axis": ["x", "y"]}, "default_state": {}},
        {"states": {"": ["x"]}, "default_state": {"": "x"}},
    ]
    for entry in invalid_entries:
        data = _sample_catalog()
        data["block"]["minecraft:stone"] = entry
        _rehash(data)
        try:
            validate_catalog(data)
        except CatalogError:
            pass
        else:
            raise AssertionError(f"expected CatalogError for {entry!r}")


# 2h. allowed values are non-empty, finite, homogeneous JSON scalar arrays
def test_validate_catalog_rejects_invalid_allowed_values():
    invalid_allowed = [
        [],
        [None],
        [["x"]],
        [float("nan")],
        ["x", 1],
        [True, 1],  # bool is not a Python-int-compatible JSON number here
    ]
    for allowed in invalid_allowed:
        data = _sample_catalog()
        data["block"]["minecraft:stone"] = {
            "states": {"value": allowed},
            "default_state": {"value": allowed[0] if allowed else "x"},
        }
        _rehash(data)
        try:
            validate_catalog(data)
        except CatalogError:
            pass
        else:
            raise AssertionError(f"expected CatalogError for {allowed!r}")


# 2i. duplicate values and defaults outside the allowed set are rejected
def test_validate_catalog_rejects_duplicate_and_invalid_default_values():
    invalid_entries = [
        {
            "states": {"axis": ["x", "x"]},
            "default_state": {"axis": "x"},
        },
        {
            "states": {"axis": ["x", "y"]},
            "default_state": {"axis": "z"},
        },
        {
            "states": {"level": [0, 1]},
            "default_state": {"level": True},
        },
    ]
    for entry in invalid_entries:
        data = _sample_catalog()
        data["block"]["minecraft:stone"] = entry
        _rehash(data)
        try:
            validate_catalog(data)
        except CatalogError:
            pass
        else:
            raise AssertionError(f"expected CatalogError for {entry!r}")


# 2j. unknown extension fields are ignored after the required schema validates
def test_validate_catalog_allows_unknown_extension_fields():
    data = _sample_catalog()
    data["block"]["minecraft:stone"]["future_extension"] = {"anything": True}
    _rehash(data)
    validate_catalog(data)


# 2k. signatures ignore defaults and canonicalise property/value order
def test_state_signature_is_canonical_and_excludes_default():
    first = {
        "states": {
            "waterlogged": [True, False],
            "facing": ["west", "east", "north", "south"],
            "level": [2, 0, 1],
        },
        "default_state": {"waterlogged": False, "facing": "north", "level": 0},
    }
    second = {
        "states": {
            "level": [1, 2, 0],
            "facing": ["south", "north", "east", "west"],
            "waterlogged": [False, True],
        },
        "default_state": {"level": 2, "facing": "east", "waterlogged": True},
    }
    expected = (
        ("facing", "string", ("east", "north", "south", "west")),
        ("level", "number", (0, 1, 2)),
        ("waterlogged", "boolean", (False, True)),
    )
    assert state_signature(first) == expected
    assert state_signature(second) == expected


# 2l. declared catalogHash does not match the recomputed digest
def test_validate_catalog_rejects_hash_mismatch():
    data = _sample_catalog()
    data["catalogHash"] = "0" * 64
    try:
        validate_catalog(data)
    except CatalogError as e:
        assert "mismatch" in str(e), e
    else:
        raise AssertionError("expected CatalogError")


# 3a. cache round-trip: save then load returns the same data
def test_cache_round_trip():
    with tmp_cache() as d:
        data = _sample_catalog()
        save_cached_catalog(data["catalogHash"], data)
        assert cache_dir() == d
        loaded = load_cached_catalog(data["catalogHash"])
        assert loaded == data, loaded


# 3b. a missing cache entry is a miss, not an error
def test_cache_miss_returns_none():
    with tmp_cache():
        assert load_cached_catalog("does-not-exist") is None


# 3c. a corrupt cache file is a miss, not an error
def test_cache_corrupt_file_returns_none():
    with tmp_cache() as d:
        path = os.path.join(d, "catalogs", "deadbeef.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        assert load_cached_catalog("deadbeef") is None


# 4a. generated source is valid and exposes constants plus state builders
def test_codegen_generates_valid_module():
    catalog = _sample_catalog()
    source = _constants_codegen.generate_source(
        catalog, "1.21.11", catalog["catalogHash"], world_info={"Y_SEA": 63}
    )
    namespace = {}
    compile(source, "<mc_constants>", "exec")  # raises SyntaxError on bad codegen
    exec(source, namespace)  # noqa: S102
    assert namespace["block"].OAK_LOG == "minecraft:oak_log"
    assert namespace["block"].STONE == "minecraft:stone"
    assert namespace["block_state"].OAK_LOG(axis="z") == {"axis": "z"}
    assert namespace["block_state"].OAK_LOG() == {}
    assert namespace["block_state"].STONE() == {}
    assert namespace["entity"].ZOMBIE == "minecraft:zombie"
    assert namespace["particle"].FLAME == "minecraft:flame"
    assert namespace["world_info"].Y_SEA == 63
    assert namespace["CATALOG_HASH"] == catalog["catalogHash"]


# 4b. generated stub binds each block ID to its key/value-specific state type
def test_codegen_generates_catalog_specific_stub():
    catalog = _sample_catalog()
    stub = _constants_codegen.generate_stub(catalog, world_info={"Y_SEA": 63})
    compile(stub, "<mc_constants.pyi>", "exec")
    assert "class _OAK_LOG_State(TypedDict, total=False):" in stub
    assert "axis: Literal['x', 'y', 'z']" in stub
    assert "OAK_LOG: BlockId[_OAK_LOG_State]" in stub
    assert "def OAK_LOG(*, axis: Literal['x', 'y', 'z'] = ...)" in stub
    assert "class _STONE_State(TypedDict, total=False):" in stub


# 4c. same local name from two namespaces gets disambiguated, not overwritten
def test_codegen_disambiguates_local_name_collision():
    body = _sample_body()
    body["block"]["modid:oak_log"] = {"states": {}, "default_state": {}}
    catalog = {"catalogHash": compute_catalog_hash(body), **body}
    source = _constants_codegen.generate_source(catalog, "1.21.11", catalog["catalogHash"])
    namespace = {}
    exec(source, namespace)  # noqa: S102
    values = {namespace["block"].OAK_LOG, namespace["block"].OAK_LOG_1}
    assert values == {"minecraft:oak_log", "modid:oak_log"}, values


# 6a. no catalogHash -> sync_constants no-ops without creating artifacts
def test_sync_constants_noop_without_catalog_hash():
    mc = Minecraft(FakeConn({}))
    mc.catalog_hash = None
    with tmp_chdir() as d:
        assert mc.sync_constants() is None
        assert os.listdir(d) == []


# 6b. cache miss: catalog.get runs on a separate authenticated stream
def test_sync_constants_cache_miss_fetches_and_writes():
    catalog = _sample_catalog()
    main = FakeConn({"world.setBlock": None})
    auxiliary = FakeConn(
        {
            "hello": dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"]),
            "catalog.get": catalog,
        }
    )
    mc = Minecraft(main)
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    mc.world_constants = {"y_sea": 63}
    configure_catalog_stream(mc, auxiliary)
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        path = mc.sync_constants(target_dir=d)
        assert main.calls == [], main.calls
        assert auxiliary.calls == [
            ("hello", {"protocol": PROTOCOL, "auth": {"token": "mcrs_tok"}}),
            ("catalog.get", []),
        ], auxiliary.calls
        assert auxiliary.closed
        assert load_cached_catalog(catalog["catalogHash"]) == catalog
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
            assert "OAK_LOG" in content
            # world_constants passes through in full (not just a hardcoded
            # Y_SEA), so a future bN sending more fields needs no client change
            assert "Y_SEA = 63" in content


# 5c. manifest is the commit marker and verifies both generated artifacts
def test_projection_manifest_has_required_key_and_checksum():
    catalog = _sample_catalog()
    mc = Minecraft(FakeConn({}))
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        save_cached_catalog(catalog["catalogHash"], catalog)
        path = mc.sync_constants(target_dir=d)
        manifest_path = os.path.join(d, MANIFEST_NAME)
        with open(path, "rb") as fh:
            artifact_hash = hashlib.sha256(fh.read()).hexdigest()
        stub_path = os.path.join(d, STUB_NAME)
        with open(stub_path, "rb") as fh:
            stub_hash = hashlib.sha256(fh.read()).hexdigest()
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        assert manifest["catalogHash"] == catalog["catalogHash"]
        assert manifest["generatorVersion"] == GENERATOR_VERSION
        assert manifest["projectionSchemaVersion"] == PROJECTION_SCHEMA_VERSION
        assert len(manifest["projectionKey"]) == 64
        assert manifest["artifacts"] == {
            ARTIFACT_NAME: {"sha256": artifact_hash},
            STUB_NAME: {"sha256": stub_hash},
        }


# 6d. a verified projection is not rewritten
def test_projection_skips_verified_unchanged_pair():
    catalog = _sample_catalog()
    mc = Minecraft(FakeConn({}))
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        save_cached_catalog(catalog["catalogHash"], catalog)
        path = mc.sync_constants(target_dir=d)
        manifest_path = os.path.join(d, MANIFEST_NAME)
        before = (os.stat(path).st_mtime_ns, os.stat(manifest_path).st_mtime_ns)
        mc.sync_constants(target_dir=d)
        after = (os.stat(path).st_mtime_ns, os.stat(manifest_path).st_mtime_ns)
        assert after == before


# 6e. failure while publishing the manifest restores the prior valid pair
def test_projection_publish_failure_preserves_previous_valid_pair():
    catalog = _sample_catalog()
    old_source = _constants_codegen.generate_source(
        catalog, "1.21.11", catalog["catalogHash"]
    )
    old_stub = _constants_codegen.generate_stub(catalog)
    with tmp_chdir() as d:
        artifact = projection_mod.publish_projection(
            old_source, old_stub, catalog["catalogHash"], target_dir=d
        )
        manifest = os.path.join(d, MANIFEST_NAME)
        stub_path = os.path.join(d, STUB_NAME)
        with open(artifact, "rb") as fh:
            old_artifact_bytes = fh.read()
        with open(stub_path, "rb") as fh:
            old_stub_bytes = fh.read()
        with open(manifest, "rb") as fh:
            old_manifest_bytes = fh.read()

        original_replace = projection_mod.os.replace

        def fail_manifest_replace(source, target):
            if target == manifest:
                raise OSError("simulated manifest publish failure")
            return original_replace(source, target)

        projection_mod.os.replace = fail_manifest_replace
        try:
            try:
                projection_mod.publish_projection(
                    old_source + "\n# next generation\n",
                    old_stub + "\n# next generation\n",
                    "f" * 64,
                    target_dir=d,
                )
            except CatalogProjectionError as exc:
                assert exc.stage == "publish"
            else:
                raise AssertionError("expected CatalogProjectionError")
        finally:
            projection_mod.os.replace = original_replace

        with open(artifact, "rb") as fh:
            assert fh.read() == old_artifact_bytes
        with open(stub_path, "rb") as fh:
            assert fh.read() == old_stub_bytes
        with open(manifest, "rb") as fh:
            assert fh.read() == old_manifest_bytes


def test_projection_artifact_failure_restores_already_replaced_source():
    catalog = _sample_catalog()
    source, stub = _constants_codegen.generate_projection(
        catalog, "1.21.11", catalog["catalogHash"]
    )
    with tmp_chdir() as d:
        artifact = projection_mod.publish_projection(
            source, stub, catalog["catalogHash"], target_dir=d
        )
        stub_path = os.path.join(d, STUB_NAME)
        manifest_path = os.path.join(d, MANIFEST_NAME)
        before = {
            path: Path(path).read_bytes()
            for path in (artifact, stub_path, manifest_path)
        }
        original_replace = projection_mod.os.replace

        def fail_stub_replace(staged, target):
            if target == stub_path:
                raise OSError("simulated stub publication failure")
            return original_replace(staged, target)

        projection_mod.os.replace = fail_stub_replace
        try:
            try:
                projection_mod.publish_projection(
                    source + "\n# changed\n",
                    stub + "\n# changed\n",
                    "e" * 64,
                    target_dir=d,
                )
            except CatalogProjectionError as exc:
                assert exc.stage == "publish"
            else:
                raise AssertionError("expected CatalogProjectionError")
        finally:
            projection_mod.os.replace = original_replace

        for path, expected in before.items():
            assert Path(path).read_bytes() == expected


# 7a. cache hit: no auxiliary stream is opened
def test_sync_constants_cache_hit_skips_fetch():
    catalog = _sample_catalog()
    main = FakeConn({})
    mc = Minecraft(main)
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        save_cached_catalog(catalog["catalogHash"], catalog)
        mc.sync_constants(target_dir=d)
        assert main.calls == [], main.calls


# 7b. force=True uses an auxiliary stream even with a cache entry
def test_sync_constants_force_refetches():
    catalog = _sample_catalog()
    main = FakeConn({})
    auxiliary = FakeConn(
        {
            "hello": dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"]),
            "catalog.get": catalog,
        }
    )
    mc = Minecraft(main)
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    configure_catalog_stream(mc, auxiliary)
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        save_cached_catalog(catalog["catalogHash"], catalog)
        mc.sync_constants(target_dir=d, force=True)
        assert ("catalog.get", []) in auxiliary.calls
        assert main.calls == []


# 7c. explicit sync stays strict but never closes the build stream
def test_sync_constants_rejects_invalid_catalog():
    expected = _sample_catalog()
    bad = dict(expected, catalogHash="0" * 64)
    main = FakeConn({"world.setBlock": None})
    auxiliary = FakeConn(
        {
            "hello": dict(HELLO_WITH_CATALOG, catalogHash=expected["catalogHash"]),
            "catalog.get": bad,
        }
    )
    mc = Minecraft(main)
    mc.catalog_hash = expected["catalogHash"]
    mc.mc_version = "1.21.11"
    configure_catalog_stream(mc, auxiliary)
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        try:
            mc.sync_constants(target_dir=d)
        except CatalogProjectionError as exc:
            assert exc.stage == "validate"
        else:
            raise AssertionError("expected CatalogProjectionError")
        assert not main.closed
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None
        assert load_cached_catalog(expected["catalogHash"]) is None


# 8a. create() keeps the build stream and fetches on a second stream
def test_create_syncs_catalog_by_default():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello})
    auxiliary = FakeConn({"hello": hello, "catalog.get": catalog})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        with api_env(), patched_connection(main, auxiliary):
            Minecraft.create()
        assert main.calls == [
            ("hello", {"protocol": PROTOCOL, "auth": {"token": "mcrs_tok"}})
        ]
        assert ("catalog.get", []) in auxiliary.calls
        assert auxiliary.closed and not main.closed
        assert os.path.exists(os.path.join(d, "mc_constants.py"))
        assert os.path.exists(os.path.join(d, MANIFEST_NAME))


# 8b. create(sync_catalog=False) skips catalog.get and the file write entirely
def test_create_can_skip_catalog_sync():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    fake = FakeConn({"hello": hello, "catalog.get": RuntimeError("should not be called")})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        with api_env(), patched_connection(fake):
            Minecraft.create(sync_catalog=False)
        assert fake.calls == [
            ("hello", {"protocol": PROTOCOL, "auth": {"token": "mcrs_tok"}})
        ], fake.calls
        assert not os.path.exists(os.path.join(d, "mc_constants.py"))


# 8c. projection failure is a warning; the returned build stream still works
def test_create_catalog_failure_warns_and_returns_connected_client():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello, "world.setBlock": None})
    auxiliary = FakeConn(
        {
            "hello": hello,
            "catalog.get": RuntimeError("secret=mcrs_must_not_appear"),
        }
    )
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with api_env(), patched_connection(main, auxiliary):
                mc = Minecraft.create()
        assert len(caught) == 1
        assert issubclass(caught[0].category, CatalogProjectionWarning)
        message = str(caught[0].message)
        assert "stage=fetch" in message
        assert "catalog.get failed on the short-lived stream" in message
        assert "building can continue" in message
        assert "may be stale" in message
        assert "mcrs_must_not_appear" not in message
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None
        assert not main.closed
        assert not os.path.exists(os.path.join(d, ARTIFACT_NAME))


# 8d. validation, cache, and generation failures share the non-fatal boundary
def test_create_other_projection_stages_warn_and_keep_build_stream():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])

    # Validation: declared hello hash matches, but body content does not.
    invalid = _sample_catalog()
    invalid["block"]["minecraft:extra"] = {"states": {}, "default_state": {}}
    main = FakeConn({"hello": hello, "world.setBlock": None})
    auxiliary = FakeConn({"hello": hello, "catalog.get": invalid})
    with tmp_config(), tmp_cache(), tmp_chdir():
        save_token("localhost:25575", "mcrs_tok")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with api_env(), patched_connection(main, auxiliary):
                mc = Minecraft.create()
        assert "stage=validate" in str(caught[0].message)
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None

    # Cache publication: the catalog is valid, but the global save fails.
    main = FakeConn({"hello": hello, "world.setBlock": None})
    auxiliary = FakeConn({"hello": hello, "catalog.get": catalog})
    original_save = minecraft_mod._catalog.save_cached_catalog

    def fail_cache(*args, **kwargs):
        raise OSError("secret=mcrs_cache_secret")

    with tmp_config(), tmp_cache(), tmp_chdir():
        save_token("localhost:25575", "mcrs_tok")
        minecraft_mod._catalog.save_cached_catalog = fail_cache
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with api_env(), patched_connection(main, auxiliary):
                    mc = Minecraft.create()
        finally:
            minecraft_mod._catalog.save_cached_catalog = original_save
        message = str(caught[0].message)
        assert "stage=cache" in message
        assert "mcrs_cache_secret" not in message
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None

    # Generation: a validated cache hit avoids opening any auxiliary stream.
    main = FakeConn({"hello": hello, "world.setBlock": None})
    original_generate = minecraft_mod._constants_codegen.generate_projection

    def fail_generate(*args, **kwargs):
        raise RuntimeError("secret=mcrs_generate_secret")

    with tmp_config(), tmp_cache(), tmp_chdir():
        save_token("localhost:25575", "mcrs_tok")
        save_cached_catalog(catalog["catalogHash"], catalog)
        minecraft_mod._constants_codegen.generate_projection = fail_generate
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with api_env(), patched_connection(main):
                    mc = Minecraft.create()
        finally:
            minecraft_mod._constants_codegen.generate_projection = original_generate
        message = str(caught[0].message)
        assert "stage=generate" in message
        assert "mcrs_generate_secret" not in message
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None


# 8e. even an unexpected publication failure remains inside the warning boundary
def test_create_publish_failure_warns_and_keeps_build_stream():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello, "world.setBlock": None})
    original = projection_mod.publish_projection

    def fail_publish(*args, **kwargs):
        raise RuntimeError("simulated publication failure")

    with tmp_config(), tmp_cache(), tmp_chdir():
        save_token("localhost:25575", "mcrs_tok")
        save_cached_catalog(catalog["catalogHash"], catalog)
        projection_mod.publish_projection = fail_publish
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with api_env(), patched_connection(main):
                    mc = Minecraft.create()
        finally:
            projection_mod.publish_projection = original
        assert len(caught) == 1
        assert "stage=publish" in str(caught[0].message)
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None
        assert not main.closed


# 8f. a null catalogHash performs no projection work and emits no warning
def test_create_null_catalog_hash_is_clean_noop():
    hello = dict(HELLO_WITH_CATALOG, catalogHash=None)
    main = FakeConn({"hello": hello, "world.setBlock": None})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with api_env(), patched_connection(main):
                mc = Minecraft.create()
        assert caught == []
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None
        assert not os.path.exists(os.path.join(d, ARTIFACT_NAME))


# 8g. a global cache hit still creates nothing before authenticated hello
def test_cached_catalog_does_not_project_before_hello():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        save_cached_catalog(catalog["catalogHash"], catalog)
        assert not os.path.exists(os.path.join(d, ARTIFACT_NAME))
        with api_env(), patched_connection(main):
            Minecraft.create()
        assert os.path.exists(os.path.join(d, ARTIFACT_NAME))


# 9a. Git projects must opt in; create warns before fetching or generating
def test_missing_ignore_blocks_generation_but_not_building():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello, "world.setBlock": None})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        save_token("localhost:25575", "mcrs_tok")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with api_env(), patched_connection(main):
                mc = Minecraft.create()
        assert len(caught) == 1
        assert "stage=ignore" in str(caught[0].message)
        assert mc.setBlock(1, 2, 3, "minecraft:stone") is None
        assert not os.path.exists(os.path.join(d, ARTIFACT_NAME))
        assert not os.path.exists(os.path.join(d, MANIFEST_NAME))


# 9b. explicit project init is idempotent and never creates projection files
def test_project_init_supplies_ignore_rules_idempotently():
    with tmp_chdir() as d:
        path, changed = init_project(d)
        assert changed
        path2, changed2 = init_project(d)
        assert path2 == path and not changed2
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        assert content.count("/param_mc_remote.py") == 1
        assert content.splitlines().count("/mc_constants.py") == 1
        assert content.splitlines().count("/mc_constants.pyi") == 1
        assert content.count("/mc_constants.manifest.json") == 1
        assert content.count("/.mc_constants.*") == 1
        assert not os.path.exists(os.path.join(d, ARTIFACT_NAME))


# 9c. generated files remain invisible to status and local clone
def test_initialized_git_project_stays_clean_and_clone_has_no_projection():
    catalog = _sample_catalog()
    mc = Minecraft(FakeConn({}))
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        init_project(d)
        subprocess.run(["git", "-C", d, "add", ".gitignore"], check=True)
        subprocess.run(
            [
                "git", "-C", d, "-c", "user.name=Test", "-c",
                "user.email=test@example.invalid", "commit", "-qm", "init",
            ],
            check=True,
        )
        save_cached_catalog(catalog["catalogHash"], catalog)
        mc.sync_constants(target_dir=d)
        status = subprocess.run(
            ["git", "-C", d, "status", "--porcelain"],
            text=True, stdout=subprocess.PIPE, check=True,
        ).stdout
        assert status == ""
        clone = tempfile.mkdtemp(prefix="mcremote_clone_parent_") + "/clone"
        subprocess.run(["git", "clone", "-q", d, clone], check=True)
        assert not os.path.exists(os.path.join(clone, ARTIFACT_NAME))
        assert not os.path.exists(os.path.join(clone, STUB_NAME))
        assert not os.path.exists(os.path.join(clone, MANIFEST_NAME))


# 9d. tracked starter preserves the environment adapter and before/after path
def test_starter_contract():
    starter = Path(__file__).resolve().parent.parent / "starter"
    expected = {
        ".gitignore",
        ".vscode/launch.json",
        ".vscode/settings.json",
        "README_ja.md",
        "b6_sign.py",
        "b7_direction_lightning.py",
        "hello.py",
        "param_mc_remote.template.py",
        "with_completion.py",
    }
    actual = {
        str(path.relative_to(starter))
        for path in starter.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert actual == expected
    assert ARTIFACT_NAME not in actual
    assert STUB_NAME not in actual
    assert MANIFEST_NAME not in actual

    template = (starter / "param_mc_remote.template.py").read_text(encoding="utf-8")
    assert 'ADRS_MCR = "sb.mc-remote.com"' in template
    assert "PORT_MCR = 25575" in template
    assert "BUILD_ORIGIN = Vec3(" in template
    assert "PLAYER_NAME" not in template
    assert "PLAYER_ORIGIN" not in template
    assert "PLATFORM" not in template

    ignore = (starter / ".gitignore").read_text(encoding="utf-8")
    for rule in IGNORE_RULES:
        assert rule in ignore

    hello = (starter / "hello.py").read_text(encoding="utf-8")
    assert "# from mc_constants import block" in hello
    assert 'mc.postToChat("Hello, Minecraft from Python!")' in hello
    assert 'mc.setBlock(5, 62 + 5, 5, "sea_lantern")' in hello

    after = (starter / "with_completion.py").read_text(encoding="utf-8")
    assert "from mc_constants import block, block_state, world_info" in after
    assert "mc.setBlock(6, world_info.Y_SEA + 5, 5, block.GOLD_BLOCK)" in after
    assert 'state=block_state.OAK_LOG(axis="z")' in after


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
