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
  6. write_constants_file: writes into target_dir and is a no-op (does not
     re-touch the file) when the content is unchanged
  7. Minecraft.getCatalog / sync_constants: no catalogHash -> no-op; a cache
     miss fetches+validates+caches+writes; a cache hit skips the network
     call; force=True re-fetches; an invalid fetched catalog raises and does
     not poison the cache
  8. Minecraft.create(sync_catalog=...): True writes mc_constants.py after a
     successful handshake when a catalogHash is advertised; False skips it

The catalog/auth layers are tested against a fake connection, a temp cache
dir, and a temp CWD; no socket, server, or real filesystem config is
touched.
"""
import contextlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote.catalog import (  # noqa: E402
    CatalogError,
    block_ref,
    cache_dir,
    compute_catalog_hash,
    load_cached_catalog,
    save_cached_catalog,
    validate_catalog,
)
from mc_remote import _constants_codegen  # noqa: E402
from mc_remote.auth import save_token  # noqa: E402
from mc_remote.minecraft import Minecraft, PROTOCOL  # noqa: E402
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
        pass


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
def patched_connection(conn):
    """Make Minecraft.create() use a fake connection without opening a socket."""
    prev = minecraft_mod.Connection
    conn.connect_args = []

    def fake_connection(address, port, debug=False):
        conn.connect_args.append((address, port, debug))
        return conn

    minecraft_mod.Connection = fake_connection
    try:
        yield
    finally:
        minecraft_mod.Connection = prev


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


# 2f. declared catalogHash does not match the recomputed digest
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


# 6a. write_constants_file lands the file in target_dir and puts it on sys.path
def test_write_constants_file_writes_and_extends_path():
    with tmp_chdir() as d:
        source = _constants_codegen.generate_source(_sample_catalog(), "1.21.11", "abc")
        path = _constants_codegen.write_constants_file(source, target_dir=d)
        assert path == os.path.join(d, "mc_constants.py")
        with open(path, "r", encoding="utf-8") as fh:
            assert fh.read() == source
        assert d in sys.path


# 6b. identical content is not rewritten (avoids mtime/diff churn)
def test_write_constants_file_skips_unchanged_write():
    with tmp_chdir() as d:
        source = _constants_codegen.generate_source(_sample_catalog(), "1.21.11", "abc")
        path = _constants_codegen.write_constants_file(source, target_dir=d)
        os.chmod(d, 0o500)  # read+execute only: a real write would now raise
        try:
            _constants_codegen.write_constants_file(source, target_dir=d)
        finally:
            os.chmod(d, 0o700)
        with open(path, "r", encoding="utf-8") as fh:
            assert fh.read() == source


# 7a. no catalogHash -> sync_constants no-ops without calling catalog.get
def test_sync_constants_noop_without_catalog_hash():
    mc = Minecraft(FakeConn({}))
    mc.catalog_hash = None
    assert mc.sync_constants() is None


# 7b. cache miss: fetches via catalog.get, validates, caches, writes the file
def test_sync_constants_cache_miss_fetches_and_writes():
    catalog = _sample_catalog()
    fake = FakeConn({"catalog.get": catalog})
    mc = Minecraft(fake)
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    mc.world_constants = {"y_sea": 63}
    with tmp_cache(), tmp_chdir() as d:
        path = mc.sync_constants(target_dir=d)
        assert fake.calls == [("catalog.get", [])], fake.calls
        assert load_cached_catalog(catalog["catalogHash"]) == catalog
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
            assert "OAK_LOG" in content
            # world_constants passes through in full (not just a hardcoded
            # Y_SEA), so a future bN sending more fields needs no client change
            assert "Y_SEA = 63" in content


# 7c. cache hit: no catalog.get call
def test_sync_constants_cache_hit_skips_fetch():
    catalog = _sample_catalog()
    fake = FakeConn({"catalog.get": RuntimeError("should not be called")})
    mc = Minecraft(fake)
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        save_cached_catalog(catalog["catalogHash"], catalog)
        mc.sync_constants(target_dir=d)
        assert fake.calls == [], fake.calls


# 7d. force=True re-fetches even though a cache entry already exists
def test_sync_constants_force_refetches():
    catalog = _sample_catalog()
    fake = FakeConn({"catalog.get": catalog})
    mc = Minecraft(fake)
    mc.catalog_hash = catalog["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        save_cached_catalog(catalog["catalogHash"], catalog)
        mc.sync_constants(target_dir=d, force=True)
        assert fake.calls == [("catalog.get", [])], fake.calls


# 7e. an invalid fetched catalog raises and is never written to the cache
def test_sync_constants_rejects_invalid_catalog():
    bad = _sample_catalog()
    bad["catalogHash"] = "0" * 64  # declared hash won't match the body
    fake = FakeConn({"catalog.get": bad})
    mc = Minecraft(fake)
    mc.catalog_hash = bad["catalogHash"]
    mc.mc_version = "1.21.11"
    with tmp_cache(), tmp_chdir() as d:
        try:
            mc.sync_constants(target_dir=d)
        except CatalogError:
            pass
        else:
            raise AssertionError("expected CatalogError")
        assert load_cached_catalog(bad["catalogHash"]) is None


# 8a. create(sync_catalog=True) writes mc_constants.py after a clean handshake
def test_create_syncs_catalog_by_default():
    catalog = _sample_catalog()
    hello = dict(HELLO_WITH_CATALOG, catalogHash=catalog["catalogHash"])
    fake = FakeConn({"hello": hello, "catalog.get": catalog})
    with tmp_config(), tmp_cache(), tmp_chdir() as d:
        save_token("localhost:25575", "mcrs_tok")
        with api_env(), patched_connection(fake):
            Minecraft.create()
        assert ("catalog.get", []) in fake.calls, fake.calls
        assert os.path.exists(os.path.join(d, "mc_constants.py"))


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
