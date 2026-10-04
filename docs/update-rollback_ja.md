# Pythonクライアントの更新と元の版への復帰

公開済みReleaseのwheelを使うuv project向けの手順です。
更新先は[GitHub Releases](https://github.com/Naohiro2g/minecraft-remote-api/releases)と対応serverの案内で選び、
candidateやbranchの最新版を公開版の代わりに指定しないでください。
PyPIからの取得は、公開後の[PyPI案内](pypi-publication_ja.md)を参照してください。

## 1. 現在の環境を控える

Pythonのプログラムを終了し、Notebookでは必要なら`mc.close()`してからkernelとJupyterLabを止めます。
作業用projectのPowerShellで、現在の版を確認します。

```powershell
uv run python -c "from importlib.metadata import version; print(version('minecraft-remote-api'))"
```

`pyproject.toml`と`uv.lock`を、更新前の組として退避します。
次のfolderが既にある場合は、別の新しい名前を使います。

```powershell
mkdir .mcr-before-update
Copy-Item pyproject.toml .mcr-before-update/pyproject.toml
Copy-Item uv.lock .mcr-before-update/uv.lock
```

## 2. 指定した公開wheelへ更新する

ReleaseのAssetsからwheelのURLをコピーし、次の`<公開wheelのURL>`を置き換えます。

```powershell
uv add '<公開wheelのURL>'
uv run python -c "from mc_remote import Minecraft; from importlib.metadata import version; print(version('minecraft-remote-api')); print(Minecraft.__name__)"
```

指定した版と`Minecraft`が表示されることを確認します。このimport確認ではserverへ接続しません。
Jupyterを使う場合は`uv run jupyter lab`で再開し、新しいkernelで同じimportを確認します。
その後、対応するserverへ接続します。保存済みの接続設定とtokenは、そのまま利用します。

`uv add`は依存の取得元を更新し、projectとlockを同期します。
挙動の詳細は[uvの依存変更](https://docs.astral.sh/uv/concepts/projects/dependencies/#changing-dependencies)を参照してください。

## 3. 更新前の環境へ戻す

プログラムとkernelを再び終了し、手順1で保存した2fileを組で戻します。

```powershell
Copy-Item .mcr-before-update/pyproject.toml pyproject.toml
Copy-Item .mcr-before-update/uv.lock uv.lock
uv sync --locked
uv run python -c "from importlib.metadata import version; print(version('minecraft-remote-api'))"
```

`--locked`はlockの更新が必要なら停止します。[uvのlock同期](https://docs.astral.sh/uv/concepts/projects/sync/)を参照してください。
手順1の版に戻ったことを確認してから、新しいkernel／接続で再開します。
追加extraを指定して使っていた場合は、元と同じextraでsyncします。

これはPython環境を戻す手順です。実行したコードによるworldの変更は、作例ごとの復元処理で扱います。
更新後に追加したAPIを使うコードも、戻した版で使える内容へ戻します。
serverの差し替えは、server側の公開・復帰手順と対応protocolに従います。

## source checkoutのstarterを使う場合

公開tagを指定した別folderを作ると、既存の編集を保ったまま試せます。
`<公開tag>`と`<新しいfolder>`を実際の値に置き換えます。

```powershell
git clone --branch '<公開tag>' --single-branch https://github.com/Naohiro2g/minecraft-remote-api.git '<新しいfolder>'
cd '<新しいfolder>'
uv sync --frozen
cd starter
Copy-Item param_mc_remote.template.py param_mc_remote.py
```

必要な接続設定を新しいlocal fileへ記入し、[starterの手順](../starter/README_ja.md)を進めます。
以前のcheckoutは残しておき、戻すときはそのfolderの環境とコードを使います。
