#!/usr/bin/env python3
"""Manual catalog sync helper (b3): connect, fetch+cache the live
block/entity/particle catalog, and (re)write mc_constants.py.

This is for live checks and operator use -- in particular, for producing the
first real ``mc_constants.py`` from an actual server (this repo does not
fabricate catalog content; only a live ``catalog.get`` round trip can) -- not
for automated unit tests.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc_remote.catalog import CatalogError, load_cached_catalog
from mc_remote.connection import McRpcError
from mc_remote.minecraft import Minecraft


def _env_first(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return default


def _env_first_int(*names, default):
    value = _env_first(*names)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Live catalog.get -> mc_constants.py sync helper (b3)."
    )
    parser.add_argument(
        "address",
        nargs="?",
        default=_env_first("MCREMOTE_API_HOST", "JRP_API_HOST", default="localhost"),
        help=("Server address (default: MCREMOTE_API_HOST, legacy JRP_API_HOST, "
              "or localhost)."),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_first_int("MCREMOTE_API_PORT", "JRP_API_PORT", default=25575),
        help=("Server port (default: MCREMOTE_API_PORT, legacy JRP_API_PORT, "
              "or 25575)."),
    )
    parser.add_argument(
        "--token-key",
        default=None,
        help="Local token-store key. Defaults to address:port.",
    )
    parser.add_argument(
        "--token-type",
        choices=("session", "long_lived"),
        default="session",
        help="Token type to request during pairing.",
    )
    parser.add_argument(
        "--no-pair",
        action="store_true",
        help="Skip interactive pairing fallback and fail on auth errors.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Directory to write mc_constants.py into (default: current directory).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch catalog.get even if this catalogHash is already cached.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw JSON-RPC frames (including catalog.get, if sent) to stderr.",
    )
    args = parser.parse_args(argv)

    try:
        mc = Minecraft.create(
            address=args.address,
            port=args.port,
            debug=args.debug,
            token_key=args.token_key,
            token_type=args.token_type,
            pair=not args.no_pair,
            sync_catalog=False,  # sync explicitly below so we can report clearly
        )
        print(f"protocol={mc.protocol}")
        print(f"mc_version={mc.mc_version}")
        print(f"catalogHash={mc.catalog_hash}")
        if not mc.catalog_hash:
            print("no catalog advertised by this server/session -- nothing to sync")
            return 0
        # Checked *before* sync_constants() touches the cache, so this
        # reflects what actually happens on the call below (fetch vs. reuse).
        was_cached = load_cached_catalog(mc.catalog_hash) is not None
        source = "network (--force)" if args.force else ("cache" if was_cached else "network")
        path = mc.sync_constants(target_dir=args.out, force=args.force)
        print(f"catalog_source={source}")
        print(f"wrote {path}")
        return 0
    except McRpcError as e:
        print(f"rpc_error={e.reason}")
        print(f"code={e.code}")
        print(f"data={e.data}")
        return 1
    except CatalogError as e:
        print(f"catalog_error={e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
