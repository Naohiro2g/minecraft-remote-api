#!/usr/bin/env python3
"""Manual hello/auth smoke helper.

This is for live checks and operator use, not for automated unit tests.
It keeps the examples directory focused on API samples.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def _print_summary(mc):
    origin = getattr(mc, "_origin", None)
    if origin is None:
        origin_text = "unknown"
    else:
        origin_text = f"{origin.x},{origin.y},{origin.z}"
    print(f"protocol={mc.protocol}")
    print(f"mc_version={mc.mc_version}")
    print(f"world={getattr(mc, '_world', None)}")
    print(f"origin={origin_text}")
    print(f"player={mc.player}")
    print(f"permissions={mc.permissions}")
    print(f"catalogHash={mc.catalog_hash}")
    print(f"y_sea={mc.y_sea}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Live hello/auth smoke helper for Minecraft Remote."
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
        "--sandbox",
        default=None,
        help="Compatibility alias for the local token-store key.",
    )
    parser.add_argument(
        "--token-type",
        choices=("session", "player"),
        default="session",
        help="Token type to request during pairing.",
    )
    parser.add_argument(
        "--no-pair",
        action="store_true",
        help="Skip interactive pairing fallback and fail on auth errors.",
    )
    parser.add_argument(
        "--chat",
        default=None,
        help="Optional chat message to send after a successful hello.",
    )
    parser.add_argument(
        "--set-block",
        nargs=4,
        metavar=("X", "Y", "Z", "BLOCK"),
        help="Optional world.setBlock smoke, e.g. --set-block 0 64 0 minecraft:stone.",
    )
    parser.add_argument(
        "--get-pos",
        action="store_true",
        help="Optional player.getPos smoke for the paired player.",
    )
    parser.add_argument(
        "--set-pos",
        nargs=4,
        metavar=("WORLD", "X", "Y", "Z"),
        help="Optional player.setPos smoke, e.g. --set-pos overworld 0 64 0.",
    )
    args = parser.parse_args(argv)

    try:
        mc = Minecraft.create(
            address=args.address,
            port=args.port,
            token_key=args.token_key,
            sandbox=args.sandbox,
            token_type=args.token_type,
            pair=not args.no_pair,
        )
        _print_summary(mc)
        if args.chat is not None:
            mc.postToChat(args.chat)
            print("chat=sent")
        if args.set_block is not None:
            x, y, z, block = args.set_block
            mc.setBlock(int(x), int(y), int(z), block)
            print("setBlock=ok")
        if args.get_pos:
            print(f"getPos={mc.getPos()}")
        if args.set_pos is not None:
            world, x, y, z = args.set_pos
            print(f"setPos={mc.setPos(world, int(x), int(y), int(z))}")
        return 0
    except McRpcError as e:
        print(f"rpc_error={e.reason or e.message}")
        print(f"code={e.code}")
        print(f"data={e.data}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
