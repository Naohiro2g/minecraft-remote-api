# Windows 11からB8を導入する

クリーンインストールのWindows 11で、Gitを入れずにuv、B8のwheel、JupyterLabまで導入する手順です。
対象は公開済みの `2320.0.0b8` です。実行担当はhuman owner（プロジェクトオーナー）です。
2026-10-05にhuman ownerから、この入口ルートを問題なく完了したとの報告を受領しました。
環境はWindows 11、uv `0.12.23`（`46b84fd0b`、`x86_64-pc-windows-msvc`）です。
Jupyterのimportと版表示、PowerShellでのpackage情報が報告されています。
以下の確定したRelease wheelのURLで進めます。

## 1. uvを入れる

スタートメニューで「PowerShell」を開き、次を実行します。

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

[uv公式のWindows導入方法](https://docs.astral.sh/uv/getting-started/installation/)です。
完了したらPowerShellを閉じて開き直し、次を実行します。

```powershell
uv --version
```

版番号が出れば次へ進みます。Pythonを別に入れる必要はありません。

## 2. 作業用フォルダを作る

既存のプロジェクトを使わず、新しいフォルダで始めます。

```powershell
cd $env:USERPROFILE
mkdir mc-b8-entry
cd mc-b8-entry
uv init --python 3.13
```

同名のフォルダがある場合は別名にします。Pythonのdownloadを求められた場合は完了を待ちます。

## 3. 公開済みのB8 wheelを追加する

次をそのまま実行します。

```powershell
$b8WheelUrl = 'https://github.com/Naohiro2g/minecraft-remote-api/releases/download/v2320.0.0b8/minecraft_remote_api-2320.0.0b8-py3-none-any.whl'
uv add $b8WheelUrl
```

`pyproject.toml` と `uv.lock` が作業用フォルダにあり、追加が成功したことを確認します。
版を変えたURLやsource checkoutへ置き換えず、指定されたwheelで続けます。

## 4. Importを確認する

```powershell
uv run python -c "from mc_remote import Minecraft; from importlib.metadata import version; print(version('minecraft-remote-api')); print(Minecraft.__name__)"
```

`2320.0.0b8` と `Minecraft` が出れば成功です。この操作でMinecraftのserverには接続しません。

## 5. JupyterLabを追加して開く

```powershell
uv add --dev jupyterlab
uv run jupyter lab
```

ブラウザが開かない場合は、PowerShellに出たlocalhostのURLを同じPCのブラウザへ貼り付けます。
JupyterLabでPython 3のNotebookを新しく開き、最初のセルに次を入れて実行します。

```python
from mc_remote import Minecraft
from importlib.metadata import version
print(version("minecraft-remote-api"))
print(Minecraft.__name__)
```

`2320.0.0b8` と `Minecraft` が表示されたら完了です。終了時はNotebookを保存し、PowerShellでCtrl+Cを押して
JupyterLabを止めます。[uv公式のJupyter案内](https://docs.astral.sh/uv/guides/integration/jupyter/)も参照できます。

## 途中で止まった場合

失敗した手順番号、command、error、Windowsとuvの版、指定wheelの版、Git未導入であることを記録します。
localhost URLに含まれるJupyter tokenを公開記録へ貼らないでください。
成功した場合も、PowerShellとNotebook両方のimport結果を記録します。

Gitなしのルートが通らなければ、knowledge coordinatorへ結果を返して、
[Git for Windows](https://gitforwindows.org/)を入れる正準の通常ルートへ進みます。
通常ルートの開始は [READMEのスターター手順](../README.md#本格的な学習とスターターstarter) を使います。
その場合も試験用のsource commitと接続先はcoordinator指定に合わせ、入口ルートの結果と分けて記録します。
