# Pythonクライアントの公開確認記録

公開手順は [PUBLISHING.md](../PUBLISHING.md)、導入手順は [README](../README.md) を参照してください。
リリースの判断・実機試験・過去の記録の正本はknowledgeの
[release gate記録](https://github.com/Naohiro2g/mc-remote-knowledge/blob/main/00-hub/release-gate-notes_ja.md)です。

## 公開成果物

`2320.0.0b9`を2026-10-05にPyPI.orgとGitHub prereleaseへ公開し、TestPyPIでも同じ成果物を確認しました。

- [PyPI.org](https://pypi.org/project/minecraft-remote-api/2320.0.0b9/)
- [GitHub Release](https://github.com/Naohiro2g/minecraft-remote-api/releases/tag/v2320.0.0b9)
- [TestPyPI](https://test.pypi.org/project/minecraft-remote-api/2320.0.0b9/)
- tag: `v2320.0.0b9` → `b901c88fe41b67530ff353271683ece9fd453076`
- [tag CI](https://github.com/Naohiro2g/minecraft-remote-api/actions/runs/37267690375): Python 3.10〜3.13とbuildが成功
- [公開workflow](https://github.com/Naohiro2g/minecraft-remote-api/actions/runs/37267882665): 全job成功。PyPI jobはhuman ownerの承認後に実行

| 成果物 | bytes | SHA-256 |
| --- | ---: | --- |
| wheel | 196,221 | `e166bc9c14c425b3859f9af6c7af52900b58d1769fc077a3524a5368d05638c6` |
| sdist | 190,627 | `bd027b8b94ff775bfb7a3c02ada9716ad8785e5499180bb0cfb26f1da4afe479` |
| manifest.json | 681 | `da9887d12e57d929a93531bbcffc7795895aa0bbc7eef1792e2d03cb4979e838` |

GitHub Releaseの3 assetと、両indexのwheel／sdistを取得してbytesとSHA-256の一致を確認しました。
PyPI.orgとTestPyPIの成果物は確認時点でyankされていません。
同梱WireScopeのsource commitは`dc1ab834183e29f2eb03059b07e99d2b463776ee`です。

Linux／Python 3.13.13の新しいuv projectで、PyPI.orgから版を指定して取得し、
import結果`2320.0.0b9`／`Minecraft`を確認しました。
gateは2026-10-06にCLOSEDとなり、公開・実機・close素材はknowledgeへ収容済みです。

- [公開とcloseの正式記録](https://github.com/Naohiro2g/mc-remote-knowledge/blob/5beaad2557abbc6e90ada03edf7d0a2918fa7a52/14-evidence/records/2026-10-05-b9-release_ja.md)
- [公開時の正式素材](https://github.com/Naohiro2g/mc-remote-knowledge/tree/5beaad2557abbc6e90ada03edf7d0a2918fa7a52/14-evidence/artifacts/2026-10-05-b9-python-release)
