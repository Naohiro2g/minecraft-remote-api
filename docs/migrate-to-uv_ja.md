# pyenv／pip／Poetryからuvへの移行ガイド

マイクラリモコンのPython手順は、uvを正準とします（`uv init` → `uv add` → `uv run`）。
このガイドは、これまでpyenv、pip＋venv、Poetryを使っていた人が、手元の環境やプロジェクトをuvへ移すためのものです。

uvは、Python本体の導入、仮想環境の作成、パッケージの追加、ロックファイルによる再現を1つのコマンドで扱います。
python.orgがWindows用インストーラーを出さなくなったセキュリティ修正版（例：3.11.10以降）も、uvなら
`uv python install` で入ります。

## 1. uvを入れる

[公式のインストール手順](https://docs.astral.sh/uv/getting-started/installation/) に従います。

```bash
# macOS / Linux / WSL2
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. 旧コマンドとの対応表

| やりたいこと | pyenv／pip＋venv | Poetry | uv |
| --- | --- | --- | --- |
| Pythonを入れる | `pyenv install 3.13` | （pyenv等に任せる） | `uv python install 3.13` |
| プロジェクトのPythonを固定する | `pyenv local 3.13`（`.python-version`） | `poetry env use 3.13` | `uv python pin 3.13`（`.python-version`） |
| プロジェクトを作る | `mkdir` ＋ `python -m venv .venv` | `poetry new` / `poetry init` | `uv init --python 3.13 <名前>` |
| パッケージを追加する | `pip install <pkg>` | `poetry add <pkg>` | `uv add <pkg>` |
| 開発用のパッケージを追加する | `pip install <pkg>` | `poetry add --group dev <pkg>` | `uv add --dev <pkg>` |
| パッケージを外す | `pip uninstall <pkg>` | `poetry remove <pkg>` | `uv remove <pkg>` |
| 依存を再現する | `pip install -r requirements.txt` | `poetry install` | `uv sync` |
| スクリプトを実行する | `source .venv/bin/activate` → `python hello.py` | `poetry run python hello.py` | `uv run hello.py` |
| ロックファイル | （`pip freeze > requirements.txt`） | `poetry.lock` | `uv.lock`（`uv lock`） |
| 一時的にツールを使う | `pipx run <tool>` | — | `uvx <tool>` |

`uv run` は、実行の前に仮想環境を `pyproject.toml` と `uv.lock` に合わせます。`activate` は不要です。

## 3. 既存のものから移る

### pyenvで入れたPythonを使っていた場合

pyenvは消さなくてかまいません。uvは自分で入れたPythonを優先して使います。
プロジェクトごとに `uv init --python 3.13` か `uv python pin 3.13` で版を固定すれば、pyenvの設定とは衝突しません。

### venvと`pip install`だけで使っていた場合

依存が少なければ、新しくプロジェクトを作り直すのが一番簡単です。

```bash
uv init --python 3.13 mc-hello
cd mc-hello
uv add "minecraft-remote-api @ git+https://github.com/Naohiro2g/minecraft-remote-api.git@v2301.0.0b7.post2"
```

古い `.venv` フォルダは削除してかまいません。uvが作り直します。

### `requirements.txt`がある場合

```bash
uv init --python 3.13
uv add -r requirements.txt
```

`requirements.txt` の中身が `pyproject.toml` の依存へ移り、`uv.lock` が作られます。以後は `requirements.txt` を手で更新しません。

### Poetryのプロジェクトの場合

移行ツール [migrate-to-uv](https://github.com/osprey-oss/migrate-to-uv) を使うと、`pyproject.toml` のPoetry固有の書き方（`^` 指定など）をPEP 621の標準形へ変換し、`poetry.lock` の版を保ったまま `uv.lock` を作ります。

```bash
cd <Poetryのプロジェクト>
git status          # 変更がコミット済みであることを確認してから
uvx migrate-to-uv
uv sync
```

変換結果は `git diff` で確認してください。`poetry.lock` は不要になります。
依存の少ない学習用プロジェクトなら、ツールを使わず `uv init` から作り直しても手間は変わりません。

## 4. VS Codeで使う

VS Codeは、プロジェクトの `.venv` を自動で見つけます。見つからないときは、コマンドパレットの「Python: インタープリターを選択」から `.venv` を選びます。
Jupyter Notebookで使う手順は、[README の Jupyter の節](https://github.com/Naohiro2g/minecraft-remote-api#jupyter) を見てください。
