"""Fetch pinned optional reader animations; the reader works without them."""
import hashlib
import json
import urllib.request
from pathlib import Path

PINNED = {
    "gsap.min.js": "96c01b81f44a3290e2b4532f55e2c9534b2adc43273a19f3756b2cb41f0fd0b6",
    "ScrollTrigger.min.js": "308219390e5e3b84cda0c481e70caa9820883ae10bda44e6e9a149a81aac4b3f",
}
root = Path(__file__).resolve().parents[1] / "web/vendor"
root.mkdir(parents=True, exist_ok=True)
manifest = []
for name, checksum in PINNED.items():
    url = "https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/" + name
    data = urllib.request.urlopen(url, timeout=20).read(200_000)
    if hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError("Vendor checksum mismatch: " + name)
    (root / name).write_bytes(data)
    manifest.append({"name": name, "url": url, "sha256": checksum})
(root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
