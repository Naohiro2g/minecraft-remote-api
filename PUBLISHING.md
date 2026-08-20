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
