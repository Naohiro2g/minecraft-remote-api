"""Convenient imports that follow a reloaded client submodule."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .minecraft import Minecraft as Minecraft

__all__ = ["Minecraft"]


def __getattr__(name):
    if name == "Minecraft":
        from . import minecraft

        return minecraft.Minecraft
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))
