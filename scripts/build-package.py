"""Build the local distribution from an explicit source allowlist."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from morningpaper.catalog import catalog_public, public_checkpoint
from morningpaper.core import read_json
from morningpaper.public_news import news_public


def source_files(project=root):
    base = ["README.md", "VERSION", ".gitignore", ".gitattributes", "config.toml", "Open-Skills-Morning-Brief.cmd", "open-skills-morning-brief.sh", ".github/workflows/ci.yml", "web/vendor/manifest.json",
            "docs/SECURITY.md", "docs/release-v1.md", "profile/inventory-sources.example.json",
            ".agents/skills/agent-morning-paper/SKILL.md", ".agents/skills/agent-morning-paper/agents/openai.yaml"]
    files = [project / name for name in base if (project / name).is_file()]
    for folder, suffixes in (("morningpaper", {".py"}), ("tests", {".py"}), ("scripts", {".py", ".ps1"}), ("web", {".html", ".css", ".js"})):
        files.extend(path for path in (project / folder).rglob("*") if path.is_file() and path.suffix in suffixes
                     and not {"__pycache__", "data", "node_modules"} & set(path.relative_to(project / folder).parts))
    for folder in ("prompts", "seeds"):
        files.extend(path for path in (project / folder).glob("*") if path.is_file() and path.name not in {"product-v2.md", "product-v3.md", "product-v4.md"})
    return sorted(set(files))


def build(project=root):
    version = (project / "VERSION").read_text().strip()
    destination = project / "dist" / ("Skills-Morning-Brief-" + version + ".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    prefix = "Skills-Morning-Brief/"
    catalog = catalog_public(read_json(project / "seeds/catalog.json", {}))
    if not catalog["items"]: raise RuntimeError("Export and review public seeds before building")
    collection = public_checkpoint(read_json(project / "seeds/collection.json", {}))
    for repo in collection["repositories"].values():
        for row in repo.get("candidates", {}).values(): row.pop("source_text", None)
    news = news_public(read_json(project / "seeds/news.json", {}))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(project): archive.write(path, prefix + path.relative_to(project).as_posix())
        for name, value in (("catalog", catalog), ("collection", collection), ("news", news)):
            archive.writestr(prefix + "data/public/" + name + ".json", json.dumps(value, ensure_ascii=False))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(".zip.sha256")
    checksum.write_text(digest + "  " + destination.name + "\n", encoding="ascii")
    print(json.dumps({"package": destination.name, "bytes": destination.stat().st_size, "sha256": digest, "files": len(source_files(project)) + 3}))
    return destination


if __name__ == "__main__": build()
