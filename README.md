# 泰拉阅览室

明日方舟剧情阅读、地区分类与 EPUB 导出项目。现有资料包括 2,061 个游戏剧情片段、干员密录姓名、作品地区与两类时间字段。内容快照截至 2026-11-03；尚未核实的地区和时间保留“待考证”。

GitHub Pages 部署成功后的阅读地址：<https://archer223.github.io/Terra-reading-room/>。

## 自动发布

提交到 `main` 后，GitHub Actions 会恢复并核对正文文件，检查阅读逻辑，生成网站和地区 EPUB，再部署到 GitHub Pages。也可以在 Actions 页手动运行 **Publish Terra Reading Room**。

首次部署需要在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。部署状态见本仓库 Actions 页。

## 修改资料

- `editorial/regions.json`：作品主要舞台及分类依据，可设置多个地区。
- `editorial/chronology.json`：事件时间与国服开放时间的人工核对结果。
- `sources/registry.json`：来源与参考入口。
- `catalog/catalog.json`：篇目、稳定编号、干员姓名及来源记录。
- `sites/terra-archive/`：阅读器界面和浏览器 EPUB 导出逻辑。

地区按剧情舞台整理；用户人工分类会单独记录判断依据。作品开放时间与单篇分阶段解锁时间分列，字幕时间也可能包含插叙。

## 本地生成

使用 Python 3.10 或以上版本：

```sh
python3 scripts/restore_corpus.py
python3 scripts/archive.py build
python3 -m http.server 8765 --directory sites/terra-archive/dist
```

打开 <http://localhost:8765/>。生成的电子书位于 `sites/terra-archive/dist/downloads/`。

正文来自用户已提供并完成核对的本地导出。`corpus/archives/` 保存经过压缩、分块和 SHA-256 核对的正文包；构建时恢复为 `corpus/provided/`，不依赖其他网站在线提供正文。每篇仍保留工作簿、工作表与原始脚本哈希。

重新导入正文后，运行 `python3 scripts/package_corpus.py` 更新正文包，再将目录、编目和正文包一同提交。首次导入 XLSX 所需依赖列在 `requirements-dev.txt`。

## 阅读记录

收藏、进度、书签和额外导入的个人正文保存在浏览器。迁移到新网址前，可在原网站“来源与收录”中备份，再在新网站恢复。额外个人文件不会自动加入本仓库。

本项目为非官方个人阅读整理项目；明日方舟剧情及相关作品归各自权利方所有。
