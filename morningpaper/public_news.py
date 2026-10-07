from __future__ import annotations

import os
import re
from xml.etree.ElementTree import ParseError
from html import unescape
from html.parser import HTMLParser

from .collect import CollectionError, HttpClient, collect_feed
from .core import ROOT, fingerprint, now_iso, read_json, write_json
from .providers import ProviderError, generate_json

NEWS_FIELDS = {"id", "title", "url", "source", "published_at", "date_precision", "fingerprint", "collected_at", "summary", "impact", "edit_status"}
STATUS_FIELDS = {"source", "status", "detail", "checked_at"}


def news_public(news):
    return {"updated_at": news.get("updated_at"),
            "items": [{key: value for key, value in row.items() if key in NEWS_FIELDS} for row in news.get("items", [])],
            "sources": [{key: value for key, value in row.items() if key in STATUS_FIELDS} for row in news.get("sources", [])]}


PUBLIC_FEEDS = [
    {"name": "OpenAI 官方动态", "url": "https://learn.chatgpt.com/docs/whats-new", "kind": "official_docs"},
    {"name": "Codex 发布", "url": "https://github.com/openai/codex/releases.atom", "kind": "atom"},
    {"name": "Claude Code 发布", "url": "https://github.com/anthropics/claude-code/releases.atom", "kind": "atom"},
]


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.skip = 0; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == "article": self.active = True
        if self.active and tag in ("script", "style"): self.skip += 1
        if self.active and tag in ("p", "h1", "h2", "h3", "li", "br"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag == "article": self.active = False
        if self.active and tag in ("script", "style") and self.skip: self.skip -= 1
    def handle_data(self, data):
        if self.active and not self.skip: self.parts.append(data)


def deepseek_updates(client):
    url = "https://api-docs.deepseek.com/updates/"
    parser = ArticleText(); parser.feed(client.get(url))
    text = unescape("".join(parser.parts))
    sections = re.split(r"Date:\s*(\d{4}-\d{2}-\d{2})", text)
    rows = []
    for index in range(1, len(sections) - 1, 2):
        day, body = sections[index], sections[index + 1]
        lines = [line.strip().strip("# \u200b") for line in body.splitlines() if line.strip()]
        if not lines: continue
        title = lines[0][:180]
        rows.append({"id": fingerprint(url + day + title), "title": title, "url": url, "source": "DeepSeek 官方更新",
                     "published_at": day + "T00:00:00+00:00", "date_precision": "day", "source_text": body[:6000],
                     "fingerprint": fingerprint(body), "collected_at": now_iso()})
        if len(rows) == 3: break
    if not rows: raise CollectionError("官方更新页面未提取到带日期的正文")
    return rows


def refresh_public_news(root=ROOT, settings=None):
    previous = read_json(root / "data/public/news.json", {})
    old_items = {row["id"]: row for row in previous.get("items", [])}
    source_state = read_json(root / "data/public/news-state.json", {})
    pending = dict(source_state.get("candidates", {}))
    client = HttpClient(root, budget=8, timeout=20)
    statuses = []
    for feed in PUBLIC_FEEDS:
        try:
            rows = collect_feed(client, feed, source_state)
            for row in rows:
                row["collected_at"] = now_iso()
                row["source_text"] = unescape(re.sub(r"<[^>]+>", " ", row["source_text"]))
                pending[row["id"]] = row
            statuses.append({"source": feed["name"], "status": "ok", "detail": "已检查官方来源", "checked_at": now_iso()})
        except (CollectionError, ValueError, ParseError) as exc:
            statuses.append({"source": feed["name"], "status": "failed", "detail": str(exc)[:150], "checked_at": now_iso()})
    try:
        for row in deepseek_updates(client): pending[row["id"]] = row
        statuses.append({"source": "DeepSeek 官方更新", "status": "ok", "detail": "已读取带日期的官方更新", "checked_at": now_iso()})
    except (CollectionError, ValueError) as exc:
        statuses.append({"source": "DeepSeek 官方更新", "status": "failed", "detail": str(exc)[:150], "checked_at": now_iso()})
    candidates = sorted(pending.values(), key=lambda row: row.get("published_at") or row.get("collected_at", ""), reverse=True)
    selected, counts = [], {}
    for row in candidates:
        if counts.get(row["source"], 0) < 2:
            selected.append(row); counts[row["source"]] = counts.get(row["source"], 0) + 1
        if len(selected) == 8: break
    needs_edit = [row for row in selected if old_items.get(row["id"], {}).get("fingerprint") != row["fingerprint"] or old_items.get(row["id"], {}).get("edit_status") != "ai_reviewed"]
    edited = dict(old_items)
    if needs_edit:
        try:
            provider = settings or {"id": "deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "codex"}
            result = generate_json((root / "prompts/public-news.md").read_text(encoding="utf-8"), {"checked_at": now_iso(), "sources": needs_edit},
                                   read_json(root / "prompts/public-news.schema.json"), provider, root / ".runtime/public-news")
            known = {row["id"]: row for row in needs_edit}; seen = set()
            for row in result["items"]:
                if row["id"] not in known or row["id"] in seen: raise ProviderError("资讯编辑返回未知或重复来源")
                seen.add(row["id"])
                source = known[row["id"]]
                edited[row["id"]] = {**{key: value for key, value in source.items() if key != "source_text"}, **row, "edit_status": "ai_reviewed"}
            if seen != set(known):
                raise ProviderError("资讯编辑未覆盖全部输入来源")
            statuses.append({"source": "公共资讯编辑", "status": "ok", "detail": "只使用公开原文，未输入私人画像", "checked_at": now_iso()})
        except (ProviderError, OSError) as exc:
            statuses.append({"source": "公共资讯编辑", "status": "failed", "detail": str(exc)[:200], "checked_at": now_iso()})
    items = []
    for source in selected:
        row = edited.get(source["id"])
        if row and row.get("fingerprint") == source["fingerprint"]:
            items.append(row)
        else:
            items.append({**{key: value for key, value in source.items() if key != "source_text"}, "summary": "官方原文已收录，中文摘要正在整理。", "impact": "", "edit_status": "pending"})
    news = {"updated_at": now_iso(), "items": items, "sources": statuses}
    source_state["candidates"] = dict(list(pending.items())[-40:])
    write_json(root / "data/public/news-state.json", source_state)
    write_json(root / "data/public/news.json", news)
    return news
