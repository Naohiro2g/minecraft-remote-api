import param_mc_remote as param
from param_mc_remote import BUILD_ORIGIN as ORIGIN
from mc_constants import block, world_info
from mc_remote.minecraft import Minecraft


mc = Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR)
mc.setBuildOrigin(ORIGIN.x, ORIGIN.y, ORIGIN.z)

mc.postToChat("Completion is ready!")
mc.setBlock(6, world_info.Y_SEA + 5, 5, block.GOLD_BLOCK)
