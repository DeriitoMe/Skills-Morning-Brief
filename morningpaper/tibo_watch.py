"""Public quota-reset monitoring. Discovery hints are never publication evidence."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

from .core import ROOT, fingerprint, now_iso, read_json, write_json
from .network import urlopen

ACCOUNT = "thsottiaux"
PROFILE_URL = "https://x.com/" + ACCOUNT
OFFICIAL = {
    "changelog": "https://learn.chatgpt.com/docs/changelog",
    "pricing": "https://learn.chatgpt.com/docs/pricing",
    "resets": "https://learn.chatgpt.com/docs/app-server",
}
DISCOVERY = [
    ("公开 RSS 发现", "https://x.noodl3.net/thsottiaux/rss"),
    ("公开页面发现", "https://twiscan.com/en/x/thsottiaux"),
]
ITEM_FIELDS = {"id", "title", "summary", "source", "url", "published_at", "date_precision", "collected_at", "last_verified_at",
               "mechanism", "mechanism_label", "scope", "event_status", "reset_at", "reset_time_text", "time_note", "facts", "uncertainties",
               "verification", "fingerprint", "content_key", "excerpt", "source_truncated", "related_urls", "conflict_group"}
STATUS_FIELDS = {"source", "status", "detail", "checked_at", "url"}


class SourceError(RuntimeError):
    pass


class DocumentText(HTMLParser):
    def __init__(self, paragraph_only=False):
        super().__init__(); self.parts = []; self.skip = 0; self.paragraph_only = paragraph_only; self.in_p = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"): self.skip += 1
        if tag == "p": self.in_p += 1
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "br", "div"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self.skip: self.skip -= 1
        if tag == "p" and self.in_p: self.in_p -= 1
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "div"): self.parts.append("\n")
    def handle_data(self, data):
        if not self.skip and (not self.paragraph_only or self.in_p): self.parts.append(data)
    def text(self):
        return unescape("".join(self.parts))


def fetch_text(url, *, secret=None, allowed_domains=None, timeout=12):
    headers = {"User-Agent": "Skills-Morning-Brief/1.1", "Accept": "application/json,text/html,application/rss+xml"}
    if secret: headers["Authorization"] = "Bearer " + secret
    try:
        with urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            final = urllib.parse.urlparse(response.geturl())
            if allowed_domains and (final.scheme != "https" or final.hostname not in allowed_domains):
                raise SourceError("来源重定向至未认可的发布域名")
            raw = response.read(1_500_001)
        if len(raw) > 1_500_000: raise SourceError("来源超过读取上限")
        return raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise SourceError("来源访问受限或不可用（HTTP " + str(exc.code) + "）") from None
    except (OSError, UnicodeError, ValueError):
        raise SourceError("来源连接或解析失败") from None


def status(source, state, detail, url=None):
    return {"source": source, "status": state, "detail": detail, "url": url, "checked_at": now_iso()}


def tibo_public(value):
    return {"schema_version": 1, "updated_at": value.get("updated_at"), "last_success_at": value.get("last_success_at"),
            "status": value.get("status", "not_checked"), "coverage": value.get("coverage", "尚未执行此专栏监测"),
            "new_count": value.get("new_count", 0), "updated_count": value.get("updated_count", 0),
            "candidate_count": value.get("candidate_count", 0), "verified_count": value.get("verified_count", 0),
            "pending_count": value.get("pending_count", 0),
            "items": [{key: row[key] for key in ITEM_FIELDS if key in row} for row in value.get("items", [])],
            "references": [{key: row[key] for key in ITEM_FIELDS if key in row} for row in value.get("references", [])],
            "sources": [{key: row[key] for key in STATUS_FIELDS if key in row} for row in value.get("sources", [])]}


def is_reset_topic(text):
    reset = re.search(r"\breset(?:s|ting)?\b|重置|补发", text, re.I)
    target = re.search(r"\bcodex\b|chatgpt", text, re.I)
    banked = re.search(r"\bbanked reset|reset banking", text, re.I)
    other = re.search(r"github|claude|anthropic|gemini|google|cursor", text, re.I)
    quota = bool(target or banked and not other)
    unrelated = re.search(r"password|factory reset|reset (?:your |the )?(?:password|conversation|memory)|密码", text, re.I)
    return bool(reset and quota and not unrelated)


def source_date(html, canonical):
    class DateLinks(HTMLParser):
        def __init__(self): super().__init__(); self.active = False; self.parts = []; self.links = []
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                href = urllib.parse.urlparse(dict(attrs).get("href", ""))
                target = urllib.parse.urlparse(canonical)
                self.active = href.hostname in ("x.com", "twitter.com", "www.x.com", "www.twitter.com") and href.path == target.path
                self.parts = []
        def handle_data(self, data):
            if self.active: self.parts.append(data)
        def handle_endtag(self, tag):
            if tag == "a" and self.active:
                self.links.append("".join(self.parts)); self.active = False
    parser = DateLinks(); parser.feed(html)
    anchor_text = parser.links[-1] if parser.links else ""
    months = {name: index for index, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
    match = re.search(r"(" + "|".join(months) + r")\s+(\d{1,2}),\s*(\d{4})", anchor_text)
    if not match: return None
    try: return datetime(int(match[3]), months[match[1]], int(match[2])).date().isoformat()
    except ValueError: return None


def verify_oembed(post_id, getter=fetch_text):
    if not re.fullmatch(r"\d{18,20}", post_id): raise SourceError("帖子标识不正确")
    canonical = PROFILE_URL + "/status/" + post_id
    endpoint = "https://publish.twitter.com/oembed?" + urllib.parse.urlencode({"url": canonical, "omit_script": "true"})
    data = json.loads(getter(endpoint, allowed_domains={"publish.twitter.com", "publish.x.com"}))
    author = urllib.parse.urlparse(data.get("author_url", ""))
    post = urllib.parse.urlparse(data.get("url", ""))
    hosts = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}
    if author.hostname not in hosts or author.path.strip("/").lower() != ACCOUNT or post.hostname not in hosts or post.path != "/thsottiaux/status/" + post_id:
        raise SourceError("原发布接口的作者或帖子链接不一致")
    html = data.get("html", "")
    parser = DocumentText(paragraph_only=True); parser.feed(html)
    text = re.sub(r"\s+", " ", parser.text()).strip()
    if not text: raise SourceError("原发布接口没有可读正文")
    published = source_date(html, canonical)
    return {"id": post_id, "text": text, "url": canonical, "published_at": published,
            "date_precision": "day" if published else "unknown", "truncated": "…" in text and "https://t.co/" in text,
            "evidence": "X 官方发布接口", "author_id": ACCOUNT, "verified_at": now_iso()}


def classify_post(post):
    text = post["text"]
    if not is_reset_topic(text): return None
    lower = text.lower()
    reset_sentences = " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if re.search(r"reset|重置|补发", sentence, re.I))
    reset_lower = reset_sentences.lower()
    banked = bool(re.search(r"bank(?:ed|ing)? reset|reset bank", lower))
    denied = bool(re.search(r"\b(?:can.?t|cannot|won.?t)\b.{0,120}\breset|\bno (?:new |banked )?reset|\bnot (?:going to )?(?:give|giving|ship|shipping|do|doing|grant|granting|reset|resetting|coming|happening|planned|available)\b", reset_lower))
    proposal = "?" in reset_sentences or bool(re.search(r"\b(?:if|could|might|would|should|may)\b|\bwhat if\b", reset_lower))
    planned = bool(re.search(r"\bwill\b|tomorrow|going to|plan to|by eod|soon", reset_lower))
    underway = bool(re.search(r"loading|propagating|rolling out", lower))
    complete = bool(re.search(r"\b(?:we(?: have|.?ve)?|i(?: have|.?ve)?|have|has) reset (?:all|codex|usage|limits)|reset (?:has been |is )?(?:processed|done|completed)|reset all propagated", lower))
    state = "not_announced" if denied else "proposal" if proposal else "mixed" if complete and planned else "announced" if planned else "in_progress" if underway else "completed" if complete else "unclear"
    mechanism = "banked_reset" if banked else "quota_refresh"
    if denied: mechanism = "no_reset"
    scope = "原文未明确适用账户或计划"
    if re.search(r"everyone.?s paid|all paid|paid accounts", lower): scope = "原文称付费账户，未逐项列出计划"
    elif "all plans" in lower: scope = "原文称所有计划，具体额度窗口未逐项说明"
    elif re.search(r"\bplus\b|\bpro\b", lower): scope = "原文提及 " + " / ".join(name for name in ("Plus", "Pro") if re.search(r"\b" + name.lower() + r"\b", lower))
    time_context = " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text)
                            if re.search(r"reset|重置|补发", sentence, re.I) and not re.search(r"expir|expires|到期", sentence, re.I))
    time_match = re.search(r".{0,12}\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b.{0,20}\b(?:PST|PDT|UTC|GMT)\b|\b(?:tomorrow|by EOD(?: PST| PDT)?|end of day)\b", time_context, re.I)
    time_text = " ".join(time_match[0].strip().split()[:12]) if time_match else "原文未给出确切重置时刻"
    if denied or proposal: time_text = "原帖未确认重置安排，不能据条件或提问指定时刻"
    uncertainty = []
    if post.get("truncated"): uncertainty.append("原发布接口返回截断正文，未读取部分不作为结论")
    if time_match: uncertainty.append("保留原文时间表述；相对日期或 PST/PDT 含义未确认时不换算北京时间")
    else: uncertainty.append("发帖时间与额度重置发生时间分别记录")
    uncertainty.append("公告不证明某个具体账户已到账，账户状态以官方用量页为准")
    if denied:
        title, summary = "Tibo：本条未宣布新的额度重置", "原帖含否定或尚未确认表述，本条没有据此确认为账户新补发或宣布额度刷新。具体含义以原文为准。"
    elif proposal:
        title, summary = "Tibo：额度重置讨论，尚未宣布", "原帖是条件、提问或提议，本条没有据此确认为账户新补发或刷新完成。"
    elif banked:
        granted = bool(re.search(r"loading|grant|giv(?:e|ing)|add(?:ed|ing)?|ship", reset_lower))
        title = "Tibo：可储存的额度重置补发" if granted else "Tibo：可储存的额度重置信息"
        if granted:
            summary = "原帖提到补发可储存的额度重置。" + ("原文描述正在补发，尚不能据此确认每个账户到账。" if underway else "具体到账时刻和账户资格请结合原文确认。")
        else:
            summary = "原帖涉及可储存的额度重置。本条没有据此确认为账户新补发，获取或使用条件以原文为准。"
    else:
        title = "Tibo：额度刷新" + ("已宣布" if state == "announced" else "完成" if state == "completed" else "状态待确认")
        summary = "原帖明确涉及额度重置。" + ("作者表示刷新已完成。" if state == "completed" else "当前可读原文未确认具体执行结果。")
    excerpt_words = text.split()
    index = next((i for i, word in enumerate(excerpt_words) if "reset" in word.lower()), 0)
    excerpt = " ".join(excerpt_words[max(0, index - 3):max(0, index - 3) + 12])
    key_text = re.sub(r"https?://\S+", "", text).lower()
    result = {"id": "x:" + post["id"], "title": title, "summary": summary, "source": "Tibo @thsottiaux", "url": post["url"],
              "published_at": post.get("published_at"), "date_precision": post.get("date_precision", "unknown"),
              "collected_at": now_iso(), "last_verified_at": post.get("verified_at", now_iso()), "mechanism": mechanism,
              "mechanism_label": "可储存重置信息" if banked and proposal else {"banked_reset": "额度补发 / 可储存重置", "quota_refresh": "额度刷新", "no_reset": "未宣布重置"}[mechanism],
              "scope": scope, "event_status": state, "reset_at": None, "reset_time_text": time_text,
              "time_note": "仅保留来源明确写出的时间；没有统一固定重置时刻的推断", "facts": [summary], "uncertainties": uncertainty,
              "verification": "source_verified", "fingerprint": fingerprint(text),
              "content_key": fingerprint([re.sub(r"\s+", " ", key_text).strip(), (post.get("published_at") or "")[:10]]),
              "excerpt": excerpt, "source_truncated": bool(post.get("truncated"))}
    if post.get("conversation_id"):
        result["conflict_group"] = "x-thread:" + str(post["conversation_id"])
    return result


def merge_records(previous, incoming):
    rows = {row["id"]: dict(row) for row in previous}
    by_content = {row.get("content_key"): row["id"] for row in rows.values() if row.get("content_key")}
    new, updated = 0, 0
    for row in incoming:
        old = rows.get(row["id"])
        if old:
            old_key = old.get("content_key")
            if old_key and by_content.get(old_key) == row["id"]: by_content.pop(old_key, None)
            updated += old.get("fingerprint") != row["fingerprint"]
            row = {**row, "collected_at": old.get("collected_at", row["collected_at"])}
        elif row.get("content_key") in by_content:
            existing = rows[by_content[row["content_key"]]]
            existing["related_urls"] = list(dict.fromkeys([*existing.get("related_urls", []), row["url"]]))[:4]
            existing["last_verified_at"] = row["last_verified_at"]
            continue
        else:
            new += 1
        rows[row["id"]] = row; by_content[row.get("content_key")] = row["id"]
    result = sorted(rows.values(), key=lambda row: (row.get("published_at") or "", row["id"]), reverse=True)[:80]
    return result, new, updated


def mark_conflicts(rows):
    groups = {}
    for row in rows:
        if row.get("conflict_group"): groups.setdefault(row["conflict_group"], []).append(row)
    for group in groups.values():
        declared = {row.get("reset_at") or row.get("reset_time_text") for row in group
                    if row.get("reset_at") or row.get("reset_time_text") not in (None, "原文未给出确切重置时刻")}
        states = {row.get("event_status") for row in group}
        if len(declared) > 1 or "not_announced" in states and "announced" in states:
            for row in group:
                row["verification"] = "conflicting"
                row["uncertainties"] = [*row.get("uncertainties", []), "同一事件的来源表述存在冲突，暂不确认重置时间或机制"]
    return rows


def official_information(getter=fetch_text):
    records, refs, statuses = [], [], []
    for key, url in OFFICIAL.items():
        try:
            html = getter(url, allowed_domains={"learn.chatgpt.com", "developers.openai.com"})
            parser = DocumentText(); parser.feed(html); text = parser.text()
            if key == "changelog":
                current_day = None
                for line in text.splitlines():
                    match = re.search(r"\b(202\d-\d{2}-\d{2})\b", line)
                    if match: current_day = match[1]
                    if re.search(r"added rate.limit reset banking", line, re.I):
                        records.append({"id": "official:banking:" + str(current_day), "title": "官方说明：可储存的额度重置上线",
                            "summary": "历史上线说明介绍 Plus、Pro 的可储存额度重置。上线时的赠送和邀请活动有各自条件，不代表今天所有账户再次补发。",
                            "source": "OpenAI 官方更新", "url": url, "published_at": current_day, "date_precision": "day" if current_day else "unknown",
                            "collected_at": now_iso(), "last_verified_at": now_iso(), "mechanism": "mechanism_update", "mechanism_label": "重置方式说明",
                            "scope": "历史上线说明：Plus / Pro，活动资格以当时规则为准", "event_status": "documented", "reset_at": None,
                            "reset_time_text": "功能上线日期，不是统一账户重置时刻", "verification": "official_verified", "facts": ["支持储存额度重置"],
                            "uncertainties": ["当前账户是否持有可用重置，以官方用量页为准"], "fingerprint": fingerprint(line.strip()),
                            "content_key": fingerprint([url, current_day, line.strip()])})
            elif key == "pricing":
                if not re.search(r"reset times|重置时间", text, re.I): raise SourceError("官方页面未提取到重置时间说明")
                refs.append({"id": "reference:pricing", "title": "个人重置时间以官方用量页为准", "summary": "官方说明建议查看用量页中的当前限制和重置时间。本专栏记录公共公告，不读取你的账户额度。",
                    "source": "OpenAI 官方定价与用量说明", "url": url, "published_at": None, "date_precision": "undated", "collected_at": now_iso(),
                    "last_verified_at": now_iso(), "mechanism_label": "常规额度窗口", "scope": "具体账户的当前限制", "verification": "official_verified"})
            else:
                if "account/rateLimitResetCredit/consume" not in text or "nothingToReset" not in text: raise SourceError("官方页面未提取到可用重置说明")
                refs.append({"id": "reference:banking", "title": "可用的储存重置需要手动使用", "summary": "官方说明区分已兑换、没有可用重置和没有可重置窗口等状态。兑换后应重新查看账户限制。本网站只提供信息，不替你消费重置。",
                    "source": "OpenAI 官方重置说明", "url": url, "published_at": None, "date_precision": "undated", "collected_at": now_iso(),
                    "last_verified_at": now_iso(), "mechanism_label": "可储存 / 手动重置", "scope": "有可用重置且有合格额度窗口的账户", "verification": "official_verified"})
            statuses.append(status("官方额度说明：" + key, "ok", "已读取官方原文", url))
        except (SourceError, ValueError, KeyError, TypeError):
            statuses.append(status("官方额度说明：" + key, "failed", "官方原文暂不可读或结构发生变化，保留之前的核对记录", url))
    return records, refs, statuses


def api_posts(getter, limit=20):
    secret = os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN")
    if not secret: return None
    user = json.loads(getter("https://api.x.com/2/users/by/username/thsottiaux?user.fields=protected,username", secret=secret, allowed_domains={"api.x.com"}))
    data = user["data"]
    if data.get("username", "").lower() != ACCOUNT or data.get("protected") is not False:
        raise SourceError("账号不是已确认的公开目标账号")
    user_id = str(data["id"])
    if not user_id.isdigit(): raise SourceError("账号标识不正确")
    params = urllib.parse.urlencode({"max_results": min(100, max(5, limit)), "exclude": "retweets", "tweet.fields": "created_at,author_id,conversation_id"})
    result = json.loads(getter("https://api.x.com/2/users/" + user_id + "/tweets?" + params, secret=secret, allowed_domains={"api.x.com"}))
    return [{"id": row["id"], "text": row.get("note_tweet", {}).get("text") or row["text"], "url": PROFILE_URL + "/status/" + row["id"], "published_at": row["created_at"],
             "date_precision": "second", "truncated": "…" in row["text"] and "https://t.co/" in row["text"] and not row.get("note_tweet"),
             "author_id": ACCOUNT, "conversation_id": row.get("conversation_id"), "verified_at": now_iso()}
            for row in result.get("data", []) if str(row.get("author_id")) == user_id]


def refresh_tibo(root=ROOT, getter=fetch_text, max_posts=20, max_verifications=8):
    path = root / "data/public/tibo.json"
    previous = tibo_public(read_json(path, {})); incoming, statuses, candidates = [], [], set()
    cache_path = root / "data/cache/tibo/verified.json"
    cache = read_json(cache_path, {"posts": {}})
    cached_posts = cache.get("posts", {})
    api_complete = False; verified = 0
    withdrawn = set()
    try:
        posts = api_posts(getter, max_posts)
        if posts is None:
            statuses.append(status("X 官方时间线", "not_configured", "使用公开发现和原发布接口，完整时间线尚未启用", PROFILE_URL))
        else:
            api_complete = True; verified = len(posts)
            candidates.update(post["id"] for post in posts)
            for post in posts:
                row = classify_post(post)
                if row: incoming.append(row)
                else: withdrawn.add("x:" + post["id"])
            statuses.append(status("X 官方时间线", "ok", "核对最近最多 " + str(max_posts) + " 条原帖，非全量历史", PROFILE_URL))
    except (SourceError, ValueError, KeyError, TypeError):
        statuses.append(status("X 官方时间线", "failed", "授权、额度或接口读取失败，改用公开发现；密钥未保存", PROFILE_URL))
    if not api_complete:
        for label, url in DISCOVERY:
            try:
                raw = getter(url)
                ids = re.findall(r"thsottiaux/(?:status/)?(\d{18,20})", unescape(raw))
                candidates.update(ids)
                statuses.append(status(label, "ok" if ids else "partial", "仅发现原帖链接；镜像正文和时间不作为发布证据", url))
            except (SourceError, ValueError, ET.ParseError):
                statuses.append(status(label, "failed", "发现来源暂不可用；不能据此判断今天没有重置", url))
        failures = 0
        candidates = set(sorted(candidates, key=int, reverse=True)[:max_posts])
        relevant_old = [row["id"].removeprefix("x:") for row in previous["items"] if row["id"].startswith("x:")]
        pending = [pid for pid in sorted(candidates, key=int, reverse=True) if pid not in cached_posts]
        oldest = lambda pid: (cached_posts.get(pid, {}).get("verified_at", ""), -int(pid))
        recheck = sorted((pid for pid in relevant_old if pid in candidates), key=oldest)[:2]
        remainder = sorted((pid for pid in candidates if pid not in pending and pid not in recheck), key=oldest)
        order = list(dict.fromkeys([*recheck, *pending, *remainder]))[:min(max_posts, max_verifications)]
        for post_id in order:
            try:
                post = verify_oembed(post_id, getter); verified += 1
                cached_posts[post_id] = post
                if not classify_post(post): withdrawn.add("x:" + post_id)
            except (SourceError, ValueError, KeyError, TypeError): failures += 1
        for post in cached_posts.values():
            row = classify_post(post)
            if row: incoming.append(row)
        cache["posts"] = {key: cached_posts[key] for key in sorted(cached_posts, key=int, reverse=True)[:200]}
        write_json(cache_path, cache)
        statuses.append(status("X 原发布接口核验", "partial" if failures or len(candidates) > max_verifications else "ok" if verified else "failed",
                               "已核对 " + str(verified) + " 条原帖；失败 " + str(failures) + " 条；截断或含糊正文不作完整结论", PROFILE_URL))
    official, refs, official_status = official_information(getter)
    incoming.extend(official); statuses.extend(official_status)
    eligible_old = [row for row in previous["items"] if row["id"] not in withdrawn]
    merged, new, updated = merge_records(eligible_old, incoming)
    updated += len(previous["items"]) - len(eligible_old)
    reference_map = {row["id"]: row for row in previous["references"]}
    reference_map.update({row["id"]: row for row in refs})
    any_success = bool(verified or official or refs)
    result = {"schema_version": 1, "updated_at": now_iso(), "last_success_at": now_iso() if any_success else previous.get("last_success_at"),
              "status": "ok" if api_complete and not any(row["status"] == "failed" for row in statuses) else "partial" if any_success else "unavailable",
              "coverage": "每天 08:30 / 20:30 核对（上海时间）；公开发现不保证完整时间线。最近最多 " + str(max_posts) + " 个链接，本轮最多 " + str(max_verifications) + " 条原发布接口核验。发帖时间只到日期时明确标注，绝不当作重置发生时间。",
              "new_count": new, "updated_count": updated, "candidate_count": len(candidates), "verified_count": verified,
              "pending_count": len(candidates - set(cached_posts)) if not api_complete else 0,
              "items": mark_conflicts(merged), "references": list(reference_map.values()), "sources": statuses}
    result = tibo_public(result); write_json(path, result)
    return result
