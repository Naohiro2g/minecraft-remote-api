# scripts

Manual helper scripts live here.

- `auth_smoke.py` - live hello/auth smoke with optional pairing, chat post,
  `world.setBlock`, `player.getPos`, and `player.setPos`
- `sync_catalog.py` - live `catalog.get` fetch + cache + `mc_constants.py` /
  `mc_constants.pyi` projection. It generates from an actual server; the projection is
  never bundled or committed, and this repo does not fabricate catalog content.
- `check_wirescope_wheel.py` - verify the immutable WireScope pair, wheel
  `RECORD`, distribution license inventory, and corresponding-source link
- `b4_pose_wirescope_live.py` - run the retained b4 paired-player pose contract
  on protocol 22 through an isolated pairing session and WireScope app
- `b5_build_modes_live.py` - exercise DEBUG/TRACE/FAST, explicit flush, automatic
  close flush, and `getBlocks` against a real protocol 22 plugin; every touched
  block is captured first and restoration is attempted in `finally`

Run from the repo root, for example:

```bash
uv run python scripts/auth_smoke.py --help
uv run python scripts/auth_smoke.py 127.0.0.1 --get-pos
uv run python scripts/auth_smoke.py 127.0.0.1 --set-block 0 64 0 minecraft:stone

uv run python scripts/sync_catalog.py --help
uv run python scripts/sync_catalog.py 127.0.0.1 --out examples

uv run python scripts/check_wirescope_wheel.py dist/*.whl
uv run python scripts/b4_pose_wirescope_live.py
uv run python scripts/b5_build_modes_live.py 127.0.0.1 0 64 0
```
