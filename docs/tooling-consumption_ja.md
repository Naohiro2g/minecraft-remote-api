# 共有fixtureと同梱WireScopeの取り込み

Pythonが使う共有TypeScriptのsourceは、[minecraft-remote-tooling](https://github.com/Naohiro2g/minecraft-remote-tooling) にあります。
所有・移管の判断はknowledgeの`10-protocol/protocol-tooling-migration-plan_ja.md`と
DECISIONS `2026-10-05-01/02`を参照してください。この文書はPython側の取り込み手順です。

## 共有fixture

`tests/fixtures/*.source.json`の`repository`、`commit`、`path`が取得元です。
共有fixtureは次の7件です。`chat-event-compat-v23.2.json`はb9で追加したものです。

| Python側のfile | tooling側のpath |
| --- | --- |
| `sign-v23.json` | `packages/protocol/test/fixtures/sign-v23.json` |
| `events-v23.json` | `packages/protocol/test/fixtures/events-v23.json` |
| `direction-lightning-v23.1.json` | `packages/protocol/test/fixtures/direction-lightning-v23.1.json` |
| `entity-particle-v23.2.json` | `packages/protocol/test/fixtures/entity-particle-v23.2.json` |
| `chat-event-compat-v23.2.json` | `packages/protocol/test/fixtures/chat-event-compat-v23.2.json` |
| `display-alias-v1.json` | `packages/live/test/fixtures/display-alias-v1.json` |
| `station-attach-v1.json` | `packages/live/test/fixtures/station-attach-v1.json` |

1. ownerが発行した固定commitからfileを取得する。JSONの再整形や改行変換をせず、bytesのまま保存する。
2. ownerのbytes／SHA-256と照合し、fixtureとsidecarを更新する。`branch`は参考情報であり、取得は`commit`に固定する。
3. 対応するconsumer testのsource pin／digestも更新する。移管だけの場合は、取り込み前後のfixture本体がbyte一致することを確認する。
4. `tests/test_b6.py`、`test_b7.py`、`test_b8_fixture.py`、`test_b9_fixture.py`、
   `test_wirescope.py`、`test_wirescope_station_contract.py`を実行する。

`observer-session-lifecycle.ndjson`などPython自身が作るfixtureは、この7件に含めません。
契約caseの追加と取得元の移管は、別commitにします。

## 同梱WireScope

ownerの成功したCI runから`wirescope-app.zip`と`wirescope-app.manifest.json`を取得します。
CI artifactのID、source commit、providerのartifact ZIP digestを照合したうえで、
各fileのbytes／SHA-256をownerのcandidate manifestと比較します。
最新版のbranchからその都度作り直して、凍結したcandidateへ混ぜることは避けます。

更新する箇所は次のとおりです。

- `mc_remote/_wirescope_app/`のZIPとdetached manifestを、検証した組で置き換える。
- `_wirescope_app.py`と`check_wirescope_wheel.py`のbytes／SHA-256を揃える。
- `_wirescope_artifact.py`のrepository／subdirectory、`pyproject.toml`とwheel checkerの対応source URL、testのsource pinを揃える。
- ZIP内の`LICENSE`／`NOTICE`と`LICENSES/`の同梱fileがbyte一致することを確認する。ownerのnoticeが同一なら、文面を独自に書き換えない。

PythonのCIが生成する`manifest.json`の`bundled_wirescope_source_commit`は、
同梱detached manifestの`source.commit`から取得します。Pythonのcommitとは別の値です。

移管だけの比較では、移管直前の同じ機能を持つsourceから作ったZIPの内部file名と全asset bytesを比べます。
source repository／commitが変わるdetached manifestは比較対象から外します。
公開b8から契約修正や列幅変更が入った分と、移管による分は分けて記録します。

```bash
uv lock --check
uv run --with pytest pytest -q
uv build
uv run python scripts/check_wirescope_wheel.py dist/*.whl
```

branch／commit、CI run／artifact ID、wheel／sdistと同梱pairのbytes／SHA-256、
fixtureとassetの比較結果を確認票へ返します。tag／releaseやshared環境の操作は、別の実施票に従います。
