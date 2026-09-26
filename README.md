# minecraft-remote-api

マイクラリモコン（Minecraft Remote / mc-remote）のための公式Pythonクライアント／APIパッケージです。Pythonコードを書いて、最新のマインクラフトの世界を自由にプログラミング・自動建築できます。

> [!NOTE]
> **🌐 言語方針について / Language Policy**  
> 本リポジトリは、一次情報（SSOT）の鮮度と正確性を保つため、日本語を正本として記述しています。多言語参加やIssue/PRの利用方針については [主要言語についての方針転換 / Language Policy](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/LANGUAGE_POLICY.md) をご覧ください。  
> *This repository is maintained in Japanese as its primary Single Source of Truth (SSOT). Multi-language contributions are welcome. Please see our [Language Policy](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/LANGUAGE_POLICY.md).*

---

## 3分で動かす（最短クイックスタート）

前提: [uv](https://docs.astral.sh/uv/getting-started/installation/) がインストールされていること。Python本体はuvが用意します。

### Step 1: プロジェクトを作り、モジュールを追加

```bash
uv init --python 3.13 mc-hello
cd mc-hello
uv add https://github.com/Naohiro2g/minecraft-remote-api/releases/download/v2301.0.0b7.post3/minecraft_remote_api-2301.0.0b7.post3-py3-none-any.whl
```

現在は、新プロトコル版がPyPIに未登録なので、GitHub.comのリリースに添付されたパッケージを使います。

### Step 2: 最小コード（`hello.py`）を書く

`mc-hello` フォルダの `main.py` は使わないので削除してかまいません。`hello.py` を作ります。

```python
from mc_remote.minecraft import Minecraft
# 公式箱庭サーバー（ベータ）に接続
mc = Minecraft.create(address="sb-beta.mc-remote.com", port=25575)

# 建築原点の設定
mc.setBuildOrigin(200, 0, 200)

# チャット送信
mc.postToChat("Hello, Minecraft from Python!")

# プレイヤー位置、視線方向の設定
mc.setPos("overworld", 30, 120, 30)  # (230, 120, 230) に移動
mc.setDirection(-1, -2, -1)

# ブロック設置
# 建築原点からの相対計算で実際は (205, 67, 205) に置かれます。
mc.setBlock(5, 67, 5, "sea_lantern")
```

### Step 3: 実行とペアリング

```bash
uv run hello.py
```

ターミナルに表示される `/mcremote pair NNN-NNN` をゲーム内チャットに貼り付け、Enterを押すと認証が完了します。認証は2時間有効です。チャットに `Hello, Minecraft from Python!` と表示され、`(205, 67, 205)` にシーランタンが光れば成功です。

---

<a id="jupyter"></a>

## Jupyter Notebookで1行ずつ実行する

コードを1行ずつ実行して、マイクラの世界がどう変わるかを確かめながら進められます。Step 1で作った `mc-hello` フォルダで作業します。

### VS Codeで使う

1. ノートブックの実行に必要なカーネルを、開発用の依存として追加します。

   ```bash
   uv add --dev ipykernel
   ```

2. VS Codeに拡張機能「Jupyter」（Microsoft）を入れ、`mc-hello` フォルダを開きます。
3. `hello.ipynb` などのノートブックを作り、右上の「カーネルの選択」→「Python環境」から `mc-hello` の `.venv` を選びます。
4. セルに `hello.py` の内容を分けて書き、1つずつ実行します。ペアリング用の `/mcremote pair NNN-NNN` はセルの出力に表示されます。

### JupyterLabで使う

```bash
uv add --dev jupyterlab
uv run jupyter lab
```

ブラウザでJupyterLabが開きます。新しいノートブックを作れば、`mc-hello` の環境でそのまま実行できます。

### `.py` を書き換えたら、カーネルを再起動する

ノートブックは、一度 import したモジュールを覚えています。自分で作った `.py` や `mc_remote` 自体を書き換えたら、**カーネルを再起動**（VS Code・JupyterLabとも「Restart」）してから、import のセルから実行し直してください。再起動しないと、書き換える前のコードが動き続けます。

---

## 本格的な学習とスターター（`starter/`）

環境を安全に分離し、VS Code等のエディタで **ブロック名やアイテム名の自動補完（IntelliSense）** を獲得するための公式スターターキットが用意されています。

```bash
git clone https://github.com/Naohiro2g/minecraft-remote-api.git
cd minecraft-remote-api
uv sync --frozen
cd starter
cp param_mc_remote.template.py param_mc_remote.py
uv run python hello.py
```

- **環境アダプター (`param_mc_remote.py`)**: サーバー接続先や建築原点をプログラム本体から分離します（Git管理外）。
- **生きたカタログ補完 (`mc_constants`)**: 初回接続時に接続先サーバーのブロック定義を自動取得し、Pythonコード内で `block.SEA_LANTERN` のような正確な型補完が効くようになります。
- 詳しい段階的学習法は [`starter/README_ja.md`](https://github.com/Naohiro2g/minecraft-remote-api/blob/main/starter/README_ja.md) をご覧ください。

---

## 主な機能と作例

- **チャットとプレイヤー操作**: `mc.postToChat()`, `mc.getPos()`, `mc.setPos()`, `mc.getDirection()`, `mc.setDirection()`
- **ブロックの設置と取得**: `mc.setBlock()`, `mc.getBlock()`, `mc.setBlocks()`
- **看板の読み書き**: `mc.setSign()`, `mc.getSign()`, `mc.updateSignLine()`
- **演出とイベント**: `mc.spawnParticle()`, `mc.strikeLightning()`, `mc.pollEvents()`（ツルハシで叩いた検知など）
- **高速建築モード**: `DEBUG`（1行ずつ確認）、`TRACE`（動作を観察）、`FAST`（超高速建築）

---

## パッケージ情報 & 対応環境

- **パッケージ名**: `minecraft-remote-api`（インポート名: `mc_remote`）
- **現行バージョン**: `2301.0.0b7.post3`（Protocol 23.1.0 準拠）
- **対応Python**: 3.10〜3.13（標準は3.13）
- **対応マインクラフト**: Java版 1.21.11（Paper 26.x対応準備中）
- **接続先**:
  - 公式箱庭（サンドボックス）サーバー: `sb-beta.mc-remote.com:25575`
  - 自前サーバー: PaperMC サーバーに [McRemote プラグイン](https://github.com/Naohiro2g/McRemote) を導入して起動
- **コミュニティ & サポート**: [Discord サーバー](https://discord.gg/xUqhhqWsuS) 内の `#mc-remote-chat` チャンネル

---

## 関連プロジェクト & 設計思想

- **プロジェクト公式サイト**: [mc-remote.com](https://mc-remote.com/)（探究の全体像、Web版Scratchエディタ、開発ロードマップ）
- **ナレッジベース & 設計正本 (SSOT)**: [Naohiro2g/mc-remote-knowledge](https://github.com/Naohiro2g/mc-remote-knowledge)
  - Pythonクライアント設計仕様: [`12-python-client/`](https://github.com/Naohiro2g/mc-remote-knowledge/tree/main/12-python-client)
  - プロトコル仕様: [`10-protocol/`](https://github.com/Naohiro2g/mc-remote-knowledge/tree/main/10-protocol)
  - 決定ログ: [`00-hub/DECISIONS_ja.md`](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/00-hub/DECISIONS_ja.md)

---

## 開発者向け情報・ライセンス

### 開発環境のセットアップ (uv)

```bash
git clone https://github.com/Naohiro2g/minecraft-remote-api.git
cd minecraft-remote-api
uv sync
```

pyenv／pip／Poetryを使っていた方は [uvへの移行ガイド](https://github.com/Naohiro2g/minecraft-remote-api/blob/main/docs/migrate-to-uv_ja.md) をご覧ください。

### ライセンス

- Python クライアントコード本体: **MIT License**
- 同梱 WireScope browser app (`@mc-remote/live`): **AGPL-3.0-only**
  - ソースコード、ライセンス条項、アセットハッシュ値の検証データは [GitHub Releases](https://github.com/Naohiro2g/minecraft-remote-api/releases) および [`LICENSE`](https://github.com/Naohiro2g/minecraft-remote-api/blob/main/LICENSE) を参照してください。
