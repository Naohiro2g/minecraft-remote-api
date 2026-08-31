"""Generate the deterministic Python main-connection observer fixture."""

from __future__ import annotations

import argparse
import json

from .observer import PythonObserverSource


FIXTURE_TIME = 1786118400000

FIXTURE_HELLO = {
    "protocol": "23.1.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "dimension": "minecraft:overworld",
    "origin": [200, 0, 200],
    "world_constants": {"y_sea": 62},
    "permissions": {"online": True, "offline": False, "buildRange": 100},
}


class _FixtureClock:
    def __init__(self):
        self.value = FIXTURE_TIME

    def __call__(self):
        value = self.value
        self.value += 1
        return value


def build_fixture():
    """Return a deterministic, credential-free Python lifecycle fixture."""

    frames = []
    clock = _FixtureClock()
    source = PythonObserverSource(
        frames.append,
        clock=clock,
        target_id_factory=lambda: "target-python-01",
        alias_factory=lambda: "MIND-STORM-000027",
    )
    source.observe_request("hello", {"protocol": "23.1.0"}, 1)
    source.observe_result("hello", FIXTURE_HELLO, 1)

    initial = source.snapshot((), emitted_at=FIXTURE_TIME)
    frames.clear()
    clock.value = FIXTURE_TIME + 100
    source.observe_request("build.setDimension", ["the_nether"], 2)
    source.observe_result(
        "build.setDimension",
        {"dimension": "minecraft:the_nether", "origin": [200, 0, 200]},
        2,
    )
    source.observe_request(
        "world.setBlock",
        [0, 1, 2, {"block_id": "minecraft:oak_log", "state": {"axis": "z"}}],
        None,
    )
    source.observe_request("connection.flush", [], 3)
    source.observe_result("connection.flush", None, 3)
    source.observe_request("world.getHeight", [0, 2, 90], 4)
    source.observe_result("world.getHeight", 71, 4)
    source.observe_request(
        "world.spawnParticle",
        [0.25, 70.5, 2.75, 0.1, 0.2, 0.3, "minecraft:flame", 0.0, 8],
        5,
    )
    source.observe_result("world.spawnParticle", 8, 5)
    source.observe_request(
        "world.spawnEntity", [0.25, 71.0, 2.75, "minecraft:pig"], 6
    )
    source.observe_result(
        "world.spawnEntity", "mcr_eh_AAAAAAAAAAAAAAAAAAAAAA", 6
    )
    source.observe_request("events.poll", [0], 7)
    source.observe_result(
        "events.poll",
        {
            "events": [
                {
                    "sequence": 1,
                    "type": "chat_posted",
                    "dimension": "minecraft:overworld",
                    "origin": [200, 0, 200],
                    "message": "hello",
                }
            ],
            "through_sequence": 1,
            "latest_sequence": 1,
            "filtered_out": 0,
            "overflow_dropped_total": 0,
            "capacity_dropped_total": 0,
            "explicitly_discarded_total": 0,
        },
        7,
    )
    source.observe_request("player.getDirection", [], 8)
    source.observe_result("player.getDirection", [0, 0, 1], 8)
    source.observe_request("player.setDirection", [1, 2, 3], 9)
    source.observe_result(
        "player.setDirection", [0.267261, 0.534522, 0.801784], 9
    )
    source.observe_request(
        "entity.getDirection", ["mcr_eh_AAAAAAAAAAAAAAAAAAAAAA"], 10
    )
    source.observe_result("entity.getDirection", [1, 0, 0], 10)
    source.observe_request(
        "entity.setDirection",
        ["mcr_eh_AAAAAAAAAAAAAAAAAAAAAA", 1, 2, 3],
        11,
    )
    source.observe_result(
        "entity.setDirection", [0.267261, 0.534522, 0.801784], 11
    )
    source.observe_request("world.strikeLightning", [1.25, 2.5, -3.75], 12)
    source.observe_result("world.strikeLightning", None, 12)
    updated = source.snapshot(frames, emitted_at=FIXTURE_TIME + 100)
    source.connection_closed()
    return [initial, updated]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m mc_remote.observer_fixture",
        description=(
            "Generate deterministic mcremote.observer schema v1 fixtures "
            "for compatibility set v1.1."
        ),
    )
    parser.add_argument(
        "--dump-observer-fixture",
        action="store_true",
        help="write the credential-free Python main lifecycle fixture as JSON",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.dump_observer_fixture:
        build_parser().error("--dump-observer-fixture is required")
    print(json.dumps(build_fixture(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
