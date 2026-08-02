"""protocol 21.0.0 b3 catalog tests (catalog.get fetch, hash/validation,
disk cache, mc_constants.py codegen, kwargs sugar, sync orchestration).

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
  4. block_ref: namespace defaulting, state kwargs formatting (bool ->
     lowercase true/false), bare ref when no state is given
  5. codegen: generate_source produces syntactically valid Python exposing
     block/entity/particle/world_info; catalog-id collisions across
     namespaces get disambiguated instead of overwriting each other
  6. project projection: mc_constants.py plus checksum manifest, verified
     no-op when unchanged, no .pyi
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
    block_ref,
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
    MANIFEST_NAME,
    PROJECTION_SCHEMA_VERSION,
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
    "world": "overworld",
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


# 4a. bare name gets the minecraft: namespace; namespaced name is kept as-is
def test_block_ref_namespace_defaulting():
    assert block_ref("oak_log") == "minecraft:oak_log"
    assert block_ref("modid:thing") == "modid:thing"


# 4b. state kwargs are formatted onto the ref; bool becomes lowercase true/false
def test_block_ref_state_kwargs():
    assert block_ref("oak_log", axis="y") == "minecraft:oak_log[axis=y]"
    assert block_ref("minecraft:water", level=0) == "minecraft:water[level=0]"
    assert block_ref("oak_door", open=True, waterlogged=False) == (
        "minecraft:oak_door[open=true,waterlogged=false]"
    )


# 5a. generated source is syntactically valid and exposes the expected names
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
    assert namespace["entity"].ZOMBIE == "minecraft:zombie"
    assert namespace["particle"].FLAME == "minecraft:flame"
    assert namespace["world_info"].Y_SEA == 63
    assert namespace["CATALOG_HASH"] == catalog["catalogHash"]


# 5b. same local name from two namespaces gets disambiguated, not overwritten
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


# 6c. manifest is the commit marker and verifies the generated .py
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
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        assert manifest["catalogHash"] == catalog["catalogHash"]
        assert manifest["generatorVersion"] == GENERATOR_VERSION
        assert manifest["projectionSchemaVersion"] == PROJECTION_SCHEMA_VERSION
        assert len(manifest["projectionKey"]) == 64
        assert manifest["artifacts"] == {
            ARTIFACT_NAME: {"sha256": artifact_hash}
        }
        assert not os.path.exists(os.path.join(d, "mc_constants.pyi"))


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
    main = FakeConn({"world.setBlock": "built"})
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
        assert mc.setBlock(1, 2, 3, "minecraft:stone") == "built"
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
    main = FakeConn({"hello": hello, "world.setBlock": "built"})
    auxiliary = FakeConn(
        {"hello": hello, "catalog.get": RuntimeError("catalog temporarily down")}
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
        assert "building can continue" in message
        assert mc.setBlock(1, 2, 3, "minecraft:stone") == "built"
        assert not main.closed
        assert not os.path.exists(os.path.join(d, ARTIFACT_NAME))


# 8d. even an unexpected publication failure remains inside the warning boundary
def test_create_publish_failure_warns_and_keeps_build_stream():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello, "world.setBlock": "built"})
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
        assert mc.setBlock(1, 2, 3, "minecraft:stone") == "built"
        assert not main.closed


# 9a. Git projects must opt in; create warns before fetching or generating
def test_missing_ignore_blocks_generation_but_not_building():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    main = FakeConn({"hello": hello, "world.setBlock": "built"})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        save_token("localhost:25575", "mcrs_tok")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with api_env(), patched_connection(main):
                mc = Minecraft.create()
        assert len(caught) == 1
        assert "stage=ignore" in str(caught[0].message)
        assert mc.setBlock(1, 2, 3, "minecraft:stone") == "built"
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
        assert content.count("/mc_constants.py") == 1
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
        assert not os.path.exists(os.path.join(clone, MANIFEST_NAME))


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
