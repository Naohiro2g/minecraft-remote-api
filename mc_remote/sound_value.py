"""Optional sound controls; defaults and error priority belong to the server."""

from typing import Literal, TypedDict

from .particle_value import _json_copy


class SoundOptions(TypedDict, total=False):
    volume: int | float
    pitch: int | float
    note: int
    receiver: Literal["world", "self"]


def sound_options(*, volume=None, pitch=None, note=None, receiver="world"):
    """Project named controls, retaining server defaults for omitted fields."""
    if pitch is not None and note is not None:
        raise ValueError("pitch and note cannot both be specified")
    values = {"volume": volume, "pitch": pitch, "note": note, "receiver": receiver}
    return _json_copy(
        {key: value for key, value in values.items() if value is not None},
        context="sound",
    )
