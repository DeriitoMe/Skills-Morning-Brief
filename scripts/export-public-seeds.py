"""Export shareable public facts using the application's public field allowlists."""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from morningpaper.catalog import catalog_public, public_checkpoint
from morningpaper.core import read_json, write_json
from morningpaper.public_news import news_public


def export_seeds(project=root):
    catalog = catalog_public(read_json(project / "data/public/catalog.json", {}))
    collection = public_checkpoint(read_json(project / "data/public/collection.json", {}))
    for repo in collection["repositories"].values():
        for candidate in repo.get("candidates", {}).values():
            candidate.pop("source_text", None)
    news = news_public(read_json(project / "data/public/news.json", {}))
    for name, value in (("catalog", catalog), ("collection", collection), ("news", news)):
        write_json(project / "seeds" / (name + ".json"), value)
    return len(catalog["items"])


if __name__ == "__main__":
    print("Public summaries exported:", export_seeds())
