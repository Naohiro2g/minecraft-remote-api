"""Place, observe, and clean up one sign."""

import param_mc_remote as param
from param_mc_remote import BUILD_ORIGIN as ORIGIN
from mc_remote import Minecraft


SIGN_POS = (8, 67, 5)


with Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR) as mc:
    mc.setBuildOrigin(ORIGIN.x, ORIGIN.y, ORIGIN.z)
    try:
        mc.setBlock(*SIGN_POS, "oak_sign", state={"rotation": "0"})
        mc.setSign(
            *SIGN_POS,
            front=[
                {"text": "McRemote", "color": "gold", "decorations": ["bold"]},
                "Hello, Minecraft",
                "Python sign",
                "Press Enter",
            ],
        )
        sign = mc.getSign(*SIGN_POS)
        print("front:", tuple(line.text for line in sign.front))
        input("Observe the sign in Minecraft, then press Enter to clean it up: ")
    finally:
        mc.setBlock(*SIGN_POS, "air")
