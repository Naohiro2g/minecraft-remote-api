"""Protocol 23.2 entity snapshots; handles remain scoped to their connection."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TypedDict

from .b5_values import EntityHandle
from .connection import McRemoteError
from .dimension import require_dimension_key


class PoseValue(TypedDict):
    dimension: str
    pos: list[int | float]
    yaw: int | float
    pitch: int | float


@dataclass(frozen=True, slots=True)
class NearbyEntity:
    """An origin-relative snapshot, in the server's distance order."""

    handle: EntityHandle
    type: str
    pos: tuple[int | float, int | float, int | float]


def _number(value, where):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise McRemoteError(f"{where} must be a finite number")
    return value


def _position(value, where):
    if not isinstance(value, list) or len(value) != 3:
        raise McRemoteError(f"{where} must be a three-number array")
    return tuple(_number(item, where) for item in value)


def decode_entity_pose(value) -> PoseValue:
    """Keep the server's post-read numbers without rounding or normalization."""

    if not isinstance(value, dict) or set(value) != {
        "dimension", "pos", "yaw", "pitch"
    }:
        raise McRemoteError("entity pose must contain dimension, pos, yaw, and pitch")
    try:
        dimension = require_dimension_key(value["dimension"], "entity pose.dimension")
    except (TypeError, ValueError) as exc:
        raise McRemoteError(str(exc)) from exc
    pos = _position(value["pos"], "entity pose.pos")
    yaw = _number(value["yaw"], "entity pose.yaw")
    pitch = _number(value["pitch"], "entity pose.pitch")
    if not -180 <= yaw < 180 or not -90 <= pitch <= 90:
        raise McRemoteError("entity pose angles are outside their canonical ranges")
    return {"dimension": dimension, "pos": list(pos), "yaw": yaw, "pitch": pitch}


def decode_nearby_entities(value, max_entities) -> tuple[NearbyEntity, ...]:
    if not isinstance(value, list) or len(value) > max_entities:
        raise McRemoteError("nearby result must be an array within max_entities")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"handle", "type", "pos"}:
            raise McRemoteError("nearby entry must contain exactly handle, type, and pos")
        try:
            handle = EntityHandle(item["handle"])
        except ValueError as exc:
            raise McRemoteError(str(exc)) from exc
        entity_type = item["type"]
        if not isinstance(entity_type, str) or re.fullmatch(
            r"[a-z0-9_.-]+:[a-z0-9/._-]+", entity_type
        ) is None:
            raise McRemoteError("nearby type must be a canonical namespace ID")
        result.append(
            NearbyEntity(handle, entity_type, _position(item["pos"], "nearby pos"))
        )
    return tuple(result)


__all__ = ["NearbyEntity", "PoseValue"]
