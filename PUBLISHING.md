# 公開手順 / Publishing

`minecraft-remote-api` を公開するための手順です。ビルドバックエンドは `uv_build`、手順はすべて uv を前提とします。

- パッケージ名: `minecraft-remote-api`（import 名: `mc_remote`）
- 依存は `[project.dependencies]`（PEP 621 標準）に記載
- 対応 Python: 3.10〜3.13（`requires-python = ">=3.10"`、上限は付けない。対応範囲は classifiers と CI matrix で示す。3.10 は iPad の Pythonista 3 のため。DECISIONS `2026-09-27-02`）

> **貢献するだけなら公開は不要。** PR を出すのに build / publish は要りません。
> `uv sync` で開発環境を作り、コードを動かし／テストして push するだけです。

## 公開チャンネルの現状

採番・配布チャンネル・機構モードの正本はナレッジ `10-protocol/versioning-design_ja.md`（§10.4、§10.9）です。

| チャンネル | 状態 | 経路 |
| --- | --- | --- |
| PyPI.org | 利用者向けの標準配布先 | `publish-pypi` job、environment `pypi`でhuman ownerが承認 |
| GitHub Release | 成果物とmanifestの配布・照合先 | 候補artifactを再buildせず添付 |
| TestPyPI | 公開の予行用 | 現行workflowは公開時に自動実行。手動化は後続作業 |

PyPI.orgのTrusted Publisher（`release.yml`／environment `pypi`）はhuman ownerが登録済みです（2026-10-05）。
公開・取得確認は [公開確認記録](docs/release-records_ja.md) に記録しています。設定と実施手順は [PyPI.org公開ガイド](docs/pypi-publication_ja.md) を参照してください。

API token による手作業の upload は正式経路にしません。

---

## 1. 全体の流れ

1. `pyproject.toml` の `version` を上げ、`uv lock` する。READMEの取得先は公開済み版のままにし、新版の公開時に更新する。
2. candidateをpushし、PRまたは`workflow_dispatch`で`ci.yml`を実行する。Python 3.10〜3.13のtestと候補 artifact（wheel／sdist／`manifest.json`）を確認し、公開承認後に`main`へ統合する。
3. tag を作って push する。
4. GitHub Release を作る（`--prerelease`、draft にしない）。
5. `release.yml` が動く。
   - `promote`：候補 artifact を再 build せずに Release asset へ添付する。
   - `prepare-publication`：Release assetのsource／version／SHA-256を検証し、両index用のartifactを共通に用意する。
   - `publish-testpypi`：検証済みの同じ bytes を TestPyPI へ publish する。
   - `publish-pypi`：公開対象のtagで`PYPI_PUBLISH_ENABLED=true`の場合、同じ bytes を PyPI.org へ publish し、bytes／SHA-256を照合する。
6. PyPI.orgの公開結果とGitHub Releaseの成果物を確認する（§5）。

---

## 2. バージョンを上げる

PyPI／TestPyPIでは、**同じindexの既出file名を異なる内容でuploadできません**（削除しても再利用できません）。
内容を変えて出し直す場合はversionを上げます。別indexに初めて公開する場合は、既存の検証済みwheel／sdistを同じ版で使えます。
同じbytesの再実行は`--check-url`で既存fileを照合してskipします。

```toml
[project]
version = "2320.0.0b9"   # 例。実際の版はknowledgeの指示で決める
```

- 採番はprotocolに連動します。fold 規則（protocol `X.Y.Z` → メジャー番号）と接尾辞（`bN`／`rcN`）は versioning-design が正本。
- コードを変えずに公開物だけ差し替える場合は `.postN`（ドット区切り）を使う（DECISIONS `2026-09-07-03`）。

```bash
uv lock
uv lock --check
```

---

## 3. 候補 artifact（`ci.yml`）

`main` への push で `ci.yml` が動きます。
共有fixtureと同梱WireScopeを更新する場合は、[toolingからの取り込み手順](docs/tooling-consumption_ja.md) で取得元とbytesを確認します。

- `test` job：Python 3.10／3.11／3.12／3.13 の matrix で `uv lock --check` と pytest。
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

以下はbeta／rcを公開する例です。版と公開の扱いはknowledgeの指示に従います。

```bash
git tag v<version>
git push origin v<version>
gh release create v<version> \
  --title "minecraft-remote-api <version>" \
  --generate-notes \
  --latest=false \
  --prerelease            # bN／rcN（.postN を含む）のときのみ。stable では省略する
```

- **title は `minecraft-remote-api <version>`**（`<version>` は tag から先頭の `v` を除いた文字列。versioning-design §10.12.1、DECISIONS `2026-09-27-03`）。
  `release.yml` もこの形へ明示的に設定し直すので、GitHub の既定（tag 名）にはならない。

- **`--draft` は使わない。** draft では `release: published` が発火せず、`release.yml` が動かない。
- GitHub は version 文字列から prerelease を自動判定しない（versioning-design §10.12）。`--prerelease` を付け忘れると `release.yml` の整合チェックで失敗する。

### `release.yml` の処理

`promote` job は **checkout も build もしません**（DECISIONS `2026-09-07-01`：artifact が変わらなければ検証済みのものを再利用する）。

1. tag が指す commit を API で解決する。
2. その commit で成功した `ci.yml` の run を探す。
3. 候補 artifact をそのまま download する。
4. tag と wheel の version の一致を確認し、title を `minecraft-remote-api <version>` に設定する。`prerelease` フラグと接尾辞の整合、sha256 と候補 `manifest.json` の一致を確認する。
5. `manifest.json` の `release_tag` だけを実際の tag 名へ更新する。
6. wheel／sdist／`manifest.json` を Release へ添付する。

`prepare-publication` jobが、Release assetをdownloadし、`manifest.json`の`release_tag`／`source_commit`／SHA-256と
wheelのversionを照合します。TestPyPIとPyPI.orgは、この共通の検証済みartifactをdownloadし、
`uv publish --trusted-publishing always`で公開します。再buildしません。

### 注意：`release.yml` は tag が指す commit の内容で動く

`release: published`イベントは、tagが指すcommitにある`release.yml`で実行されます。
公開済みtagは動かさないので、workflowの修正は次の版から効きます。

### 失敗時の復旧

| 失敗した箇所 | 復旧 |
| --- | --- |
| 一時的な失敗（network 等） | Actions の「Re-run failed jobs」。`--clobber` と `--check-url` により再実行は安全 |
| `promote` の手順自体のバグ | `main` で修正し、次の版（`.postN` 等）で出し直す |
| asset検証／publishの手順自体のバグ | TestPyPIは`main`で修正してdispatch。PyPI.orgはtag限定のenvironment policyがあるため、[公開ガイド](docs/pypi-publication_ja.md#4-既存releaseを指定して公開する場合)の実行ref制限を確認する |
| 対応する `ci.yml` run が見つからない（90 日超過等） | その commit で `ci.yml` を再実行（`gh workflow run ci.yml --ref <branch>`）してから Release を作り直す |

既存Releaseの成果物をPyPI.orgへ送る場合は、[公開ガイド](docs/pypi-publication_ja.md#4-既存releaseを指定して公開する場合)に従い、
公開済みtagを実行refに選び、`channel=pypi`を明示します。
dispatchではpromoteを行わず、指定indexへ既存Releaseの検証済みassetを送ります。

---

## 5. PyPI.org（標準配布先）

### 5.1 公開の設定と承認

公開jobはGitHub Trusted Publishingを使います。repository variable `PYPI_PUBLISH_ENABLED=true`、
environment `pypi`の承認者、tag `v*`限定のdeployment policyを設定します。
未設定／falseの間は、Release公開・dispatchのどちらでもPyPI jobをskipします。

登録値、human ownerの承認、既存Releaseの再実行、公開後の照合は
[PyPI.org公開ガイド](docs/pypi-publication_ja.md)にまとめています。

### 5.2 利用者の取得

beta／rcは版を明示してPyPI.orgから取得します。以下は公開betaを指定した例です。
導入する版は [README](README.md) で確認してください。

```bash
uv init --python 3.13 mc-hello
cd mc-hello
uv add "minecraft-remote-api==2320.0.0b9"
uv run python -c "from mc_remote import Minecraft; print(Minecraft.__name__)"
```

OSS開発者はsource checkoutで`uv sync --frozen`して開発します。
特定の公開sourceを確認する場合は、そのReleaseのtagをcheckoutしてください。

### 5.3 yank／unyankと出し直し

yankは無指定や範囲指定の解決から外す操作です。exact-pinではyank後も取得できます。
対象indexのproject管理画面でReleases → 対象版 → Yankを選び、理由を記録します。
戻す場合はUn-yankを選びます。

版番号は消費されたままで、同じfile名を異なる内容で再uploadできません。
修正は新しい版番号で出し直し、変更したのがpackagingだけなら`.postN`を使います。
公開済みtagやassetを、異なる内容へ差し替えないでください。

予行でyankの効果を確認する場合は、対象が唯一の候補になる範囲を選び、
`--prerelease allow --refresh`を付けて解決します。exact-pinでの取得確認とは分けて記録します。

## 6. TestPyPI（予行用）

予行先への登録は、TestPyPIのproject管理画面のPublishingから行います。
GitHub Trusted Publisherはowner `Naohiro2g`、repository `minecraft-remote-api`、
workflow `release.yml`、environment `testpypi`を指定します。

既存Releaseで予行するときは、ActionsのRelease workflowに対象tagと`channel=testpypi`を指定します。
公開時の自動予行を手動のみに絞る方針は採用済みで、workflowの切り替えは後続作業です。

取得を試すprojectでは、本packageだけTestPyPIを使い、依存はPyPI.orgから取得します。

```toml
[[tool.uv.index]]
name = "testpypi"
url = "https://test.pypi.org/simple/"
explicit = true

[tool.uv.sources]
minecraft-remote-api = { index = "testpypi" }
```

`<version>`を予行対象の版へ置き換えます。

```bash
uv add "minecraft-remote-api==<version>"
```

owner・2FA・maintainer体制の運用記録はknowledgeへ返します。

## 7. manifest.json

GitHub Releaseにはwheel／sdistと次のmanifestを添付します。

```json
{
  "schema": "mc-remote.release-manifest",
  "schema_version": 1,
  "release_tag": "v<version>",
  "source_commit": "<このrepoのcommit>",
  "bundled_wirescope_source_commit": "<同梱WireScopeのsource commit>",
  "artifacts": [
    { "role": "wheel", "kind": "https-file", "file": "...", "sha256": "..." },
    { "role": "sdist", "kind": "https-file", "file": "...", "sha256": "..." }
  ]
}
```

公開source・成果物の照合結果は [公開確認記録](docs/release-records_ja.md)を参照してください。
