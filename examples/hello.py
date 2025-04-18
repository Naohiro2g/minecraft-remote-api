import param_mc_remote as param
from param_mc_remote import PLAYER_ORIGIN as PO
from param_mc_remote import block
from mc_remote.minecraft import Minecraft

# Connect to minecraft and open a session as player with origin location
mc = Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR)
mc.setPlayer(param.PLAYER_NAME, PO.x, PO.y, PO.z)

mc.postToChat("Hello, Minecraft Server!!")
mc.setBlock(5, 68, 5, block.GOLD_BLOCK)
mc.setBlocks(8, 63, 8, 8, 68, 8, block.SEA_LANTERN)
