#!/bin/bash
# 双击即跑：只做抓取（fetch_news.py），生成当天草稿，用于快速验证源/乱码/配图。
# 不调用 Codex（快）。完整日报用 run_daily.sh。
cd "$(dirname "$0")"
echo "==> 抓取中（约1-3分钟，安静运行）..."
python3 fetch_news.py
echo ""
echo "✅ 完成。草稿在本目录 资讯日报-草稿-*.md。"
echo "按任意键关闭窗口。"
read -n 1 -s
