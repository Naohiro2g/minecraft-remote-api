"""Directory-local environment settings for McRemote.

Copy this file to ``param_mc_remote.py``. The copy is ignored by Git, so a
private server address and a directory-specific build origin stay local.
"""

from mc_remote.vec3 import Vec3


ADRS_MCR = "sb.mc-remote.com"  # the official sandbox server
PORT_MCR = 25575

BUILD_ORIGIN = Vec3(2000, 0, 2000)
