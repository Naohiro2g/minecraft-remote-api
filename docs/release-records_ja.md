# リリースごとの確認記録（b3〜b7）

旧 `PUBLISHING.md` に置いていた、release ごとの確認手順と成果物の記録です。内容は当時のまま移しました。
現行の公開手順は [`PUBLISHING.md`](../PUBLISHING.md) を見てください。

## b3 GitHub pre-release 確認

`2100.0.0b3` は PyPI に publish しない。release gate では、少なくとも次を確認する。

```bash
uv --cache-dir /tmp/uv-cache run python tests/test_b1.py
uv --cache-dir /tmp/uv-cache run python tests/test_b2.py
uv --cache-dir /tmp/uv-cache run python tests/test_b3.py
uv --cache-dir /tmp/uv-cache build
unzip -p dist/minecraft_remote_api-2100.0.0b3-py3-none-any.whl '*/METADATA' | grep -iE '^Name:|^Version:|^Requires-Dist:'
```

実機確認は `scripts/auth_smoke.py` を使う。`token_key` / `sandbox` はローカル token-store key
であり、`hello.params` には送らない。権限検証用サーバーでは
`permission_denied` が token 破棄に繋がらないことも確認する。

b3 の `catalog.get` 実機確認は `scripts/sync_catalog.py` を使う。`catalogHash` が実値であること、
生成された `mc_constants.py` に接続先の block/entity/particle が namespace 付きで並ぶこと、
manifest と `~/.cache/mcremote/catalogs/<catalogHash>.json` が作られること、同じ catalog の
再同期では cache が使われることを確認する。projection は同梱せず、実機確認後も
`git status` に現れないことを確認する。

Python client repo には現時点で専用 lint 設定を置いていないため、b3 の Python 側 gate は
unit tests + build + live smoke を blocker とする。lint は設定追加時に gate へ組み込む。

## b5 / protocol 22 GitHub pre-release 確認

`2200.0.0b5`はprotocol 22最初のexact compatibility setであり、構造化block値に加えて
DEBUG／TRACE／FAST、bounded connection FIFO、`connection.flush`、自動flushを同じ
候補へ収容する。部分実装をb5 GREENとしない。

```bash
uv --cache-dir /tmp/uv-cache run --with pytest pytest -q
uv --cache-dir /tmp/uv-cache build
unzip -p dist/minecraft_remote_api-2200.0.0b5-py3-none-any.whl \
  '*/METADATA' | grep -iE '^Name:|^Version:|^Requires-Dist:'
```

deterministic gateでは、全modeのsetterが`None`、TRACEがsetter一回につき一回だけ待機、
FAST notificationに`id`が無いこと、mode transition fence、queue backpressure、
明示／正常closeのflush、WireScopeのrequest-id `null`／`connection.flush`投影を確認する。
plugin、Scratch、common WireScope artifactとのexact fixtureおよびreal-browser／live evidenceは
別gateとして記録する。

## b6 / protocol 23 GitHub pre-release 確認（released）

`2300.0.0b6`はprotocol 23最初のexact compatibility set（sign三操作`getSign`／`setSign`／
`updateSignLine`、`pickaxe_poke`、`mcr_eh_` entity handle、protocol 23 cleanup）。GitHub
prereleaseとして公開済み、PyPI／TestPyPIは非公開のまま。

- release: [`v2300.0.0b6`](https://github.com/Naohiro2g/minecraft-remote-api/releases/tag/v2300.0.0b6)
- tag target: `a30a37b15658da655fe1e3535a73fb0e80c06f56`（`main`と一致）
- prerelease=true、draft=false、Latest非対象
- GitHub binary assets: なし
- wheel: `minecraft_remote_api-2300.0.0b6-py3-none-any.whl`、173,301 bytes、
  SHA-256 `0887807f0d00f71fcb543caf16c3963b70580bf073b6a7576d7f274399a1877b`
- sdist: `minecraft_remote_api-2300.0.0b6.tar.gz`、178,483 bytes、
  SHA-256 `0507a10cbd6b31c2dd84ebff0034c5f72625ff1142d30f1c0d41e14d0ce2da3b`
- 独立クリーンチェックアウト2件からの再buildでwheel／sdist両方のSHA-256がbyte-for-byte一致
  （reproducibility確認済み）。全test 242/242 PASS
- exact compatible McRemote: `v1.21.11-2300.0.0b6@4e8f1ff1bd48bfa28c465f2dc24060fbb419317f`
- exact compatible Scratch／Bridge／WireScope: `v2300.0.0b6@df9264ec355dd722a848df46e96d4b0fc9340ca2`
- knowledge close: `mc-remote-knowledge@c3a14878660ce8dc9d02ec9861340e64b2050dea`
  （`00-hub/release-gate-notes_ja.md`「2026-08-27 b6横断release gate（CLOSED）」、
  `10-protocol/b6-artifact-candidate-record_ja.md`）

## b7 / protocol 23.1 GitHub pre-release 確認（released）

`2301.0.0b7`はdirection四methodとdamage-capableなfull lightningを追加する
protocol `23.1.0`のGitHub prereleaseである。PyPI／TestPyPIは非公開のまま。

- release: [`v2301.0.0b7`](https://github.com/Naohiro2g/minecraft-remote-api/releases/tag/v2301.0.0b7)
- tag target: `91a25d317c95570fd9d92b5e63a5f585a856eda3`（公開時の`main`と一致）
- prerelease=true、draft=false、Latest非対象
- GitHub binary assets: なし
- wheel: `minecraft_remote_api-2301.0.0b7-py3-none-any.whl`、196,970 bytes、
  SHA-256 `81540d22b1ee05d7b24bd2e6c9270a37a194c6c1ddc868148a8263624826d2ba`
- sdist: `minecraft_remote_api-2301.0.0b7.tar.gz`、203,313 bytes、
  SHA-256 `55a9915b7607e35e2c1f335561b65fcd38deff90fe49f5b56c65122665b37a0b`
- 全test 253/253 PASS、targeted WireScope／b7 test 112/112 PASS、clean buildを二回実行して
  wheel／sdistともbyte-for-byte一致
- owner fixture: `scratch-editor@773e2984132d82bb6e740d6458107fe42ef68a0a`
- fixture path: `mc-remote/protocol/test/fixtures/direction-lightning-v23.1.json`
- fixture SHA-256: `586d24bf40136eec31f1827f23ef5b317f15100a17a635d7fe9f165e0af40dce`
- fixture case ledger: 93 unique IDs
- bundled WireScope source: `scratch-editor@0be46fcfaca409a5ede10f592520d93e7c59ba15`
- exact compatible McRemote: `v1.21.11-2301.0.0b7@3d5f710db97f4b14613f7e0abaafd535701d1906`
- exact compatible Scratch／WireScope: `v2301.0.0b7@0be46fcfaca409a5ede10f592520d93e7c59ba15`
- live evidence: knowledge `14-evidence/records/2026-09-03-b7-direction-lightning-live_ja.md`
- knowledge close: `mc-remote-knowledge@5945a79b357d9bb8a14ddb942f30629d410f6c8d`
  （`00-hub/release-gate-notes_ja.md`「2026-09-02 b7横断release gate（CLOSED）」、
  `10-protocol/b7-artifact-candidate-record_ja.md`）

公開成果物の再現確認には、exact tag `v2301.0.0b7`のclean checkoutで次を使う。

```bash
uv lock --check
uv run --with pytest pytest -q tests/test_b7.py tests/test_b6.py tests/test_wirescope.py
uv run --with pytest pytest -q
uv build
uv run python scripts/check_wirescope_wheel.py \
  dist/minecraft_remote_api-2301.0.0b7-py3-none-any.whl
unzip -p dist/minecraft_remote_api-2301.0.0b7-py3-none-any.whl \
  '*/METADATA' | grep -iE '^Name:|^Version:|^Requires-Dist:'
```

同梱WireScopeの実browser確認には
`uv run python scripts/b7_wirescope_browser_e2e.py`でloopback stationへ接続し、
direction四methodと`world.strikeLightning`それぞれの成功／server error exchangeを確認する。

`world.strikeLightningEffect`はaliasを含めて公開しない。`world.strikeLightning`の
damage／fire／rod／copper／entity変化、visual／audio、event cancellation、後続tickは
deterministic client testからlive PASSを導かない。b7 live gateはcoordinator指定のexact setで
完了しており、記録済み結果を別serverへ一般化しない。

