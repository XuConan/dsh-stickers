# dsh-stickers

表情包收藏页的 DSH bundle：把 `douyin-sticker-bot` 那个本地工具接进 Harness —— 侧栏多一个「表情包」入口，Agent 多了 6 个 `stickers_*` 工具。

## 它做什么

- **Host 半边**（`index.js`）：按需拉起本地 Python 服务（`douyin-sticker-bot`），并注册 5 个工具：
  | 工具 | 用途 |
  | --- | --- |
  | `stickers_collect` | 抓取（抖音 `sticker/collection/like/keyword/user`、小红书 `smiles/redmoji`、目录库 `chinesebqb` + 分类） |
  | `stickers_markets` | 列来源、抓取方式、登录状态、分类清单 |
  | `stickers_list` | 查候选（状态 / 来源 / 分页） |
  | `stickers_download` | 下载并归一化成 240×240 PNG/GIF + 查重 |
  | `stickers_folder` | 返回下载目录（素材库）路径并尝试弹出资源管理器 |
- **Client 半边**（`client.js`）：Harness Web UI 里的一个整页面板（`main` 槽），页签切来源、筛选（全部 / 未下载 / 已下载）、勾选、下载、打开下载文件夹。**不做导入微信**：下载好的图在素材库里，用户自己全选拖进微信表情面板，所以只有「未下载 / 已下载」两态，样式走 `--dsw-alias-*` 主题 token。

## 依赖

- 本地项目 `douyin-sticker-bot`（默认 `D:\Documents\deepseek-harness\default-workspace\douyin-sticker-bot`），需要它的 `.venv`。
- 面板走 HTTP 调本地服务 `http://127.0.0.1:8799`（服务端已开 CORS）。登录（抖音扫码 / 小红书扫码）在独立控制台里做一次即可，cookie 与插件共用。

## 配置（`cordis.patch.yml`）

```yaml
- insert:
    - id: dsh-stickers
      name: 'dsh-stickers'
      config:
        port: 8799
        autoStart: true
```

- `autoStart: true` = 第一次用到时自动 `python -m app --no-browser --port <port>`，插件卸载时把它关掉。
- 想自己先开服务（比如要看扫码窗口），把 `autoStart` 设成 `false`。
- 后端位置不用配：插件依次找 `./douyin-sticker-bot`、`../douyin-sticker-bot`、`../../douyin-sticker-bot`，再退回本机开发路径。放别处就加 `projectDir: '...'`，或设环境变量 `DSH_STICKERS_PROJECT`。
- 解释器同理：默认 `<project>/.venv/Scripts/python.exe`，可用 `pythonPath` 或 `DSH_STICKERS_PYTHON` 覆盖。

## 安装

**给别人用：只发 `dist/dsh-stickers-portable.zip`，让对方解压后双击 `install.bat`。**
一个动作搞定：找 dsh → 建 Python 环境 → 装插件。装到别的 profile 用 `install.bat <profile名>`。

自测/开发时也可以手写命令：

```bat
:: 1) 本地目录（开发时最方便，改动即时可见）
dsh plugin --profile desktop add D:\path	o\dsh-stickers

:: 2) npm tarball（后端已在目标机器别处）
dsh plugin --profile desktop add D:\path	o\dsh-stickers-0.1.2.tgz

:: 3) 便携包：zip 里同时带插件 + Python 后端，解压后装插件目录
dsh plugin --profile desktop add D:\sticker-kit\dsh-stickers
```

装完重启 Harness 桌面应用；侧栏会出现「表情包」，点开就是面板。

> **路径别删**：profile 里记的是绝对路径（目录装是 `link:`，tgz 装是 `file:`）。
> 解压目录 / tgz 一旦删掉或挪走，以后任何一次 `pnpm install`（比如再装别的插件）都会
> 整体失败：`pnpm: ENOENT: no such file or directory, open '...dsh-stickers-0.1.2.tgz'`。
> 所以解压到固定目录（比如 `D:\sticker-kit`）就别动了。

## 打包

```bat
:: 需要 node + pnpm（DSH 自带的也行，用 DSH_NODE / DSH_PNPM 指过去）
python scripts/build-dist.py
```

产出 `dist/`：

| 文件 | 内容 |
| --- | --- |
| `dsh-stickers-<ver>.tgz` | 只有插件本体（约 9 KB），`dsh plugin add` 可装 |
| `dsh-stickers-portable.zip` | 插件 + `douyin-sticker-bot` 源码（排除 `.venv`、`data`）+ 安装说明，约 117 KB |

装到另一台机器：解压 → 双击 `install.bat`（它自己建 venv + 装插件）→ 重启 DSH。

## 自检

```bat
node --check index.js
node --check client.js
node scripts/smoke-client.mjs
```
