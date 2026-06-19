# 资讯日报 Skill

一个可复用的资讯日报流水线：抓取出海泛娱乐、AI 娱乐与全球融资资讯，生成候选草稿，再由 Codex/Claude 按固定格式浓缩成《资讯类简报》，最后输出质检报告。

## 功能

- 按北京时间 `前一日 16:00 — 当日 16:00` 抓取资讯。
- 自动按链接、近重复标题、前 2 天历史 URL 去重。
- 白鲸、36氪出海等列表页会进入正文页解析发布时间；仍无发布时间的列表页条目默认不进正式候选，但会保留在草稿排查区，避免旧文混入日报同时减少静默漏收。
- 支持 RSS、RSSHub、WeWe RSS/VBRS、白鲸/36氪出海列表页、预留 API 源。
- 成稿后运行质检，检查精选覆盖、格式、裸链、Source 计数和潜在事实依据问题。

## 版本与更新

当前版本：`0.2.0`

版本更新记录见 `CHANGELOG.md`。建议通过 GitHub Release 或 tag 获取稳定版本；已下载项目的使用者可在项目目录运行：

```bash
git pull origin main
```

如需固定到某个版本，可切换 tag：

```bash
git checkout v0.2.0
```

## 安装

```bash
git clone <your-repo-url>
cd zixun-ribao-skill
python3 -m pip install -r requirements.txt
```

可选：复制 `.env.example` 为 `.env`，填写点点数据、StartupHub 等 API key。

```bash
cp .env.example .env
```

## 快速运行

```bash
python3 fetch_news.py
```

生成：

- `资讯日报-草稿-YYYYMMDD.md`：候选清单、精选、备选、抓取告警。

然后让 Codex/Claude 读取 `SKILL.md` 与 `format/格式规范.md`，把草稿浓缩成：

- `资讯类简报-{月.日}日.md`

成稿后运行质检：

```bash
python3 check_report.py \
  --draft 资讯日报-草稿-YYYYMMDD.md \
  --report ../资讯类简报-{月.日}日.md \
  --write 资讯日报-质检-YYYYMMDD.md
```

质检报告不进入最终日报正文。

## 历史日期测试

```bash
python3 fetch_news.py --date 20260410
```

历史模式仍按北京时间 `前一日 16:00 — 当日 16:00` 取数。列表页来源会先进入正文页解析发布时间；如果正文页仍无发布时间，默认不进入精选/备选正式候选，只保留在草稿末尾排查区，避免把当前列表页内容或旧文误当成历史新闻。

只有排查抓取问题、且需要把无时间戳列表页临时放回候选区时才加 `--include-undated`，不建议用于正式日报：

```bash
python3 fetch_news.py --date 20260410 --include-undated
```

正式日报不要用 `--hours 24`。

## 一键流程

如果本机已安装并登录 Codex CLI：

```bash
bash run_daily.sh
```

默认把最终日报写到 skill 上一级目录。也可以指定输出目录：

```bash
RIBAO_OUT_DIR=/path/to/output bash run_daily.sh
```

## 定时运行

用 cron 时，请确保运行环境时区为北京时间。若系统不是北京时间，建议使用支持 `Asia/Shanghai` 的任务调度器。

```cron
5 16 * * * /bin/bash "/path/to/zixun-ribao-skill/run_daily.sh" >> "/path/to/zixun-ribao-skill/run.log" 2>&1
```

macOS 用户也可以双击 `一键设置.command`，它会安装依赖并写入 cron。

## 公众号接入

`wewe-rss/` 下提供 WeWe RSS Docker 配置。启动后订阅公众号，并把 `sources.yaml` 中的 `微信公众号(WeWe RSS)` 源改成你的 feed 地址。

```bash
cd wewe-rss
docker compose up -d
```

默认示例地址是：

```text
http://localhost:4000/feeds/all.rss
```

## 目录

- `SKILL.md`：日报生成工作流与校验清单。
- `fetch_news.py`：抓取候选资讯。
- `check_report.py`：成稿后质检。
- `sources.yaml`：信息源注册表。
- `format/格式规范.md`：成稿格式与写作规则。
- `format/日报模板.md`：固定骨架和示例结构。
- `run_daily.sh`：抓取、成稿、质检的一键脚本。
- `wewe-rss/`：微信公众号 RSS 接入示例。

## 注意

- 本工具只做资讯聚合和摘要，最终成稿需保留原文链接。
- 质检脚本可以发现格式问题和部分事实依据风险，但不能替代人工回看原文。
- 公开发布前请确认 `sources.yaml` 中的信息源和使用方式符合团队合规要求。
