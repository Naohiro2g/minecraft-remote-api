# Python：F1の固定し直しとE2の接続動作（2026-11-12）

参照したknowledgeは`076a127a22eaf0188c1d13822bfd55bfeee9ec38`です。
依頼は`00-hub/polyglot-f1-e2-repin-instructions_ja.md`の「共通」「Python」、根拠は
DECISIONS `2026-11-11-01`②④⑦⑧と`2026-11-12-01`、wire「3.4」「6.2」「6.5」です。
比較基準はPython main `8cb2d55db4ee2c59bee3fca2957354aed60ad126`。
③⑤は以下のAPI案を返す段階です。この変更で自動再接続や新しいtimeout設定は実装していません。
package／protocolの版とwireは変更していません。公開は行いません。

## F1のcopyとtest

取得元はtooling `ea7838a78bf78947c7dde5876f6cc93b43f7e3cc`から
`36ebe9e63e4f0afcf949eae998832f68209b8119`（PR #7）へ固定し直しました。
owner pathは`packages/protocol/test/fixtures/`。再整形せず取得し、9 fileすべてでownerとbytes／SHA-256が一致します。
前から実際のbytesが変わったのはpairing、close、schemaです。
旧copyの全identityは前の[F3返却](polyglot-f3_ja.md)にあります。
現在の機械可読なidentityは[`client-bootstrap.source.json`](../tests/fixtures/client-bootstrap.source.json)です。
従来のProtocol fixture 7本の取得元と、WireScopeの同梱物は変更していません。

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `LICENSE` | 1070 | `aa329a0bafc839b95124306141db13a381de45818bf629e983c44ea55ab5a7fb` |
| `block-value-v22.json` | 3217 | `e8e108d59c40751d67a432543d75cb4bf9146ef9781721012085c80545b854f3` |
| `client-bootstrap-blocks-v23.2.1.json` | 45945 | `664babdf3131a74e4aaf6d9e5dfb5e4cfc6e197df0a0d48142688820f1be813d` |
| `client-bootstrap-close-v23.2.1.json` | 14884 | `a030cc72aa0e4f41575cb15610b1e06e941d3eab07157ce47f0eafe744475154` |
| `client-bootstrap-errors-v23.2.1.json` | 9179 | `c458d3ffbae846cfb33c032eba14d8f0005c6a1fbe871290b53fcfec8ec41aaa` |
| `client-bootstrap-framing-v23.2.1.json` | 15131 | `be063b519b5d653a4bb4ec3da6f67e5d481a28dcf5913961c848b2b909d4b26d` |
| `client-bootstrap-hello-v23.2.1.json` | 20913 | `78297f05eb4352b0dabffab3242e933c1e68cb192bbb6d242019c7956c809d57` |
| `client-bootstrap-pairing-v23.2.1.json` | 35577 | `5864c23ef3f31af6134d36770cab80b569b708b35fd3fdbed69fb6db195e3aeb` |
| `client-bootstrap-v1.schema.json` | 10916 | `8c3e4ff6e7b5b0cf438d358578096579dafab699a40df9cd56de7b9513837413` |

`tests/test_client_bootstrap_fixture.py`は本体のframer、TCP reader、RPC serializer、認証処理、block APIを使います。
scripted peerを使う決定論的testで、実サーバの全経路を保証するものではありません。

| suite | 前のcase数 | 今回のcase／PASS | test |
| --- | ---: | ---: | --- |
| framing | 7 | 7 / 7 | `test_f1_framing` |
| hello | 10 | 10 / 10 | `test_f1_hello` |
| pairing | 7 | 10 / 10 | `test_f1_pairing` |
| blocks | 12 | 12 / 12 | `test_f1_blocks_and_errors` |
| errors | 3 | 3 / 3 | `test_f1_blocks_and_errors` |
| close | 6 | 6 / 6 | `test_f1_close` |
| 合計 | 45 | 48 / 48 | skipなし |

schema、case IDの一意性、全copyのbytes／SHA-256は`test_f1_pinned_identity_schema_and_48_case_inventory`で確認します。
blocksの`value_refs`はcopyした`block-value-v22.json`を参照します。
AU-07は単発のtoken破棄のsnapshotで、`_hello_attempt`を通して確認します。
完全な認証回復の流れはAU-08〜10で確認します。新しいserver reasonやwireは作っていません。

## 決定との差と修正

先にtestを追加／更新して失敗を確認してから本体を修正しました。
下の「前」は比較基準の実装での失敗です。④には差がなく、修正は不要でした。

| 決定 | 前の動作・違い | 今回の修正 | 修正前に落ちたtest → 修正後 |
| --- | --- | --- | --- |
| ② close後の全応答待ちの解決 | EOFでは例外を返したが、pending一覧を管理せず、送信後の完了不明を明示していなかった。自分のcloseは応答待ちのworker終了を待っていた | active／queuedのpendingを追跡して全件を解決し、socketをshutdownする。`ConnectionLostError`に`completion_unknown`を付け、送信開始後はtrue、未送信はfalse。LFのない末尾は採用しない。code／reasonは付けない | F1-CL-03/05（期待したlocal failureがなかった）→ PASS。`test_close_settles_outstanding_calls_without_waiting_for_peer`（activeが解決しない）→ PASS |
| ④ 自動再送しない | 元から通常のRPCを再送しない | 維持。closeやtimeout後も再送しない | 差なし。F1-CL群と`test_flush_timeout_reclaims_connection_and_is_never_retried`がPASS |
| ⑦ token破棄後はtokenなしhello | invalid tokenの直後にpairingしていた。enforcementが不要でも人の承認が必要になりえた | tokenを消し、新しい接続でtokenなしhelloへ戻る。`auth_required`だけでpairing。一接続試行で一度まで。pairing後のtoken拒否も破棄するが再pairingしない | F1-AU-08/09/10（helloの順序／pairing回数が違う）→ PASS。`test_b2.py`の古い期待もこの動作へ更新 |
| ⑧ clientによるpairing期限切れ | local期限切れでserver風の`McRpcError(-32000, reason=pair_expired)`を作っていた | `PairingExpiredError`（`McRemoteError`の派生、`origin="client"`、code／reasonなし）。serverのpair_expiredは従来の`McRpcError`を保持。どちらも承認されなかったか期限切れという案内 | `test_client_pairing_expiry_is_local_not_a_synthetic_rpc_error`（server風の例外）→ PASS。server期限切れはF1-AU群でPASS |
| 2026-11-12-01 不一致helloのclose | `create()`は後始末したが、直接`hello()`を呼ぶと、不一致後も接続が残った | 成功helloの版が非互換なら、flushせず接続と観測runtimeを閉じ、次のrequestを送らず失敗。既存の版不一致情報とtoken保持は維持 | `test_direct_hello_mismatch_closes_before_another_request`（HE-04/05、socketが閉じない）→ PASS |

②のレビュー時に、送信queueの満杯でenqueue lockを持つproducerがいる場合のcloseも先に失敗させ、修正しました
（上のself-close testの`backpressure=True`）。closeはenqueue lockを待つ前に受付を停止するため、producerも解放されます。
また、直前のtimeoutを新しい未送信callの完了不明として返さないことを、
`test_call_after_failure_is_not_mislabeled_as_completion_unknown`のFAIL→PASSで確認しました。
送信を開始した後の部分送信の成否は判定できないため、保守的に完了不明とします。
遅れて届いた応答で確定済みの失敗を上書きしません。
通常のFASTとclose時のflushは維持し、すでに応答待ちのrequestを自分で中断した場合はflushの完了を保証しません。

## ③⑤：現在の動作

| 観点 | 現在の実装 |
| --- | --- |
| 応答の待機 | `Connection._connect()`がconnect用10秒、接続後のsocketに`DEFAULT_REQUEST_TIMEOUT_SECONDS=60`秒を設定。`readline()`のsocket timeoutで`RequestTimeoutError`になり、接続を回収する。接続全体の最終受信時刻から数える明示的なtimerはない |
| 設定の入口 | `Minecraft.create()`に応答timeoutの公開設定はない。`request_timeout`属性は接続時にsocketへ反映する実装で、接続後に属性だけ変えても既存socketの設定は変わらない。呼び出し別の設定もない |
| FIFO待ち | workerが要求を順に送って応答を読む。queueでの待機は独立の応答期限を持たない。最後の応答／受信による接続全体の期限更新という契約をまだ実装していない |
| 生存確認 | `is_connected()`でselect／peekする。送信などの利用時に呼ぶ方式で、idle時に独立して切断を検知するmonitorはない |
| つなぎ直し | 初回authenticateのhello／pairingで明示的に`Connection.reconnect()`するだけ。通常APIの失敗後、次の呼び出しで自動回復しない |
| 状態と通知 | 建築状態はMinecraft objectに持つが、最後に確認済みの状態を新しいhello.buildへ復元する回復経路はない。handle／cursorのepoch検証、再接続通知、backoff、thread間の回復集約も未実装 |

確認方法はsourceとunit testによる静的・決定論的な確認です。Wi-Fi切断や長時間の混雑でのtimeout実測はしていません。

## ③⑤：次の実装に向けたPython API案（未実装・未確定）

以下はknowledgeへの検討候補です。名前や値の確定、実装は次の依頼で行います。

```python
# APIの形だけの案。現在のパッケージでは使用できない。
mc = Minecraft.create(
    connection_options=ConnectionOptions(
        response_idle_timeout=measured_response_budget,
        liveness=LivenessOptions(idle=measured_idle, grace=measured_grace),
        reconnect=ReconnectOptions(enabled=True, backoff=measured_backoff),
    ),
    on_reconnect=observe_reconnection,
)
with mc.call_options(response_idle_timeout=longer_budget):
    mc.setBlocks(...)
```

- **timeout**：秒単位の接続既定値とcall単位の延長を提供する。call設定はcontext managerとcontext-localな状態で引き渡し、既存の各APIの引数を一斉変更しない。共有connection上で複数callの待ちが重なる場合は、待機中callの最も長い許容時間を使う案。queue入りからの経過ではなく接続全体の最終受信から数える。値は大規模建築・Paper混雑・一時的なWi-Fi切断の実測から決める。現在の60秒を新仕様の既定とはしない。
- **生存確認**：応答待ちの期限とは独立したtransport monitorを持つ。無通信は故障と決めつけず、長いgraceを持つ。TCP keepalive等の実際の対応をOSごとに確認する。idle時に切断が判明しても状態を切断へ変えるだけで、その場では接続し直さない（G）。新しいwire methodは追加しない。
- **回復の入口**：次の新しいAPI呼び出しを送る前に、既定で一度の回復処理へ合流させる。`ReconnectOptions(enabled=False)`で無効にできる。前の失敗した要求は再送しない。回復を待つcallはまだ未送信であり、接続失敗・中止の場合はその状態を返す（A、④）。明示的な`close()`は終端として自動回復させない案。
- **回復の内容**：保存済みtokenを使ってhelloし、最後に成功応答を確認したdimension／originをhello.buildへ渡す。version／catalogHashを再照合し、必要なcatalogの更新／補完処理を行う。非互換なら次のrequestを送らずcloseする（C）。`auth_required`は`PairingRequiredError`で止め、callbackがあってもpairingは自動で行わない（D）。
- **通知と安全な状態**：`on_reconnect(ReconnectInfo)`に新旧epoch、server／session／catalogHashの変更有無、event lossの可能性、前epochのFAST完了保証が失われたことを渡す案。handle／event cursorはepoch付きで無効化し、古いものの利用はlocal errorとする。新epochのflushは旧epochの通知の成功を証明しない（B）。通知を設定しなくても、epochと回復状態を問い合わせられる入口を用意する。
- **競合と待機**：connectionごとのlock／conditionで一つの回復試行を共有し、全threadが同じ結果を見る（E）。試行間隔はjitterを入れて増やし、長く粘る。上限・回数・全体の待機budget・中止方法は設定できる案。短い固定回数を根拠なく既定にしない（F）。observer callbackはlockの外で呼ぶ。
- **失敗の型**：`RequestNotSentError(ConnectionLostError)`と`CompletionUnknownError(ConnectionLostError)`を候補とする。`RequestTimeoutError`は後者の派生として互換性を保つ案。両方ともserver code／reasonを持たない。既存の`completion_unknown`属性との移行を整理する。失敗した要求と、新しい未送信callを混同しない。serverから届いたerrorは`McRpcError`をそのまま返す。

未確定：設定名、具体的な秒数／backoff、call別延長の共有接続上の集約、callback失敗の扱い、明示closeの終端性、
回復中のキャンセル、FASTのepoch越えをapplicationへ示す最小の形。toolingの③⑤のfixtureも待つ。
これらをclientだけで新しい横断契約にしていません。

## 実機pulse

- 実行日：2026-11-12 02:36:47 JST（2026-11-11 17:36:47 UTC）。
- 相手：operatorが確認したPaper `1.21.11-132-ver/1.21.11@c5eb079`、公開McRemote `2321.1.0`。応答のprotocol `23.2.1`、Minecraft `1.21.11`。
- 認証：先にhuman ownerが別端末で`uv run --frozen python scripts/auth_smoke.py`を実行し、Minecraft内で承認。pulse自体は保存済みtokenを使う`pair=False`で実行した。
- script：[`scripts/f3_bootstrap_pulse.py`](../scripts/f3_bootstrap_pulse.py)。`--paper-version`でoperator確認値を渡す。hello → 空気の候補をgetBlockで確認 → setBlock → getBlock一致 → 元のblockへ復元 → getBlock一致 → close。
- 結果：PASS、`restored=true`。token／pairing_id／実接続先／player／座標は返却に保存しない。認証が必要な人間操作とpulseを分離したlive-auto相当で、script＋PASS summaryを根拠にする。14-evidenceの正式recordは作成しない。
- 範囲：保存済みtokenでの実機接続と建築の往復を確認。invalid tokenからのtokenなしhelloの分岐、clientの期限切れ、切断競合は決定論的testで確認した。これらの分岐の実機網羅を主張しない。

## 検証とInventoryへの候補行

実行：`uv run --frozen --offline --with pytest pytest -q`（uv cacheを指定）。全846件PASS。
`uv run --frozen python scripts/build_client_api_reference.py --check`と`git diff --check`も確認する。
CIではPython 3.10〜3.13とbuild／wheel同梱検証を実行する。PR／merge／run identityは返却票に記載する。

Protocol Inventory「共有fixtureの使い方」のPython行の変更案：

| 前 | 後 |
| --- | --- |
| 従来7本のcopyに加え、F1全6本／45case、block-value-v22のvalue_refs、schema、LICENSE。取得元ea7838a | 従来7本のpinを維持。F1全6本／48case（7+10+10+12+3+6）、block-value-v22のvalue_refs、schema、LICENSE。取得元36ebe9e。全9 copyのidentityをtestで確認。新しいtokenless hello・closeの意味論もPASS。認証変更後の実機pulse PASS |

契約と異なるため差し戻すcaseはありません。AU-07の単発snapshotと、AU-08〜10の回復シナリオを分けて読みました。
③⑤の実装と上記API案の未確定は次の票へ返します。
