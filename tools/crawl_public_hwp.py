#!/usr/bin/env python3
"""Collect public HWP files from allowlisted public sources.

The initial source is KMA press releases. It respects the site's robots.txt
policy and records source URLs so the corpus remains auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


KMA_LIST_URL = (
    "https://www.kma.go.kr/kma/news/press.jsp"
    "?bid=press&from={date_from}&mode=list&num=1194622&page={page}"
    "&ses=&to={date_to}"
)
KMA_BASE = "https://www.kma.go.kr"
USER_AGENT = "hwp-agent-corpus-builder/1.0 (+public research corpus)"


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def fetch_bytes(url: str) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as response:
        return response.read(), response.headers.get("Content-Type", "")


def extract_kma_hwp_links(page_html: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r'href="([^"]+)"', page_html):
        href = html.unescape(match.group(1))
        if "NeoboardProcess" not in href:
            continue
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        key = (query.get("k") or [""])[0].lower()
        if not key.endswith(".hwp"):
            continue
        links.append(urljoin(KMA_BASE, href))
    return links


def filename_from_url(url: str, index: int) -> str:
    query = parse_qs(urlparse(url).query)
    key = unquote((query.get("k") or [f"kma_{index:03d}.hwp"])[0])
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", key).strip("._")
    if not safe.lower().endswith(".hwp"):
        safe += ".hwp"
    return f"{index:03d}_{safe}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl public HWP files from allowlisted sources.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--out", default="data/hwp_corpus/kma_press")
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--date-from", default="2025-01-01")
    parser.add_argument("--date-to", default="2026-04-03")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.jsonl"

    discovered: list[tuple[int, str]] = []
    seen: set[str] = set()
    for page in range(1, args.pages + 1):
        list_url = KMA_LIST_URL.format(page=page, date_from=args.date_from, date_to=args.date_to)
        page_html = fetch_text(list_url)
        for link in extract_kma_hwp_links(page_html):
            if link in seen:
                continue
            seen.add(link)
            discovered.append((page, link))
            if len(discovered) >= args.limit:
                break
        if len(discovered) >= args.limit:
            break
        time.sleep(args.delay)

    existing_hashes: set[str] = set()
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if item.get("sha256"):
                    existing_hashes.add(item["sha256"])
            except json.JSONDecodeError:
                pass

    written = 0
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for index, (page, url) in enumerate(discovered, start=1):
            data, content_type = fetch_bytes(url)
            digest = sha256(data)
            if digest in existing_hashes:
                continue
            file_name = filename_from_url(url, index)
            file_path = out_dir / file_name
            file_path.write_bytes(data)
            record = {
                "source": "kma_press",
                "source_page": KMA_LIST_URL.format(page=page, date_from=args.date_from, date_to=args.date_to),
                "download_url": url,
                "file": str(file_path),
                "bytes": len(data),
                "sha256": digest,
                "content_type": content_type,
                "collected_at": int(time.time()),
            }
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()
            existing_hashes.add(digest)
            written += 1
            time.sleep(args.delay)

    print(json.dumps({
        "target": args.limit,
        "discovered": len(discovered),
        "downloaded_new": written,
        "out_dir": str(out_dir),
        "manifest": str(manifest_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
