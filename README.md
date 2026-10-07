# Skills Morning Brief

Skills Morning Brief tracks popular AI skills on GitHub and brings together useful discoveries, growth trends, and AI agent news. Browse public updates immediately, or choose optional recommendations based on your own capabilities.

每日查看 GitHub 热门 AI Skills、真实 Stars 增长和 Agent 动态；打开即可浏览，个人推荐可选。

## 开始使用

下载 [v1.0.0 本地安装包](https://github.com/DeriitoMe/Skills-Morning-Brief/releases/tag/v1.0.0) 并解压。需要 Python 3.11+，应用只依赖 Python 标准库。

- Windows：双击 `Open-Skills-Morning-Brief.cmd`。
- macOS / Linux：运行 `sh open-skills-morning-brief.sh`。
- 命令行：在项目目录运行 `python -m morningpaper open`。

启动器自动启动当前用户的本机服务并打开浏览器。默认地址是 `http://127.0.0.1:8765`，被占用时自动选择可用端口。服务关闭后重新运行启动器。

源码下载同样包含经过白名单过滤的公开摘要。首次打开即可阅读；这些是带采样时间的快照，更新前不会被标作实时数据。正文默认 20px，可选 18px / 22px。

## 监测与更新

首页、热门 Skills、近期增长、AI / Agent 动态直接开放。Stars 是仓库级数据；增长显示两次真实采样的实际窗口，积累不足完整 7 天时不估算周增幅。

默认关注 OpenAI、Anthropic、Trail of Bits、Superpowers、Vercel 和 GitHub 的公共 Skills 来源，并按预算轮换发现更多仓库。官方资讯来源包括 OpenAI、Codex、Claude Code 和 DeepSeek。预发布版本与无日期更新分别标注。

手动更新公开内容：

```sh
python -m morningpaper monitor
```

Windows 每日 08:30 本机更新（当前配置为 Asia/Shanghai）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-schedule.ps1
```

任务名为 `Skills Morning Brief - Daily`。执行策略参数只作用于该脚本进程。电脑开启且用户登录时运行，错过时间后补执行；任务调用 `refresh`，私人推荐仅对明确勾选每日更新的方案执行。公开任务互斥，源或模型失败时保留已有内容与已完成进度。

定时任务在 `.runtime/monitor-runs/` 写入每轮结果，最新记录在 `.runtime/latest-monitor.json`，包括来源检查时间、状态、请求数和摘要数量。Windows 任务的退出码用于判断任务执行是否完成；记录中的 `degraded` 表示部分来源或模型失败，需结合记录判断内容是否完整。

更新结果显示在本机网页。本版本不配置邮件、Slack 或手机通知，也不会自动将每次监测结果提交到 GitHub。持续在线服务与云端调度需要另外部署。

## 可选个人推荐

点击“按我推荐”后，自动发现目录，由用户确认检查，再选择目标生成个人增量。随时可关闭、稍后再说或返回资讯首页。

支持 Codex、Claude Code、Cursor、DeepSeek / Deep Code 的目录适配，以及其他 Agent 的自选目录或 JSON 能力清单。扫描只确认定义存在，账号、依赖与运行能力需另行验证。未读取的目录不会被视为零能力。

推荐模型支持本机 Codex CLI 登录、DeepSeek API，以及其他 Chat Completions 兼容接口或本地模型。公开浏览与读取来源标题无需模型 Key；AI 摘要及个人推荐需要所选模型可用。API 模型名可在高级选项中设置，默认 DeepSeek 模型以项目配置为准。

DeepSeek Key 可放在 `DEEPSEEK_API_KEY` 环境变量。GitHub 采集优先使用 `GITHUB_TOKEN` / `GH_TOKEN`，其次在内存中复用当前用户已登录的 GitHub CLI；均不可用时匿名访问，可能限流。也可在页面临时输入模型 Key，仅在当前服务内存中保存，重启后清除。不要把密钥写进源码或配置。`MORNINGPAPER_CODEX` 可指定 Codex CLI。

导入清单示例：

```json
{"skills":[{"name":"my-review","description":"Review Python API changes.","enabled":true}]}
```

明确没有 Skills 时可导入 `{"skills":[],"confirmed_empty":true}`。

## 私人资料与安全

工作区画像、清单、匹配、反馈与报告保存在 OS 用户应用数据目录中，各方案独立。为保留升级兼容性，资料目录仍使用 `AgentSkillShelf` 标识；`MORNINGPAPER_DATA_DIR` 可指定独立实验目录。

私人接口需要本机启动会话，工作区 ID 本身不能授权。模型分析会将能力名称、说明及业务目标发送到所选提供方，不发送目录路径或完整私有 Skill 指令。公开监测只使用公共资料。不会自动安装或执行第三方 Skills。

安全边界、发布审计范围和托管限制见 [SECURITY.md](docs/SECURITY.md)。运行日志、缓存、作者画像、实验资料和密钥不进入仓库或安装包。

## 开发与发布

```sh
python -m unittest discover -s tests -v
python scripts/export-public-seeds.py
python scripts/build-package.py
python scripts/audit-release.py --staged --history --zip dist/Skills-Morning-Brief-1.0.0.zip
```

公开 seeds 更新必须再次审核。发布包含本地 ZIP 与 SHA-256 校验文件；GitHub 源码与 ZIP 均可启动。

产品需求见 [产品提示词](prompts/product-v5.md)，发布流程见 [发布提示词](prompts/release-v1.md)，1.0.0 验证范围见 [发布说明](docs/release-v1.md)。
