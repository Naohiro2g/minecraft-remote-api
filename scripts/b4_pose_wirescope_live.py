#!/usr/bin/env python3
"""Live-human b4 pose regression on the protocol 22/b5 client."""

from __future__ import annotations

import argparse
import math
import os
import tempfile

from mc_remote.connection import McRpcError
from mc_remote.minecraft import Minecraft, PROTOCOL


POSE_FIELDS = {"dimension", "pos", "yaw", "pitch"}


def _close_number(left, right, tolerance=1e-4):
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _assert_pose_shape(pose):
    assert isinstance(pose, dict)
    assert set(pose) == POSE_FIELDS
    assert isinstance(pose["dimension"], str) and ":" in pose["dimension"]
    assert isinstance(pose["pos"], list) and len(pose["pos"]) == 3
    for value in [*pose["pos"], pose["yaw"], pose["pitch"]]:
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        assert math.isfinite(value)
    assert -90.0 <= pose["pitch"] <= 90.0


def _assert_pose_close(actual, expected):
    assert actual["dimension"] == expected["dimension"]
    for actual_value, expected_value in zip(actual["pos"], expected["pos"]):
        assert _close_number(actual_value, expected_value)
    assert _close_number(actual["yaw"], expected["yaw"])
    assert _close_number(actual["pitch"], expected["pitch"])


def _expect_invalid_without_pose_change(mc, params):
    before = mc.getPose()
    try:
        mc.conn.rpc("player.setPose", params)
    except McRpcError as exc:
        assert exc.reason == "invalid_params"
    else:
        raise AssertionError("invalid player.setPose unexpectedly succeeded")
    _assert_pose_close(mc.getPose(), before)


def _exercise_pose_contract(mc):
    assert PROTOCOL == "22.0.0"
    assert mc.protocol == PROTOCOL
    original_origin = tuple(mc._origin)
    original_pose = mc.getPose()
    _assert_pose_shape(original_pose)
    try:
        delta = (7, -3, 11)
        shifted_origin = [
            original_origin[index] + delta[index] for index in range(3)
        ]
        mc.setBuildOrigin(*shifted_origin)
        shifted_pose = mc.getPose()
        _assert_pose_shape(shifted_pose)
        assert shifted_pose["dimension"] == original_pose["dimension"]
        for shifted, initial, offset in zip(
            shifted_pose["pos"], original_pose["pos"], delta
        ):
            assert _close_number(shifted, initial - offset)
        assert _close_number(shifted_pose["yaw"], original_pose["yaw"])
        assert _close_number(shifted_pose["pitch"], original_pose["pitch"])

        mc.setBuildOrigin(*original_origin)
        _assert_pose_close(mc.getPose(), original_pose)

        yaw_result = mc.setPose(
            original_pose["dimension"],
            *original_pose["pos"],
            725.0,
            original_pose["pitch"],
        )
        _assert_pose_shape(yaw_result)
        assert -180.0 <= yaw_result["yaw"] < 180.0
        assert _close_number((yaw_result["yaw"] - 725.0) % 360.0, 0.0)

        for pitch in (-90.0, 90.0):
            pitch_result = mc.setPose(
                original_pose["dimension"],
                *original_pose["pos"],
                yaw_result["yaw"],
                pitch,
            )
            _assert_pose_shape(pitch_result)
            assert _close_number(pitch_result["pitch"], pitch)

        stable_pose = mc.setPose(
            original_pose["dimension"],
            *original_pose["pos"],
            original_pose["yaw"],
            original_pose["pitch"],
        )
        _expect_invalid_without_pose_change(
            mc,
            [
                stable_pose["dimension"],
                *stable_pose["pos"],
                stable_pose["yaw"],
                90.0001,
            ],
        )
        _expect_invalid_without_pose_change(
            mc,
            [stable_pose["dimension"], *stable_pose["pos"]],
        )
    finally:
        mc.setBuildOrigin(*original_origin)
        mc.setPose(
            original_pose["dimension"],
            *original_pose["pos"],
            original_pose["yaw"],
            original_pose["pitch"],
        )


def _arguments():
    parser = argparse.ArgumentParser(
        description="Run the b4 pose contract through a real WireScope browser."
    )
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25575)
    return parser.parse_args()


def main():
    args = _arguments()
    mc = None
    completed = False
    with tempfile.TemporaryDirectory(prefix="mcremote-b4-pair-") as config_dir:
        previous_config = os.environ.get("MCREMOTE_CONFIG_DIR")
        os.environ["MCREMOTE_CONFIG_DIR"] = config_dir
        try:
            mc = Minecraft.create(
                address=args.address,
                port=args.port,
                sync_catalog=False,
                wirescope=True,
            )
            input(
                "Enter the displayed WireScope attach code in the browser, "
                "confirm it is connected, then press Enter here: "
            )
            _exercise_pose_contract(mc)
            input(
                "Confirm WireScope shows player.getPose/player.setPose request, "
                "result, and invalid_params frames, then press Enter to close: "
            )
            completed = True
        finally:
            if mc is not None:
                mc.close()
            if previous_config is None:
                os.environ.pop("MCREMOTE_CONFIG_DIR", None)
            else:
                os.environ["MCREMOTE_CONFIG_DIR"] = previous_config

        if completed:
            input(
                "Confirm WireScope now shows the source as ended and the "
                "stream status as ended, then press Enter: "
            )
            print("LIVE-HUMAN B4 POSE + WIRESCOPE PASS")


if __name__ == "__main__":
    main()
