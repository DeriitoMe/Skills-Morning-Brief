from __future__ import annotations

from pathlib import Path
from .core import ROOT, fingerprint, now_iso, read_json, write_json
from .providers import ProviderError, generate_json, provider_identity


SOURCE_FIELDS = ("id", "name", "description", "repository", "path", "url", "repository_url", "stars", "stars_delta_7d", "collected_at",
                 "fingerprint", "source_fingerprint", "official", "tags", "license", "source_status", "source_text", "source_text_truncated",
                 "compatibility", "allowed_tools", "dependency_paths", "dependency_review", "blob_sha", "commit_sha")
GENERAL_FIELDS = ("summary", "general_score", "general_reason", "difficulty", "host_notes", "evidence_paths", "general_reviewed_at", "neutral_status")


def public_checkpoint(state):
    repositories = {}
    for name, repo in state.get("repositories", {}).items():
        clean = {key: repo[key] for key in ("repo_id", "tree_sha", "commit_sha", "stars", "skill_count", "checked_at", "last_complete_at", "star_snapshots", "star_observations", "stars_captured_at", "pending_files") if key in repo}
        clean["candidates"] = {path: {key: row[key] for key in SOURCE_FIELDS if key in row} for path, row in repo.get("candidates", {}).items()}
        repositories[name] = clean
    return {"repositories": repositories,
            "feeds": {url: {key: row[key] for key in ("fingerprint", "last_success_at") if key in row} for url, row in state.get("feeds", {}).items()},
            "discovered_repositories": {name: {key: row[key] for key in ("name", "priority", "stars") if key in row} for name, row in state.get("discovered_repositories", {}).items()},
            "rotation_cursor": state.get("rotation_cursor", 0)}


def prepare_catalog(root=ROOT, public_state=None):
    # Ship public summaries so a clean download can be read before its first refresh.
    for name, clean in (("catalog", catalog_public),):
        seed = read_json(root / "seeds" / (name + ".json"))
        destination = root / "data/public" / (name + ".json")
        if seed and not destination.exists():
            write_json(destination, clean(seed))
    for name in ("collection", "news"):
        seed = read_json(root / "seeds" / (name + ".json"))
        destination = root / "data/public" / (name + ".json")
        if seed and not destination.exists():
            if name == "collection":
                seed = public_checkpoint(seed)
            else:
                from .public_news import news_public
                seed = news_public(seed)
            write_json(destination, seed)
    state = public_state if public_state is not None else read_json(root / "data/public/collection.json") or read_json(root / "data/state.json", {})
    path = root / "data/public/catalog.json"
    previous = read_json(path, {})
    old_rows = {row["id"]: row for row in previous.get("items", [])}
    rows = []
    for repo in state.get("repositories", {}).values():
        for source in repo.get("candidates", {}).values():
            row = {key: source[key] for key in SOURCE_FIELDS if key in source}
            old = old_rows.get(row["id"], {})
            if old.get("fingerprint") == row["fingerprint"]:
                row.update({key: old[key] for key in GENERAL_FIELDS if key in old})
            row.setdefault("neutral_status", "pending")
            rows.append(row)
    if not rows and previous:
        return previous
    catalog = {"schema_version": 1, "updated_at": now_iso(), "items": rows,
               "repositories": [{"name": name, "stars": repo.get("stars", 0), "skill_count": repo.get("skill_count", len(repo.get("candidates", {}))),
                                 "read_count": len(repo.get("candidates", {})), "checked_at": repo.get("checked_at"), "url": "https://github.com/" + name}
                                for name, repo in state.get("repositories", {}).items()]}
    catalog["version"] = fingerprint([(row["id"], row["fingerprint"]) for row in sorted(rows, key=lambda row: row["id"])])
    write_json(path, catalog)
    # A public collection checkpoint never carries a person's reading history or feedback.
    write_json(root / "data/public/collection.json", public_checkpoint(state))
    return catalog


def catalog_public(catalog):
    allowed = (set(SOURCE_FIELDS) | set(GENERAL_FIELDS)) - {"source_text"}
    repo_fields = {"name", "stars", "skill_count", "read_count", "checked_at", "url"}
    return {"schema_version": catalog.get("schema_version", 1), "updated_at": catalog.get("updated_at"),
            "version": catalog.get("version"),
            "items": [{key: value for key, value in row.items() if key in allowed} for row in catalog.get("items", [])],
            "repositories": [{key: value for key, value in row.items() if key in repo_fields} for row in catalog.get("repositories", [])]}


def evaluate_catalog(catalog, settings, runtime, root=ROOT, limit=80, progress=None, secret=None):
    instruction = (root / "prompts/catalog-editor.md").read_text(encoding="utf-8")
    schema = read_json(root / "prompts/catalog.schema.json")
    pending = [row for row in catalog["items"] if row.get("neutral_status") != "ai_reviewed"][:limit]
    for index in range(0, len(pending), 6):
        batch = pending[index:index + 6]
        from .source_cache import with_source
        payload = {"skills": [with_source(row, Path(runtime) / "source-cache") for row in batch]}
        result = generate_json(instruction, payload, schema, settings, runtime, secret)
        by_id = {row["id"]: row for row in batch}
        seen = set()
        for analysis in result["analyses"]:
            candidate = by_id.get(analysis["id"])
            if candidate is None or analysis["id"] in seen or analysis["evidence_paths"] != [candidate["path"]]:
                raise ProviderError("通用评价包含未知条目或尚未读取的证据")
            seen.add(analysis["id"])
        if seen != set(by_id):
            raise ProviderError("通用评价没有覆盖全部输入条目")
        for analysis in result["analyses"]:
            by_id[analysis["id"]].update(analysis, neutral_status="ai_reviewed", general_reviewed_at=now_iso())
        write_json(root / "data/public/catalog.json", catalog)
        if progress:
            progress(sum(row.get("neutral_status") == "ai_reviewed" for row in catalog["items"]), len(catalog["items"]))
    return catalog
