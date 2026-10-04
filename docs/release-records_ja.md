# リリースごとの確認記録

リリースごとの成果物と確認結果を記録します。
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

## b8 / protocol 23.2 GitHub prerelease 確認（released）

`2320.0.0b8`は2026-10-03に公開したprotocol `23.2.0`のGitHub prereleaseです。
entity lifecycle、ParticleSpec、サウンド2 method、短いimport、`pygame` extraを追加しました。
TestPyPIにも公開済みで、PyPI.orgには公開していません。

- release: [`v2320.0.0b8`](https://github.com/Naohiro2g/minecraft-remote-api/releases/tag/v2320.0.0b8)
- tag target: `52d35f5304e62f465c1f47ab47c00fe9bcf62470`（公開時に`main`へfast-forward統合）
- prerelease=true、draft=false、Latest非対象
- exact compatibility set: `b8-integrated-artifact-set-1`
- 対応Minecraft: Java版 `1.21.11`。実機確認は通常devのPaper `1.21.11-132`で実施

公開Release asset:

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `minecraft_remote_api-2320.0.0b8-py3-none-any.whl` | 195,068 | `dcedff010feac0d5df24ff85dd84b321fb819f78563c39431ac32d9d75bc0180` |
| `minecraft_remote_api-2320.0.0b8.tar.gz` | 188,775 | `9d56d92b10936787e1eebc1cf85a521ea19aa2e57b391f474eb695b0ba3fad32` |
| `manifest.json` | 681 | `7aa2868f1d9fc75b414cb37ac8d0886d390691d7b169f060def99248e29d9fc0` |

- [公開前CI run `37113256520`](https://github.com/Naohiro2g/minecraft-remote-api/actions/runs/37113256520)はPython 3.10〜3.13とbuildがsuccess。
  wheel／sdistが凍結したcandidateのbytes／SHA-256に一致してから公開しました。
- [release workflow `37113530599`](https://github.com/Naohiro2g/minecraft-remote-api/actions/runs/37113530599)の
  `promote`／`publish-testpypi`がsuccess。公開後にRelease assetを実downloadし、bytes／SHA-256を再照合しました。
- [TestPyPI `2320.0.0b8`](https://test.pypi.org/project/minecraft-remote-api/2320.0.0b8/)のwheel／sdistも同じbytes／SHA-256、yanked=falseを確認。
- 公開manifestはschema `mc-remote.release-manifest` v1、release tag／source commitは上記identity。
  `bundled_wirescope_source_commit`は`df34849d2502a498a06c5fe07a91d03e925124eb`です。
- 同梱WireScopeはScratchのこのsourceから生成し、ZIPは83,746 bytes／
  `4cb349894b71d61d7ca143d8362a5b79deb1810e1d7a9e31ad30e29bfe370a07`、manifestは2,321 bytes／
  `45d56d5012c2c0b21631597e160363d93bcf3e736b74cc0b8a1041afc8101413`に一致。
- owner fixture: `scratch-editor@054a3af017f1abb8cc01cf85b3bc83181e648e19`の
  `mc-remote/protocol/test/fixtures/entity-particle-v23.2.json`、36,481 bytes、111 case、
  SHA-256 `ca636b4a2685ea67f24d8e7931e3d30a84e7cec872bb5c5d2eadd178cdac39f2`。
- exact compatible McRemote: [`v1.21.11-2320.0.0b8`](https://github.com/Naohiro2g/McRemote/releases/tag/v1.21.11-2320.0.0b8)@`8f13b2f4dc14798899ab5153a0a647c2dea7aa18`
- exact compatible Scratch: [`v2320.0.0b8`](https://github.com/Naohiro2g/scratch-editor/releases/tag/v2320.0.0b8)@`691576f60b7f0824e1753bd6823901d01fbe2422`。
  Python同梱WireScopeは、coordinatorが同じZIP bytesを確認した上記`df34849`由来のままです。

正式な [b8 dev live record](https://github.com/Naohiro2g/mc-remote-knowledge/blob/e3812c25768a8c69b54e3c336eb7b1cdeb3243fc/14-evidence/records/2026-10-03-b8-dev-live_ja.md) に、
b7からb8への実token継続、Python代表往復、WireScope表示、2-playerの描画とサウンドの確認を記録しています。
Python segmentではentity lifecycle、ParticleSpec、`playSound`、`getBlock`と復元、`playBlockSound`の5 kind、
3D graphの81往復、無印resource ID、短いimportを確認しました。

knowledgeの [b8 gate close記録](https://github.com/Naohiro2g/mc-remote-knowledge/blob/e3812c25768a8c69b54e3c336eb7b1cdeb3243fc/00-hub/release-gate-notes_ja.md)
（2026-09-30節）では、human ownerの判断で2026-10-03にCLOSEDです。
搬送素材は [正式artifact一覧](https://github.com/Naohiro2g/mc-remote-knowledge/blob/e3812c25768a8c69b54e3c336eb7b1cdeb3243fc/14-evidence/artifacts/2026-10-03-b8-dev-live/INVENTORY_ja.md) に収容し、
Python原本は`d0e4e085fafba41177e0ed19a82b4d1e1915d49a`での全文・SHA-256一致を確認して整理しました。

WindowsでのMinecraft操作、Paper 26.x、capacity／soak／rollback、正確な可聴距離・減衰曲線・音高の測定は未確認です。
Bedrock（Geyser経由）ではdustの大きさが変わらない制限があります。
公開後の2026-10-05に、Windows 11のGitなし入口ルート（uv `0.12.23`、B8 wheelの導入、Jupyterでのimport）を
問題なく完了したとのhuman ownerの報告を受領しました。[公開wheelを使う手順](windows-b8-entry_ja.md) の結果を
b9のPyPI遷移ゲート④のWindows検証材料へ引き継ぎます。mature判定はhuman ownerが行います。
