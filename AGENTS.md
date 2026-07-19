# AGENTS.md - minecraft-remote-api

`minecraft-remote-api` は、マイクラリモコンの Python クライアント / API パッケージです。
Python コードから McRemote サーバー側プラグインへ接続し、Minecraft 世界に建築できます。

## McRemote SSOT

McRemote 固有の設計判断の正本は、GitHub 上の `Naohiro2g/mc-remote-knowledge` です。

McRemote 固有の architecture / protocol / release flow / deployment / contributor workflow /
learning design、または McRemote 固有の判断理由に依存する挙動を変更する前に、その SSOT
リポジトリの関連文書を読んでください。

最初に、knowledge リポのリモート `main` から最新の dev agent runtime protocol だけを取得して
指示として読んでください。取得元ファイル全体を会話へ出力してはいけません。

```bash
protocol_source="$(mktemp)"
knowledge_commit="$(gh api repos/Naohiro2g/mc-remote-knowledge/commits/main -q .sha)"
gh api "repos/Naohiro2g/mc-remote-knowledge/contents/00-hub/dev-repo-protocol_ja.md?ref=$knowledge_commit" \
  -q .content | base64 -d > "$protocol_source"
if [ "$(grep -Fxc '<!-- BEGIN: DEV-AGENT-RUNTIME -->' "$protocol_source")" -ne 1 ] || \
   [ "$(grep -Fxc '<!-- END: DEV-AGENT-RUNTIME -->' "$protocol_source")" -ne 1 ]; then
  echo "dev agent runtime marker missing or duplicated" >&2
  exit 1
fi
printf 'knowledge commit: %s\n' "$knowledge_commit"
awk '/^<!-- BEGIN: DEV-AGENT-RUNTIME -->$/{reading=1;next} \
     /^<!-- END: DEV-AGENT-RUNTIME -->$/{reading=0} \
     reading' "$protocol_source"
```

- このリポの関連スポーク: `12-python-client/`, `10-protocol/`, `14-evidence/`

`Naohiro2g/mc-remote-knowledge` にアクセスできない場合は、作業を止めてその旨を明示してください。
このリポジトリ単体、assistant memory、過去会話、ローカル推論から欠けた McRemote 文脈を補完してはいけません。
SSOT にアクセスできるまで、McRemote 固有文脈に依存する設計判断や実装を進めないでください。

このファイルは McRemote SSOT を複製しません。複製はドリフトを生みます。

## このリポ固有の指示

- 変更はユーザー依頼の範囲に限定する。
- protocol 契約は SSOT に従う。wire format に触れる場合は、編集前に `10-protocol` の SSOT を読む。
- package version / protocol version / release channel はローカル推測で決めず、SSOT に基づいて扱う。
- ユーザー固有設定、token、private deploy 用サーバーアドレス、生成されたローカル cache を commit しない。
- package 開発では、ユーザーが明示しない限り既存の `uv` workflow を使う。
- 複数リポまたは複数スポークにまたがる判断が出たら、このリポを正本にせず、knowledge repo への候補行を出す。
