# Windows 11からPythonクライアントを導入する

Gitを使わず、uvでPyPIからPythonクライアントを取得し、JupyterLabまで進める手順です。
導入する版と対応サーバーは [README](../README.md) で確認してください。
以下は公開beta `2320.0.0b9` を導入する例です。

## 1. uvを入れる

スタートメニューでPowerShellを開き、次を実行します。

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

[uv公式のWindows導入方法](https://docs.astral.sh/uv/getting-started/installation/)です。
完了したらPowerShellを閉じて開き直し、次を実行します。

```powershell
uv --version
```

版番号が表示されれば準備完了です。Python本体はuvが用意します。

## 2. 作業用フォルダを作る

```powershell
cd $env:USERPROFILE
mkdir mc-hello
cd mc-hello
uv init --python 3.13
```

同名のフォルダがある場合は別名にします。Pythonのダウンロードが終わるまで待ちます。

## 3. PyPIから取得してimportを確認する

beta／rcは版を指定します。

```powershell
uv add "minecraft-remote-api==2320.0.0b9"
uv run python -c "from mc_remote import Minecraft; from importlib.metadata import version; print(version('minecraft-remote-api')); print(Minecraft.__name__)"
```

指定した版と`Minecraft`が表示されれば成功です。この確認ではサーバーへ接続しません。

## 4. JupyterLabを開く

```powershell
uv add --dev jupyterlab
uv run jupyter lab
```

ブラウザが開かない場合は、PowerShellに表示されたlocalhostのURLを同じPCのブラウザへ貼り付けます。
Python 3のNotebookを新しく開き、最初のセルで次を実行します。

```python
from mc_remote import Minecraft
from importlib.metadata import version

print(version("minecraft-remote-api"))
print(Minecraft.__name__)
```

指定した版と`Minecraft`が表示されたら、[READMEの接続例](../README.md#step-2-最小コードhellopyを書く)へ進みます。
JupyterLabを終了するときはNotebookを保存し、PowerShellでCtrl+Cを押します。

途中で止まった場合は、実行したコマンド、エラー、Windows・uv・パッケージの版を控えます。
JupyterのURLに含まれるtokenは共有しないでください。

エディタで使う手順は [READMEのJupyter案内](../README.md#jupyter) と
[uv公式のJupyter案内](https://docs.astral.sh/uv/guides/integration/jupyter/)を参照してください。
