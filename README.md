# minecraft-remote-api / Naohiro2g

## Python Client/API package for Minecraft Remote
マイクラリモコンのためのPythonクライアント/APIパッケージ

- package name（パッケージ名）: `minecraft-remote-api`
- description（概要）: `Python Client/API for Minecraft Remote`
- version（バージョン）: `1214.10.3`
- module name（モジュール名）: `mc_remote`

**Works with [Minecraft Remote (`McRemote`) plugin](https://github.com/Naohiro2g/McRemote) for [PaperMC](https://papermc.io/) server. You can use the sandbox server for testing**

**[PaperMC](https://papermc.io/)サーバー用の[Minecraft Remote（`McRemote`）プラグイン](https://github.com/Naohiro2g/McRemote)と連携します。我々のサンドボックスサーバーをテストに使用できます。**



## Very important preparation   非常に重要な準備

Edit these parameters in `param_mc_remote.py` to fit your environment.
`param_mc_remote.py`のパラメータを環境に合わせて編集してください。


You have to load the `McRemote` plugin to your own PaperMC server in your environment. The most compact environment is to use the server built on your own PC, but if you have a weak PC, it is better to use the server of another machine.

自分の環境のPaperMCサーバーを使いたいときは、`McRemote`プラグインをロードする必要があります。最もコンパクトな環境としては、自分のPCで建てたサーバーを使うことができますが、非力なPCの場合は他のマシンのサーバーを利用したほうが良いです。


```python
PLAYER_NAME = "PLAYER_NAME"  # set your player name in Minecraft
PLAYER_ORIGIN = Vec3(2000, 0, 2000)  # PO.x, PO.y, PO.z
ADRS_MCR = "mc-remote.xgames.jp"  # mc-remote sandbox server
PORT_MCR = 25575  # socket server port
```

- You must be an online player of the Minecraft Server with the same player name as `PLAYER_NAME` to use the API.
- The `PLAYER_ORIGIN` is the origin of the coordinate system for building. The coordinates for building are relative to `PLAYER_ORIGIN`. For example, `setBlock(5, 68, 5, block.GOLD_BLOCK)` will place a gold block at (2005, 68, 2005).

APIを利用するには、`PLAYER_NAME`と同じプレイヤー名のMinecraftサーバーのオンラインプレイヤーである必要があります。`PLAYER_ORIGIN`は建築座標系の原点で、PLAYER_ORIGINからの相対座標となります。例えば、`setBlock(5, 68, 5, block.GOLD_BLOCK)`で、実際には座標（2005, 68, 2005）に金ブロックが置かれます。


## Discord community and sandbox server

We have a Discord community for Minecraft Remote. You can ask questions and share your experiences with other users. We also have a sandbox server for testing, which is available to all users. The sandbox server is a great place to experiment with the API and try out new ideas without worrying about breaking anything. Please visit the 'mc-remote-chat' channel of [our Discord server](https://discord.gg/xUqhhqWsuS) to get support.


## Discordコミュニティとサンドボックスサーバー
マイクラリモコンのためのDiscordコミュニティがあります。質問をしたり、他のユーザーと経験を共有したりできます。また、テスト用のサンドボックスサーバーもあり、すべてのユーザーが利用できます。サンドボックスサーバーは、APIを試したり、新しいアイデアを試したりするのに最適な場所です。何か壊すことを心配せずに実験できます。[Discordサーバー](https://discord.gg/xUqhhqWsuS)の'mc-remote-chat'チャンネルでサポートを受けられます。


## インストール（初回のみ）

If you have pyenv / poetry installed:
pyenv / poetryがインストールされている場合

```bash
poetry install

# don't forget to enter the virtual environment '.venv/'
# 仮想環境'.venv/'に入るのを忘れないで
```

If you don't have pyenv / poetry installed:
pyenv / poetryがイントールされていない場合

```bash
pip install minecraft-remote-api
```

## Run Example

```bash
cd examples
python hello.py
python axis_flat.py
```


## Usage
```bash
python hello.py
```


==================================
Minecraft Remote / mc-remote is a remote control system for Minecraft. It works with the plugin (McRemote) loaded on the [Minecraft server (PaperMC)](https://papermc.io/) and allows users to code and perform automatic construction.  It is based on `RaspberryJuice` by zhowei and `mcpi` by martinohanlon, and `JuicyraspberryPie` by wensheng, which are strongly intended to support learning (rather than education), and the wisdom and efforts of users of these projects.
**It is also strongly influenced by Dr. Mitchel Resnick (MIT)'s Lifelong Kindergarten.**

The mission of the Minecraft Remote project is one:
### To support the acquisition of a self-learning approach (for beginners)
The acquisition of technical skills is secondary.
### Technical skills to be acquired through the self-learning approach
 - Coding concepts and techniques
 - Techniques for open source development using Git/GitHub
 - Techniques for realizing/expressing one's own ideas
### Points to keep in mind regarding the maintenance of motivation for self-learning
  - To make the latest Minecraft available as an attractive playground and sandbox
  - To enable the use of code assets cultivated in past projects
  - To enable the use of a wide range of languages, including Python, Scratch, C#, Java, and others
  - To enable the use of not only the Minecraft world but also 3D worlds such as Unity, Blender, and Houdini
  - To enable not only output to 3D worlds but also input to build interactive experiences
  - To apply artificial intelligence technology
  For example, to be able to play rock-paper-scissors with hands in the Minecraft world using computer vision and machine learning.

https://github.com/zhuowei/RaspberryJuice
https://github.com/martinohanlon/mcpi
https://github.com/wensheng/JuicyraspberryPie

Minecraft Remote / mc-remote（マイクラリモコン、あるいは、エムシーリモート） は、Minecraftのリモコンシステムです。クライアント / APIは、Minecraftサーバー（PaperMC）にロードしたプラグイン（McRemote）によるサーバーのクライアントとして働き、ユーザーがコーディングして自動建築を行うことを可能にします。これは、zhoweiによる`RaspberryJuice`、martinohanlonによる`mcpi`、およびwenshengによる`JuicyraspberryPie`などの、（教育というよりも）学習支援の意図を強く持ったプロジェクトと、その利用者たちの知恵と努力の成果に基づいています。**また、Dr. Mitchel Resnick(MIT)のライフロングキンダーガーテンの影響を強く受けています。**

==================================
## Minecraft Remoteプロジェクトのミッションは、1つ
### (初学者の)自学自習アプローチ習得を支援すること
技術スキル習得は2の次。

### 自学自習アプローチ習得の題材とする技術スキル
 - コーディング概念、手法
 - Git/GitHubを活用したオープンソース開発の手法
 - 自分のアイデアを実現／表現するための手法

### 自学自習のモチベーション維持に関連して留意している点
  - 魅力的なプレイグラウンド、サンドボックスとして最新版マインクラフトを利用可能にす
  - ること
  - 過去のプロジェクトで培われてきたコード資産を活用できるようにすること
  - Python、Scratch、C#、Java他、幅広い言語の利用を可能にすること
  - マインクラフト世界だけでなく、Unity、Blender、Houdiniなどの3D世界の利用を可能にすること
  - 3D世界への出力だけでなく、入力を可能にしてインタラクティブな体験を構築できるようにすること
  - 人工知能技術を応用すること
  例えば、コンピュータービジョンと機械学習を利用し、マインクラフト世界の中の手とじゃんけんができるなど。


![image](https://private-user-images.githubusercontent.com/587586/420673574-fd451bf5-a038-449b-aa7b-b2635d0609d1.png?jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NDQyMTQwMzksIm5iZiI6MTc0NDIxMzczOSwicGF0aCI6Ii81ODc1ODYvNDIwNjczNTc0LWZkNDUxYmY1LWEwMzgtNDQ5Yi1hYTdiLWIyNjM1ZDA2MDlkMS5wbmc_WC1BbXotQWxnb3JpdGhtPUFXUzQtSE1BQy1TSEEyNTYmWC1BbXotQ3JlZGVudGlhbD1BS0lBVkNPRFlMU0E1M1BRSzRaQSUyRjIwMjUwNDA5JTJGdXMtZWFzdC0xJTJGczMlMkZhd3M0X3JlcXVlc3QmWC1BbXotRGF0ZT0yMDI1MDQwOVQxNTQ4NTlaJlgtQW16LUV4cGlyZXM9MzAwJlgtQW16LVNpZ25hdHVyZT1mZTI0ZWZhY2E0YTY3MTYyM2VkMGIyN2YxMTJiODYzZWJiNWFjNTgwOWFlY2NhOTM1OWRhOWIzNDBjMzE0NmE5JlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCJ9.VKHLJR0NbOuL4lnBfrVyFsUGHXx8ANj0hj8wqf74Xro)
