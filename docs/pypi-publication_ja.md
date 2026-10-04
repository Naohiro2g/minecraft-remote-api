# PyPI.org公開の準備と実施

## 現在の状態（2026-10-05）

- human ownerがPyPI.orgの既存project `minecraft-remote-api` の管理権限と2FAを確認した。
- 次のGitHub Trusted Publisherを登録済みと報告した。
- Windows 11のGitなし入口（B8 wheel、uv、Jupyter）は成功報告を受領済み。
- **今回は準備まで。b8をPyPI.orgへ公開しない。**
- `PYPI_PUBLISH_ENABLED` は未設定で、PyPI.org用jobは無効。変数を有効化するのは公開承認後。
- matureへの移行はhuman ownerが承認済み。b9からPyPI.orgへpre-releaseとして公開する（knowledge `2026-10-05-03`）。実際の公開はgateの公開承認後。

| Trusted Publisherの項目 | 登録値 |
| --- | --- |
| Repository owner | `Naohiro2g` |
| Repository name | `minecraft-remote-api` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

登録先はPyPI.orgのproject管理画面 → **Publishing**。
API tokenを作成したりGitHub Secretsへ保存したりする必要はない。
[PyPI公式の登録手順](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)を参照。

## 1. GitHub側の準備

[repositoryのEnvironments](https://github.com/Naohiro2g/minecraft-remote-api/settings/environments)にenvironment `pypi` を作成済み。
公開jobの `environment: pypi` は、PyPI側の登録値と一致させる。

2026-10-05のprovider API確認ではrequired reviewer／deployment branch policyは未設定。
environmentの存在と公開の保護設定は別なので、現在の保護状態を確認しておく。

承認者を設定する場合はhuman release ownerを指定する。
本人がworkflowを開始して本人が承認する運用なら、自分の実行を承認できる設定にする。

準備段階ではrepository variable `PYPI_PUBLISH_ENABLED` を未設定、または `false` のままにする。
登録済みTrusted Publisherだけでは、このworkflowはPyPIへ公開しない。

## 2. 公開承認後に有効化する

ここから先は、公開承認後の手順。今回は実施しない。

[Actions variables](https://github.com/Naohiro2g/minecraft-remote-api/settings/variables/actions)で、
repository variableを次の値にする。

| Name | Value |
| --- | --- |
| `PYPI_PUBLISH_ENABLED` | `true` |

これは公開の有効化設定で、credentialではない。API tokenは使わない。

## 3. 新しい版の通常公開

approved candidateをmainへ統合し、そのcommitへtagを付け、GitHub Releaseを公開する。
詳しい手順は [PUBLISHING.md](../PUBLISHING.md) §1〜§4。

tagが指すcommitに、PyPI.org用jobを含む `release.yml` が必要。
公開済みtagは付け替えない。

`release: published` → candidateのpromote → TestPyPIと、設定が有効な場合のPyPI.org公開へ進む。
共通の`prepare-publication` jobがGitHub Releaseからwheel／sdist／manifestを取得し、tagのsource commit・version・SHA-256を照合する。
両indexのpublish jobは、この検証済みartifactを使う。
既存Releaseの成果物を使い、publish jobでbuildは行わない。

## 4. 既存Releaseを指定して公開する場合

新しい版の通常公開とは別に、mainのworkflowから公開済みReleaseのassetを送る経路がある。
対象tagはhuman ownerが承認したものを指定する。

例（対象版の公開が承認済みで、GitHub Releaseも存在する場合）:

```bash
gh workflow run release.yml --repo Naohiro2g/minecraft-remote-api --ref main -f tag=v2320.0.0b9 -f channel=pypi
```

UIでは [Actions → Release](https://github.com/Naohiro2g/minecraft-remote-api/actions/workflows/release.yml) →
**Run workflow** → branch `main` → 対象tag → channel `pypi` とする。

この経路ではpromoteとTestPyPI jobをskipし、PyPI.org jobだけを実行する。
共通の`prepare-publication`は実行する。b8以前のbetaはPyPI.org jobの対象外。
公開済みReleaseと照合し、manifestのsource／version／digestが合わなければupload前に停止する。
有効化変数が未設定／falseならPyPI jobもskipする。その場合は公開成功ではない。

## 5. 公開結果を確認する

Actionsの **Publish to PyPI.org** と **Verify the PyPI.org files match the Release assets** がsuccessであることを確認する。
後者はPyPI JSON APIでwheel／sdistのSHA-256とbytesをRelease assetへ照合し、yank状態も確認する。

freshなuv projectで、公開した版を明示して取得する。以下は公開済みb9を検証する場合の例:

```powershell
uv init --python 3.13 mc-pypi-check
cd mc-pypi-check
uv add "minecraft-remote-api==2320.0.0b9"
uv run python -c "from mc_remote import Minecraft; from importlib.metadata import version; print(version('minecraft-remote-api')); print(Minecraft.__name__)"
```

期待出力は `2320.0.0b9` と `Minecraft`。GitHub wheel URLやTestPyPIのindex設定を入れず、PyPI.orgから取得する。

betaはexact-pinで選ぶ。無指定の取得と区別する。
公開後の退避はyank、修正の出し直しは新しい版番号を使う。詳細はPUBLISHING.md §5.3。
同一indexの同じfile名を異なる内容で置換できない。別indexに未公開の版は、既存の検証済みbytesをそのまま公開できる。

## 6. knowledgeへ返す情報

公開対象のtag／source commit、workflow commit／run URL、PyPI release URL、
wheel／sdistのbytes／SHA-256、exact-pin取得結果を返す。
準備段階の今回は、Trusted Publisher登録・Windows結果・job無効の状態だけを返す。

[uv公式のpublish案内](https://docs.astral.sh/uv/guides/package/)と
[PyPI公式のTrusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)も参照。
