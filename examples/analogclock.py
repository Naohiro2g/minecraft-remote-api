# from: https://github.com/martinohanlon/minecraft-clock
# www.stuffaboutcode.com
# Raspberry Pi, Minecraft Analogue Clock

import datetime
import math
import time

import axis_flat
from mc_remote.minecraft import Minecraft
from mc_remote.vec3 import Vec3
import param_mc_remote as param
from param_mc_remote import PLAYER_ORIGIN as po
from param_mc_remote import block


BLOCK_HOUR_HAND = block.IRON_BLOCK
LENGTH_HOUR_HAND = 0.65
BLOCK_MINUTE_HAND = block.RED_WOOL
LENGTH_MINUTE_HAND = 0.9
BLOCK_SECOND_HAND = block.SEA_LANTERN
LENGTH_SECOND_HAND = 1.1
BLOCK_RING = block.GLOWSTONE


def drawCircle(mc, x0, y0, z, radius, blockType=BLOCK_RING):
    f = 1 - radius
    ddf_x = 1
    ddf_y = -2 * radius
    x = 0
    y = radius
    mc.setBlock(x0, y0 + radius, z, blockType)
    mc.setBlock(x0, y0 - radius, z, blockType)
    mc.setBlock(x0 + radius, y0, z, blockType)
    mc.setBlock(x0 - radius, y0, z, blockType)

    while x < y:
        if f >= 0:
            y -= 1
            ddf_y += 2
            f += ddf_y
        x += 1
        ddf_x += 2
        f += ddf_x
        mc.setBlock(x0 + x, y0 + y, z, blockType)
        mc.setBlock(x0 - x, y0 + y, z, blockType)
        mc.setBlock(x0 + x, y0 - y, z, blockType)
        mc.setBlock(x0 - x, y0 - y, z, blockType)
        mc.setBlock(x0 + y, y0 + x, z, blockType)
        mc.setBlock(x0 - y, y0 + x, z, blockType)
        mc.setBlock(x0 + y, y0 - x, z, blockType)
        mc.setBlock(x0 - y, y0 - x, z, blockType)


def drawLine(mc, x, y, z, x2, y2, blockType):
    """Brensenham line algorithm"""
    steep = 0
    dx = abs(x2 - x)
    if (x2 - x) > 0:
        sx = 1
    else:
        sx = -1
    dy = abs(y2 - y)
    if (y2 - y) > 0:
        sy = 1
    else:
        sy = -1
    if dy > dx:
        steep = 1
        x, y = y, x
        dx, dy = dy, dx
        sx, sy = sy, sx
    d = (2 * dy) - dx
    for _i in range(0, dx):
        if steep:
            mc.setBlock(y, x, z, blockType)
        else:
            mc.setBlock(x, y, z, blockType)
        while d >= 0:
            y += sy
            d -= (2 * dx)
        x += sx
        d += (2 * dy)
    mc.setBlock(x2, y2, z, blockType)


def findPointOnCircle(cx, cy, radius, angle):
    x = cx + math.sin(math.radians(angle)) * radius
    y = cy + math.cos(math.radians(angle)) * radius
    return (int(x + 0.5), int(y + 0.5))


def getAngleForHand(positionOnClock):
    angle = 360 * (positionOnClock / 60.0)
    return angle


def drawHourHand(mc, clockCenter, radius, hours, minutes, clear=False):
    if hours > 11:
        hours = hours - 12
    angle = getAngleForHand(int((hours * 5) + (minutes * (5.0 / 60.0))))
    hourHandEnd = findPointOnCircle(clockCenter.x, clockCenter.y, radius * LENGTH_HOUR_HAND, angle)
    blockType = block.AIR if clear else BLOCK_HOUR_HAND
    drawLine(mc, clockCenter.x, clockCenter.y, clockCenter.z - 1, hourHandEnd[0], hourHandEnd[1], blockType)


def drawMinuteHand(mc, clockCenter, radius, minutes, clear=False):
    angle = getAngleForHand(minutes)
    minuteHandEnd = findPointOnCircle(clockCenter.x, clockCenter.y, radius * LENGTH_MINUTE_HAND, angle)
    blockType = block.AIR if clear else BLOCK_MINUTE_HAND
    drawLine(mc, clockCenter.x, clockCenter.y, clockCenter.z, minuteHandEnd[0], minuteHandEnd[1], blockType)


def drawSecondHand(mc, clockCenter, radius, seconds, clear=False):
    angle = getAngleForHand(seconds)
    secondHandEnd = findPointOnCircle(clockCenter.x, clockCenter.y, radius * LENGTH_SECOND_HAND, angle)
    blockType = block.AIR if clear else BLOCK_SECOND_HAND
    drawLine(mc, clockCenter.x, clockCenter.y, clockCenter.z + 1, secondHandEnd[0], secondHandEnd[1], blockType)


def drawClock(mc, clockCenter, radius, time):
    drawCircle(mc, clockCenter.x, clockCenter.y, clockCenter.z, radius)
    drawHourHand(mc, clockCenter, radius, time.hour, time.minute)
    drawMinuteHand(mc, clockCenter, radius, time.minute)
    drawSecondHand(mc, clockCenter, radius, time.second)


def updateTime(mc, clockCenter, radius, lastTime, time):
    # draw hour and minute hand
    if lastTime.minute != time.minute:
        # clear hour hand
        drawHourHand(mc, clockCenter, radius, lastTime.hour, lastTime.minute, clear=True)
        # new hour hand
        drawHourHand(mc, clockCenter, radius, time.hour, time.minute)

        # clear hand
        drawMinuteHand(mc, clockCenter, radius, lastTime.minute, clear=True)
        # new hand
        drawMinuteHand(mc, clockCenter, radius, time.minute)

    # draw second hand
    if lastTime.second != time.second:
        # clear hand
        drawSecondHand(mc, clockCenter, radius, lastTime.second, clear=True)
        # new hand
        drawSecondHand(mc, clockCenter, radius, time.second)


def big_clock(mc, clockCenter=Vec3(0, axis_flat.AXIS_Y_V_ORG, 0), radius=20):
    # clear area
    mc.setBlocks(clockCenter.x - radius, clockCenter.y - radius, clockCenter.z - 1,
                 clockCenter.x + radius, clockCenter.y + radius, clockCenter.z + 1, block.AIR)

    mc.postToChat(f"Analog Clock started at: ({clockCenter.x}, {clockCenter.y}, {clockCenter.z})")

    lastTime = datetime.datetime.now()
    drawClock(mc, clockCenter, radius, lastTime)
    while True:
        # this thing runs forever in thread
        nowTime = datetime.datetime.now()
        updateTime(mc, clockCenter, radius, lastTime, nowTime)
        lastTime = nowTime
        time.sleep(0.25)


def main():
    # Connect to minecraft and open a session as player with origin location
    mc = Minecraft.create(address=param.ADRS_MCR, port=param.PORT_MCR)
    mc.setPlayer(param.PLAYER_NAME, po.x, po.y, po.z)

    big_clock(mc, Vec3(0, axis_flat.AXIS_Y_V_ORG, -45), radius=16)


if __name__ == "__main__":
    main()
