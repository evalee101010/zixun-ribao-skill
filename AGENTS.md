# AGENTS.md — 出海泛娱乐资讯日报（给 Codex / 自动化 agent 的运行说明）

本目录是一个可移植的 skill。**完整规则见 `SKILL.md`**（含需求基线、源分层、校验清单）。本文件只讲"每天怎么自动跑出来"，不要在自动化 prompt 里复制业务规则。

## 一次性准备
```bash
pip install feedparser pyyaml requests
# 可选：cp .env.example .env 并填 DIANDIAN_API 等 key
```

## 每天的执行步骤（Codex 按此做）
1. **抓取**（确定性，纯脚本）：
   ```bash
   python fetch_news.py
   ```
   生成 `资讯日报-草稿-YYYYMMDD.md`：已按"北京时间 昨16:00–今16:00"窗口过滤、去重、精选排序；脚本会回溯前 2 天草稿/成稿链接，重复 URL 不再新增；白鲸/36氪出海等无时间戳链接只在第一次出现时保留一次，并自动带正文（summary）。
   历史日期测试可运行 `python fetch_news.py --date YYYYMMDD`；默认跳过无时间戳列表页，避免混入当前列表页内容。
2. **读规则**：读 `SKILL.md`（需求基线 + 校验清单）与 `format/格式规范.md`（模板 A/B/C）。
3. **浓缩成稿**：把草稿里的 ⭐精选条目，逐条按模板浓缩成最终日报——
   - **只浓缩、不解读**：忠实提炼原文已有的主体、背景、数据，不要加入自己的分析/判断。
   - 每条把原文写明的关键事实提全（例：融资条目要写清是哪家公司、估值、成立背景、数据，不能只写标题）。
   - 篇幅按信息量（通常 200–400 字）；融资走模板 C；排除具身/机器人方向。
4. **产出**：保存为 `资讯类简报-{月.日}日.md`，写入产出目录（见下）。
5. **质检**：运行 `check_report.py`，生成 `资讯日报-质检-YYYYMMDD.md`；如有 `FAIL`，先修成稿再重跑。
6. **自检**：对照 `SKILL.md` 的"校验清单"逐项过一遍。

### 推荐的一条龙命令（headless）
```bash
# 1) 抓取
python fetch_news.py
# 2) 让 Codex 读规则 + 草稿，产出当天日报（--sandbox workspace-write 让无人值守也能写文件）
codex exec --sandbox workspace-write --skip-git-repo-check "阅读并严格执行本目录 SKILL.md 与 format/ 下的规则，把今天的 资讯日报-草稿-*.md 浓缩成《资讯类简报-{今日月.日}日.md》并保存到产出目录；完成后按 SKILL.md 校验清单自检。"
```

## 产出目录（与"每日检查"对接的关键）
把最终 `资讯类简报-*.md` **写入团队约定的共享目录**（默认是本 skill 的上一级目录）。**务必固定输出位置**，否则后续质检或人工复核环节读不到。

## 定时（每天自动跑）
本机 cron（建议显式使用北京时间/Asia-Shanghai；服务器时区不同时需换算）：
```cron
5 16 * * *  cd /path/to/zixun-ribao-skill && python fetch_news.py && codex exec --cd /path/to/output --sandbox workspace-write --skip-git-repo-check "阅读并严格执行 /path/to/zixun-ribao-skill/SKILL.md 与 format/ 规则，将今天的 资讯日报-草稿-*.md 浓缩成《资讯类简报-{今日月.日}日.md》写入输出目录，并按校验清单自检" >> run.log 2>&1
# 实际更推荐直接调封装好的 run_daily.sh（已内置上面参数）：
# 5 16 * * *  /bin/bash "/path/to/zixun-ribao-skill/run_daily.sh" >> "/path/to/zixun-ribao-skill/run.log" 2>&1
```
- 云端可用 `codex cloud exec` 提交远程任务，或用 Codex Cloud 的定时任务能力。
- 时间点设在 16:00 之后，确保覆盖"昨16:00–今16:00"窗口刚好闭合。

## 注意
- 公众号优先经 WeWe RSS/VBRS 接入；未接入或抓不到全文的 `type: wechat` 源会列入"待人工贴链接"。
- 抓取仅用于聚合，保留原文出处链接。
