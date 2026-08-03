import param_mc_remote as param
from param_mc_remote import BUILD_ORIGIN as ORIGIN
from mc_remote.minecraft import Minecraft

# Before the first connection, temporarily uncomment the next line.
# from mc_constants import block


mc = Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR)
mc.setBuildOrigin(ORIGIN.x, ORIGIN.y, ORIGIN.z)

mc.postToChat("Hello, Minecraft from Python!")
mc.setBlock(5, 62 + 6, 5, "sea_lantern")
