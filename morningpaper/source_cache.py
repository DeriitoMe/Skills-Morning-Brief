from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path

from .core import fingerprint, read_json, write_json
from .providers import ProviderError


def with_source(candidate, cache_directory):
    if candidate.get("source_text"):
        return candidate
    cache_directory = Path(cache_directory)
    key = fingerprint([candidate["id"], candidate["fingerprint"]])
    cached = read_json(cache_directory / (key + ".json"))
    if cached:
        return {**candidate, **cached}
    repository, commit, path = candidate.get("repository", ""), candidate.get("commit_sha", ""), candidate.get("path", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit) or ".." in path.split("/"):
        raise ProviderError("候选来源缺少可核对的固定版本")
    url = "https://raw.githubusercontent.com/" + repository + "/" + commit + "/" + urllib.parse.quote(path, safe="/")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "private-skill-shelf/0.2"}), timeout=20) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ProviderError("Skill 原文超过研究大小限制")
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeError):
        raise ProviderError("无法取回该 Skill 的固定版本原文，可稍后重试") from None
    expected = candidate.get("source_fingerprint")
    if expected and fingerprint(text) != expected:
        raise ProviderError("Skill 原文指纹与目录不一致，暂不生成推荐")
    material = {"source_text": text[:16000], "source_text_truncated": len(text) > 16000}
    write_json(cache_directory / (key + ".json"), material)
    return {**candidate, **material}
