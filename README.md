# clawbot-dev-assistant

接在个人微信 **ClawBot** 上的开发助手，给嵌入式工程师用：每天早上推送 GitHub 热榜和嵌入式精选，平时能聊技术、查资料、记笔记、看服务器。后端用 DeepSeek。

和 [clawbot-health-buddy](https://github.com/Hanye1108/clawbot-health-buddy) 是同一套架构，可以装在同一台服务器上，互不影响。

## 能做什么

| 功能 | 怎么用 |
|---|---|
| 每日 GitHub 热榜 | 每天 `REPORT_TIME`（默认 07:40）推送：过去 24 小时新增 star 最多的 10 个项目，DeepSeek 写中文简介和看点；连续上榜会标注 |
| 嵌入式精选 | 从 C/C++/Rust/汇编的今日趋势 + 近期新建的嵌入式相关项目里，按你的关注方向挑 2～3 个，推荐过的不再重复 |
| 展开 / 收藏 | 「展开 3」读 README 详细介绍第 3 个项目；「收藏 3」存进笔记 |
| 技术问答 | 随便问，需要最新信息会联网搜索；发 GitHub 链接会读 README |
| 笔记 | 「记一下……」；「笔记」看最近的；配置了 Memos 会同步过去 |
| 关注方向 | 「我的关注」「关注 RK3588」「取消关注 STM32」 |
| 服务器看门狗 | 「服务器」看负载/内存/磁盘/服务/容器；磁盘快满、DeepSeek 余额不足会主动提醒；可选监视指定的 systemd 服务 |
| 补发 | 微信只允许在你最近一次发消息后约 23 小时内主动推送；超时的推送会暂存，你下次说话时补发 |

## 不会和现有服务冲突

- 目录 `/opt/clawbot-dev-assistant`，独立的 `.venv`、`.env`、数据库 `data/devbot.db`、ClawBot 凭据 `data/ilink/`
- systemd 服务名 `clawbot-dev-assistant`，Python 包名 `devbot`（健康助手是 `bot`）
- **不监听任何端口**，不碰 OpenResty / 1Panel / Docker 配置；对服务器只做只读查询
- 备份在每天 04:20（健康助手是 04:00）

唯一要注意的是**微信账号**：如果健康助手里已经用你自己的微信绑定过（通常叫 `me`），建议先让健康助手放开它，再在这里绑定，避免两个程序抢同一个微信的消息（setup 向导会检测并提示具体命令）。

## 部署

需要：Linux 服务器（root）、Python 3.8+、一个 DeepSeek API Key、你自己微信里的 ClawBot。

### 方式一：服务器能连 GitHub

```bash
curl -fsSL https://raw.githubusercontent.com/Hanye1108/clawbot-dev-assistant/main/deploy/bootstrap.sh | sudo bash -s -- --mirror
cd /opt/clawbot-dev-assistant && .venv/bin/python -m devbot setup
```

### 方式二：上传压缩包（国内服务器连 GitHub 不稳时）

1. 在 1Panel「文件」里把 `clawbot-dev-assistant.zip` 上传到 `/opt` 并解压，确认得到 `/opt/clawbot-dev-assistant/`
2. 在 1Panel 终端（或 SSH）运行：

```bash
cd /opt/clawbot-dev-assistant && bash deploy/install.sh --mirror
.venv/bin/python -m devbot setup
```

`setup` 向导会：填 DeepSeek Key（可以复用健康助手的）和推送时间 → 自动检查 DeepSeek、GitHub、iLink → 提示可能的微信冲突 → 扫码绑定你的微信 → 启动服务。

然后在微信里给 ClawBot 发「你好」看功能介绍，发「热榜」马上看今天的。

### 更新代码

上传新的压缩包覆盖解压（`.env` 和 `data/` 不在压缩包里，不会被覆盖），然后：

```bash
cd /opt/clawbot-dev-assistant && bash deploy/install.sh --mirror   # 会自动重启服务
```

## 常用命令

```bash
systemctl status clawbot-dev-assistant          # 运行状态
journalctl -u clawbot-dev-assistant -f          # 实时日志
cd /opt/clawbot-dev-assistant
.venv/bin/python -m devbot check                # 检查配置和外部服务
.venv/bin/python -m devbot report               # 现场生成一份热榜打印出来（不发微信）
.venv/bin/python -m devbot login                # 重新扫码绑定（登录过期时）
```

微信里的管理指令：`#status` 运行状态和余额，`#report` 重新生成今天的热榜，`服务器` 服务器状态，`清空聊天记录`。

## 配置

都在 `.env` 里，说明见 [.env.example](.env.example)。常改的：

- `REPORT_TIME`：推送时间，建议 9 点前（DeepSeek 如果还在实行白天高峰加价，早上生成更便宜）
- `INTERESTS`：关注方向，决定嵌入式精选挑什么（微信里也能改）
- `EMBEDDED_TOPICS` / `EMBEDDED_LANGS`：嵌入式候选的来源
- `GITHUB_TOKEN`：可选，不填每小时 60 次 API 额度，日常够用
- `MEMOS_URL` / `MEMOS_TOKEN`：可选，笔记同步到你的 Memos
- `WATCH_SERVICES`：可选，看门狗盯哪些 systemd 服务，默认不监视

改完 `systemctl restart clawbot-dev-assistant`。

## 工作原理

- **热榜数据**：GitHub 没有官方 Trending API，解析 `github.com/trending?since=daily` 网页，按「今日新增 star」排序取前 10；每个项目取 README 前 1500 字给 DeepSeek 写简介。
- **嵌入式候选**：C / C++ / Rust / Assembly 的今日趋势 + GitHub 搜索 API 查最近 45 天新建、标签或描述含嵌入式关键词、star ≥ 15 的项目，DeepSeek 按你的关注方向挑。
- **稳定性**：GitHub 请求带超时和重试；当天抓取失败 20 分钟后重试，最多 4 次；DeepSeek 失败时退化成英文原描述照常推送。服务重启后如果当天还没推送会自动补上。
- **排版**由代码完成，模型只写字段，格式稳定；长消息在项目之间断开，不会把一个项目拆成两半。

## 开发与测试

```bash
python3 tests/run_tests.py        # 不需要 pytest；装了 pytest 也可以 pytest -q
```

## 给 AI 的部署说明

如果让 AI 助手在一台干净的服务器上部署，按顺序执行，每步检查输出：

1. `cd /opt/clawbot-dev-assistant && bash deploy/install.sh --mirror`（代码已上传）或运行上面的 bootstrap 命令；末尾应看到「✅ 安装完成」。
2. 编辑 `.env`：至少填 `DEEPSEEK_KEY`。不要把 `.env` 内容打印到日志或聊天里。
3. `.venv/bin/python -m devbot check`：除「已绑定 ClawBot」外应全部 ✅；GitHub 项失败通常是网络抖动，可以重试。
4. 检查 `/opt/clawbot-health-buddy/data/ilink/` 下是否有用户本人的账号文件，如有，先和用户确认再按上面的说明处理。
5. `.venv/bin/python -m devbot login`：终端出现二维码，**需要用户本人扫码**，AI 不能代替。
6. `systemctl restart clawbot-dev-assistant && systemctl status clawbot-dev-assistant`，然后让用户在微信里发「你好」和「热榜」验证。

## License

MIT
