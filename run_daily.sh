#!/bin/bash
# 每日运行：抓取 → 让 Codex 浓缩成稿 → 写回「日报」文件夹
# 由 cron 在每天 16:05 调用（也可手动 bash run_daily.sh 测试）
# UTF-8：确保中文路径与输出正常
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# cron 环境 PATH 很精简，显式补全 homebrew/python 的常见位置
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
# 关键：nvm 安装的新版 codex 放最前，避免用到 Homebrew 的旧版（取最高 node 版本）
NVM_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
[ -n "$NVM_BIN" ] && export PATH="$NVM_BIN:$PATH"

set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${RIBAO_OUT_DIR:-$(cd "$SKILL_DIR/.." && pwd)}"

cd "$SKILL_DIR"

echo "[$(date '+%F %T')] 1/3 抓取..."
python3 fetch_news.py

echo "[$(date '+%F %T')] 2/3 Codex 浓缩成稿..."
# --sandbox workspace-write：无人值守也能写文件、不弹审批；--cd 设为日报文件夹(产出落这里)
codex exec --cd "$OUT_DIR" --sandbox workspace-write --skip-git-repo-check "阅读并严格执行 $SKILL_DIR/SKILL.md 与 $SKILL_DIR/format/格式规范.md，把 $SKILL_DIR 里今天的 资讯日报-草稿-*.md 浓缩成最终日报，保存为 $OUT_DIR/资讯类简报-{今日月.日}日.md；完成后对照 SKILL.md 校验清单自检。"

DRAFT="$(ls -t "$SKILL_DIR"/资讯日报-草稿-*.md | head -1)"
YMD="$(basename "$DRAFT" | sed -E 's/[^0-9]//g')"
MD="$(python3 -c 'import sys; y=sys.argv[1]; print(f"{int(y[4:6])}.{int(y[6:8])}")' "$YMD")"
REPORT="$OUT_DIR/资讯类简报-${MD}日.md"
CHECK="$SKILL_DIR/资讯日报-质检-${YMD}.md"

echo "[$(date '+%F %T')] 3/3 质检..."
python3 "$SKILL_DIR/check_report.py" --draft "$DRAFT" --report "$REPORT" --write "$CHECK"

echo "[$(date '+%F %T')] 完成。"
