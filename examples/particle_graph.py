"""Particleで y = 3 + 2 sin(r) の曲面を描く、有限の3D graphサンプル。"""

import math

from mc_remote.minecraft import Minecraft, ParticleSpec


def draw_graph(mc):
    # 単点requestを81回だけ送る。selfはpairingしたplayerだけに表示する。
    dust: ParticleSpec = {
        "particle_id": "minecraft:dust",
        "receiver": "self",
        "data": {"color": [64, 160, 255], "size": 1.0},
    }
    for x in range(-4, 5):
        for z in range(-4, 5):
            y = 3 + 2 * math.sin(math.hypot(x, z))
            mc.spawnParticle(x, y, z, 0, 0, 0, dust, 0, 1)


def main():
    import param_mc_remote as param

    with Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR) as mc:
        mc.setBuildOrigin(0, 0, 0)
        player = mc.getPos()
        mc.setDimension(player["dimension"])
        # origin=0で読んだ位置を使い、playerの足元を新しい原点にする。
        mc.setBuildOrigin(*(math.floor(value) for value in player["pos"]))
        draw_graph(mc)


if __name__ == "__main__":
    main()
