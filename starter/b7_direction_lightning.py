"""Observe b7 direction and optionally request one full lightning strike."""

import param_mc_remote as param
from param_mc_remote import BUILD_ORIGIN as ORIGIN
from mc_remote.minecraft import Minecraft


LIGHTNING_POS = (10, 67, 5)


confirmation = input(
    "Type STRIKE to allow one damage-capable full lightning strike, "
    "or press Enter for direction only: "
)

with Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR) as mc:
    mc.setBuildOrigin(ORIGIN.x, ORIGIN.y, ORIGIN.z)
    original = mc.getDirection()
    try:
        current = mc.setDirection(1, 2, 3)
        print("canonical direction:", current)
    finally:
        mc.setDirection(*original)

    if confirmation == "STRIKE":
        mc.strikeLightning(*LIGHTNING_POS)
        print("full lightning requested at starter coordinate", LIGHTNING_POS)
    else:
        print("lightning skipped")
