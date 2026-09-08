# minecraft-remote-api

マイクラリモコン（Minecraft Remote / mc-remote）のための公式Pythonクライアント／APIパッケージです。Pythonコードを書いて、最新のマインクラフトの世界を自由にプログラミング・自動建築できます。

> [!NOTE]
> **🌐 言語方針について / Language Policy**  
> 本リポジトリは、一次情報（SSOT）の鮮度と正確性を保つため、日本語を正本として記述しています。多言語参加やIssue/PRの利用方針については [主要言語についての方針転換 / Language Policy](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/LANGUAGE_POLICY.md) をご覧ください。  
> *This repository is maintained in Japanese as its primary Single Source of Truth (SSOT). Multi-language contributions are welcome. Please see our [Language Policy](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/LANGUAGE_POLICY.md).*

---

## 3分で動かす（最短クイックスタート）

前提: Python 3.10以上、およびマインクラフト（Java版 1.21.1 推奨）が起動していること。

### Step 1: パッケージのインストール

```bash
pip install minecraft-remote-api
```

*(開発やソースコードから動かす場合は `uv sync` を推奨します)*

### Step 2: 最小コード（`hello.py`）を作成

```python
from mc_remote import Minecraft

# 公式箱庭サーバーまたは自前サーバーに接続
mc = Minecraft.create(address="sb-beta.mc-remote.com", port=25575)

# 建築原点とプレイヤー位置の設定
mc.setBuildOrigin(200, 0, 200)
mc.setPos(200, 100, 200)

# チャットを送信し、ブロックを1個置く（原点からの相対座標で (205, 67, 205) に置かれます）
mc.postToChat("Hello, Minecraft from Python!")
mc.setBlock(5, 67, 5, "sea_lantern")
print("マインクラフトの世界にブロックを置きました！")
```

### Step 3: 実行とペアリング

```bash
python hello.py
```

1. 実行すると、ターミナルに `/mcremote pair NNN-NNN`（数字6桁）が表示されます。
2. マインクラフトのゲーム内チャットを開き、そのコマンドを貼り付けてEnterキーを押します。
3. チャットに `Hello, Minecraft from Python!` と表示され、座標 `(205, 67, 205)`（原点 `(200, 0, 200)` ＋ 相対座標 `(5, 67, 5)`）にシーランタン（海のランタン）が光れば成功です！

---

## 本格的な学習とスターター（`starter/`）

環境を安全に分離し、VS Code等のエディタで **ブロック名やアイテム名の自動補完（IntelliSense）** を獲得するための公式スターターキットが用意されています。

```bash
git clone https://github.com/Naohiro2g/minecraft-remote-api.git
cd minecraft-remote-api/starter
cp param_mc_remote.template.py param_mc_remote.py
python hello.py
```

- **環境アダプター (`param_mc_remote.py`)**: サーバー接続先や建築原点をプログラム本体から分離します（Git管理外）。
- **生きたカタログ補完 (`mc_constants`)**: 初回接続時に接続先サーバーのブロック定義を自動取得し、Pythonコード内で `block.SEA_LANTERN` のような正確な型補完が効くようになります。
- 詳しい段階的学習法は [`starter/README_ja.md`](starter/README_ja.md) をご覧ください。

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
- **現行バージョン**: `2301.0.0b7.post2`（Protocol 23.1.0 準拠）
- **対応マインクラフト**: Java版 1.21.1（Paper 26.x対応準備中）
- **接続先**:
  - 公式箱庭（サンドボックス）サーバー: `sb-beta.mc-remote.com:25575`
  - 自前サーバー: PaperMC サーバーに [McRemote プラグイン](https://github.com/Naohiro2g/McRemote) を導入して起動
- **コミュニティ & サポート**: [Discord サーバー](https://discord.gg/xUqhhqWsuS) 内の `#mc-remote-chat` チャンネル

---

## 関連プロジェクト & 設計思想

- **プロジェクト公式サイト**: [mc-remote.com](https://mc-remote.com/)（カリキュラム全体像、Web版Scratchエディタ、開発ロードマップ）
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

### ライセンス

- Python クライアントコード本体: **MIT License**
- 同梱 WireScope browser app (`@mc-remote/live`): **AGPL-3.0-only**
  - ソースコード、ライセンス条項、アセットハッシュ値の検証データは [GitHub Releases](https://github.com/Naohiro2g/minecraft-remote-api/releases) および [`LICENSE`](LICENSE) を参照してください。
