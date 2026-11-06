# tests/fixtures の取得元とLICENSEの範囲

このdirectoryには、異なる取得元・用途のfixtureが同居します。

## Protocol共有fixtureのcopy（7本）

- 固定元: `Naohiro2g/minecraft-remote-tooling@21a2a9a0aed8b4d9c715da46616aad86f1174b4c`。
- owner directory: `packages/protocol/test/fixtures/`。このdirectoryのfixtureに限ってMIT（knowledge `2026-10-23-01`）。
- 同梱の`LICENSE`はownerの`packages/protocol/test/fixtures/LICENSE`そのもの。1,070 bytes、SHA-256 `aa329a0bafc839b95124306141db13a381de45818bf629e983c44ea55ab5a7fb`。
- 下の7本は固定元から取得したbytesに一致する。JSONの再整形・case内容の変更はしていない。各`.source.json`がpath、commit、bytes、SHA-256を記録する。
- 今回はLICENSEの入ったsourceへ固定し直す更新。旧source、case成立時のknowledge contract、過去CIのidentityはsidecarに履歴として残す。

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `chat-event-compat-v23.2.1.json` | 32,384 | `eead244a7340c315cb63e1e77ede0fe9cf48162c06fedbeef36d941950d5000d` |
| `chat-event-compat-v23.2.json` | 32,382 | `670b0a86df1956c0e44c6986a0a2598caab32c7328804f9c703190e62e9dd727` |
| `direction-lightning-v23.1.json` | 20,367 | `586d24bf40136eec31f1827f23ef5b317f15100a17a635d7fe9f165e0af40dce` |
| `entity-particle-v23.2.1.json` | 36,483 | `0319ff8373a96798cf5e9e421a804729fd33a0fa53e96adc12c93ed7994777ae` |
| `entity-particle-v23.2.json` | 36,481 | `ca636b4a2685ea67f24d8e7931e3d30a84e7cec872bb5c5d2eadd178cdac39f2` |
| `events-v23.json` | 2,112 | `31760d267f3c2641042fbe8595fda9c259134a1c05423271a99cb74da1efa9aa` |
| `sign-v23.json` | 5,043 | `7ffb63c264602cba56117eefff1f9604b955df04c5cc655e877772b8ff7cd30e` |

## その他のfixture

この`LICENSE`の追加は、上記以外のfileを一律にMITへ変更するものではない。

- `display-alias-v1.json` / `station-attach-v1.json`はtoolingの`packages/live/test/fixtures/`からのcopyで、Protocol fixture directoryのMIT化の対象外。既存の`.source.json`と取得元のlicenseを維持する。
- `observer-session-lifecycle.ndjson`とsidecarは別の履歴素材。今回のProtocol 10本に含めない。
- `python-*.json`等はPython側の方針・consumer test用。ownerのProtocol fixture copyという意味ではない。
- `.source.json`はPython側の取得元記録。元fixtureの内部metadataと役割を分ける。

ownerの10本に対するtest接続状況・未接続の理由と予定は[`docs/polyglot-e1_ja.md`](../../docs/polyglot-e1_ja.md)に記載する。
同梱WireScopeのZIP／manifestとそのsource pinは、このLICENSEの固定し直しとは別の入力である。
