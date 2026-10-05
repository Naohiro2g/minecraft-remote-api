# Python APIの利用例

PyPIからの導入と対応サーバーの案内は [README](../README.md) を参照してください。
Pythonの呼び出し方・引数・戻り値を探すには [クライアントAPI一覧（ドラフト）](python-api-reference_ja.md) を参照してください。
公開APIの全体像は [Protocol API一覧](https://mc-remote.com/api/) から確認できます。掲載対象のreleaseはページ冒頭に表示されています。
一覧は通信上の名前・引数・応答を載せています。Pythonの `mc.playSound()` などの書き方は、このガイドの作例を参照してください。
引数・error・数値規則の正本は [wire §5.0.2／§5.8.3](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/10-protocol/wire-format-design_ja.md) です。

## Importとpygame

`from mc_remote import Minecraft` を使います。
Jupyterでモジュールを更新したらカーネルを再起動し、importと接続をやり直してください。

pygameを使う教材では `uv add pygame-ce` で追加できます。
パッケージのextraを使う場合は、導入する版も指定します。公開betaを選ぶ例:

```bash
uv add "minecraft-remote-api[pygame]==2320.0.0b9"
```

extraは `pygame-ce>=2.5` を指定します。本家の `pygame` と同時に入れないでください。

## Resource ID

block、particle、entity、soundは `stone`、`flame`、`pig`、`entity.cow.ambient` のような
`minecraft:` なしのIDも使えます。Pythonは入力をそのまま送り、serverがnamespaceを補います。
`ParticleSpec` の `particle_id` とdata内の `block_id` にも適用します。
大文字、空文字、不正なコロン、前後の空白は補正しません。serverから返るIDは完全修飾です。

## 音を鳴らす

```python
mc.playSound(0.25, 3, 0.5, "entity.cow.ambient")
mc.playSound(0, 3, 0, "block.note_block.harp", volume=0.5, note=12, receiver="self")
mc.playBlockSound(0, 0, 0, "hit", receiver="self")
```

`playSound()` は連続座標、`playBlockSound()` は整数のblock座標で、どちらも建築原点からの相対位置です。
kindは `place`／`hit`／`break`／`step`／`fall`。volume、pitch、note、receiverはキーワード専用引数です。volumeは0〜1、
pitchは0.5〜2、noteは整数0〜24（12は倍率1）。pitchとnoteの両方を指定すると、送信前に `ValueError` になります。
receiverは省略時 `world`、`self` はpairingしたplayerだけです。

volume、pitch、noteの既定値は `None` で、その項目を送らずserverの既定を使います。
通常の音はvolume／pitchとも1.0です。blockの音は省略した項目ごとに
SoundGroupの元のvolume／pitchを使い、pitch／noteの指定はその高さを置き換えます。
座標に0.5を足す処理や音の高さの補正はPythonでは行いません。
`None` は省略として扱い、`note=0` や `volume=0` はそのまま送ります。
音名（ドレミ、C4など）はユーザーコードでnoteへ換算します。
変数のdictからキーワード引数を渡すときは `**controls` と書きます。
数値の範囲とselfの認証はserverが判定します。
結果は `None`。`unknown_sound`、`no_block`、`backpressure` などは `McRpcError.reason` で確認できます。
自動再試行は行いません。

Windowsから始める場合は [Windows 11導入手順](windows-install_ja.md) を参照してください。

## Entityの検索・移動・削除

```python
nearby = mc.getNearbyEntities(0, 0, 0, radius=16, max_entities=8)
for entity in nearby:
    print(entity.handle, entity.type, entity.pos)

handle = mc.spawnEntity(0, 2, 0, "minecraft:armor_stand")
try:
    pose = mc.getEntityPose(handle)
    x, y, z = pose["pos"]
    moved = mc.setEntityPose(handle, pose["dimension"], x + 1, y, z, 45, 0)
    print(moved)
finally:
    mc.removeEntity(handle)
```

座標はこの接続の建築原点からの相対位置です。近傍検索はplayerを除外し、chunkをloadせず、
距離順の `NearbyEntity` のtupleを返します。半径は0〜64、件数は1〜64で、serverの設定によって
さらに小さい上限になる場合があります。一覧はsnapshotであり、次の操作までにentityが消えることもあります。

Poseはplayerの `getPose()` と同じ `{dimension, pos, yaw, pitch}` のdictです。
`setEntityPose()` は入力を丸めず送信し、移動後にserverが読み直したposeを返します。
dimension移動に成功してもhandleは維持されます。建築dimension・原点は変わりません。
handleは取得した接続だけで使い、再接続後は取り直します。削除後のhandleは即時失効します。
`entity_not_found`、`entity_unavailable`、`entity_dimension_changed`、`teleport_failed`、
`backpressure` などのserver errorは `McRpcError.reason` で確認できます。自動再試行は行いません。

## Particleの色と表示先

particle ID文字列、または`ParticleSpec`のdictを渡せます。

```python
from mc_remote.minecraft import ParticleSpec

dust: ParticleSpec = {
    "particle_id": "minecraft:dust",
    "receiver": "self",
    "data": {"color": [64, 160, 255], "size": 1.0},
}
mc.spawnParticle(0, 3, 0, 0, 0, 0, dust, 0, 1)

mc.spawnParticle(1, 3, 0, 0, 0, 0, {
    "particle_id": "minecraft:block",
    "data": {"block_id": "minecraft:oak_log", "state": {"axis": "y"}},
}, 0, 1, False)
```

receiverを省略すると `world`、`self` はpairingしたplayerだけへ配送します。
RGBは0〜255の整数3個、sizeは0.01〜4.0です。block dataは既存のBlockSpecです。
data省略と `data=None` は異なり、後者はserverの `invalid_params` になります。
data必須のparticleでは `particle_data_required`、未対応のdata型では
`particle_data_unsupported` を返します。ID・data・receiverの判定はserverに委ね、errorの優先順を保ちます。
force省略と明示booleanの違いもそのまま送信します。

## 3D graphサンプル

[particle_graph.py](../examples/particle_graph.py) は、playerの足元を原点にして
`y = 3 + 2 sin(sqrt(x² + z²))` を81点の青いdustで描きます。
`examples/param_mc_remote.py` の接続設定を用意し、対応するMcRemoteサーバーへ接続して実行します。

```bash
uv run python examples/particle_graph.py
```

初回は表示されるpair commandをMinecraft内で実行します。描画範囲は原点からX/Z ±4、Y 1〜5です。
表示はself向けで、blockやentityは変更せず、粒子は自然に消えます。
単点RPCを81回送り、自動再描画や自動retryは行いません。
`spawnParticle()` は `FAST` でも応答を待つrequestです。
