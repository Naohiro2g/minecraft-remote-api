import random

import param_mc_remote as param
from param_mc_remote import PLAYER_ORIGIN as PO
from param_mc_remote import block
from param_mc_remote import entity
from param_mc_remote import particle
from mc_remote.minecraft import Minecraft

x, y, z = 20, 70, 20

# wool blocks
blocks1 = [block.WHITE_WOOL, block.ORANGE_WOOL, block.MAGENTA_WOOL,
           block.LIGHT_BLUE_WOOL, block.YELLOW_WOOL, block.LIME_WOOL,
           block.PINK_WOOL, block.GRAY_WOOL, block.LIGHT_GRAY_WOOL,
           block.CYAN_WOOL, block.PURPLE_WOOL, block.BLUE_WOOL,
           block.BROWN_WOOL, block.GREEN_WOOL, block.RED_WOOL, block.BLACK_WOOL]

blocks2 = [block.GRASS_BLOCK, block.GOLD_ORE, block.IRON_ORE, block.COAL_ORE,
           block.GLASS, block.GOLD_BLOCK, block.IRON_BLOCK,
           block.TNT, block.DIAMOND_ORE, block.DIAMOND_BLOCK,
           block.REDSTONE_ORE, block.SNOW, block.ICE, block.GLOWSTONE]

# Connect to minecraft and open a session as player with origin location
mc = Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR)
mc.setPlayer(param.PLAYER_NAME, PO.x, PO.y, PO.z)

mc.postToChat(msg="mc_remote testing!! 1")
# print(mc.getHeight(x, z))
result = mc.spawnParticle(x, y, z, 1, 1, 1, particle.HAPPY_VILLAGER, 0.2, 30000)
print(result)

result = mc.setBlocks(x - 1, y, z - 1, x + 1, y, z + 1, blocks1[random.randint(0, 15)])
print(result)
result = mc.setBlock(x - 1, y + 3, z, blocks2[random.randint(0, 13)])
print(result)

mob1 = mc.spawnEntity(x, y, z, entity.CAT)
print(mob1)
# print(mob1.setPos(x + 2, y + 7, z))
# print(mob1.getPos())

# print(mc.getPlayerEntityId("nao2g"))


result = mc.spawnParticle(x - 10, y + 5, z, 1, 1, 1, particle.DRAGON_BREATH, 0.2, 10000)
print(result)
result = mc.setBlock(x - 1, y + 5, z, blocks1[random.randint(0, 15)])
print(result)
mc.postToChat(msg="mc_remote testing!! 2")

# mob1 = mc.spawnEntity(x, y, z, entity.COW)
# mc.spawnParticle(x, y, z, 1, 1, 1, particle.DRAGON_BREATH, 0.2, 10000)

# mc.postToChat("mc_remote testing!!")
# mc.postToChat("mc_remote testing!!2222222")


# player = mc.getPlayerEntityId("nao2g")  # 動いてない
# print("player: ", player)

# print(mc.getPlayerEntityIds())  # 動いてない
# print(mc.getNearbyEntities())  # 動いてない
# print(mc.player.getPos())  # 動いてない


# mc.setPlayer(param.PLAYER_NAME, po.x, po.y, po.z)
# mc.postToChat("Hello, Minecraft Server!!")

# mc.setBlock(x, y, z,  block.DIAMOND_BLOCK)
# print(mc.setBlock(x, y, z,  block.SEA_LANTERN))
# mc.setBlocks(x - 1, y, z - 1, x + 1, y, z + 1, block.SEA_LANTERN)

# mob1 = mc.spawnEntity(x, y, z, entity.CAT)
# print(mob1.setPos(x + 2, y, z))
# print(mob1.getPos())  # 動いてない

# mc.spawnParticle(x, y, z, 1, 1, 1, particle.DRAGON_BREATH, 0.2, 10000)

# ゲット系
# print(mc.getHeight(x, z))


# 怪しいブロック？？　何故か、時々エラーが出る
# result = mc.setBlock(69, 70, z - 1, block.JACK_O_LANTERN)
# for _i in range(10):
#     result = mc.setBlock(69 + _i, 70, z - 1, block.JACK_O_LANTERN)
#     print(result)
