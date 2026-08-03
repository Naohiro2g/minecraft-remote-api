"""Installed command line surface for project setup.

Authentication commands intentionally do not exist while the long-lived
credential gate is closed. ``init`` only prepares ignore rules for the local
environment adapter and disposable projection; it never connects,
authenticates, or creates either file.
"""
import argparse

from .projection import init_project


def build_parser():
    parser = argparse.ArgumentParser(prog="mcremote")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser(
        "init", help="prepare a project for local settings and catalog completion"
    )
    init.add_argument(
        "path",
        nargs="?",
        default=".",
        help="project root (default: current directory)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "init":
        path, changed = init_project(args.path)
        state = "updated" if changed else "already configured"
        print(f"{state}: {path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
