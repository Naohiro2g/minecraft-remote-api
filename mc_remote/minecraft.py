import sys
import os
import math

from .connection import Connection
from .vec3 import Vec3
from .event import BlockEvent, ChatEvent, ProjectileEvent
from .util import flatten


def intFloor(*args):
    return [int(math.floor(x)) for x in flatten(args)]


class CmdPositioner:
    """Methods for setting and getting positions"""
    def __init__(self, connection, packagePrefix):
        self.conn = connection
        self.pkg = packagePrefix

    def getPos(self, entityId):
        """Get entity position (entityId:int) => Vec3"""
        s = self.conn.sendReceive(self.pkg + b".getPos", entityId)
        return Vec3(*list(map(float, s.split(","))))

    def setPos(self, entityId, *args):
        """Set entity position (entityId:int, x,y,z)"""
        self.conn.send(self.pkg + b".setPos", entityId, *args)

    def getTilePos(self, entityId):
        """Get entity tile position (entityId:int) => Vec3"""
        s = self.conn.sendReceive(self.pkg + b".getTile", entityId)
        return Vec3(*list(map(int, s.split(","))))

    def setTilePos(self, entityId, *args):
        """Set entity tile position (entityId:int) => Vec3"""
        self.conn.send(self.pkg + b".setTile", entityId, intFloor(*args))

    def setDirection(self, entityId, *args):
        """Set entity direction (entityId:int, x,y,z)"""
        self.conn.send(self.pkg + b".setDirection", entityId, args)

    def getDirection(self, entityId):
        """Get entity direction (entityId:int) => Vec3"""
        s = self.conn.sendReceive(self.pkg + b".getDirection", entityId)
        return Vec3(*map(float, s.split(",")))

    def setRotation(self, entityId, yaw):
        """Set entity rotation (entityId:int, yaw)"""
        self.conn.send(self.pkg + b".setRotation", entityId, yaw)

    def getRotation(self, entityId):
        """get entity rotation (entityId:int) => float"""
        return float(self.conn.sendReceive(self.pkg + b".getRotation", entityId))

    def setPitch(self, entityId, pitch):
        """Set entity pitch (entityId:int, pitch)"""
        self.conn.send(self.pkg + b".setPitch", entityId, pitch)

    def getPitch(self, entityId):
        """get entity pitch (entityId:int) => float"""
        return float(self.conn.sendReceive(self.pkg + b".getPitch", entityId))

    def setting(self, setting, status):
        """Set a player setting (setting, status). keys: autojump"""
        self.conn.send(self.pkg + b".setting", setting, 1 if bool(status) else 0)


class CmdEntity(CmdPositioner):
    """Methods for entities"""
    def __init__(self, connection):
        CmdPositioner.__init__(self, connection, b"entity")

    def getName(self, id):
        """Get the list name of the player with entity id => [name:str]
        Also can be used to find name of entity if entity is not a player."""
        return self.conn.sendReceive(b"entity.getName", id)

    def remove(self, id):
        self.conn.send(b"entity.remove", id)


class Entity:
    def __init__(self, conn, entity_uuid, typeName):
        self.p = CmdPositioner(conn, b"entity")
        self.id = entity_uuid
        self.type = typeName

    def getPos(self):
        return self.p.getPos(self.id)

    def setPos(self, *args):
        self.p.setPos(self.id, *args)

    def getTilePos(self):
        return self.p.getTilePos(self.id)

    def setTilePos(self, *args):
        self.p.setTilePos(self.id, *args)

    def setDirection(self, *args):
        self.p.setDirection(self.id, *args)

    def getDirection(self):
        return self.p.getDirection(self.id)

    def setRotation(self, yaw):
        self.p.setRotation(self.id, yaw)

    def getRotation(self):
        return self.p.getRotation(self.id)

    def setPitch(self, pitch):
        self.p.setPitch(self.id, pitch)

    def getPitch(self):
        return self.p.getPitch(self.id)

    def remove(self):
        self.p.conn.send(b"entity.remove", self.id)


class CmdPlayer(CmdPositioner):
    """Methods for the host (Raspberry Pi) player"""
    def __init__(self, connection):
        CmdPositioner.__init__(self, connection, b"player")
        self.conn = connection

    def getPos(self):
        return CmdPositioner.getPos(self, [])

    def setPos(self, *args):
        CmdPositioner.setPos(self, [], *args)

    def getTilePos(self):
        return CmdPositioner.getTilePos(self, [])

    def setTilePos(self, *args):
        CmdPositioner.setTilePos(self, [], *args)

    def setDirection(self, *args):
        CmdPositioner.setDirection(self, [], *args)

    def getDirection(self):
        return CmdPositioner.getDirection(self, [])

    def setRotation(self, yaw):
        CmdPositioner.setRotation(self, [], yaw)

    def getRotation(self):
        return CmdPositioner.getRotation(self, [])

    def setPitch(self, pitch):
        CmdPositioner.setPitch(self, [], pitch)

    def getPitch(self):
        return CmdPositioner.getPitch(self, [])


class CmdCamera:
    def __init__(self, connection):
        self.conn = connection

    def setNormal(self, *args):
        """Set camera mode to normal Minecraft view ([entityId])"""
        self.conn.send(b"camera.mode.setNormal", *args)

    def setFixed(self):
        """Set camera mode to fixed view"""
        self.conn.send(b"camera.mode.setFixed")

    def setFollow(self, *args):
        """Set camera mode to follow an entity ([entityId])"""
        self.conn.send(b"camera.mode.setFollow", *args)

    def setPos(self, *args):
        """Set camera entity position (x,y,z)"""
        self.conn.send(b"camera.setPos", *args)


class CmdEvents:
    """Events"""
    def __init__(self, connection):
        self.conn = connection

    def clearAll(self):
        """Clear all old events"""
        self.conn.send(b"events.clear")

    def pollBlockHits(self):
        """Only triggered by sword => [BlockEvent]"""
        s = self.conn.sendReceive(b"events.block.hits")
        events = [e for e in s.split("|") if e]
        return [BlockEvent.Hit(*e.split(",")) for e in events]

    def pollChatPosts(self):
        """Triggered by posts to chat => [ChatEvent]"""
        s = self.conn.sendReceive(b"events.chat.posts")
        events = [e for e in s.split("|") if e]
        return [ChatEvent.Post(int(e[:e.find(",")]), e[e.find(",") + 1:]) for e in events]

    def pollProjectileHits(self):
        """Only triggered by projectiles => [BlockEvent]"""
        s = self.conn.sendReceive(b"events.projectile.hits")
        events = [e for e in s.split("|") if e]
        return [ProjectileEvent.Hit(*e.split(",")) for e in events]


class Minecraft:
    """The main class to interact with a running instance of Minecraft Pi."""
    def __init__(self, connection):
        self.conn = connection

        self.camera = CmdCamera(connection)
        self.entity = CmdEntity(connection)
        self.player = CmdPlayer(connection)
        self.events = CmdEvents(connection)

    def getBlock(self, *args):
        """Get block (x,y,z) => id:int"""
        return self.conn.sendReceive(b"world.getBlock", intFloor(args))

    def getBlockWithData(self, *args):
        """Get block with data (x,y,z) => Block"""
        s = self.conn.sendReceive(b"world.getBlockWithData", intFloor(args)).split(",")
        if s[-1] == "":
            s.pop()
        return s

    def getBlocks(self, *args):
        """Get a cuboid of blocks (x0,y0,z0,x1,y1,z1) => [id:int]"""
        s = self.conn.sendReceive(b"world.getBlocks", *args).split(",")
        if s[-1] == "":
            s.pop()
        return s

    def setBlock(self, *args):
        """Set block (x,y,z,id,[data])"""
        self.conn.send(b"world.setBlock", *args)
        return
        # return self.conn.sendReceive(b"world.setBlock", *args)

    def setBlocks(self, *args):
        """Set a cuboid of blocks (x0,y0,z0,x1,y1,z1,id,[data])"""
        self.conn.send(b"world.setBlocks", *args)
        return
        # return self.conn.sendReceive(b"world.setBlocks", *args)

    def setSign(self, *args):
        """Set a sign (x,y,z,sign_type,direction,line1,line2,line3,line4)
        direction: 0-north, 1-east, 2-south 3-west
        """
        self.conn.send(b"world.setSign", *args)

    def spawnEntity(self, *args):
        """Spawn entity (x,y,z,id,[data])"""
        return Entity(self.conn, self.conn.sendReceive(b"world.spawnEntity", *args), args[3])
        # return self.conn.send(b"world.spawnEntity", *args)

    def spawnParticle(self, *args):
        """Spawn entity (x,y,z,x1,y1,z1,id,speed,count,[force,data])"""
        self.conn.send(b"world.spawnParticle", *args)

    def getNearbyEntities(self, *args):
        """get nearby entities (x,y,z)"""
        entities = []
        for i in self.conn.sendReceive(b"world.getNearbyEntities", *args).split(","):
            name, eid = i.split(":")
            entities.append(Entity(self.conn, eid, name))
        return entities

    def removeEntity(self, *args):
        """Remove entity (x,y,z,id,[data])"""
        self.conn.send(b"world.removeEntity", *args)

    def getHeight(self, *args):
        """Get the height(=y) of the world at (x,z) => int"""
        print(*args)
        return int(self.conn.sendReceive(b"world.getHeight", intFloor(args)))

    def getPlayerEntityIds(self):
        """Get the entity ids of the connected players => [id:int]"""
        ids = self.conn.sendReceive(b"world.getPlayerIds")
        return ids.split("|")

    def getPlayerEntityId(self, name):
        """Get the entity id of the named player => [id:int]"""
        return self.conn.sendReceive(b"world.getPlayerId", name)

    def saveCheckpoint(self):
        """Save a checkpoint that can be used for restoring the world"""
        self.conn.send(b"world.checkpoint.save")

    def restoreCheckpoint(self):
        """Restore the world state to the checkpoint"""
        self.conn.send(b"world.checkpoint.restore")

    def postToChat(self, msg):
        """Post a message to the game chat"""
        self.conn.send(b"chat.post", msg)

    def setting(self, setting, status):
        """Set a world setting (setting, status). keys: world_immutable, nametags_visible"""
        self.conn.send(b"world.setting", setting, 1 if bool(status) else 0)

    def setPlayer(self, *args):
        """Set player position (name, x,y,z) this is the first remote command to call"""
        result = self.conn.sendReceive(b"setPlayer", *args)
        if "Error" in result:
            sys.exit(result)
        else:
            print(result)
            return result
        # return self.conn.sendReceive(b"setPlayer", *args)

    def close(self):
        """Close the connection to the Minecraft server"""
        self.conn.close()
        return True

    @staticmethod
    def create(address="localhost", port=4711, debug=False):
        if "JRP_API_HOST" in os.environ:
            address = os.environ["JRP_API_HOST"]
        if "JRP_API_PORT" in os.environ:
            try:
                port = int(os.environ["JRP_API_PORT"])
            except ValueError:
                pass
        return Minecraft(Connection(address, port, debug))


def mcpy(func):
    # these will be created as global variable in module, so not good idea
    # func.__globals__['mc'] = Minecraft.create()
    # func.__globals__['pos'] = func.__globals__['mc'].player.getTilePos()
    # func.__globals__['direction'] = func.__globals__['mc'].player.getDirection()
    func.__doc__ = ("_mcpy :" + func.__doc__) if func.__doc__ else "_mcpy "
    return func


if __name__ == "__main__":
    mc = Minecraft.create()
    mc.postToChat("Hello, Minecraft!")
