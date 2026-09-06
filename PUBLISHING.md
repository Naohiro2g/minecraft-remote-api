# PyPI 公開手順 / Publishing to PyPI

`minecraft-remote-api` を [PyPI](https://pypi.org/project/minecraft-remote-api/) に公開・更新するための手順です。
このリポは **uv に全面移行**しました（ビルドバックエンド `uv_build`）。以下は uv を前提とします。
従来の Poetry 手順は、ロールバック用に末尾の付録に残します。

- パッケージ名: `minecraft-remote-api`
- モジュール名: `mc_remote`
- ビルドバックエンド: `uv_build`（`pyproject.toml` の `[build-system]`）
- 依存は `[project.dependencies]`（PEP 621 標準）に記載

> **貢献するだけなら公開は不要。** PR を出すのに build / publish は要りません。
> `uv sync` で開発環境を作り、コードを動かし／テストして push するだけです。
> 本書は「PyPI へ配布する人」向けです。
>
> **ベータ（bN）は PyPI に出しません。** `2200.0.0b5`（protocol 22.0.0 b5）は
> **GitHub の pre-release タグのみ**で配布します。Python API の tag は
> `v2200.0.0b5`、package は `minecraft-remote-api==2200.0.0b5` です。
> PyPI 公開は rc/stable 以降です。採番・配布チャンネルの正本は
> ナレッジ `10-protocol/versioning-design_ja.md`。

---

## 0. 事前準備（初回のみ）

### アカウントと API トークン

1. [PyPI](https://pypi.org/account/register/) と [TestPyPI](https://test.pypi.org/account/register/) のアカウントを作成（別々のアカウント／別々のトークン）。
2. API トークンを発行する。
   - PyPI: <https://pypi.org/manage/account/token/>
   - TestPyPI: <https://test.pypi.org/manage/account/token/>
3. トークンは `pypi-` で始まる文字列。**一度しか表示されない**ので安全な場所に保管する。

uv はトークンを `--token` 引数か環境変数で受け取ります（`~/.pypirc` は読みません）。

```bash
export UV_PUBLISH_TOKEN=pypi-XXXXXXXXXXXX          # 本番 PyPI 用
```

---

## 1. バージョンを上げる（必須）

PyPI は**同じバージョンで再アップロードできません**。公開のたびに必ず上げること。

`pyproject.toml` の `version` を編集します。

```toml
[project]
version = "2000.0.0"   # ← ここを更新
```

### バージョニング規則（重要）

採番は新スキーム（protocol 連動）に従う。**詳細・根拠はナレッジが正本**:
`mc-remote-knowledge` の `10-protocol/versioning-design_ja.md`。

- MC 1.21.11 対応の**改訂初版 = `2000.0.0`**（protocol 20.0.0 を fold）。
- 旧版（`〜1214.10.13`）はベータ扱いで仕切り直し。`2000 > 1214` なので素の
  `pip install` でも確実に新版が「最新」として配られる（epoch 不使用）。
- fold 規則: protocol `X.Y.Z` の数字を連結してメジャー番号にする（例 20.0.0 → `2000`）。
  右から patch・minor を各1桁、残り全部がメジャー。**minor / patch は 0–9 を維持**する。

README の Package Information のバージョンも合わせて更新すること。

---

## 2. 古いビルド成果物を掃除する（推奨）

```bash
rm -rf dist/
```

---

## 3. ビルド

```bash
uv build
```

`dist/` に wheel（`minecraft_remote_api-<version>-py3-none-any.whl`）と sdist（`.tar.gz`）が生成されます。

確認（中身に `mc_remote/` が入り、依存が宣言されているか）:

```bash
unzip -l dist/minecraft_remote_api-*-py3-none-any.whl | grep mc_remote
unzip -p dist/minecraft_remote_api-*-py3-none-any.whl '*/METADATA' | grep -iE '^Version:|^Requires-Dist:'
```

### b3 GitHub pre-release 確認

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

### b5 / protocol 22 GitHub pre-release 確認

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

### b6 / protocol 23 GitHub pre-release 確認（released）

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

### b7 / protocol 23.1 GitHub pre-release 確認（released）

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

---

## 4. TestPyPI で確認

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-YYYYYYYYYYYY
```

インストール確認（依存は本番 PyPI から取得させる）:

```bash
uv pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ \
               minecraft-remote-api
```

---

## 5. 本番 PyPI へ公開

```bash
uv publish                      # UV_PUBLISH_TOKEN を使う場合
# または
uv publish --token pypi-XXXXXXXXXXXX
```

---

## 6. 公開後の確認

1. プロジェクトページで新バージョンを確認: <https://pypi.org/project/minecraft-remote-api/>
2. クリーンな環境でインストール確認:

   ```bash
   uv pip install --upgrade minecraft-remote-api
   python -c "import mc_remote; print('ok')"
   ```

3. コミットしてタグを付け push:

   ```bash
   git add pyproject.toml README.md uv.lock
   git commit -m "Release <version>"
   git tag v<version>
   git push && git push --tags
   ```

---

## 7. GitHub Release を作成する

タグ push 後、GitHub Release を作成する。

```bash
gh release create v<version> \
  --title "v<version>" \
  --generate-notes \
  --prerelease            # bN／rcN のときのみ付ける。stable では省略する
```

- **`--draft` は使わない。** draft のままだと `release: published` イベントが発火せず、
  `.github/workflows/release.yml` による wheel／sdist／`manifest.json` の自動添付が動かない。
- `--prerelease` を付けると GitHub 側の「Latest」表示対象からも自動的に外れる（別途フラグ不要）。
- GitHub は tag／version 文字列から `prerelease` 状態を自動判定しない（自動認識は PyPI の
  PEP 440 のみ。`mc-remote-knowledge` `10-protocol/versioning-design_ja.md` §10.12）。`bN`／
  `rcN` のリリースで `--prerelease` を付け忘れると、`release.yml` の prerelease 整合チェックで
  失敗する。

---

## 8. wheel／sdist／manifest.json が Release Assets へ自動添付される（vNEXT 以降）

`v2301.0.0b7` までの GitHub prerelease には GitHub binary assets が一切添付されていない（本書の
各リリース節に記載の通り）。**次のリリースから**、`.github/workflows/release.yml` が
`release: published` イベントをtriggerに、wheel／sdist／`manifest.json` を同じ Release へ自動
添付する。**v2301.0.0b7 以前は遡及的に添付しない**（そのまま asset 無しで残る）。

### 処理内容（再build しない設計）

`release.yml` は **checkout も build もしない**。仕組みは次の通り。

1. release の tag が指す commit を API で解決する。
2. その commit に対応する、`.github/workflows/ci.yml` の成功済み run を検索する。
3. その run が生成した候補 artifact（wheel／sdist／`manifest.json`）を **そのまま** download
   する（bytes は一切加工しない）。
4. tag の version と候補 wheel の version が一致すること、`prerelease` フラグが version の
   `bN`／`rcN` サフィックスと整合すること、download した bytes の SHA-256 が候補 manifest の
   記録値と一致することを確認する。
5. `manifest.json` の `release_tag` フィールドだけを実際の tag 名へ更新する（wheel／sdist の
   bytes は無変更）。
6. wheel／sdist／`manifest.json` を Release へ添付する。

この設計は `mc-remote-knowledge` `DECISIONS_ja.md` `2026-09-07-01`（build要否はartifactの変更
有無で決まる。releaseというphase名やeventそのものでは決まらない）に従っている。release時点で
再buildすると、実際にtestした実体とRelease assetになる実体が食い違う余地が生まれるため、意図
的に避けている。

### 前提条件：tag作成前に、そのcommitで ci.yml が成功していること

`release.yml` は候補 artifact が既に存在することを前提にする。version bump した commit を
`main` へ push すれば（本書 §1〜§6 の通常の流れに既に従っていれば）`ci.yml` が自動的に候補
artifact を生成するので、通常は追加の作業は要らない。

候補 artifact の `retention-days` は 90 日（GitHub 既定上限）。それを超えて release 作成が
遅れた場合や、対応する `ci.yml` run が見つからない場合、`release.yml` は **rebuild へ
フォールバックせず**明確なエラーで停止する。復旧するには、該当 commit で `ci.yml` を再実行
（`gh workflow run ci.yml --ref <commit/branch>` 等）してから、あらためて release を作り直す。

### 失敗時の復旧

`release.yml` が失敗して停止した場合、原因を直してから GitHub Actions の
「Re-run failed jobs」で再実行できる（`gh release upload ... --clobber` を使っているため、
一部 asset が既に添付済みでも安全に再実行できる）。

### 成功後のインストール経路

成功すると、次の2経路が両方使えるようになる。

```bash
# 既存: tag から直接 build（変更なし）
uv pip install git+https://github.com/Naohiro2g/minecraft-remote-api.git@v<version>

# 新規: Release asset から直接 install
pip install https://github.com/Naohiro2g/minecraft-remote-api/releases/download/v<version>/minecraft_remote_api-<version>-py3-none-any.whl
```

### manifest.json

同じ Release へ、次の schema（`mc-remote-knowledge` `DECISIONS_ja.md` `2026-09-06-04` で
cross-repo共通に確定したもの）で `manifest.json` も添付される。

```json
{
  "schema": "mc-remote.release-manifest",
  "schema_version": 1,
  "release_tag": "v<version>",
  "source_commit": "<このrepoのcommit>",
  "bundled_wirescope_source_commit": "<同梱WireScopeの由来commit（scratch-editor）>",
  "artifacts": [
    { "role": "wheel", "kind": "https-file", "file": "...", "sha256": "..." },
    { "role": "sdist", "kind": "https-file", "file": "...", "sha256": "..." }
  ]
}
```

`bundled_wirescope_source_commit` は現状の vendoring 経路（scratch-editor の特定 commit を手作業
で pin して取り込む方式）の由来をそのまま記録するだけで、vendoring 自体の切り替えは今回対象外
（`2026-09-06-02`で「本統一が実装された後の切替対象」と明記された将来作業）。

---

## チートシート

毎回の流れ: **バージョンを上げる → `dist/` を掃除 → `uv build` → TestPyPI で確認 → `uv publish` → タグ付け**

| 作業 | コマンド |
| --- | --- |
| 開発環境（貢献者向け） | `uv sync` |
| ビルド | `uv build` |
| TestPyPI へ公開 | `uv publish --publish-url https://test.pypi.org/legacy/ --token <TOKEN>` |
| 本番 PyPI へ公開 | `uv publish --token <TOKEN>`（または `UV_PUBLISH_TOKEN`） |

---

## 付録: Poetry へのロールバック

uv 運用で問題が出た場合、ビルドバックエンドを Poetry に戻せます。`pyproject.toml` を以下に差し替える:

```toml
[project]
# dependencies は [project] に残したまま（PEP 621 標準なので Poetry 2.x も読む）

[tool.poetry]
packages = [{ include = "mc_remote", from = "." }]   # 配布名≠import名のため必須

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"
```

その後:

```bash
poetry lock          # poetry.lock を再生成
poetry build
poetry publish       # 公開
```

> 注: `mc_remote` は配布名（`minecraft-remote-api`）と import 名が異なるため、
> poetry-core では `[tool.poetry].packages` の明示が**必須**（無いとパッケージが空になる）。
> uv_build では `[tool.uv.build-backend]` の `module-name` / `module-root` が同じ役割を担う。
