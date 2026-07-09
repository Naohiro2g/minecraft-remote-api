# scripts

Manual helper scripts live here.

- `auth_smoke.py` - live hello/auth smoke with optional pairing, chat post,
  `world.setBlock`, `player.getPos`, and `player.setPos`

Run from the repo root, for example:

```bash
uv run python scripts/auth_smoke.py --help
uv run python scripts/auth_smoke.py 127.0.0.1 --get-pos
uv run python scripts/auth_smoke.py sb-dev.mc-remote.com --set-block 0 64 0 minecraft:stone
```
