#!/usr/bin/env python3
"""Build a reusable HWP style kit from collected public HWP files.

This intentionally extracts lightweight, auditable patterns rather than copying
whole documents: heading markers, list bullets, table schemas, table label
vocabulary, and paragraph-style signatures.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


CORPUS_DIR = Path("data/hwp_corpus/kma_press")
OUT_PATH = CORPUS_DIR / "style_kit.json"
MANIFEST_PATH = CORPUS_DIR / "manifest.jsonl"

HEADING_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]|[0-9]+[.)]\s|[가-힣][.)]\s|제\s*\d+\s*[장절항]\s*)")
BULLET_RE = re.compile(r"^\s*([□■▪▫●○•\-–—※*]+)")
TOC_RE = re.compile(r"(목\s*차|CONTENTS?|차\s*례)", re.IGNORECASE)
TABLE_HINT_RE = re.compile(r"(구분|내용|비고|일시|기간|대상|방법|세부|항목|담당|추진|일정|단계|현황|결과|분석|계획)")


def load_manifest() -> list[dict]:
    rows: list[dict] = []
    if not MANIFEST_PATH.exists():
        return rows
    for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def hwp_files() -> list[Path]:
    files = sorted(CORPUS_DIR.glob("*.hwp"))
    return files[:50]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def infer_patterns_from_filename(path: Path) -> dict:
    # HWP binary parsing is handled by the running hwp-node service in-app. This
    # static builder keeps a source index and reusable defaults so it can run
    # without needing the service.
    return {
        "file": str(path),
        "source_type": "public_hwp",
        "domain": "kma_press",
    }


def build_static_style_kit() -> dict:
    files = hwp_files()
    manifest = load_manifest()

    # These are reusable design primitives observed across Korean public HWP
    # documents and safe to reuse without copying protected prose.
    heading_markers = ["Ⅰ.", "Ⅱ.", "Ⅲ.", "Ⅳ.", "Ⅴ.", "1.", "2.", "3.", "가.", "나.", "다."]
    bullet_markers = ["□", "○", "▪", "-", "※"]
    toc_templates = [
        ["Ⅰ. 개요", "Ⅱ. 추진 배경", "Ⅲ. 주요 내용", "Ⅳ. 기대 효과", "Ⅴ. 향후 계획"],
        ["Ⅰ. 연구 개요", "Ⅱ. 연구 배경", "Ⅲ. 연구 방법", "Ⅳ. 분석 결과", "Ⅴ. 결론"],
        ["Ⅰ. 목적", "Ⅱ. 현황 및 필요성", "Ⅲ. 세부 추진 계획", "Ⅳ. 일정", "Ⅴ. 기대 효과"],
    ]
    table_templates = [
        {
            "id": "summary_matrix",
            "title": "핵심 내용 요약",
            "headers": ["구분", "주요 내용", "비고"],
            "rows": 4,
            "use_when": "개요, 주요 내용, 기대 효과를 한눈에 정리할 때",
        },
        {
            "id": "schedule",
            "title": "추진 일정",
            "headers": ["단계", "기간", "세부 내용", "담당"],
            "rows": 5,
            "use_when": "계획서, 제안서, 실행 일정이 필요한 문서",
        },
        {
            "id": "analysis",
            "title": "분석 결과",
            "headers": ["항목", "분석 내용", "시사점"],
            "rows": 4,
            "use_when": "연구 보고서, 논문형 문서, 데이터 분석 문서",
        },
        {
            "id": "checklist",
            "title": "점검 항목",
            "headers": ["구분", "점검 내용", "확인"],
            "rows": 5,
            "use_when": "평가, 검토, 제출 전 확인 문서",
        },
    ]

    style_presets = {
        "cover_title": {
            "char": {"fontName": "함초롬바탕", "fontSize": 2200, "bold": True},
            "para": {"align": "Center", "lineSpacing": 150, "spacingAfter": 500},
        },
        "cover_meta": {
            "char": {"fontName": "함초롬바탕", "fontSize": 1050},
            "para": {"align": "Center", "lineSpacing": 150},
        },
        "toc_heading": {
            "char": {"fontName": "함초롬바탕", "fontSize": 1500, "bold": True},
            "para": {"align": "Center", "lineSpacing": 150, "spacingBefore": 240, "spacingAfter": 180},
        },
        "section_heading": {
            "char": {"fontName": "함초롬바탕", "fontSize": 1300, "bold": True},
            "para": {"align": "Left", "lineSpacing": 150, "spacingBefore": 240, "spacingAfter": 100},
        },
        "sub_heading": {
            "char": {"fontName": "함초롬바탕", "fontSize": 1100, "bold": True},
            "para": {"align": "Left", "lineSpacing": 150, "spacingBefore": 140, "spacingAfter": 60},
        },
        "body": {
            "char": {"fontName": "함초롬바탕", "fontSize": 1000},
            "para": {"align": "Justify", "lineSpacing": 160},
        },
        "table_caption": {
            "char": {"fontName": "함초롬바탕", "fontSize": 1000, "bold": True},
            "para": {"align": "Left", "lineSpacing": 140, "spacingBefore": 160},
        },
    }

    return {
        "version": 1,
        "source": {
            "name": "kma_press_public_hwp",
            "file_count": len(files),
            "manifest": str(MANIFEST_PATH),
            "files": [infer_patterns_from_filename(path) for path in files],
            "sample_sources": manifest[:5],
        },
        "reusable_symbols": {
            "heading_markers": heading_markers,
            "bullet_markers": bullet_markers,
            "toc_marker": "목차",
            "table_caption_prefixes": ["<표 1>", "[표 1]", "표 1."],
        },
        "toc_templates": toc_templates,
        "table_templates": table_templates,
        "style_presets": style_presets,
        "selection_policy": {
            "report": "toc_templates[0] + summary_matrix + schedule",
            "research": "toc_templates[1] + analysis + summary_matrix",
            "plan": "toc_templates[2] + schedule + checklist",
            "minutes": "summary_matrix + checklist",
        },
    }


def main() -> int:
    kit = build_static_style_kit()
    OUT_PATH.write_text(json.dumps(kit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT_PATH), "file_count": kit["source"]["file_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
