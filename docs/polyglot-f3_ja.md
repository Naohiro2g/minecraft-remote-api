# Python F3：client bootstrap fixture

> この文書はF3／PR #13・#14の履歴（45case、取得元ea7838a）です。現在の48caseとE2の修正は[後続の返却](polyglot-f1-e2_ja.md)を参照してください。


参照knowledge: `5e00768911feb7be1e54ae3b7e9c2d776b88927a` / `00-hub/polyglot-f3-instructions_ja.md`。
基準sourceは2321.1.0公開後のmain。申告protocolは`23.2.1`を維持します。

## 取得元と全case

F1のcopyは、tooling `ea7838a78bf78947c7dde5876f6cc93b43f7e3cc`の`packages/protocol/test/fixtures/`から取得しました。
取得元と各fileのbytes/SHA-256は`tests/fixtures/client-bootstrap.source.json`。既存のMIT LICENSEとbytesが同一であることを確認しています。
従来の共有fixtureの取得元・本文は変えていません。F1は今回初めて接続しました。schemaもcopyし、ownerのrequired/constとcase IDの一意性をtestします。

| fileのsuite | case数 | consumer |
| --- | ---: | --- |
| framing | 7 | `_JsonRpcFrames`の増分decode・id相関、Connectionのrequest encode |
| hello | 10 | `Minecraft.hello()`、Connectionのerror decode |
| pairing | 7 | `authenticate()`、`auth.pair()`、tokenの保存・破棄。AU-03は意図的な未知pairing IDをraw RPCで送るwire拒否のcase |
| blocks | 12 | Connectionの送受信・error、`getBlock()`のBlockValue decode、value_refsのcatalog読込み |
| errors | 3 | Connectionのopaque error data保持 |
| close | 6 | sequencerのclose/reconnect、EOF前後の成功・未応答、create失敗 |
| 合計 | 45 | skipなし |

Pythonのtest runnerは`tests/test_client_bootstrap_fixture.py`。framingはproductionで使うdecoderを直接検証します。
FR-07はfixtureのpending ID集合による相関primitiveのunit testであり、PythonのFIFO APIが並行requestをwireへ多重化するという主張ではありません。
ほかの対話はPythonの実Connection sequencerを使い、ネットワークI/Oをfixtureのpeerストリームに置き換えます。
helloの`client`/`build`は任意metadataで、Pythonのhello APIは申告protocolと任意authだけを送ります。必須の値と応答はfixtureで照合し、任意metadataのAPI追加は行っていません。
BlockSpecが不正なcaseはlocal builderで補正せずraw RPCで送り、peerのreasonと後続getBlockを照合します。block-value-v22.jsonの参照は12 caseすべてで解決します。

## 直した振る舞い

- F1-HE-04/05：以前は応答protocolをそのまま採用していた。今はmajor一致・server minorが要求以上・patch不問で判定し、不一致はcreateの失敗にする。`data.reason=protocol_mismatch`と`server`/`client_requires`を保持し、tokenは消さない。
- F1-FR-06：以前は非JSON行で接続が失敗した。今は行を捨てて次の完全な応答を読む。未知idも捨て、該当requestの応答を待つ。途中のUTF-8/LFはproductionの増分decoderで保持する。
- TCP readerはUTF-8を明示し、端末OSの既定encodingに依存しないようにした。指定が無いことによる補助testの失敗を修正前に確認した。
- 修正前にHE-04/05とFR-06が意図した理由で落ちることを確認した（3 failed / 7 passed）。修正後の追加検証ではcreateの後始末・token温存、両error codeでのreason判定と版の欄の保持も検証する。
- 従来のhelloを使う別機能のtestに残っていた古いprotocolのダミー応答は現行版へ合わせた。履歴fixtureやobserver単体の過去protocolの検証は変えていない。

EOF時の例外型、pendingのtimeout・完了方法、自動再送、人間による拒否の専用wireなど、fixtureのunresolvedは新しく決めていません。
既存のcleanup/再送しない方針は維持し、成功応答が無いことなどexpectedの観測だけを検証します。
2026-11-11、knowledge `6f7ca001988387d172bd698579a0f42c72d24ac5`の照合を受け、tooling PR #5のmerge commitへ固定し直しました。HE-09のdata.server/client_requiresと追加HE-10を同じconsumerで検証します。codeでは分岐せずreasonで判定し、code/message/dataをそのまま保持することも確かめます。

## 実McRemote pulseとF3の境界

2026-11-10 19:20 JST、Paper `1.21.11-132-ver/1.21.11@c5eb079`、McRemote `2321.1.0`でlive-auto pulseがPASSしました。Paperとロード中のpluginの版はhuman ownerのbootstrap情報で確認しました。human ownerが既存auth_smokeでMinecraft内の承認を済ませ、その後は保存済みtokenを`pair=False`で再利用しました。hello→setBlock→getBlockを確認し、元の空気への復元と読戻しもPASSしました。
`python scripts/f3_bootstrap_pulse.py --help`で、既存のtoken storeを使う非対話の手順を確認できます。`--paper-version`に手元で確認した実環境の版/buildを指定します。`--position`を省略するとペア済みプレイヤー付近の候補を読み、空気だけを試験位置にします（playerの移動はしません）。空気が見つからなければ変更前に止まります。位置を明示しても空気以外は変更しません。
実行前にPaperの版/buildと、公開McRemote2321.1.0のJARが実際にロードされていることをoperatorが確認してください。helperのrequired_mcremote_versionは要求値で、helloから実plugin版を推測した値ではありません。
hello後に元のblockを保存し、set→getを確認、元のBlockValueへ戻します。`pair=False`で実行し、認証が要れば人の承認前で止まります。
必要なら既存の`scripts/auth_smoke.py`でhuman ownerがpairingを済ませ、同じtoken store/keyでpulseを再実行します。接続先・token・pair code・player・座標は返却に含めません。
ローカルの全回帰は837 tests PASS（F1の45caseと補助8testを含む）を確認しました。
現取得元のF1全45caseと実機pulseがPASSしました。前回44caseとpulseはknowledge `6f7ca001988387d172bd698579a0f42c72d24ac5`で照合済み。pulseはlive-auto相当としてscriptとPASS summaryを根拠にし、14-evidenceにrecordは作りません（以前の配置案は採用しない）。今回の固定し直しでpulseをやり直してはいません。

## Protocol Inventory：共有fixtureの使い方の更新案

Pythonの前：既存10本のうちcopy7本（5本の意味のtestと履歴2本）。F1の6本は未接続。block-value-v22は未接続。
Pythonの後：従来の7本に加え、F1全6本/45caseを接続。block-value-v22はblocks12caseのvalue_refsとして読む。schemaとMIT LICENSEも同梱。上記の実機pulseもPASS。

## copyのidentity

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `LICENSE` | 1070 | `aa329a0bafc839b95124306141db13a381de45818bf629e983c44ea55ab5a7fb` |
| `block-value-v22.json` | 3217 | `e8e108d59c40751d67a432543d75cb4bf9146ef9781721012085c80545b854f3` |
| `client-bootstrap-blocks-v23.2.1.json` | 45945 | `664babdf3131a74e4aaf6d9e5dfb5e4cfc6e197df0a0d48142688820f1be813d` |
| `client-bootstrap-close-v23.2.1.json` | 14535 | `44e9a4276bbd204671db0385f4f801cd3b152d0853ac943876ede73db6bd8dd1` |
| `client-bootstrap-errors-v23.2.1.json` | 9179 | `c458d3ffbae846cfb33c032eba14d8f0005c6a1fbe871290b53fcfec8ec41aaa` |
| `client-bootstrap-framing-v23.2.1.json` | 15131 | `be063b519b5d653a4bb4ec3da6f67e5d481a28dcf5913961c848b2b909d4b26d` |
| `client-bootstrap-hello-v23.2.1.json` | 20913 | `78297f05eb4352b0dabffab3242e933c1e68cb192bbb6d242019c7956c809d57` |
| `client-bootstrap-pairing-v23.2.1.json` | 19322 | `cdb2209d8a1d46fede158db50c3672936dad152c7fd2bec7ef5a068ed57a1fe1` |
| `client-bootstrap-v1.schema.json` | 9953 | `e848bd3a61d4c0a737f7f3a8963baf2fcbb83247486f3d8aa69f022bb55a7ede` |

互換判定のInventory更新案：応答のmajor/minor検証が未実装だった「部分」から、§8.2の応答互換判定を実装済みの「あり」へ。申告protocolは23.2.1のままです。
