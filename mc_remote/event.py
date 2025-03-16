from .vec3 import Vec3


class BlockEvent:
    """An Event related to blocks (e.g. placed, removed, hit)"""

    HIT = 0

    def __init__(self, event_type, x, y, z, face, entityId):
        self.event_type = event_type
        self.pos = Vec3(int(x), int(y), int(z))
        self.face = face
        self.entityId = entityId

    def __repr__(self):
        sType = {BlockEvent.HIT: "BlockEvent.HIT"}.get(self.event_type, "???")

        return f"BlockEvent({sType}, {self.pos.x}, {self.pos.y}, {self.pos.z}, {self.face}, {self.entityId})"

    @staticmethod
    def Hit(x, y, z, face, entityId):
        return BlockEvent(BlockEvent.HIT, x, y, z, face, entityId)


class ChatEvent:
    """An Event related to chat (e.g. posts)"""

    POST = 0

    def __init__(self, event_type, entityId, message):
        self.event_type = event_type
        self.entityId = entityId
        self.message = message

    def __repr__(self):
        sType = {ChatEvent.POST: "ChatEvent.POST"}.get(self.event_type, "???")

        return f"ChatEvent({sType}, {self.entityId}, {self.message})"

    @staticmethod
    def Post(entityId, message):
        return ChatEvent(ChatEvent.POST, entityId, message)


class ProjectileEvent:
    """An Event related to projectiles (e.g. placed, removed, hit)"""

    HIT = 0

    def __init__(self, event_type, x, y, z, face, shooterName, victimName):
        self.event_type = event_type
        self.pos = Vec3(int(x), int(y), int(z))
        self.face = face
        self.shooterName = shooterName
        self.victimName = victimName

    def __repr__(self):
        sType = {ProjectileEvent.HIT: "ProjectileEvent.HIT"}.get(self.event_type, "???")

        return f"ProjectileEvent({sType}, {self.pos.x}, {self.pos.y}, {self.pos.z}, {self.face}, {self.shooterName}, {self.victimName})"

    @staticmethod
    def Hit(x, y, z, face, shooterName, victimName):
        return ProjectileEvent(BlockEvent.HIT, x, y, z, face, shooterName, victimName)
