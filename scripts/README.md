# 開発補助スクリプト

公開物の検査と手動の実機確認に使うスクリプトです。

- `auth_smoke.py`: hello／認証、pairing、chat、ブロック設置、player位置の確認
- `sync_catalog.py`: 実サーバーからcatalogを取得し、`mc_constants.py`と型補完を生成
- `check_wirescope_wheel.py`: 同梱WireScope、wheelのRECORD、license、対応sourceリンクの検査
- `b4_pose_wirescope_live.py`: pairingしたplayerのposeとWireScopeの確認
- `b7_wirescope_browser_e2e.py`: 同梱WireScopeをloopback stationで表示し、direction／lightningの成功・error応答を確認
- `b5_build_modes_live.py`: DEBUG／TRACE／FAST、flush、close、getBlocksの確認。変更するブロックを取得し、finallyで復元を試みる

repoのrootで実行します。実サーバーへ接続するものは、実施票の接続先と許可範囲に従ってください。

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
