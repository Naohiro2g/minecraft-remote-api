# McRemote Python starter（protocol 23.0.0 / package 2300.0.0b6）

この starter では、最初の接続によってブロック名の補完を獲得する変化を観察します。

source checkoutのrootで`uv sync --frozen`を済ませてから、このdirectoryで実行します。
現行公開betaの取得から始める場合は、top-level [`README.md`](../README.md) の
「Current beta quick start」を使ってください。

## 1. 環境設定を用意する

```bash
cp param_mc_remote.template.py param_mc_remote.py
```

公式 sandbox を使う場合、コピー後の変更は不要です。別のサーバーや建築原点を使う場合だけ
`param_mc_remote.py` を編集します。このファイルは Git 管理外なので、同じプログラムを共有しても
ディレクトリごとの接続先は混ざりません。

## 2. 接続前を観察する

`hello.py` の次の行から、先頭の `#` と空白を一度だけ外します。

```python
from mc_constants import block
```

エディタの unresolved import 警告、`block.` の候補が出ないこと、実行すると
`ModuleNotFoundError` で止まることを確認します。確認後は、行をもう一度コメントに戻します。

## 3. Hello World を実行する

```bash
uv run python hello.py
```

初回は表示された pairing command を Minecraft 内で実行します。接続に成功すると、chat に
メッセージが出て sea lantern が1個置かれ、同時に `mc_constants.py` と manifest が生成されます。
sea lanternはstarter座標`(5, 67, 5)`に残ります。不要になったら、接続済みのコードから
`mc.setBlock(5, 67, 5, "air")`を実行して除去してください。

## 4. 接続後を観察する

エディタを必要に応じて reload し、`with_completion.py` を開きます。今度は import が解決し、
`block.` と `world_info.` の補完が出ます。

```bash
uv run python with_completion.py
```

最初の sea lantern の隣に gold block が置かれます。補完用ファイルは接続先から得る一時生成物で、
この starter の `.gitignore` により commit されません。

この例はstarter座標`(6, 67, 5)`と`(7, 67, 5)`を変更したまま残します。観察後は、同じ
接続／build originでそれぞれを`air`へ戻せます。

## 5. 現行b6のsignを試す

```bash
uv run python b6_sign.py
```

このconcept sampleは`world.setBlock`、`world.setSign`、`world.getSign`を使います。
starter座標`(8, 67, 5)`へstanding oak signを置き、front 4行を表示して読み返します。
Enterを押すか途中で中断すると、`finally`でその位置をairへ戻します。

- 最小version: protocol `23.0.0` / package `2300.0.0b6`
- 実行mode: `DEBUG`（既定）
- 出力先: `REAL`
- world変更: 実行中だけsignを1個設置
- cleanup: `finally`で自動実行
- 利用API: `setBuildOrigin()`、`setBlock()`、`setSign()`、`getSign()`
- 成熟状態: 公開済みb6 APIのREADME隣接example
