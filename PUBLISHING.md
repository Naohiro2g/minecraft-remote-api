# 公開手順 / Publishing

`minecraft-remote-api` を公開するための手順です。ビルドバックエンドは `uv_build`、手順はすべて uv を前提とします。

- パッケージ名: `minecraft-remote-api`（import 名: `mc_remote`）
- 依存は `[project.dependencies]`（PEP 621 標準）に記載
- 対応 Python: 3.11〜3.13（`requires-python = ">=3.11"`、上限は付けない。対応範囲は classifiers と CI matrix で示す）

> **貢献するだけなら公開は不要。** PR を出すのに build / publish は要りません。
> `uv sync` で開発環境を作り、コードを動かし／テストして push するだけです。

## 公開チャンネルの現状

採番・配布チャンネル・機構モードの正本はナレッジ `10-protocol/versioning-design_ja.md`（§10.4、§10.9）です。

| チャンネル | 状態 | 経路 |
| --- | --- | --- |
| GitHub Release（pre-release） | 正式な配布先 | `release.yml` が候補 artifact を Release asset へ昇格 |
| TestPyPI | **soak 中**（公開チャンネルの予行。DECISIONS `2026-09-26-03`） | `release.yml` の `publish-testpypi` job（Trusted Publishing） |
| PyPI.org | 新プロトコル版は未公開。無指定の取得は旧 stable（`1214.x`）のまま | mature 判定後に追加する |

API token による手作業の upload は正式経路にしません。

---

## 1. 全体の流れ

1. `pyproject.toml` の `version` を上げ、README の「現行バージョン」とインストール URL を合わせ、`uv lock` する。
2. `main` へ push する。`ci.yml` が Python 3.11〜3.13 で test し、候補 artifact（wheel／sdist／`manifest.json`）を作る。
3. tag を作って push する。
4. GitHub Release を作る（`--prerelease`、draft にしない）。
5. `release.yml` が動く。
   - `promote`：候補 artifact を再 build せずに Release asset へ添付する。
   - `publish-testpypi`：添付した asset と同じ bytes を TestPyPI へ publish する。
6. TestPyPI と GitHub Release の両方を確認する（§5）。

---

## 2. バージョンを上げる

PyPI／TestPyPI は**同じバージョンを二度と upload できません**（削除しても番号は消費済み）。公開のたびに必ず上げます。

```toml
[project]
version = "2301.0.0b7.post3"   # ← ここを更新
```

- 採番は protocol 連動の新スキーム。fold 規則（protocol `X.Y.Z` → メジャー番号）と接尾辞（`bN`／`rcN`）は versioning-design が正本。
- コードを変えずに公開物だけ差し替える場合は `.postN`（ドット区切り）を使う（DECISIONS `2026-09-07-03`）。

```bash
uv lock
uv lock --check
```

---

## 3. 候補 artifact（`ci.yml`）

`main` への push で `ci.yml` が動きます。

- `test` job：Python 3.11／3.12／3.13 の matrix で `uv lock --check` と pytest。
- `build-candidate` job：`uv build`、WireScope 同梱の検査、`manifest.json` 生成、workflow artifact `minecraft-remote-api-dist`（保持 90 日）として保存。

手元で同じ確認をする場合:

```bash
uv run --with pytest pytest -q
uv build
uv run python scripts/check_wirescope_wheel.py dist/*.whl
unzip -p dist/minecraft_remote_api-*-py3-none-any.whl '*/METADATA' | grep -iE '^Version:|^Requires-Python:|^Requires-Dist:'
```

---

## 4. tag と GitHub Release

```bash
git tag v<version>
git push origin v<version>
gh release create v<version> \
  --title "v<version>" \
  --generate-notes \
  --prerelease            # bN／rcN（.postN を含む）のときのみ。stable では省略する
```

- **`--draft` は使わない。** draft では `release: published` が発火せず、`release.yml` が動かない。
- GitHub は version 文字列から prerelease を自動判定しない（versioning-design §10.12）。`--prerelease` を付け忘れると `release.yml` の整合チェックで失敗する。

### `release.yml` の処理

`promote` job は **checkout も build もしません**（DECISIONS `2026-09-07-01`：artifact が変わらなければ検証済みのものを再利用する）。

1. tag が指す commit を API で解決する。
2. その commit で成功した `ci.yml` の run を探す。
3. 候補 artifact をそのまま download する。
4. tag と wheel の version の一致、`prerelease` フラグと接尾辞の整合、sha256 と候補 `manifest.json` の一致を確認する。
5. `manifest.json` の `release_tag` だけを実際の tag 名へ更新する。
6. wheel／sdist／`manifest.json` を Release へ添付する。

`publish-testpypi` job は、Release asset を download し、`manifest.json` の `release_tag`／`source_commit`／sha256 と照合してから、
`uv publish --trusted-publishing always` で TestPyPI へ出します。

### 注意：`release.yml` は tag が指す commit の内容で動く

`release: published` イベントは、`main` の最新ではなく **tag が指す commit にある `release.yml`** で実行されます
（`v2301.0.0b7.post2` で実際に踏んだ挙動）。公開済みの tag は動かさないので、`release.yml` の修正は次の版から効きます。

### 失敗時の復旧

| 失敗した箇所 | 復旧 |
| --- | --- |
| 一時的な失敗（network 等） | Actions の「Re-run failed jobs」。`--clobber` と `--check-url` により再実行は安全 |
| `promote` の手順自体のバグ | `main` で修正し、次の版（`.postN` 等）で出し直す |
| `publish-testpypi` の手順自体のバグ | `main` で修正し、`main` の `release.yml` を dispatch して既存 Release の asset を publish し直す（下記） |
| 対応する `ci.yml` run が見つからない（90 日超過等） | その commit で `ci.yml` を再実行（`gh workflow run ci.yml --ref <branch>`）してから Release を作り直す |

```bash
gh workflow run release.yml --ref main -f tag=v<version>
```

dispatch では `promote` は動かず、`publish-testpypi` だけが動きます。

---

## 5. TestPyPI（soak）

### 5.1 Trusted Publisher の登録（human owner、初回のみ）

TestPyPI の project `minecraft-remote-api` は既にあるので、project の管理画面「Publishing」から GitHub の Trusted Publisher を追加します。

| 項目 | 値 |
| --- | --- |
| Owner | `Naohiro2g` |
| Repository name | `minecraft-remote-api` |
| Workflow name | `release.yml` |
| Environment name | `testpypi` |

GitHub 側の environment `testpypi` は、最初の実行時に自動で作られます。承認者を付ける場合は、repo の Settings → Environments で設定します。

### 5.2 exact-pin で取得する（利用目的ごと）

pre-release は、無指定の取得では選ばれません。版を明示して取得します。

**学習者（hello）**：GitHub Release に添付した wheel を直接指定します。git は不要です。

```bash
uv init --python 3.13 mc-hello
cd mc-hello
uv add https://github.com/Naohiro2g/minecraft-remote-api/releases/download/v<version>/minecraft_remote_api-<version>-py3-none-any.whl
```

**beta tester（TestPyPI から取得）**：本 package だけを TestPyPI から取り、依存（`pygame-ce`）は PyPI.org から取ります。
プロジェクトの `pyproject.toml` に次を足します。

```toml
[[tool.uv.index]]
name = "testpypi"
url = "https://test.pypi.org/simple/"
explicit = true

[tool.uv.sources]
minecraft-remote-api = { index = "testpypi" }
```

```bash
uv add "minecraft-remote-api==<version>"
```

`explicit = true` の index は `[tool.uv.sources]` で指名した package にだけ使われます。TestPyPI にある同名の旧版や、
TestPyPI 上の無関係な package が依存の解決に混ざることはありません。

**OSS 開発者**：source checkout で開発します。

```bash
git clone https://github.com/Naohiro2g/minecraft-remote-api.git
cd minecraft-remote-api
uv sync --frozen
```

特定の版を再現する場合は `git checkout v<version>` してから `uv sync --frozen` します。

**無指定の取得が旧 stable のままであることの確認**：

```bash
uv init --python 3.13 check-default && cd check-default
uv add minecraft-remote-api --refresh
uv tree --depth 1      # 1214.x が選ばれていること
```

### 5.3 yank／unyank

yank は「無指定や範囲指定の解決から外す」操作です。`==` による exact-pin では yank 後も取得できます（PEP 592）。
削除ではないので、yank しても番号は消費されたままです。

- 操作：TestPyPI の project 管理画面 → Releases → 対象版の Options → Yank（理由を書く）。戻すときは同じ画面で Un-yank。
- 出し直し：同じ版番号は再 upload できない。修正版は `.postN` を上げて §1 の流れで出す。

yank の効果を確認するときは、**pre-release を許す範囲指定**で解決させます。無指定の解決はもともと pre-release を選ばないため、
yank の有無で結果が変わらず、確認になりません。§5.2 の TestPyPI 設定をしたプロジェクトで:

```bash
# yank 後：範囲指定では選ばれないこと（候補が他に無ければ解決に失敗する）
uv add "minecraft-remote-api>=2301.0.0b0" --prerelease allow --refresh
# yank 後：exact-pin では取得できること
uv add "minecraft-remote-api==<version>" --refresh
```

### 5.4 アカウントの記録

遷移ゲート③の記録として、次を human owner が記入します。

| 項目 | PyPI.org | TestPyPI |
| --- | --- | --- |
| project owner | （未記入） | （未記入） |
| 2FA | （未記入） | 確認済み（2026-09-26） |
| 2人目の maintainer | （未記入） | （未記入） |

---

## 6. PyPI.org（未実施）

mature への移行は、soak の記録を見て human owner が判定します。移行後は `release.yml` に PyPI.org 向けの publish job
（environment `pypi`、PyPI.org 側にも Trusted Publisher を登録）を足し、`bN`／`rcN` を pre-release として出します。

---

## 7. `manifest.json`

各 Release へ次の schema（DECISIONS `2026-09-06-04`）で添付されます。

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

`v2301.0.0b7` までの Release には asset が添付されていません（遡及しない）。

---

## 付録

- リリースごとの確認記録（b3〜b7）：[`docs/release-records_ja.md`](docs/release-records_ja.md)

### Poetry へのロールバック

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

> 注: `mc_remote` は配布名（`minecraft-remote-api`）と import 名が異なるため、
> poetry-core では `[tool.poetry].packages` の明示が**必須**（無いとパッケージが空になる）。
> uv_build では `[tool.uv.build-backend]` の `module-name` / `module-root` が同じ役割を担う。
