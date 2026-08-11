"""Generate the deterministic Python main-connection observer fixture."""

from __future__ import annotations

import argparse
import json

from .observer import PythonObserverSource


FIXTURE_TIME = 1786118400000

FIXTURE_HELLO = {
    "protocol": "21.0.0",
    "mc_version": "1.21.11",
    "supported_mc_versions": ["1.21.11"],
    "catalogHash": None,
    "world": "overworld",
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
        alias_factory=lambda: "5A17C0DE",
    )
    source.observe_request("hello", {"protocol": "21.0.0"}, 1)
    source.observe_result("hello", FIXTURE_HELLO, 1)

    initial = source.snapshot((), emitted_at=FIXTURE_TIME)
    frames.clear()
    clock.value = FIXTURE_TIME + 100
    source.observe_request("build.setWorld", ["nether"], 2)
    updated = source.snapshot(frames, emitted_at=FIXTURE_TIME + 100)
    source.connection_closed()
    return [initial, updated]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m mc_remote.observer_fixture",
        description="Generate deterministic mcremote.observer schema v1 fixtures.",
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
