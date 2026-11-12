# Python E2：応答の待機と接続の回復（2026-11-13）

参照したknowledgeは`125812b47bae32120f56febc4d30058ab0fe8248`です。
依頼は`00-hub/polyglot-e2-reconnect-instructions_ja.md`「共通」「Python」「返却」。
根拠はwire「3.4」「6.2」「6.5」、DECISIONS `2026-11-11-01`③⑤、`2026-11-12-01`、`2026-11-12-05`です。
検討メモ`connection-liveness-notes_ja.md`とPython guideも読みました。
比較基準はmain `9e64b492a90c967675477a495287d9080428b390`です。
package／protocolの版、wire、同梱WireScopeのZIP／manifestは変更しません。tag／Release／公開workflowは実行しません。

## 使う入口と既定値

正面の入口は`Minecraft.create()`です。切断後の次の新しい呼び出しで、既定で接続を回復します。
前の呼び出しの失敗は取り消さず、自動再送もしません。

```python
from mc_remote.minecraft import (
    Minecraft, ConnectionOptions, LivenessOptions, ReconnectOptions,
)

mc = Minecraft.create(
    connection_options=ConnectionOptions(
        response_idle_timeout=900,
        liveness=LivenessOptions(enabled=True, idle=60, interval=30, probes=10),
        reconnect=ReconnectOptions(enabled=True),
    ),
    on_reconnect=lambda info: print("接続を回復しました", info.events_lost),
)
with mc.call_options(response_idle_timeout=1800):
    # このcontextで始める呼び出しの応答待ちを延ばす。
    ...
mc.close()
```

初回helloにも`build={"dimension": dimension, "origin": origin}`を渡せます。既存のhello.buildへ投影し、新しいwireを作りません。
`handshake=False`や直接`Minecraft(connection)`で接続を自分で組み立てる経路では、自動の認証回復を有効にしません。

| 設定 | 既定 | 理由と境界 |
| --- | --- | --- |
| response_idle_timeout | 900秒（15分） | 旧60秒から延長。Paperで複数接続の建築予算を分ける状況で、短い上限が通常利用を打ち切らないための運用初期値。TypeScriptの仮の15分も参考にした。長時間混雑の実測から較正した値とはしない |
| connect_timeout | 10秒 | 1回のTCP dialの上限。応答待ちとは別。回復の全体budgetも別に持つ |
| TCP keepalive | 有効、idle 60秒、interval 30秒、probes 10 | 一時的なWi-Fi断に数分耐え、最後の応答待機上限より先に壊れた経路を検出する初期値。全項目を設定できるOSでは検出の目安は約6分。実際の検出はOS／経路に依存する |
| reconnect.enabled | true | 新しい呼び出しのときにだけ回復。falseで無効にできる |
| backoff | 初期0.5秒、baseの上限30秒、各回0.5〜1.5倍のjitter | baseを倍増させ、server復旧時の同時dialをばらす。jitter後の間隔は最大45秒になりうる |
| reconnect.budget | 300秒（5分） | 一時的な停止で直ちに諦めず、呼び出しを無制限に止めない初期値。個々のdialがあるため、厳密なwall clockの打切りとはしない |

いずれもlocal policyです。具体的なtimeoutやbackoffはprotocol契約ではありません。
今回の実機の健康時往復は後述の約0.05秒であり、15分やWi-Fi耐性の根拠となる長時間実測ではありません。
混雑時・Wi-Fi切替・スリープ復帰の較正は未検証として返します。

## 実装した形

- 送信は一つのFIFO worker、受信は独立したreceiverで処理します。同じconnectionに複数のid付きrequestを送れ、各応答をpendingへ対応させます。送信順序は維持します。idは接続ごとに1から採番します。
- 応答待ちがある間、その接続で最後にbytesを受信してからの時間で判定します。長いidleの後に最初の要求を送った場合は、待機開始より前のidleを算入しません。pendingがない間は通常の応答timeoutで切りません。
- callごとの延長はContextVarで捕捉します。接続を共有する待機中callの最大のbudgetを使い、ほかのcallが設定した長い待機を短いcallで中断しません。値は接続既定値を短くする用途には使いません。
- 期限を超えたら全pendingをlocal failureで解決し、その接続を回収します。EOF／socket error／自分でcloseする場合も同様です。LFなしの末尾を成功応答にしません。
- 生存確認はTCP keepaliveで行い、receiverがidle中もEOFやOSのerrorを検出して切断状態へ移します。無通信だけで故障と判断せず、idle中に自動dialもしません。
- 回復では、保存tokenを使ったhello、必要ならtoken破棄後のtokenなしhelloまでを行います。`auth_required`ではpairingせずに止まります。回復中に初回のpairing callbackを再利用することもありません。
- 成功が確認されたsetterのbuild contextを、pendingの解決前に記録します。応答が失われたsetterは復元にも再送にも使いません。新しいhelloのbuildへ、最後の確定dimension／originを渡します。
- entity handleは発行時のowner／epochを記録して、旧epochの利用を`StaleEpochError`で止めます。event cursorと過去batchは回復時にリセットします。明示的に生の文字列へ作り直したhandleなど、由来を失った値の正当性はserverの検査にも依存します。
- helloで版を再判定し、`catalog_hash`を更新して最後に検証したcacheのhashと照合します。hash変更を通知し、旧cacheの適合を引き継ぎません。新しい補完の生成は`sync_constants()`で行います。cache一致はprojectionのgenerator版までの一致を意味しません。
- 明示的な`mc.close()`は終端です。回復中のbackoffも中止します。次の利用で勝手に開き直しません。

## 失敗と知らせ

| API／型 | 意味 |
| --- | --- |
| `CompletionUnknownError(ConnectionLostError)` | 送信開始後の操作の完了が不明。code／reasonは持たない |
| `RequestTimeoutError(CompletionUnknownError)` | 応答idle期限を超えた。既存の例外名を保持し、`completion_unknown=True` |
| `RequestNotSentError(ConnectionLostError)` | この新しい呼び出しは未送信。localな`cause`でconnection_failed／pairing_required／incompatible_protocol／reconnect_disabled等を区別。serverのcode／reasonを作らない |
| `StaleEpochError` | 前の接続のentity handleを使おうとしたlocal error |
| `on_reconnect(ReconnectInfo)` | 新旧epochとhello、server／session／catalogの変更、event lossの可能性、旧FASTの完了不明を通知 |
| `last_reconnect`／`connection_epoch` | callbackを使わなくても最後の回復と現在epochを読める |
| `last_flush(FlushInfo)` | 成功したflushのepoch、前の成功flushのepoch、間に回復があったかを読める。旧epochは保証から除く |

callbackは回復のlockの外で一度配信します。callbackの失敗はwarningに留め、成功した接続を壊しません。
`ReconnectInfo.events_lost`は喪失の可能性を知らせ、失ったevent数を推定しません。
serverから届いたerrorは、code／message／opaqueなdataを持つ`McRpcError`として保持します。

WireScopeは今回UIを変更していません。既存のobserver hookとepoch終了時の`target-ended`契約を維持します
（knowledge `15-wirescope/wirescope-station-attach-design_ja.md` §7・§8）。
自動再接続後の画面の継続、別processでの閲覧、観測開始・終了の改善を、この変更の合格範囲には含めません。

## 決定との対応とtest

| 条件 | 実装 | 確認したtest |
| --- | --- | --- |
| ③ | 最終受信で更新する接続単位の長いidle期限、call単位延長、独立keepalive、回収 | F1-OP-01/02/03、`test_call_options_extends_connection_idle_budget`、`test_tcp_keepalive_is_configured_separately_from_response_budget` |
| ⑤A | 回復できない新しいcallは未送信、旧要求は完了不明のまま | F1-OP-01/02/05/07/09、`test_requests_can_overlap_and_all_sent_calls_settle_on_disconnect` |
| ⑤B | epochと`last_flush`、通知で旧FASTの保証を分離 | F1-OP-06。新flush成功の前後で旧接続が保証対象に入らないことを検査 |
| ⑤C | helloの版／hash再照合、server／session変更通知、handle／cursor失効 | F1-HE-11/12、F1-OP-07/11、`test_recovery_invalidates_public_handle_before_entity_command` |
| ⑤D | auth_requiredでpairingをせず未送信として止まる | F1-OP-09 |
| ⑤E | connectionごとのconditionで一つの回復を共有。結果も共有 | F1-OP-10、`test_real_thread_barrier_shares_one_recovery`（実OS thread 8本、成功と失敗の両方） |
| ⑤F | baseを増やし、jitterを掛け、budget内で粘る | `test_reconnect_backoff_has_jitter_grows_and_stops_at_budget`（時計・乱数注入） |
| ⑤G | idleのreceiverがOSの切断検出を反映し、次callで回復 | F1-OP-12。probeの長時間実測は含めない |
| 2026-11-12-05 | 同じpairing_idの次pollを新しいTCPで送る。一度Beginしたpairingを再作成しない | F1-AU-11、AU-12の終端snapshot、`test_pairing_continues_after_lost_poll_then_uses_token_hello`（失ったpollの先からtoken付きhelloまで） |
| ④ | 自動再送なし。失ったpollの次pollは同一pairingの継続 | F1-OP-03/04、上のpairing継続test |

修正前の比較では、F1-AU-11は承認待ちEOFから続かずFAIL、CL-08は二つの応答待ちを回収できずFAILでした。
さらにnative testで、旧workerは2番目のrequestを送れずFAILすることを確認してから、送受信を分けました。
HE-11/12の最初の失敗はtest doubleのclosed属性不足だったため、実装の差の証拠には数えません。
実装途中のOP-08は、期限切れ後のcloseがidle receiverをjoinして止まる失敗を検出し、shutdown後のjoinへ修正してPASSしました。
旧mainのsnapshotでもv2を比較し、OP-01/02/04〜12の11caseがFAIL、従来から満たしていたOP-03はPASSであることを確認しました。比較用adapterでは、旧APIに無い初回helloの任意metadataなどだけを正規化しています。
残りの新しいcaseも現在のCIへ接続します。全testを最初に修正前へ追加できたとする主張はしません。

## 生存確認とthread利用の返答

PythonのTCPでは`SO_KEEPALIVE`を設定できます。Linuxで利用可能な`TCP_KEEPIDLE`／`TCP_KEEPINTVL`／`TCP_KEEPCNT`を設定し、
macOSの`TCP_KEEPALIVE`、Windowsの`SIO_KEEPALIVE_VALS`も、APIがある場合に使います。
細かな項目を設定できないOSではその項目のOS既定を使います。`conn.keepalive_applied`で成功した設定を調べられます。
今回の実機とCIはLinuxです。Windows／macOSの実OSでの検出時間は未検証です。

一つのMinecraft objectを複数threadから使えます。送信FIFO、pending表、build状態の更新、event pollのcursor、回復の共有を保護しています。
同じobjectのdimension／origin／build modeは共有状態なので、threadごとに独立の世界座標系を持つ意味にはなりません。
今回8本のOS threadが同時に切断へ気づくtestで、dialが一つにまとまり、成功または未送信の失敗を共有することを確認しました。

## fixtureの取得元と合格数

前：tooling `36ebe9e63e4f0afcf949eae998832f68209b8119`、v1 48case。
後：tooling `335c604f859d6dfad04f0434bfa4eb6445761430`、`packages/protocol/test/fixtures/`の11 file。
全11 copyのbytes／SHA-256はownerと一致し、testでも固定します。
前後の機械可読identityは返却素材に同梱します。現在の一覧は`tests/fixtures/client-bootstrap.source.json`です。

| file | case／PASS | bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `LICENSE` | — | 1070 | `aa329a0bafc839b95124306141db13a381de45818bf629e983c44ea55ab5a7fb` |
| `block-value-v22.json` | — | 3217 | `e8e108d59c40751d67a432543d75cb4bf9146ef9781721012085c80545b854f3` |
| `client-bootstrap-blocks-v23.2.1.json` | 12 / 12 | 45945 | `664babdf3131a74e4aaf6d9e5dfb5e4cfc6e197df0a0d48142688820f1be813d` |
| `client-bootstrap-close-v23.2.1.json` | 8 / 8 | 20879 | `2abb6f48942e1dc7bc42014ba016c3d08a6632c59445c048b008a4c411ea1e30` |
| `client-bootstrap-errors-v23.2.1.json` | 3 / 3 | 9179 | `c458d3ffbae846cfb33c032eba14d8f0005c6a1fbe871290b53fcfec8ec41aaa` |
| `client-bootstrap-framing-v23.2.1.json` | 7 / 7 | 15131 | `be063b519b5d653a4bb4ec3da6f67e5d481a28dcf5913961c848b2b909d4b26d` |
| `client-bootstrap-hello-v23.2.1.json` | 12 / 12 | 26046 | `caf24ad5382e411ba54172b05d6020fc59fc429dc0251ff28db3908b4189784e` |
| `client-bootstrap-operations-v23.2.1.json` | 12 / 12 | 66335 | `8309f5847ad69aa2d82fcbcb1726918c3a69ba875e04e8f38678352b06b7f7a1` |
| `client-bootstrap-pairing-v23.2.1.json` | 12 / 12 | 45943 | `19230b310c7482adc740095d5604110937ebaa7803a0fed4c294083a9e63a460` |
| `client-bootstrap-v1.schema.json` | — | 11521 | `970dd68999edc14a4dcc2b67ab2f712e830b7841b2ec4548fee66af117fd281b` |
| `client-bootstrap-v2.schema.json` | — | 19468 | `8ae1c7313d01fa0fa24f4f2079ba453129dc16b678342df6f7ef66b9255d1381` |

v1：framing7、hello12、pairing12、blocks12、errors3、close8の全54case。
v2：operations全12case。合計66case、todo／skipなし。
AU-07はtoken破棄のsnapshot、AU-12は応答を失ったpollまでのsnapshotとして確認し、続きはnative testへ分けます。
v2のexpectedは、ownerの説明どおり記載された行・fieldだけを比較し、送信数／pending集合は完全一致を要求します。
時計は仮想時計で進めます。harnessが再接続やrequestを代行せず、公開の`Minecraft.create()`から実際のclientが送るものを観測します。
seed_epoch_stateだけはtest準備としてhandle／cursor／cacheを用意します。

## 実機pulse

2026-11-13 01:04:04 JST（2026-11-12 16:04:04 UTC）。相手はoperator確認済みの
Paper `1.21.11-132-ver/1.21.11@c5eb079`、公開McRemote `2321.1.0`。
hello応答はprotocol `23.2.1`、Minecraft `1.21.11`。

最初はpair=Falseでpairing_requiredとなり、建築前に停止しました。human ownerが別端末の
`uv run --frozen python scripts/auth_smoke.py`でMinecraft内の承認を済ませた後、保存済みtoken・pair=Falseで実行しました。
scriptは[`scripts/e2_reconnect_pulse.py`](../scripts/e2_reconnect_pulse.py)。
成功が確認された非defaultのoriginを設定し、空気の試験位置を確認してから、hello→setBlock→getBlockを実施。
試験のclient TCPだけをshutdownし、次のgetBlockによる新しいhelloと接続回復、origin復元、event loss通知を確認しました。
最後に元のblockへ戻し、getBlockの一致とcloseまでPASSです。Paper／McRemoteの停止・再起動は行っていません。

| 測定 | 秒 |
| --- | ---: |
| 初回helloを含むcreate | 0.052650 |
| setBlock | 0.050694 |
| getBlock | 0.055477 |
| 再接続を含むgetBlock | 0.093500 |

`restored=true`、`reconnected=true`、`build_restored=true`、`events_lost_notified=true`。
live-auto相当としてscriptとsanitized PASS summaryを残します。正式14-evidence recordは作成しません。
token／pairing_id／実接続先／player／座標は返却に保存しません。

## 残る検証境界とInventoryへの候補行

- Wi-Fi断、IP変更、長時間のPaper混雑、OS別のkeepalive検出時間と5分の回復budgetは、実運用での較正が残ります。mockの時計の短い実行時間から耐性を主張しません。
- 長い待機の途中の「まだ待っています」という表示は、検討メモの候補で、今回の新しいUIとしては実装しません。
- WireScopeの観測開始・終了や、再接続後の表示方法は別の検討です。
- 契約と違うため差し戻すcaseはありません。Pythonが既に持つFAST／flush／entity／cursor／catalogのcaseも合格対象にしました。

Protocol Inventory「共有fixtureの使い方」のPython行の変更案：

| 前 | 後 |
| --- | --- |
| 従来7本を維持。F1 v1全6本／48case、block-value参照、schema、LICENSE。tooling36ebe9e | 従来7本を維持。F1 v1全6本／54case＋v2 operations12case、両schema、block-value参照、LICENSEの全11 copyをtooling335c604へ固定。全66case PASS、todoなし。AU-12先のpoll継続と8 OS thread競合をnative test、実機の建築・TCP切断後の回復・復元をpulseで確認 |

ローカルの全回帰は880 tests PASS（16.64秒）。API referenceは39 method／4 propertyで生成一致、git diff --checkもPASS。
PR／merge commit／CI runは返却票に記載します。
