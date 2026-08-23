#!/usr/bin/env python3
"""Live b5 build-mode/flush check that restores every touched block."""

from __future__ import annotations

import argparse
import time

from mc_remote.minecraft import BuildMode, Minecraft, PROTOCOL


def _arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Exercise protocol 22 DEBUG/TRACE/FAST and connection.flush on "
            "five origin-relative blocks, then restore their original state."
        )
    )
    parser.add_argument("address", help="McRemote host")
    parser.add_argument("x", type=int, help="First origin-relative X coordinate")
    parser.add_argument("y", type=int, help="Origin-relative Y coordinate")
    parser.add_argument("z", type=int, help="Origin-relative Z coordinate")
    parser.add_argument("--port", type=int, default=25575)
    parser.add_argument("--token-key", default=None)
    parser.add_argument("--no-pair", action="store_true")
    return parser.parse_args()


def _connect(args, *, mode=BuildMode.DEBUG):
    return Minecraft.create(
        address=args.address,
        port=args.port,
        token_key=args.token_key,
        pair=not args.no_pair,
        sync_catalog=False,
        build_mode=mode,
    )


def _positions(args):
    return [(args.x + offset, args.y, args.z) for offset in range(5)]


def _restore(mc, positions, originals):
    if mc.build_mode is not BuildMode.DEBUG:
        mc.setBuildMode(BuildMode.DEBUG)
    for position, original in zip(positions, originals):
        mc.setBlock(
            *position,
            original.block_id,
            state=dict(original.state),
        )


def _assert_block_ids(mc, args, expected):
    values = mc.getBlocks(args.x, args.y, args.z, args.x + 4, args.y, args.z)
    actual = tuple(value.block_id for value in values)
    assert actual == expected, f"unexpected getBlocks order/content: {actual!r}"


def main():
    args = _arguments()
    positions = _positions(args)
    mc = None
    originals = None
    completed = False
    try:
        mc = _connect(args)
        assert PROTOCOL == "22.0.0"
        assert mc.protocol == PROTOCOL
        originals = tuple(mc.getBlock(*position) for position in positions)

        assert mc.setBlock(*positions[0], "stone") is None

        mc.setBuildMode(BuildMode.TRACE, trace_delay=0.25)
        started = time.monotonic()
        assert mc.setBlock(*positions[1], "oak_log", state={"axis": "z"}) is None
        assert time.monotonic() - started >= 0.20

        mc.setBuildMode(BuildMode.FAST)
        assert mc.setBlock(*positions[2], "gold_block") is None
        assert mc.setBlocks(*positions[3], *positions[4], "diamond_block") is None
        mc.flush()
        _assert_block_ids(
            mc,
            args,
            (
                "minecraft:stone",
                "minecraft:oak_log",
                "minecraft:gold_block",
                "minecraft:diamond_block",
                "minecraft:diamond_block",
            ),
        )

        # A pending FAST notification must also be complete after normal close.
        assert mc.setBlock(*positions[0], "emerald_block") is None
        mc.close()
        mc = _connect(args)
        assert mc.getBlock(*positions[0]).block_id == "minecraft:emerald_block"
        completed = True
    finally:
        try:
            if originals is not None:
                if mc is None or getattr(mc, "_closed", False):
                    mc = _connect(args)
                _restore(mc, positions, originals)
        finally:
            if mc is not None:
                mc.close()

    if completed:
        print("LIVE B5 BUILD MODES + FLUSH PASS (original blocks restored)")


if __name__ == "__main__":
    main()
