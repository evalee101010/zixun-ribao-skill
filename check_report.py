#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资讯日报生成后质检。

检查两类问题：
1) 结构/格式硬规则是否满足；
2) 成稿内容是否能回到草稿里的 ⭐精选链接与摘要，降低漏选和无依据扩写。
"""

import argparse
import os
import re
import sys


BAD_BODY_PHRASES = [
    "该条来自",
    "经 WeWe RSS 抓取",
    "经 VBRS 抓取",
    "来源为",
    "补足观察信号",
    "以原文为准",
    "待补全文",
]

OLD_FOOTERS = ["兴趣产品跟踪", "Appendix", "appendix", "信息来源："]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def normalize_url(url):
    return (url or "").strip().rstrip(".,，。)")


def normalize_number_text(s):
    return s.replace("\\.", ".").replace("\\-", "-")


def numbers(s):
    s = normalize_number_text(s)
    return set(re.findall(r"\d+(?:\.\d+)?%?", s))


def parse_draft(text):
    items = []
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"- ⭐\*\*(.+?)\*\*（score .*?）｜(.+?)(?: ⏱无时间戳)?$", line)
        if m:
            if current:
                items.append(current)
            current = {
                "title": m.group(1).strip(),
                "source": m.group(2).strip(),
                "summary": "",
                "link": "",
            }
            continue
        if not current:
            continue
        s = line.strip()
        if s.startswith("- http"):
            current["link"] = normalize_url(s[2:].strip())
            items.append(current)
            current = None
        elif s.startswith("- 候选图:"):
            continue
        elif s.startswith("- "):
            current["summary"] += " " + s[2:].strip()
    if current:
        items.append(current)
    return [it for it in items if it.get("link")]


def parse_report(text):
    items = []
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^###\s+\d+）(.+)$", line)
        if m:
            if current:
                items.append(current)
            current = {"title": m.group(1).strip(), "body": [], "link": ""}
            continue
        if not current:
            continue
        s = line.strip()
        if s == "---" or s == "Source 来源：":
            items.append(current)
            current = None
            continue
        if s.startswith("http://") or s.startswith("https://"):
            if not current["link"]:
                current["link"] = normalize_url(s)
        elif not s.startswith("![]("):
            current["body"].append(line)
    if current:
        items.append(current)
    for it in items:
        it["body_text"] = "\n".join(it["body"]).strip()
    return items


def source_count(text):
    if "Source 来源：" not in text:
        return None
    total = 0
    in_table = False
    for line in text.splitlines():
        if line.strip() == "Source 来源：":
            in_table = True
            continue
        if not in_table:
            continue
        m = re.match(r"\|(.+?)\|(\d+)\|$", line.strip())
        if m and not m.group(1).strip().startswith("---"):
            total += int(m.group(2))
    return total


def previous_nonempty(lines, idx):
    for j in range(idx - 1, -1, -1):
        if lines[j].strip():
            return lines[j].strip()
    return ""


def check_heading_spacing(text):
    issues = []
    lines = text.splitlines()
    seen_h1 = False
    seen_h2_in_section = False
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            if line.startswith("# 资讯类简报"):
                continue
            if seen_h1 and previous_nonempty(lines, idx) != "<br>":
                issues.append(f"一级标题前缺少独立 <br> 行：{line}")
            seen_h1 = True
            seen_h2_in_section = False
        elif line.startswith("## "):
            if seen_h2_in_section and previous_nonempty(lines, idx) != "<br>":
                issues.append(f"二级标题前缺少独立 <br> 行：{line}")
            seen_h2_in_section = True
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True, help="资讯日报-草稿-YYYYMMDD.md")
    ap.add_argument("--report", required=True, help="资讯类简报-M.D日.md")
    ap.add_argument("--write", default=None, help="可选：写出质检报告 md")
    args = ap.parse_args()

    draft_text = read_text(args.draft)
    report_text = read_text(args.report)
    draft_items = parse_draft(draft_text)
    report_items = parse_report(report_text)
    draft_by_link = {it["link"]: it for it in draft_items}

    fail = []
    warn = []
    ok = []

    if "（北京时间）" not in report_text:
        fail.append("抬头缺少北京时间范围。")
    else:
        ok.append("时间范围已标注北京时间。")

    if "Source 来源：" not in report_text:
        fail.append("缺少 Source 来源表。")
    else:
        ok.append("已包含 Source 来源表。")

    if any(p in report_text for p in OLD_FOOTERS):
        fail.append("仍包含旧 footer（信息来源/兴趣产品跟踪/Appendix）。")

    bad_body = [p for p in BAD_BODY_PHRASES if p in report_text]
    if bad_body:
        fail.append("正文出现采集来源或兜底说明：" + "、".join(bad_body))

    report_urls = [line.strip() for line in report_text.splitlines()
                   if line.strip().startswith(("http://", "https://"))]
    bad_urls = [u for u in report_urls if "\\." in u or "\\-" in u]
    if bad_urls:
        fail.append("URL 被反斜杠转义：" + "；".join(bad_urls[:5]))
    else:
        ok.append("URL 为裸链。")

    missing_links = [it["link"] for it in draft_items if it["link"] not in report_text]
    if missing_links:
        fail.append("草稿 ⭐精选链接未进入成稿：" + "；".join(missing_links[:8]))
    else:
        ok.append("草稿 ⭐精选链接均已覆盖。")

    for it in report_items:
        if not it["link"]:
            fail.append(f"条目缺少单独成行原文链接：{it['title']}")
            continue
        if it["link"] not in draft_by_link:
            warn.append(f"成稿链接不在草稿 ⭐精选中，需确认是否为手工补充：{it['link']}")
            continue
        base = draft_by_link[it["link"]]
        source_text = normalize_number_text(base["title"] + " " + base.get("summary", ""))
        unsupported_nums = sorted(numbers(it["title"] + " " + it["body_text"]) - numbers(source_text))
        if unsupported_nums:
            warn.append(
                f"数字需回看原文确认：{it['title']}（成稿数字未在草稿摘要出现：{', '.join(unsupported_nums[:8])}）"
            )

    total_source = source_count(report_text)
    if total_source is None:
        fail.append("无法解析 Source 来源表条数。")
    elif total_source != len(report_items):
        fail.append(f"Source 来源表合计 {total_source} 条，但正文条目为 {len(report_items)} 条。")
    else:
        ok.append("Source 来源表条数与正文条目一致。")

    spacing_issues = check_heading_spacing(report_text)
    if spacing_issues:
        fail.extend(spacing_issues)
    else:
        ok.append("一级/二级标题间距符合 <br> 规则。")

    lines = [
        f"# 资讯日报质检 · {os.path.basename(args.report)}",
        "",
        f"- 草稿：`{args.draft}`",
        f"- 成稿：`{args.report}`",
        f"- 结论：{'FAIL' if fail else ('WARN' if warn else 'PASS')}",
        "",
        "## 格式与结构",
    ]
    lines += [f"- ✅ {x}" for x in ok] or ["- （无）"]
    lines.append("")
    lines.append("## 必须修复")
    lines += [f"- ❌ {x}" for x in fail] or ["- 无"]
    lines.append("")
    lines.append("## 需要人工复核")
    lines += [f"- ⚠️ {x}" for x in warn] or ["- 无"]
    lines.append("")
    lines.append("## 事实核对要求")
    lines.append("- 对每条资讯，回看草稿摘要和原文链接，确认公司/产品/金额/比例/排名/发布日期均有来源依据。")
    lines.append("- 若只能看到标题和链接，正文只保留标题级事实，不扩写细节。")
    lines.append("- 质检报告不进入最终日报正文。")

    output = "\n".join(lines) + "\n"
    if args.write:
        with open(args.write, "w", encoding="utf-8") as f:
            f.write(output)
    print(output)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
