# Windows 11からB8を導入する

クリーンインストールのWindows 11で、Gitを入れずにuv、B8のwheel、JupyterLabまで導入する手順です。
実行担当はknowledge coordinatorが指定します。この手順のWindows実機検証は未実施です。
試験開始前に、coordinatorから凍結したRelease wheelのURLと版を受け取ってください。
URLがまだない場合は、手順3で止めます。

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

## 3. 凍結したwheelを追加する

下の山括弧を含む文字列全体を、受け取ったHTTPSのwheel URLに置き換えます。

```powershell
$b8WheelUrl = '<coordinatorから受け取ったRelease wheelのURL>'
uv add $b8WheelUrl
```

`pyproject.toml` と `uv.lock` が作業用フォルダにあり、追加が成功したことを確認します。
版を変えたURLやsource checkoutへ置き換えず、指定されたwheelで続けます。

## 4. Importを確認する

```powershell
uv run python -c "from mc_remote import Minecraft; from importlib.metadata import version; print(version('minecraft-remote-api')); print(Minecraft.__name__)"
```

指定されたB8の版と `Minecraft` が出れば成功です。この操作でMinecraftのserverには接続しません。

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

指定版と `Minecraft` が表示されたら完了です。終了時はNotebookを保存し、PowerShellでCtrl+Cを押して
JupyterLabを止めます。[uv公式のJupyter案内](https://docs.astral.sh/uv/guides/integration/jupyter/)も参照できます。

## 途中で止まった場合

失敗した手順番号、command、error、Windowsとuvの版、指定wheelの版、Git未導入であることを記録します。
localhost URLに含まれるJupyter tokenを公開記録へ貼らないでください。
成功した場合も、PowerShellとNotebook両方のimport結果を記録します。

Gitなしのルートが通らなければ、knowledge coordinatorへ結果を返して、
[Git for Windows](https://gitforwindows.org/)を入れる正準の通常ルートへ進みます。
通常ルートの開始は [READMEのスターター手順](../README.md#本格的な学習とスターターstarter) を使います。
その場合も試験用のsource commitと接続先はcoordinator指定に合わせ、入口ルートの結果と分けて記録します。
