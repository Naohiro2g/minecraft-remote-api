# PyPI.orgへの公開

通常公開・再実行・公開結果の照合に使う手順です。
公開の判断と対象identityはknowledgeの指示に従い、human ownerが承認します。
実施済みの結果は [公開確認記録](release-records_ja.md) を参照してください。

## Trusted Publisher

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

次の保護を設定します。

- Required reviewer: human release owner（`Naohiro2g`）
- Prevent self-review: OFF（本人が開始したworkflowを本人が承認できる）
- Allow administrators to bypass configured protection rules: OFF
- Deployment policy: tag `v*`のみ

準備段階ではrepository variable `PYPI_PUBLISH_ENABLED` を未設定、または `false` のままにする。
登録済みTrusted Publisherだけでは、このworkflowはPyPIへ公開しない。

## 2. 公開承認後に有効化する

human ownerの公開承認後に有効化します。

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
PyPIのjobが承認待ちになったら、human ownerが実行画面の **Review deployments → pypi → Approve and deploy** で承認する。

## 4. 既存Releaseを指定して公開する場合

新しい版の通常公開とは別に、公開済みtagのworkflowから既存Releaseのassetを送る経路がある。
対象tagはhuman ownerが承認したものを指定する。

`<version>`を承認済みの対象版へ置き換えます。GitHub Releaseも存在することを確認してください。

```bash
gh workflow run release.yml --repo Naohiro2g/minecraft-remote-api --ref v<version> -f tag=v<version> -f channel=pypi
```

UIでは [Actions → Release](https://github.com/Naohiro2g/minecraft-remote-api/actions/workflows/release.yml) →
**Run workflow**で公開済みtagを実行refに選び、同じ対象tagとchannel `pypi`を指定する。

environmentはtagからの実行だけを許可するので、`--ref main`ではPyPI jobを実行できない。
tagのworkflowを使うため、mainへ加えた修正はこの経路には反映されない。
workflowの修正が必要な場合は、次の公開版に取り込む扱いをcoordinatorと確認する。公開済みtagは動かさない。

この経路ではpromoteとTestPyPI jobをskipし、PyPI.org jobだけを実行する。
共通の`prepare-publication`は実行します。公開対象かどうかの判定はworkflowに従います。
公開済みReleaseと照合し、manifestのsource／version／digestが合わなければupload前に停止する。
有効化変数が未設定／falseならPyPI jobもskipする。その場合は公開成功ではない。

## 5. 公開結果を確認する

Actionsの **Publish to PyPI.org** と **Verify the PyPI.org files match the Release assets** がsuccessであることを確認する。
後者はPyPI JSON APIでwheel／sdistのSHA-256とbytesをRelease assetへ照合し、yank状態も確認する。

freshなuv projectで、公開した版を明示して取得する。以下は公開beta `2320.0.0b9` を検証する例です:

```powershell
uv init --python 3.13 mc-pypi-check
cd mc-pypi-check
uv add "minecraft-remote-api==2320.0.0b9"
uv run python -c "from mc_remote import Minecraft; from importlib.metadata import version; print(version('minecraft-remote-api')); print(Minecraft.__name__)"
```

期待出力は指定した版と`Minecraft`です。取得先はPyPI.orgにします。

betaはexact-pinで選ぶ。無指定の取得と区別する。
公開後の退避はyank、修正の出し直しは新しい版番号を使う。詳細はPUBLISHING.md §5.3。
同一indexの同じfile名を異なる内容で置換できない。別indexに未公開の版は、既存の検証済みbytesをそのまま公開できる。

## 6. knowledgeへ返す情報

公開対象のtag／source commit、workflow commit／run URL、PyPI release URL、
wheel／sdistのbytes／SHA-256、exact-pin取得結果を返す。

[uv公式のpublish案内](https://docs.astral.sh/uv/guides/package/)と
[PyPI公式のTrusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)も参照。
