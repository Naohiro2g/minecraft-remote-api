"""Immutable protocol 22 b5 event and entity-handle projections."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias

from .block_value import BlockValue, decode_block_value
from .connection import McRemoteError
from .dimension import require_dimension_key


_HANDLE = re.compile(r"^mceh_[A-Za-z0-9_-]{22,}$")


class EntityHandle(str):
    """Opaque connection-epoch scoped entity handle."""

    def __new__(cls, value):
        if not isinstance(value, str) or _HANDLE.fullmatch(value) is None:
            raise ValueError("entity handle has an invalid shape")
        return super().__new__(cls, value)


class EventContextMismatchError(McRemoteError):
    """An event's captured coordinate context differs from the build context."""

    reason = "event_context_mismatch"

    def __init__(
        self,
        *,
        event_dimension,
        event_origin,
        current_dimension,
        current_origin,
    ):
        self.event_dimension = event_dimension
        self.event_origin = event_origin
        self.current_dimension = current_dimension
        self.current_origin = current_origin
        super().__init__(
            "event context does not match the current build context; "
            f"event dimension/origin={event_dimension!r}/{event_origin!r}, "
            f"current={current_dimension!r}/{current_origin!r}; explicitly call "
            "setDimension(event.dimension) and "
            "setBuildOrigin(*event.origin) before using event coordinates"
        )


@dataclass(frozen=True, slots=True)
class BlockTarget:
    pos: tuple[int, int, int]
    block: BlockValue
    face: str | None = None
    kind: str = "block"


@dataclass(frozen=True, slots=True)
class PlayerTarget:
    kind: str = "player"


@dataclass(frozen=True, slots=True)
class EntityTarget:
    handle: EntityHandle
    kind: str = "entity"


ProjectileTarget: TypeAlias = BlockTarget | PlayerTarget | EntityTarget


@dataclass(frozen=True, slots=True)
class BlockRightClickEvent:
    sequence: int
    dimension: str
    origin: tuple[int, int, int]
    pos: tuple[int, int, int]
    face: str
    block: BlockValue
    hand: str
    type: str = "block_right_click"


@dataclass(frozen=True, slots=True)
class ChatPostedEvent:
    sequence: int
    dimension: str
    origin: tuple[int, int, int]
    message: str
    type: str = "chat_posted"


@dataclass(frozen=True, slots=True)
class ProjectileHitEvent:
    sequence: int
    dimension: str
    origin: tuple[int, int, int]
    projectile: str
    pos: tuple[int | float, int | float, int | float]
    target: ProjectileTarget
    type: str = "projectile_hit"


EventValue: TypeAlias = BlockRightClickEvent | ChatPostedEvent | ProjectileHitEvent


@dataclass(frozen=True, slots=True)
class EventBatch:
    events: tuple[EventValue, ...]
    through_sequence: int
    latest_sequence: int
    filtered_out: int
    overflow_dropped_total: int
    capacity_dropped_total: int
    explicitly_discarded_total: int

    @property
    def loss_totals(self):
        return MappingProxyType(
            {
                "overflow": self.overflow_dropped_total,
                "capacity": self.capacity_dropped_total,
                "explicitly_discarded": self.explicitly_discarded_total,
            }
        )


def _object(value, where):
    if not isinstance(value, dict):
        raise McRemoteError(f"{where} must be an object")
    return value


def _exact(value, fields, where):
    if set(value) != set(fields):
        raise McRemoteError(f"{where} has an invalid field set")


def _integer(value, where):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise McRemoteError(f"{where} must be a non-negative integer")
    return value


def _integer_tuple(value, where):
    if not isinstance(value, list) or len(value) != 3:
        raise McRemoteError(f"{where} must be a three-integer array")
    parsed = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise McRemoteError(f"{where}[{index}] must be an integer")
        parsed.append(item)
    return tuple(parsed)


def _number_tuple(value, where):
    if not isinstance(value, list) or len(value) != 3:
        raise McRemoteError(f"{where} must be a three-number array")
    parsed = []
    for index, item in enumerate(value):
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
        ):
            raise McRemoteError(f"{where}[{index}] must be a finite number")
        parsed.append(item)
    return tuple(parsed)


def _string(value, where):
    if not isinstance(value, str) or not value:
        raise McRemoteError(f"{where} must be a non-empty string")
    return value


def _target(value):
    target = _object(value, "projectile target")
    kind = target.get("kind")
    if kind == "player":
        _exact(target, {"kind"}, "player target")
        return PlayerTarget()
    if kind == "entity":
        _exact(target, {"kind", "handle"}, "entity target")
        try:
            handle = EntityHandle(target["handle"])
        except ValueError as exc:
            raise McRemoteError(str(exc)) from exc
        return EntityTarget(handle)
    if kind == "block":
        allowed = {"kind", "pos", "block"}
        if "face" in target:
            allowed.add("face")
        _exact(target, allowed, "block target")
        face = (
            _string(target["face"], "block target.face")
            if "face" in target
            else None
        )
        return BlockTarget(
            _integer_tuple(target["pos"], "block target.pos"),
            decode_block_value(target["block"]),
            face,
        )
    raise McRemoteError("projectile target.kind is invalid")


def decode_event(value) -> EventValue:
    event = _object(value, "event")
    event_type = event.get("type")
    common = {
        "sequence": _integer(event.get("sequence"), "event.sequence"),
        "dimension": require_dimension_key(
            event.get("dimension"), "event.dimension"
        ),
        "origin": _integer_tuple(event.get("origin"), "event.origin"),
    }
    if event_type == "block_right_click":
        _exact(
            event,
            {
                "sequence",
                "type",
                "dimension",
                "origin",
                "pos",
                "face",
                "block",
                "hand",
            },
            "block_right_click event",
        )
        return BlockRightClickEvent(
            **common,
            pos=_integer_tuple(event["pos"], "event.pos"),
            face=_string(event["face"], "event.face"),
            block=decode_block_value(event["block"]),
            hand=_string(event["hand"], "event.hand"),
        )
    if event_type == "chat_posted":
        _exact(
            event,
            {"sequence", "type", "dimension", "origin", "message"},
            "chat_posted event",
        )
        return ChatPostedEvent(
            **common,
            message=_string(event["message"], "event.message"),
        )
    if event_type == "projectile_hit":
        _exact(
            event,
            {
                "sequence",
                "type",
                "dimension",
                "origin",
                "projectile",
                "pos",
                "target",
            },
            "projectile_hit event",
        )
        return ProjectileHitEvent(
            **common,
            projectile=_string(event["projectile"], "event.projectile"),
            pos=_number_tuple(event["pos"], "event.pos"),
            target=_target(event["target"]),
        )
    raise McRemoteError("event.type is invalid")


def decode_event_batch(value, *, after_sequence) -> EventBatch:
    result = _object(value, "events.poll result")
    fields = {
        "events",
        "through_sequence",
        "latest_sequence",
        "filtered_out",
        "overflow_dropped_total",
        "capacity_dropped_total",
        "explicitly_discarded_total",
    }
    _exact(result, fields, "events.poll result")
    if not isinstance(result["events"], list):
        raise McRemoteError("events.poll result.events must be an array")
    counters = {
        name: _integer(result[name], f"events.poll result.{name}")
        for name in fields - {"events"}
    }
    through = counters["through_sequence"]
    latest = counters["latest_sequence"]
    if through < after_sequence or through > latest:
        raise McRemoteError("events.poll result cursor bounds are invalid")
    events = tuple(decode_event(item) for item in result["events"])
    sequences = tuple(item.sequence for item in events)
    if sequences != tuple(sorted(set(sequences))):
        raise McRemoteError("events.poll result sequences are not strictly increasing")
    if sequences and (sequences[0] <= after_sequence or sequences[-1] > through):
        raise McRemoteError(
            "events.poll result event sequence is outside cursor bounds"
        )
    return EventBatch(events=events, **counters)


__all__ = [
    "BlockRightClickEvent",
    "BlockTarget",
    "ChatPostedEvent",
    "EntityHandle",
    "EntityTarget",
    "EventBatch",
    "EventContextMismatchError",
    "EventValue",
    "PlayerTarget",
    "ProjectileHitEvent",
    "ProjectileTarget",
]
