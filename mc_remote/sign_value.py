"""Protocol 23 b6 sign values.

Exact wire contract fixed by DECISIONS 2026-08-26-05 (wire-format-design
§5.8.1). ``LineSpec`` is the public Python input surface accepted by
``Minecraft.setSign`` / ``Minecraft.updateSignLine``. ``LineValue`` and
``SignValue`` are the immutable canonical output returned by
``Minecraft.getSign``. Color and decoration tokens are a fixed wire-level
vocabulary (not catalog/version data), so this module validates them
client-side rather than deferring to the server."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from .connection import McRemoteError


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

_NAMED_COLORS = frozenset(
    {
        "black",
        "dark_blue",
        "dark_green",
        "dark_aqua",
        "dark_red",
        "dark_purple",
        "gold",
        "gray",
        "dark_gray",
        "blue",
        "green",
        "aqua",
        "red",
        "light_purple",
        "yellow",
        "white",
    }
)

_DECORATIONS = frozenset(
    {"bold", "italic", "underlined", "strikethrough", "obfuscated"}
)

LineSpec: TypeAlias = str | dict


def _is_color(value):
    return isinstance(value, str) and (
        value in _NAMED_COLORS or _HEX_COLOR.fullmatch(value) is not None
    )


def line_spec(value):
    """Build the exact protocol 23 wire ``LineSpec`` from Python input.

    A bare string is plain-text shorthand. A mapping may additionally set
    ``color`` (one of the 16 standard Adventure ``NamedTextColor`` tokens, or
    ``#RRGGBB``) and ``decorations`` (a subset of bold/italic/underlined/
    strikethrough/obfuscated). Arbitrary JSON Component fields are rejected;
    the server does not accept them either.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        raise TypeError(
            "sign line must be a string or a {text, color?, decorations?} mapping"
        )
    if not set(value).issubset({"text", "color", "decorations"}):
        raise TypeError("sign line mapping accepts only text, color, and decorations")
    if not isinstance(value.get("text"), str):
        raise TypeError("sign line mapping requires a string 'text'")
    result = {"text": value["text"]}
    if "color" in value:
        if not _is_color(value["color"]):
            raise ValueError(
                "sign line color must be one of the 16 standard color tokens "
                "or #RRGGBB"
            )
        result["color"] = value["color"]
    if "decorations" in value:
        decorations = value["decorations"]
        if not isinstance(decorations, (list, tuple)) or not all(
            isinstance(item, str) for item in decorations
        ):
            raise TypeError("sign line decorations must be a list of strings")
        if not set(decorations).issubset(_DECORATIONS):
            raise ValueError(
                "sign line decorations must be a subset of bold/italic/"
                "underlined/strikethrough/obfuscated"
            )
        result["decorations"] = list(decorations)
    return result


def _four_lines(value, where):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise TypeError(f"{where} must contain exactly 4 lines")
    return [line_spec(item) for item in value]


def sign_face(front=None, back=None):
    """Build the exact protocol 23 ``world.setSign`` params object.

    Each specified face fully replaces its 4 lines (no per-line merge); an
    omitted face is left untouched by the server. At least one face must be
    given."""
    if front is None and back is None:
        raise ValueError("setSign requires at least one of front or back")
    params = {}
    if front is not None:
        params["front"] = _four_lines(front, "front")
    if back is not None:
        params["back"] = _four_lines(back, "back")
    return params


@dataclass(frozen=True, slots=True)
class LineValue:
    text: str
    color: str
    decorations: tuple[str, ...]


def _decode_line_value(value, where):
    if not isinstance(value, dict) or set(value) != {"text", "color", "decorations"}:
        raise McRemoteError(
            f"{where} must be an exact {{text,color,decorations}} object"
        )
    text = value["text"]
    color = value["color"]
    decorations = value["decorations"]
    if not isinstance(text, str):
        raise McRemoteError(f"{where}.text must be a string")
    if not _is_color(color):
        raise McRemoteError(f"{where}.color must be a standard color token or #RRGGBB")
    if not isinstance(decorations, list) or not all(
        isinstance(item, str) for item in decorations
    ):
        raise McRemoteError(f"{where}.decorations must be an array of strings")
    if not set(decorations).issubset(_DECORATIONS):
        raise McRemoteError(f"{where}.decorations contains an unknown token")
    if list(decorations) != sorted(decorations):
        raise McRemoteError(f"{where}.decorations must be in canonical token order")
    return LineValue(text=text, color=color, decorations=tuple(decorations))


def _decode_four_lines(value, where):
    if not isinstance(value, list) or len(value) != 4:
        raise McRemoteError(f"{where} must contain exactly 4 lines")
    return tuple(
        _decode_line_value(item, f"{where}[{index}]")
        for index, item in enumerate(value)
    )


@dataclass(frozen=True, slots=True)
class SignValue:
    front: tuple[LineValue, ...]
    back: tuple[LineValue, ...]
    waxed: bool


def decode_sign_value(value) -> SignValue:
    if not isinstance(value, dict) or set(value) != {"front", "back", "waxed"}:
        raise McRemoteError(
            "world.getSign result must contain exactly front, back, and waxed"
        )
    if not isinstance(value["waxed"], bool):
        raise McRemoteError("world.getSign result.waxed must be a boolean")
    return SignValue(
        front=_decode_four_lines(value["front"], "front"),
        back=_decode_four_lines(value["back"], "back"),
        waxed=value["waxed"],
    )


__all__ = [
    "LineSpec",
    "LineValue",
    "SignValue",
    "decode_sign_value",
    "line_spec",
    "sign_face",
]
