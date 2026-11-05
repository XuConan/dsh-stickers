# 表情包 → 微信

一个本地小工具：**从抖音 / 小红书 / 中文表情包库抓表情包 → 自动裁成微信表情规格 → 去重 → 一键整理成文件夹 → 你拖进微信即可**。

微信没有公开的「添加自定义表情」接口，写入 `emoticon.db` 需要破解 SQLCipher 并从进程内存抠密钥，既不稳定也有风控风险，所以最后一步（全选拖入聊天框 → 添加到表情）留给你手动完成，其余全部自动化。

---

## 快速开始

双击 **`run.bat`**（首次会自动建 `.venv` 并安装依赖，需要几分钟）。

启动后浏览器自动打开 `http://127.0.0.1:8799`：

1. 点右上角 **登录/检测** → 弹出 Chrome，用对应 App 扫码登录（抖音、小红书各一次，之后自动记住；小红书登录成功会自动关窗口）
2. 顶部 **页签** 选来源：`抖音表情包`、`小红书`、`中文表情包库`（`zhaoolee/ChineseBQB` 那 6000+ 张梗图，免登录）；自己加的图库会出现成新页签。页签是**各管各的**：切过去只看这个来源的列表，抓取方式、勾选状态、登录提示都各记各的，切回来还是原样
3. 抓取方式默认是 **我的表情包**，点 **开始抓取** 即可：
   - 抖音：= 抖音里你自己收藏/自定义的表情（评论区表情面板里 ❤ 那一栏）；也可以切到 **我的收藏**（收藏过的作品）、**我点赞的**、**关键词搜索**（比如 `猫咪表情包`）或 **账号主页**（粘链接）
   - 小红书：**我的表情包**（私信表情面板里 ❤ 那一栏，要登录）或 **小红书自带表情**（`[微笑R]` 这类 166 个，免登录）
   - 中文表情包库：一排可搜索的 **分类胶囊**（`115 个分类 · 5886 张`，点「全部表情包」就是整个库），上面搜索框输入「猫」「悟空」就能筛分类
4. 抓完后在网格里勾选想要的，点 **下载选中**
5. 点 **导入微信** → 自动打开导出文件夹并把微信窗口调到前面
6. 在文件夹里 `Ctrl+A` 全选 → 拖进微信聊天输入框 → 右键「添加到表情」
7. 回到网页点 **我已导入**，这批就标记完成（素材仍留在素材库，导出夹自动清空）

> 列表默认只显示 **待下载**（还没下到本地的），下载完的会自动从列表里消失，不会重复拉。
> 想看已下载的，把左上角筛选切成「已下载待导入」；切「全部」能看到所有记录。
>
> 网格是**分页**的，一页 60 张，右上角 `‹ 1 / 3 · 共 164 ›` 翻页（全选只作用于当前页，
> 已勾选的跨页保留）。缩略图在后端统一缩到 360px 再给浏览器（原图常有几百 KB～几 MB），
> 所以翻页基本是秒开；极少数特大动图会显示「原图太大，下载后可看」，不影响下载。
>
> 右上角 **「本地文件」** 可以管理磁盘上的东西：导出夹（拖进微信那份）逐张预览、单删、
> 一键清空；素材库能看占用、清孤儿文件、删掉已导入那批的原图（列表记录保留）。
> 只删文件，不会动数据库记录（除非你自己点「清空列表」）。

命令行方式：

```bat
.venv\Scripts\python.exe -m app              :: 默认 8799 端口
.venv\Scripts\python.exe -m app --port 9000
.venv\Scripts\python.exe -m app --headless   :: 无界面（登录会失败，不建议）
```

---

## 它做了什么

| 环节 | 做法 |
| --- | --- |
| 来源 | 顶部**页签**切换的**市场**：`抖音表情包`（live，要登录）+ `小红书`（live，自带表情免登录、「我的表情包」要登录）+ `中文表情包库`（GitHub 图库，免登录），还能用 `data/markets.d/*.json` 加更多 GitHub 图库 |
| 抓取 | 抖音两种路径：**我的表情包** 直接调 `/aweme/v1/web/im/resource/list/aggregation/?scenes=CUSTOM_STICKER_PAGE` 翻页（免签名，靠登录 cookie，一次拿全 200+ 个）；其余模式用 Playwright 驱动**本机 Chrome**，打开抖音的「我的收藏 / 我点赞的 / 搜索页 / 账号主页」，拦截页面自身发出的已签名 XHR（`/aweme/v1/web/*`），不自己伪造 `a_bogus` 签名 |
| 小红书 | 走 `edith.xiaohongshu.com` 的 `/api/im/web/smiles`（我的表情包，要 cookie）和 `/api/im/redmoji/detail`（自带 166 个，免登录）——这两个接口**不需要 x-s 签名**，所以抓取用 requests 直连，浏览器只在扫码登录时用一次；登录态存 `data/xhs-cookies.json`，浏览器 profile 在 `data/browser-profile-xhs/` |
| 目录市场 | 拉 `api.github.com/.../git/trees/<branch>?recursive=1` 清单（缓存在 `data/markets/<市场>.json`，24 小时有效），只把**元数据**入库，下载仍按勾选来 —— ChineseBQB 有 6000+ 张 / 600MB，不能一次全拉。分类按仓库一级目录生成，自动剥掉 `001Funny_` 这种英文前缀和 `BQB` 后缀，显示成 `001 滑稽大佬😏` 这样的编号+中文名，非表情包目录（`README`、`maker`、`site`）自动排除 |
| 解析 | 从响应 JSON 里递归找 `aweme_id`，图文作品每张图一个候选，视频作品取封面 |
| 归一化 | 240×240 透明画布等比缩放居中；静态存 PNG，动图重新编码成 GIF（`loop=0`、透明色 255、disposal=2），超 1.5MB / 200 帧自动降档抽帧 |
| 去重 | `sha256` 精确 + 64 位 dHash 汉明距离 ≤ 6 的近似去重，跨批次、跨市场生效；同一条来源 id 再抓一次不会重复入库 |
| 导出 | 已下载的表情按 `001.gif`、`002.png` 平铺到 `data/outbox/`，同时唤起文件夹和微信窗口 |

## 接入新的表情包市场

内置两个来源已经够用；想加第三个 GitHub 图库，**不用改代码**，丢一个 json 到 `data/markets.d/`：

```json
{
  "id": "mybqb",
  "name": "我的表情库",
  "kind": "github-repo",
  "repo": "someone/some-bqb-repo",
  "branch": "main",
  "description": "某个图库",
  "exclude_dirs": ["site", ".github"]
}
```

字段说明：`repo` 是 `owner/name`；`branch` 默认 `master`；`include_ext` 默认 `jpg,jpeg,png,gif,webp`；`cdn` 可覆盖图片直链模板（默认 `https://raw.githubusercontent.com/{repo}/{branch}/{path}`，备用 `cdn.jsdelivr.net`）。重启后界面「来源」里就会出现它，分类来自仓库一级目录名（`001Funny_滑稽大佬😏BQB` 会显示成 `滑稽大佬😏`）。

注意：GitHub 未登录的 API 限额是 **60 次/小时**，所以清单只在你点「刷新清单」或缓存过期时才拉一次。被限流时程序会用旧缓存并提示稍后再试。

## 目录结构

```
douyin-sticker-bot/
├─ run.bat                 一键启动
├─ app/
│  ├─ __main__.py          入口（HTTP 服务 + 采集线程）
│  ├─ config.py            配置与路径
│  ├─ store.py             sqlite：候选 / 批次 / 设置
│  ├─ events.py            进程内事件总线（SSE 推送）
│  ├─ pipeline.py          下载 → 归一化 → 去重 → 落盘
│  ├─ douyin/
│  │  ├─ worker.py         Playwright 采集线程（登录/滚动/拦截响应）
│  │  ├─ parser.py         响应 JSON → 候选
│  │  └─ downloader.py     带重试的下载、视频转 GIF
│  ├─ xhs/
│  │  ├─ api.py            小红书表情接口（smiles / redmoji）
│  │  ├─ parser.py         接口 JSON → 候选
│  │  ├─ sync.py           抓取线程（requests 直连，不开浏览器）
│  │  └─ login.py          扫码登录一次，落 cookie 到 data/xhs-cookies.json
│  ├─ markets/
│  │  ├─ base.py           Market 协议 + MarketItem
│  │  ├─ github_repo.py    GitHub 图库市场（清单缓存 / 分类 / 条目）
│  │  ├─ ingest.py         目录市场条目入库
│  │  └─ registry.py       内置 + data/markets.d 里的市场
│  ├─ media/
│  │  ├─ normalize.py      微信表情规格归一化
│  │  └─ dedupe.py         dHash
│  ├─ wechat/
│  │  └─ open_outbox.py    打开文件夹 / 唤起微信 / 平铺导出
│  └─ web/
│     ├─ server.py         本地 HTTP + SSE
│     └─ static/           控制台页面
├─ tests/                  unittest（无需 pytest）
└─ data/                   运行后生成
   ├─ stickers/            素材库（去重后的成品，全部保留）
   ├─ outbox/              待导入微信的导出夹（导入完自动清空）
   ├─ markets/             各市场清单缓存
   ├─ markets.d/           自定义市场配置（丢 json 就能加）
   ├─ browser-profile/     抖音登录态（别删，删了要重新扫码）
   ├─ browser-profile-xhs/ 小红书登录态（同上）
   ├─ xhs-cookies.json     小红书 cookie（「我的表情包」靠它）
   └─ stickers.db          候选数据库
```

## 配置

`data/config.json`（首次运行生成），常用项：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `port` | 8799 | 控制台端口 |
| `max_items` | 60 | 单次抓取目标条数 |
| `target_size` | 240 | 输出画布边长（微信显示约 120px，2x 更清晰） |
| `max_gif_bytes` | 1500000 | 动图体积上限（微信上限 5MB，留余量） |
| `min_short_edge` | 160 | 小于此边长的直接跳过 |
| `dedupe_hamming` | 6 | 感知哈希近似阈值，调大更严格 |
| `enable_video_gif` | false | 视频转 GIF，需要额外 `pip install imageio-ffmpeg` |
| `login_timeout` | 300 | 扫码等待秒数 |

## 跑测试

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

## 常见问题

**抓不到东西 / 显示 0 条**
- 抖音改版会影响接口结构，先确认浏览器里搜索页能正常出内容；
- 如果页面弹了滑块/图形验证，到那个 Chrome 窗口里手动过一下，再点抓取；
- 账号主页模式需要粘贴 `https://www.douyin.com/user/MS4wLjABAAAA...` 形式的链接。
- 「我的收藏」抓的是网页版个人主页 → 收藏 tab（接口 `aweme/v1/web/aweme/listcollection/`）。
  如果网页版的收藏列表是空的看不到东西，那就是手机上收藏的内容在网页版没同步，这种情况只能换「关键词搜索」。

**要求重新登录**
`data/browser-profile/` 被清了，或抖音登录态过期，点「登录/检测」重新扫码。

**拖进微信提示格式不支持**
微信支持的静态表情是 PNG/GIF/JPEG，体积 ≤5MB。本工具输出 PNG/GIF 且 ≤1.5MB。若微信版本对尺寸挑剔，可把 `target_size` 调成 120 再跑一次。

**会不会被封号**
工具用真实浏览器、正常浏览节奏（带随机延迟），不调用风控接口也不批量注册。但任何自动化都有风险，建议用小号或控制抓取频率。

## 边界

- 不做签名算法破解、不写微信数据库、不自动点击微信（这些都不稳定且有风险）；
- 不做手机端、不做定时任务（可自行用计划任务调用 `run.bat`）；
- 仅个人整理表情包使用，请遵守抖音与微信的用户协议及内容版权。
