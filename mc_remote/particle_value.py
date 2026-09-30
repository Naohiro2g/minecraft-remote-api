"""Typed Python inputs for protocol 23.2 ParticleSpec objects."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal, TypedDict

from .block_value import StateScalar
from .resource_id import resource_id


class DustData(TypedDict):
    color: list[int]
    size: int | float


class BlockParticleData(TypedDict):
    block_id: str
    state: Mapping[str, StateScalar]


class _ParticleOptions(TypedDict, total=False):
    receiver: Literal["world", "self"]
    data: DustData | BlockParticleData


class ParticleSpec(_ParticleOptions):
    particle_id: str


def _json_copy(value, *, context="particle"):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError(f"{context} object keys must be strings")
        return {key: _json_copy(item, context=context) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(item, context=context) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"{context} values must be finite JSON values")


def particle_spec(value):
    """Preserve omission and explicit null; the server resolves ID/data/receiver.

    Data and receiver validation stays on the server so unknown-particle and
    data errors retain their specified precedence over self authentication.
    """

    if isinstance(value, str):
        particle_id = value
    elif isinstance(value, Mapping):
        if "particle_id" not in value or set(value) - {"particle_id", "receiver", "data"}:
            raise ValueError("ParticleSpec allows only particle_id, receiver, and data")
        particle_id = value["particle_id"]
    else:
        raise TypeError("particle must be a namespace ID or ParticleSpec mapping")
    resource_id(particle_id, "particle_id")
    return particle_id if isinstance(value, str) else _json_copy(value)


__all__ = ["BlockParticleData", "DustData", "ParticleSpec"]
