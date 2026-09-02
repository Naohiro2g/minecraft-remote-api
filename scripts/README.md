# scripts

Manual helper scripts live here.

- `auth_smoke.py` - live hello/auth smoke with optional pairing, chat post,
  `world.setBlock`, `player.getPos`, and `player.setPos`
- `sync_catalog.py` - live `catalog.get` fetch + cache + `mc_constants.py` /
  `mc_constants.pyi` projection. It generates from an actual server; the projection is
  never bundled or committed, and this repo does not fabricate catalog content.
- `check_wirescope_wheel.py` - verify the immutable WireScope pair, wheel
  `RECORD`, distribution license inventory, and corresponding-source link
- `b4_pose_wirescope_live.py` - run the paired-player pose contract carried
  forward from b4, using protocol 22 DimensionKey fields, through an isolated
  pairing session and WireScope app
- `b7_wirescope_browser_e2e.py` - serve the exact bundled WireScope app over
  the loopback station and emit successful and server-error exchanges for all
  five b7 direction/lightning methods
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
uv run python scripts/b7_wirescope_browser_e2e.py
uv run python scripts/b5_build_modes_live.py 127.0.0.1 0 64 0
```
