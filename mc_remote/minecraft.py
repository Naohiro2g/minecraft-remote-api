import os
import math

from .connection import (
    Connection,
    McRemoteError,
    McRpcError,
    ConnectionLostError,
    RequestFailedError,
)
from .vec3 import Vec3
from .util import flatten

__all__ = [
    "Minecraft",
    "McRemoteError",
    "McRpcError",
    "ConnectionLostError",
    "RequestFailedError",
    "mcpy",
]


def intFloor(*args):
    return [int(math.floor(x)) for x in flatten(args)]


class Minecraft:
    """Client for a running Minecraft server speaking protocol 21.x.

    protocol 21.0.0 b1 surface: ``hello`` handshake plus ``setBlock`` /
    ``getBlock`` / ``setBlocks`` over block_state_ref strings, and the
    connection-scoped build state (``setWorld`` / ``setBuildOrigin``). The
    legacy MCPI methods (entity / player / camera / events / sign /
    checkpoint / particle ...) were removed in the payload flip and will be
    re-introduced per protocol bump as they are ported to JSON-RPC."""

    def __init__(self, connection):
        self.conn = connection

        # Build state, scoped to this connection/stream (one instance = one
        # stream = one build state). Kept as a local record of what this stream
        # last set; the server is authoritative and applies the origin.
        self._world = "overworld"
        self._origin = Vec3(200, 0, 200)

        # Populated by hello(); the server is the source of truth.
        self.protocol = None
        self.server = {}
        self.catalogs = {}

    def hello(self):
        """Handshake. Returns the server's hello response and caches the
        protocol string, server info and catalog manifest on this instance.

        In b1 the manifest is the envelope only: ``catalogs.block`` is always
        present with ``format`` set, ``hash=null`` and ``namespaces=[]`` until
        a later bump fills it in (client always falls back to its bundled
        catalog while ``hash`` is null)."""
        resp = self.conn.rpc("hello")
        if isinstance(resp, dict):
            self.protocol = resp.get("protocol")
            self.server = resp.get("server", {})
            self.catalogs = resp.get("catalogs", {})
        return resp

    def setBlock(self, x, y, z, block):
        """Set one block at (x, y, z) to a block_state_ref string, e.g.
        ``"minecraft:oak_log[axis=y]"``. The namespace is required; the input
        may omit/reorder state properties (the server canonicalises)."""
        coords = intFloor(x, y, z)
        return self.conn.rpc("world.setBlock", coords + [block])

    def getBlock(self, x, y, z):
        """Get the block at (x, y, z) as a canonical full block_state_ref
        string (all properties, names alphabetical) => round-trips with
        setBlock by string equality."""
        coords = intFloor(x, y, z)
        return self.conn.rpc("world.getBlock", coords)

    def setBlocks(self, x0, y0, z0, x1, y1, z1, block):
        """Set a cuboid (x0,y0,z0)-(x1,y1,z1) to a block_state_ref string.
        Validation is all-or-nothing: a single invalid ref rejects the whole
        request."""
        coords = intFloor(x0, y0, z0, x1, y1, z1)
        return self.conn.rpc("world.setBlocks", coords + [block])

    def setWorld(self, dimension):
        """Set the build world/dimension (overworld, nether, end, or an exact
        world name). Build state is scoped to this connection/stream."""
        result = self.conn.rpc("build.setWorld", [dimension])
        self._world = dimension
        return result

    def setBuildOrigin(self, x, y, z):
        """Set the build origin (x, y, z). Default is (200, 0, 200).
        Coordinates are absolute; no implicit Y offset is applied (abs y =
        origin y + dy)."""
        coords = intFloor(x, y, z)
        result = self.conn.rpc("build.setOrigin", coords)
        self._origin = Vec3(*coords)
        return result

    def close(self):
        """Close the connection to the Minecraft server"""
        self.conn.close()
        return True

    @staticmethod
    def create(address="localhost", port=4711, debug=False, handshake=True):
        if "JRP_API_HOST" in os.environ:
            address = os.environ["JRP_API_HOST"]
        if "JRP_API_PORT" in os.environ:
            try:
                port = int(os.environ["JRP_API_PORT"])
            except ValueError:
                pass
        mc = Minecraft(Connection(address, port, debug))
        if handshake:
            mc.hello()
        return mc


def mcpy(func):
    # these will be created as global variable in module, so not good idea
    # func.__globals__['mc'] = Minecraft.create()
    func.__doc__ = ("_mcpy :" + func.__doc__) if func.__doc__ else "_mcpy "
    return func


if __name__ == "__main__":
    mc = Minecraft.create()
    mc.setBlock(0, 0, 0, "minecraft:stone")
    print(mc.getBlock(0, 0, 0))
