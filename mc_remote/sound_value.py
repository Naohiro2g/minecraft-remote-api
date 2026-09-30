"""Optional sound controls; defaults and error priority belong to the server."""

from collections.abc import Mapping
from typing import Literal, TypedDict

from .particle_value import _json_copy


class SoundOptions(TypedDict, total=False):
    volume: int | float
    pitch: int | float
    note: int
    receiver: Literal["world", "self"]


def sound_options(value):
    # Explicit null is deliberately distinct from omission, as on the wire.
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("sound options must be a mapping")
    if set(value) - {"volume", "pitch", "note", "receiver"}:
        raise ValueError("sound options allow only volume, pitch, note, and receiver")
    return _json_copy(value, context="sound")
