from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .core import ROOT, fingerprint, now_iso, read_json, write_json
from .leaderboard import repository_heat
from .catalog import SOURCE_FIELDS, GENERAL_FIELDS


def parse_time(value):
    return datetime.fromisoformat(value.replace(" UTC", "+00:00").replace(" ", "T", 1).replace("Z", "+00:00"))


def observe_repository(state, name, stars, captured_at):
    repo = state.setdefault("repositories", {}).setdefault(name, {})
    captured = parse_time(captured_at).isoformat()
    observations = repo.setdefault("star_observations", [])
    if not any(row["captured_at"] == captured and row["stars"] == stars for row in observations):
        observations.append({"captured_at": captured, "stars": stars})
    observations.sort(key=lambda row: row["captured_at"])
    repo["star_observations"] = observations[-180:]
    if not repo.get("stars_captured_at") or parse_time(captured) >= parse_time(repo["stars_captured_at"]):
        repo.update(stars=stars, stars_captured_at=captured)


def seed_verified_observations(root=ROOT):
    path = root / "data/public/collection.json"
    state = read_json(path, {})
    # Recover only actual previous responses; date-only snapshots are never made into fake timed samples.
    for name in list(state.get("repositories", {})):
        cached = read_json(root / "data/cache/http" / (fingerprint("https://api.github.com/repos/" + name) + ".json"), {})
        if cached.get("text") and cached.get("captured_at"):
            try:
                metadata = json.loads(cached["text"])
                if metadata.get("full_name") == name and not metadata.get("private"):
                    observe_repository(state, name, metadata["stargazers_count"], cached["captured_at"])
            except (ValueError, KeyError):
                pass
    snapshots = read_json(root / "evidence/baseline-snapshots-v2.json", {})
    for snapshot in snapshots.get("snapshots", []):
        metadata = snapshot["metadata"]
        if not metadata.get("private"):
            observe_repository(state, snapshot["repository"], metadata["stargazers_count"], snapshot["captured_at"])
    for row in read_json(root / "evidence/public-repo-observations-v5.json", []):
        observe_repository(state, row["name"], row["stars"], row["checked_at"])
    write_json(path, state)
    return state


def growth_rows(state):
    rows = []
    for name, repo in state.get("repositories", {}).items():
        samples = repo.get("star_observations", [])
        if len(samples) < 2:
            continue
        latest = samples[-1]
        latest_time = parse_time(latest["captured_at"])
        choices = [row for row in samples[:-1] if timedelta(hours=2) <= latest_time - parse_time(row["captured_at"]) <= timedelta(days=7)]
        if not choices:
            continue
        baseline = choices[0]
        hours = (latest_time - parse_time(baseline["captured_at"])).total_seconds() / 3600
        delta = latest["stars"] - baseline["stars"]
        percent = delta / max(1, baseline["stars"]) * 100
        rows.append({"repository": name, "url": "https://github.com/" + name, "stars": latest["stars"], "delta": delta,
                     "percent": round(percent, 2), "hours": round(hours, 1), "stars_per_hour": round(delta / hours, 2),
                     "from_at": baseline["captured_at"], "to_at": latest["captured_at"],
                     "fast_growth": delta >= 1000 or delta >= 100 and percent >= 10})
    return sorted(rows, key=lambda row: (-row["stars_per_hour"], -row["delta"]))


def public_home(root=ROOT):
    import tomllib
    from .catalog import catalog_public
    from .public_news import news_public
    catalog = catalog_public(read_json(root / "data/public/catalog.json", {}))
    state = read_json(root / "data/public/collection.json", {})
    allowed = (set(SOURCE_FIELDS) | set(GENERAL_FIELDS)) - {"source_text"}
    skills = [{key: value for key, value in row.items() if key in allowed} for row in catalog.get("items", [])]
    for row in skills:
        latest_stars = state.get("repositories", {}).get(row["repository"], {}).get("stars")
        if latest_stars is not None:
            row["stars"] = latest_stars
        row["featured_score"] = round(row.get("general_score", 50) * .8 + repository_heat(row.get("stars", 0)) * .2)
    ranked = sorted(skills, key=lambda row: (-row["featured_score"], -row.get("stars", 0), row["name"]))
    options = tomllib.loads((root / "config.toml").read_text(encoding="utf-8-sig")) if (root / "config.toml").exists() else {}
    priority = set(options.get("leaderboard", {}).get("priority_names", []))
    ranked.sort(key=lambda row: (row["name"] not in priority, -row["featured_score"], -row.get("stars", 0)))
    featured, remainder, counts = [], [], {}
    for row in ranked:
        name = row["repository"]
        if counts.get(name, 0) < 2:
            featured.append(row)
            counts[name] = counts.get(name, 0) + 1
        else:
            remainder.append(row)
    growth = growth_rows(state)
    news = news_public(read_json(root / "data/public/news.json", {}))
    from .tibo_watch import tibo_public
    tibo = tibo_public(read_json(root / "data/public/tibo.json", {}))
    checked = [row.get("stars_captured_at", "") for row in state.get("repositories", {}).values()] + [row.get("checked_at", "") for row in news.get("sources", [])]
    return {"schema_version": 1, "updated_at": max(checked) if any(checked) else catalog.get("updated_at", now_iso()),
            "featured": featured[:6], "skills": featured + remainder, "growth": growth, "news": news.get("items", []), "tibo": tibo,
            "repositories": catalog.get("repositories", []), "skill_count": len(skills), "repository_count": len(catalog.get("repositories", [])),
            "monitor_status": news.get("sources", []), "growth_note": "增长来自两次真实采样，显示实际采样窗口；尚未积累完整 7 天时不估算周增长。"}
