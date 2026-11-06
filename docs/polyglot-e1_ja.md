# 多言語化 E1：Pythonの対応表・fixture・開発体験

## 基準と確認方法

- knowledge実読commit: **`8c81c0f115127189de117c3848d1e254f79571c9`**。
- 実読: `10-protocol/protocol-inventory_ja.md`、`10-protocol/polyglot-phase-ef-plan_ja.md`のE1、`10-protocol/api-reference-metadata.json`。runtimeは実行時remote main `7012e3b5e93ebbd0a7da4006436a06e44b9f54be`を実読。
- 形の参考: Java `2ea54074b6a03161ebe2fa8ecb98647d8a90912e`の`docs/polyglot-e1_ja.md`。Javaの対応状況をPythonへ推測で転記していない。
- **投影の基準: stable `v2321.0.0` / `fac0313ea9162dc0730412c53d665e6c42a93791`、protocol `23.2.1`**。remote mainも作業開始時点で同SHA。
- 基準sourceの静的確認と、同sourceから分離した本branchの通常CIで確認する。新しいClient API、wire、server、fixture caseは追加していない。実機・IDE操作・新しいlive PASSは今回主張しない。
- 「あり」は公開Client APIへの投影があるという意味。全reason・全server実装経路・全実機での検証済みという意味ではない。汎用`Connection.rpc()`だけで呼べるものを投影として数えない。
- 下表の **M = [`mc_remote/minecraft.py`](../mc_remote/minecraft.py)**。テストのpathはrepo root基準。名称中のb1〜b9やprotocol22は歴史的な名前で、stable sourceに残るテストを指す。

## E1：method 32行

Inventoryおよびmetadataと同じ行・順序。全32行があり。ただし応答の型付けや検証の深さは行ごとに異なる。

| method | Python | Client API／範囲 | 実装fileとtestの根拠 |
| --- | --- | --- | --- |
| `hello` | あり | `Minecraft.create() / hello()`。hello結果を保持。認証と建築文脈は下記能力表も参照 | M、`tests/test_b1.py::test_hello_declares_protocol_and_caches` |
| `connection.flush` | あり | `Minecraft.flush()`。先行命令の完了待ち。timeoutは完了不明として接続回収し、自動再送しない | M、`tests/test_b5.py::test_flush_timeout_reclaims_connection_and_is_never_retried` |
| `build.setDimension` | あり | `Minecraft.setDimension()`。server正準dimension/originを保持 | M、`tests/test_b1.py::test_build_setter_uses_canonical_result_not_input` |
| `build.setOrigin` | あり | `Minecraft.setBuildOrigin()`。server正準originを保持 | M、`tests/test_b1.py::test_set_build_origin_failure_or_invalid_result_preserves_context` |
| `world.setBlock` | あり | `Minecraft.setBlock()`。block_id / stateからBlockSpec。DEBUG/TRACE/FAST | M、`tests/test_b5.py::test_debug_trace_and_fast_keep_one_setter_surface_and_return_none` |
| `world.setBlocks` | あり | `Minecraft.setBlocks()`。同じBlockSpec入力、入力のsnapshot化 | M、`tests/test_b5.py::test_setblocks_uses_same_blockspec_and_snapshots_input` |
| `world.getBlock` | あり | `Minecraft.getBlock()`。immutable BlockValue | M、`tests/test_b5.py::test_getblock_returns_immutable_blockvalue` |
| `world.getBlocks` | あり | `Minecraft.getBlocks()`。wire順のtuple[BlockValue, ...] | M、`tests/test_b5.py::test_getblocks_returns_immutable_tuple_in_wire_order` |
| `world.getHeight` | あり | `Minecraft.getHeight()`。max_y省略可、整数応答 | M、`tests/test_b5.py::test_height_particle_and_entity_use_protocol22_exact_wire_order` |
| `world.getSign` | あり | `Minecraft.getSign()`。SignValue / LineValue | M、`tests/test_b6.py::test_b6_s03_get_sign_sends_and_decodes_fixture_shape` |
| `world.setSign` | あり | `Minecraft.setSign()`。front/backとLineSpec入力 | M、`tests/test_b6.py::test_b6_s04_set_sign_sends_fixture_params` |
| `world.updateSignLine` | あり | `Minecraft.updateSignLine()`。face / line_index / line | M、`tests/test_b6.py::test_b6_s05_update_sign_line_sends_fixture_params` |
| `player.getPos` | あり | `Minecraft.getPos()`。paired playerのdimension/posをdictで返す | M、`tests/test_b2.py::test_getpos_wire_shape` |
| `player.setPos` | あり | `Minecraft.setPos()`。明示dimension、origin相対pos | M、`tests/test_b2.py::test_setpos_wire_shape` |
| `player.getPose` | あり | `Minecraft.getPose()`。dimension/pos/yaw/pitchのdict | M、`tests/test_b4.py::test_getpose_uses_paired_player_without_identity_param` |
| `player.setPose` | あり | `Minecraft.setPose()`。小数を保持しserverの正準結果を返す | M、`tests/test_b4.py::test_setpose_preserves_fractional_values_and_server_normalized_result` |
| `player.getDirection` | あり | `Minecraft.getDirection()`。DirectionValue | M、`tests/test_b7.py::test_direction_four_methods_send_exact_fixture_shapes` |
| `player.setDirection` | あり | `Minecraft.setDirection()`。directionの数値を投影 | M、`tests/test_b7.py::test_direction_four_methods_send_exact_fixture_shapes` |
| `world.spawnEntity` | あり | `Minecraft.spawnEntity()`。EntityHandle、entity resource入力 | M、`tests/test_b5.py::test_height_particle_and_entity_use_protocol22_exact_wire_order` |
| `world.getNearbyEntities` | あり | `Minecraft.getNearbyEntities()`。tuple[NearbyEntity, ...]、server順を保持 | M、`tests/test_b8.py::test_nearby_preserves_server_order_and_numbers` |
| `entity.getPose` | あり | `Minecraft.getEntityPose()`。opaque handle、PoseValue | M、`tests/test_b8_fixture.py::test_owner_entity_lifecycle_projection` |
| `entity.setPose` | あり | `Minecraft.setEntityPose()`。handleと明示dimension。post-read結果 | M、`tests/test_b8.py::test_entity_pose_sends_original_input_and_returns_post_read_without_context_change` |
| `entity.getDirection` | あり | `Minecraft.getEntityDirection()`。opaque handle、DirectionValue | M、`tests/test_b7.py::test_direction_four_methods_send_exact_fixture_shapes` |
| `entity.setDirection` | あり | `Minecraft.setEntityDirection()`。handleとdirection | M、`tests/test_b7.py::test_direction_four_methods_send_exact_fixture_shapes` |
| `entity.remove` | あり | `Minecraft.removeEntity()`。opaque handle、null成功 | M、`tests/test_b8.py::test_entity_remove_requires_null_and_opaque_strings_go_to_server` |
| `world.spawnParticle` | あり | `Minecraft.spawnParticle()`。typed data / receiver / force等、ParticleSpec入力 | M、`tests/test_b8.py::test_particle_specs_preserve_omission_null_force_and_request_mode` |
| `world.playSound` | あり | `Minecraft.playSound()`。keyword volume/pitch/note/receiver等 | M、`tests/test_b8_surface.py::test_sound_keywords_preserve_defaults_numbers_and_omit_none` |
| `world.playBlockSound` | あり | `Minecraft.playBlockSound()`。blockとsound kindを投影 | M、`tests/test_b8_surface.py::test_block_sound_kind_is_sent_without_scene_pitch_correction` |
| `world.strikeLightning` | あり | `Minecraft.strikeLightning()`。full lightning、null成功。Effect aliasなし | M、`tests/test_b7.py::test_strike_lightning_sends_exact_params_requires_null_and_has_no_effect_alias` |
| `chat.post` | あり | `Minecraft.postToChat()`。null成功、非nullは拒否 | M、`tests/test_b9.py::test_chat_post_null_return_and_observer_frame` |
| `events.poll` | あり | `Minecraft.pollEvents()`。EventBatch、数値cursor / loss、未知type省略 | M、`tests/test_b9_fixture.py::test_shared_event_batches_keep_cursor_losses_and_observer_summary` |
| `catalog.get` | あり | `Minecraft.getCatalog() / sync_constants()`。短命の別認証streamで取得。cache/生成は後述 | M、`tests/test_b3.py::test_create_syncs_catalog_by_default` |

`player.getPos` / `getPose`等は公開wrapperがあるので「あり」だが、player poseはdictで返す。entity poseの`PoseValue`や、blockのimmutable値と同じ型付けではない。
direction/particle/sound等の値の補助実装は`mc_remote/direction_value.py`、`particle_value.py`、`sound_value.py`、`entity_value.py`、signは`sign_value.py`にある。

## auth 5行

| method | Python | API／範囲 | 実装fileとtestの根拠 |
| --- | --- | --- | --- |
| `auth.pairBegin` | あり | `Minecraft.create()` / `authenticate()` → `mc_remote.auth.pair()`の対話ペアリング内 | M、`mc_remote/auth.py`、`tests/test_b2.py::test_pairbegin_params` |
| `auth.pairPoll` | あり | 同じ処理内でpendingから承認をpollし、token付きhelloへ進む | M、`mc_remote/auth.py`、`tests/test_b2.py::test_pair_pending_then_ok` |
| `auth.listCredentials` | なし | 専用公開API・wire呼出しなし。local tokenファイルの読取りとは別 | Mと`mc_remote/auth.py`の公開関数・wire文字列を静的確認。対応testなし |
| `auth.revoke` | なし | 専用公開API・wire呼出しなし。`auth.clear_token()`はlocal削除 | 同上。local動作のtestは`tests/test_b2.py::test_pair_false_discards_token_and_fails_actionably`、server revokeの検証ではない |
| `auth.logout` | なし | 専用公開API・wire呼出しなし。`Minecraft.close()`は接続の終了 | M、`mc_remote/auth.py`を静的確認。対応testなし |

## methodでない能力：Inventoryの14行

| 能力 | Python | Client API／範囲・根拠（fileとtest） |
| --- | --- | --- |
| TCPのframing／JSON-RPC | あり | `Connection`のTCP、LF付きJSON-RPC request、id対応、timeout/EOF。`mc_remote/connection.py`、`tests/test_b1.py::test_result_id_match_and_mismatch`、`tests/test_b5.py::test_connection_notification_and_flush_share_fifo_and_wire_shape` |
| WebSocket／browser | なし | McRemoteへ接続するtransportはTCP。WebSocketのClient APIなし。`mc_remote/connection.py`を静的確認、対応testなし。WireScopeのHTTP browser observerとは区別 |
| protocol negotiation | 部分 | `Minecraft.hello()`が23.2.1を申告し、serverの`protocol_mismatch`を運ぶ。応答版のmajor/minor比較はPython内では実装していない。M、`tests/test_b1.py::test_hello_protocol_mismatch_error`、`tests/test_b1.py::test_rc1_client_accepts_compatible_hello_response`（23.2.0/23.2.1応答のunit case） |
| authentication／pairing | あり | `create()` / `authenticate()`、session token再利用、認証reason時の再接続・pair・hello。M、`mc_remote/auth.py`、`tests/test_b2.py::test_enforcement_on_pairs_and_retries` |
| session credentialのUX | あり | `create(token_key=..., pair=...)`、接続先別local token。OS keyringではなくconfig下のJSON、新規dir0700/file0600、atomic replace。認証reasonのみ破棄。`mc_remote/auth.py`、`tests/test_b2.py::test_token_store_roundtrip_and_mode`、`tests/test_b2.py::test_token_keyed_per_server`、`tests/test_b2.py::test_credential_store_unavailable_preserves_token` |
| request／notification／flushと順序 | あり | `setBuildMode(BuildMode.DEBUG/TRACE/FAST)`、`flush()`、通常closeのflush。DEBUG/TRACE/FASTの切替対象はsetBlock/setBlocks。有限FIFOを共有し後続との順序を保つ。M、`mc_remote/connection.py`、`tests/test_b5.py::test_mode_transition_fences_later_setter_until_flush_succeeds`、`tests/test_b5.py::test_normal_close_automatically_flushes_pending_notification` |
| events cursor／loss | あり | `pollEvents()`がepoch別cursorを保持、検証完了時だけ進める。`EventBatch`のloss累積と後退検出、未知typeの共通項目を検証後に省略。M、`mc_remote/b5_values.py`、`tests/test_b9_fixture.py::test_shared_invalid_state_keeps_previous_cursor_and_loss_totals`、`tests/test_b9_fixture.py::test_loss_totals_reset_on_a_new_epoch_and_never_on_invalid_response` |
| error reason | あり | `McRpcError.code/message/data/reason`。server reasonの値を保持。全reasonを実機で網羅した主張ではない。`mc_remote/connection.py`、`tests/test_b1.py::test_invalid_property_value_error_with_allowed`、`tests/test_b7.py::test_new_server_reasons_project_unchanged_without_retry` |
| build context | あり | `setDimension()` / `setBuildOrigin()`とhelloの正準dimension/origin、失敗時は以前の値を保持。M、`mc_remote/dimension.py`、`tests/test_b1.py::test_build_setter_uses_canonical_result_not_input`、`tests/test_b1.py::test_build_setter_failure_or_invalid_result_preserves_context` |
| BlockValue／BlockSpec | あり | `getBlock(s)`はimmutable値。`setBlock(s)(block_id, state=...)` / `block_spec()`で入力を投影。BlockSpec用のpublic classを必須とする設計ではない。`mc_remote/block_value.py`、M、`tests/test_b5.py::test_getblock_returns_immutable_blockvalue`、`tests/test_b5.py::test_input_rejects_protocol21_ref_and_non_json_state_values` |
| catalog／constants | あり | `getCatalog()` / `sync_constants()`、raw catalog cacheと.py/.pyi生成。M、`mc_remote/catalog.py`、`projection.py`、`_constants_codegen.py`。`tests/test_b3.py::test_sync_constants_cache_hit_skips_fetch`、`tests/test_b3.py::test_codegen_generates_catalog_specific_stub`。詳細は次節 |
| helloの`world_constants` | あり | `Minecraft.world_constants`に辞書を保持、`y_sea`を`Minecraft.y_sea`へ。生成時はnull以外を大文字keyの`world_info`へ。現在の案内・testはy_sea。M、`tests/test_b1.py::test_y_sea_only_from_world_constants`、`tests/test_b3.py::test_codegen_generates_valid_module`。キー追加や新しい意味論の実装は今回していない |
| epoch／reconnect | 部分 | `Connection.reconnect()`は新しいFIFO/id/epoch。認証処理内で利用、イベントcursor・observer targetはepochを区別する。一般の切断後の自動再認証・自動再開はなし。EntityHandleはprefix付きopaque strで、Python値自体に発行epochを結び付けて拒否する仕組みはなく、staleの判定はserverへ委ねる。`mc_remote/connection.py`、M、`mc_remote/b5_values.py`、`tests/test_b2.py::test_enforcement_on_pairs_and_retries`、`tests/test_b9_fixture.py::test_loss_totals_reset_on_a_new_epoch_and_never_on_invalid_response`、`tests/test_wirescope.py::test_reconnect_creates_a_new_target_and_alias` |
| WireScopeのobserver | あり | `Minecraft.create(wirescope=True)` / `WireScopeStation.local()`、sanitized main-stream observerと同梱appのloopback HTTP配信。TTY・同じnetwork namespaceが前提。Notebook向け起動やprocessをまたぐ継続は未実装。`mc_remote/observer.py`、`wirescope.py`、`_wirescope_http.py`、`tests/test_wirescope_station.py::test_station_preflight_starts_loopback_then_opens_secret_free_url`、`tests/test_wirescope.py::test_generation_allowlist_never_serializes_secrets` |

### 補足のclient能力（上の14行とは別）

| 能力 | Python | 根拠 |
| --- | --- | --- |
| eventを建築へ使う前の文脈確認 | あり | `Minecraft.assertEventContext(event)`。現在のdimension/originとの差をlocal例外にし、eventを捨てず状態も変えない。M、`tests/test_b5.py::test_assert_event_context_guards_use_without_mutating_or_discarding_event` |
| context managerで接続を回収 | あり | `with Minecraft.create() as mc:`、本体例外を優先してclose。M、`tests/test_b5.py::test_context_manager_auto_closes_and_preserves_body_exception` |

## catalog／constants：E2比較用の詳細

1. **取得**：`getCatalog()`はdictを返す。main建築streamを使わず、同じendpointへ短命な別streamを開き、保存済み認証でhello（`pair=False`）→`catalog.get`→close。main側helloと別streamのcatalogHashが違えば同期失敗にする。`sync_constants()`はcacheを挟むが、`getCatalog()`そのものは毎回取得する。
2. **raw cache**：`MCREMOTE_CACHE_DIR`、次に`$XDG_CACHE_HOME/mcremote`、既定は`~/.cache/mcremote`。`catalogs/<catalogHash>.json`で保存。接続先名やmc_versionだけでなく、catalog内容のhashがkey。同じMinecraft版でもmod/registry差がhashを変える。tokenのconfig storeとは分離。
3. **検証**：block/entity/particleのbodyをkey順・compact・UTF-8 JSONにしてSHA-256を再計算。schema、block stateの型／許容値／default、helloのhashとの一致を確認。cache欠損・破損・hash不一致はmissとし、再取得。保存は一時fileからatomic replace。TTLやLRUによる自動期限・容量削減は実装していない。
4. **生成**：`sync_constants(target_dir=None, force=False)`。既定の生成先はCWD。`mc_constants.py` / `mc_constants.pyi` / `mc_constants.manifest.json`を作る。runtimeのblock/entity/particle定数はstr、`block_state` builderを生成。.pyiでは`BlockId[TypedDict]`、`Literal`によって接続先catalogのpropertyと候補値を補完・型検査へ投影する。sound/dimensionの定数生成はこのcatalog方式に含まれない。
5. **生成物の更新**：manifestはcatalogHash、generatorVersion、projectionSchemaVersion、projectionKey、.py/.pyiのSHA-256を持つ。lock下で両fileを更新しmanifestを最後のcommit markerとする。途中の失敗では以前の有効な組を戻す。一致する生成物は検証して再利用する。
6. **world_constants**：raw catalog cacheに混ぜず、接続したsessionのhelloを生成へ毎回渡す。null以外のkeyを大文字化して`world_info`を作る。現在の代表は`world_info.Y_SEA`。海面値を座標式の暗黙オフセットにはしない。
7. **入口と失敗**：`Minecraft.create()`は認証後、既定でsyncする。`sync_catalog=False`で省略可。catalogHashが無ければno-op。Git projectでignore規則が不足すると生成せず、`mcremote init`で規則を用意する。自動同期失敗はstage付きwarningで建築を継続、明示`sync_constants()`は例外を返す。`force=True`はcacheがあっても再取得する。

追加の根拠：`tests/test_b3.py::test_compute_catalog_hash_order_independent`、`test_validate_catalog_rejects_hash_mismatch`、`test_cache_corrupt_file_returns_none`、`test_sync_constants_force_refetches`、`test_projection_manifest_has_required_key_and_checksum`、`test_projection_publish_failure_preserves_previous_valid_pair`、`test_missing_ignore_blocks_generation_but_not_building`、`test_create_catalog_failure_warns_and_returns_connected_client`。同fileの各test名。

## 共有fixture 10本の接続状況

全caseのledgerを数えるtestと、Python APIでcaseを投影するtestを区別する。server内部の検索・admission・transactionの記述をPythonで再実装していない。

| toolingのfixture | stableでのtestへの接続 | 根拠／未接続の理由・予定 |
| --- | --- | --- |
| `block-value-v22.json` | なし（copyなし） | blockには`tests/test_b5.py`の独自testがあるが、このJSONには未接続。F1のblock encode/decodeを具体化するときに適用caseを検討する。独自testを共有case全件PASSと数えない。導入日程は未確定 |
| `chat-event-compat-v23.2.1.json` | あり | `tests/test_b9_fixture.py::test_shared_fixture_identity_and_33_case_inventory`、`test_shared_chat_post_success_shape_on_client_and_observer`、`test_shared_event_batches_keep_cursor_losses_and_observer_summary`、`test_shared_invalid_state_keeps_previous_cursor_and_loss_totals`。33caseの投影 |
| `chat-event-compat-v23.2.json` | あり（履歴比較のみ） | `tests/test_b9_fixture.py::test_protocol_23_2_history_is_preserved`。exact hashと、schema/protocol差分以外は23.2.1版と同bytesであることを確認。現行semantic testは23.2.1を使い、履歴版を新しい機能caseとして増やさない |
| `dimensions-v22.json` | なし（copyなし） | `tests/test_b1.py`にdimension入力・正準build contextの独自testがあるが、このJSONは未接続。F1／build contextの共通caseを選ぶ時に検討。期限未確定 |
| `direction-lightning-v23.1.json` | あり | `tests/test_b7.py::test_owner_fixture_identity_protocol_and_93_case_ledger`、`test_direction_four_methods_send_exact_fixture_shapes`、`test_new_server_reasons_project_unchanged_without_retry`等。93caseのledgerとPython/observerの適用部分。serverの内部動作全件の検証ではない |
| `entity-particle-v23.2.1.json` | あり | `tests/test_b8_fixture.py::test_owner_fixture_exact_identity_and_111_case_inventory`、`test_owner_entity_lifecycle_projection`、`test_owner_particle_stage2_projection`、`test_owner_sound_keyword_projection`等。111caseのledgerを確認。N19、H03〜H07のserver内部計算／transactionはclientの実装対象にしない |
| `entity-particle-v23.2.json` | あり（履歴比較のみ） | `tests/test_b8_fixture.py::test_protocol_23_2_history_is_preserved`。case投影は23.2.1版を使い、旧fileのbytesは履歴として保持 |
| `events-v23.json` | あり | `tests/test_b6.py::test_b6_p01_poll_events_decodes_fixture_poll_result`、`test_b6_p02_omits_fixture_legacy_block_right_click_event`。旧fixtureの未知eventは現行の共通field検証後に省略する |
| `sign-v23.json` | あり | `tests/test_b6.py::test_b6_s03_get_sign_sends_and_decodes_fixture_shape`、`test_b6_s04_set_sign_sends_fixture_params`、`test_b6_s05_update_sign_line_sends_fixture_params`等 |
| `spawn-v22.json` | なし（copyなし） | particle/entityの独自testと23.2.1のfixtureを先に消費しており、この旧JSONは未接続。E2/F1で現行caseとの重複・相違を確認して採否を判断する。旧fixture全体のPASSとはしない。期限未確定 |

合計：**7本をcopy、test接続あり（意味の投影5本＋履歴のbyte比較2本）、3本は未接続**。
別ディレクトリ由来の`display-alias-v1.json` / `station-attach-v1.json`、Python自身のfixture等は、このProtocol 10本には含めない。

## fixtureのMIT取得元への固定し直し

- 新しい固定元：`Naohiro2g/minecraft-remote-tooling@21a2a9a0aed8b4d9c715da46616aad86f1174b4c`、`packages/protocol/test/fixtures/`。
- LICENSEは[`tests/fixtures/LICENSE`](../tests/fixtures/LICENSE)へexact bytesで配置。**1,070 bytes / `aa329a0bafc839b95124306141db13a381de45818bf629e983c44ea55ab5a7fb`**。
- ownerの全10本は旧`6447f6e8cbfbeeb9d229990b5c4f6e82a5875666`と同一Git blob。新commitから全10本を実取得してサイズとSHA-256を計測し、copy7本はlocalとの全文bytes一致も確認。
- 7つの`.source.json`のcommitと、consumer testのsource pinだけを更新。fixture JSONの中身・歴史版・case ID・contract commitは変更しない。従来の`ci`は以前のsourceのCIであることを明記し、新commitのrunへ見せ替えない。
- 本LICENSEの適用範囲とcopyの一覧は[`tests/fixtures/README_ja.md`](../tests/fixtures/README_ja.md)。同じdirectory内のWireScope等のfixtureをまとめてMITへ変更するものではない。同梱WireScopeのsource pin、ZIP、detached manifestも維持。

| owner file | bytes | SHA-256（21a2a9aで実取得） | Python |
| --- | ---: | --- | --- |
| `block-value-v22.json` | 3,217 | `e8e108d59c40751d67a432543d75cb4bf9146ef9781721012085c80545b854f3` | copyなし |
| `chat-event-compat-v23.2.1.json` | 32,384 | `eead244a7340c315cb63e1e77ede0fe9cf48162c06fedbeef36d941950d5000d` | copyあり |
| `chat-event-compat-v23.2.json` | 32,382 | `670b0a86df1956c0e44c6986a0a2598caab32c7328804f9c703190e62e9dd727` | copyあり |
| `dimensions-v22.json` | 766 | `44993cce8d42fc8db15822788a2b6707971b5438edfb4eb77d774aad437c0628` | copyなし |
| `direction-lightning-v23.1.json` | 20,367 | `586d24bf40136eec31f1827f23ef5b317f15100a17a635d7fe9f165e0af40dce` | copyあり |
| `entity-particle-v23.2.1.json` | 36,483 | `0319ff8373a96798cf5e9e421a804729fd33a0fa53e96adc12c93ed7994777ae` | copyあり |
| `entity-particle-v23.2.json` | 36,481 | `ca636b4a2685ea67f24d8e7931e3d30a84e7cec872bb5c5d2eadd178cdac39f2` | copyあり |
| `events-v23.json` | 2,112 | `31760d267f3c2641042fbe8595fda9c259134a1c05423271a99cb74da1efa9aa` | copyあり |
| `sign-v23.json` | 5,043 | `7ffb63c264602cba56117eefff1f9604b955df04c5cc655e877772b8ff7cd30e` | copyあり |
| `spawn-v22.json` | 682 | `1120e6c8d41b05b65c916fa96f496b02884123ec7ef59b0a226eea48bebf3abd` | copyなし |

## Phase D：Pythonの開発体験（今回の評価は静的確認）

| 観点 | 今の状態 | 根拠と評価方法／残り |
| --- | --- | --- |
| resourceの発見 | `getCatalog()`、自動生成`block/entity/particle/block_state`からID・state候補を調べられる。任意resourceが静的に全て固定されるわけではない | M、catalog/codegen/projection、`tests/test_b3.py::test_codegen_generates_catalog_specific_stub`。sourceと既存unitの確認。実際の探索操作は今回未評価 |
| 型 | `BlockValue`、`BlockId`、state TypedDict/Literal、SignValue、DirectionValue、NearbyEntity、event dataclass等。player poseはdict、動的str入力も受け付ける。server registryへの存在確認を型だけで保証しない | `mc_remote/block_value.py`、`sign_value.py`、`direction_value.py`、`entity_value.py`、`b5_values.py`、codegen。静的確認。新しいtype checker／IDEの実操作は無し |
| 補完 | .pyiの接続先別ID／property／許容値、API overloadと型注釈が補完の足場。生成先はCWD、Git ignoreが必要。sound/dimensionはこの生成対象外 | projection/codegen、`tests/test_b3.py::test_codegen_generates_catalog_specific_stub`。生成textのtestとsourceの確認まで。IDEで候補が表示されたという今回の主張はしない |
| 編集と実行 | stable READMEのuv導入→.py実行、starterのlocal設定。Notebookはmodule cacheと再起動時の再接続を説明する。未commitの教材・README再編は基準に含めない | `README.md`、`starter/README_ja.md`、`docs/migrate-to-uv_ja.md`。静的確認。cold reader／Jupyter操作は今回未実施。WireScopeの現行起動はTTY前提 |
| 文書／LLM | `scripts/build_client_api_reference.py`で公開signatureからAPI参照を生成しCIで一致検査。Pythonの引数・型・returnを読める。catalogのLLM専用exportは無し | `docs/python-api-reference_ja.md`、上記script、`.github/workflows/ci.yml`。静的確認と通常CI。LLMの利用者評価は未実施 |

## stable基準より後の差分・検証の境界

- 本branchの追加はこのE1文書、fixtureの取得元／LICENSE・範囲説明、source pinのtest同期だけ。runtime・公開API・package版・wire・共有fixtureのpayloadに変更無し。新しいreleaseは作らない。
- 通常workspaceの`work/local-drafts-before-stable-2321@c301053`にはREADME・教材・作例・editable起動修正等の未commit作業が別にある。E1の「あり」判定や本branchの変更に混ぜない。
- stableのWireScope loaderは通常wheelのRECORDを要求し、editable向け局所修正はstable基準に入っていない。Jupyter向け非TTY起動、毎回のコード入力省略、独立station等も未実装。設計メモをAPIとして数えない。
- F1の共有scripted case、F3の実サーバーpulse、IDE操作評価、新しい世界定数の実装は今回の範囲外。共有環境へ接続していない。
- 検証command：`uv lock --check`、`uv run --frozen --with pytest pytest -q`、`uv run --frozen python scripts/build_client_api_reference.py --check`。実施結果とcommit／CIのidentityは返却に添える。

## knowledgeへの返却先

`10-protocol/protocol-inventory_ja.md`のPython列、共有fixture欄、Phase Dの比較入力として返す。E2の分類や共通意味論をPython側で確定しない。
取得元の固定し直しは`2026-10-23-01`に従うconsumer側の更新。正式なknowledge本文の編集・配置はknowledge担当へ返す。
