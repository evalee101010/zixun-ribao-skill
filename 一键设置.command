#!/bin/bash
# 双击本文件即可：安装依赖 + 配置每天 16:05 自动跑 + 可选试跑一次。
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "==================================================="
echo " 出海泛娱乐资讯日报 · 一键设置"
echo " 目录：$DIR"
echo "==================================================="

echo ""
echo "==> 1/4 安装 Python 依赖"
pip3 install --user feedparser pyyaml requests 2>/dev/null \
  || pip3 install --break-system-packages feedparser pyyaml requests \
  || echo "⚠️ 依赖安装可能失败，请手动跑：pip3 install feedparser pyyaml requests"

echo ""
echo "==> 2/4 检查 Codex CLI"
if command -v codex >/dev/null 2>&1; then
  echo "    ✅ 已检测到 codex：$(command -v codex)"
else
  echo "    ⚠️ 未找到 codex 命令。请先安装并登录 Codex CLI（npm i -g @openai/codex 或官方方式），登录后重跑本脚本。"
fi

echo ""
echo "==> 3/4 配置每天 16:05 定时任务（cron）"
chmod +x "$DIR/run_daily.sh"
CRON_LINE="5 16 * * * /bin/bash '$DIR/run_daily.sh' >> '$DIR/run.log' 2>&1"
( crontab -l 2>/dev/null | grep -v 'run_daily.sh' ; echo "$CRON_LINE" ) | crontab -
echo "    已写入 crontab："
crontab -l | grep run_daily.sh
echo "    （如 macOS 提示需要权限：系统设置→隐私与安全性→完整磁盘访问权限，给 cron / 终端 打勾）"

echo ""
echo "==> 4/4 现在先手动试跑一次？这会真实抓取并调用 Codex 出稿。"
read -p "    试跑？(y/n) " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  /bin/bash "$DIR/run_daily.sh"
  echo ""
  echo "    成稿应已写到：$(cd "$DIR/.." && pwd)/资讯类简报-*.md"
fi

echo ""
echo "✅ 设置完成。之后每天 16:05 自动抓取、成稿并生成质检报告。"
echo "（关闭窗口即可）"
