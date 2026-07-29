#!/usr/bin/env python3
"""
토픽 → (LLM) 콘텐츠 모델 JSON → HWPX 생성.

base.hwpx('기본 보고서 양식')의 골격/스타일을 유지하면서, 본문 내용만
LLM 이 채운다. modules.hwpx_builder.build_hwpx 로 raw OWPML 조립.
"""
from __future__ import annotations
import json, re, datetime
from pathlib import Path
from typing import Any, Optional

from modules.hwpx_builder import build_hwpx

SYSTEM_PROMPT = (
    "너는 대한민국 공공기관의 보고서 기획 전문가다. 사용자가 준 주제로 "
    "'기본 보고서 양식'(관공서 개조식 보고서)에 맞는 보고서 개요를 작성한다. "
    "반드시 설명 없이 JSON 객체 하나만 출력한다."
)

SCHEMA_GUIDE = """다음 JSON 스키마로만 출력해라. 코드펜스/설명 금지.

{{
  "org":   "발행 기관명 (예: ○○시청, ○○공사). 알 수 없으면 '담당 부서'",
  "title": "보고서 제목 (간결한 명사구)",
  "date":  "{today}",
  "sections": [
    {{
      "title": "섹션 제목 (예: 추진 배경 / 현황 및 문제점 / 개선 방안 / 추진 계획 / 기대 효과)",
      "lines": [
        ["□", "대주제 (개조식, 명사형 종결)"],
        ["○", "□를 뒷받침하는 설명"],
        ["―", "○의 세부 항목"],
        ["※", "보충/유의 사항 (선택)"]
      ]
    }}
  ]
}}

규칙:
- sections 는 4~5개. 보고서 흐름(배경→현황/문제→방안→계획/효과)을 따른다.
- 각 section 의 lines 는 3~8줄. 마커 계층은 □(대주제) > ○(설명) > ―(세부) > ※(보충).
- 한 □ 아래 ○/―/※ 가 이어지는 묶음을 1~3개씩 둔다.
- 모든 텍스트는 개조식(명사형 종결, 간결). 문장 부호 남발 금지.
- 마커는 정확히 "□","○","―","※" 중 하나만 사용.
- JSON 외 어떤 텍스트도 출력하지 마라.

주제: {topic}
"""


def _today_kr() -> str:
    d = datetime.date.today()
    return f"{d.year}. {d.month}. {d.day}."


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON 을 찾지 못함: {text[:200]}")
    return json.loads(text[start:end + 1])


# 빌더가 번호(Ⅰ..)와 마커(□○―※)를 따로 붙이므로, LLM 출력에 섞여 들어온
# 선행 번호/마커를 제거해 중복(예: "Ⅰ Ⅰ. 추진 배경", " □ □ ...")을 방지한다.
_LEADING_NUM = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|\d+)\s*[.)\]:]?\s*")
_LEADING_MARK = re.compile(r"^[\s□○◦●▪▶•·∙\-–—―※*]+")


def _clean_title(s: str) -> str:
    return _LEADING_NUM.sub("", str(s).strip()).strip()


def _clean_line(s: str) -> str:
    return _LEADING_MARK.sub("", str(s).strip()).strip()


def _normalize(model: dict[str, Any]) -> dict[str, Any]:
    model.setdefault("org", "담당 부서")
    model.setdefault("date", _today_kr())
    model["title"] = _clean_title(model.get("title", "보고서")) or "보고서"
    secs = []
    for s in model.get("sections", []):
        lines = []
        for ln in s.get("lines", []):
            if isinstance(ln, (list, tuple)) and len(ln) >= 2:
                marker, text = str(ln[0]).strip(), ln[1]
            elif isinstance(ln, dict):
                marker, text = str(ln.get("marker", "○")).strip(), ln.get("text", "")
            else:
                marker, text = "○", ln
            if marker not in {"□", "○", "―", "※"}:
                marker = "○"
            text = _clean_line(text)
            if text:
                lines.append([marker, text])
        title = _clean_title(s.get("title", ""))
        if title and lines:
            secs.append({"title": title, "lines": lines})
    model["sections"] = secs
    model["appendix"] = [_clean_line(a) for a in (model.get("appendix") or []) if str(a).strip()]
    return model


def generate_content_model(content_generator, topic: str) -> dict[str, Any]:
    """LLM 으로 토픽 → 콘텐츠 모델 dict."""
    prompt = SCHEMA_GUIDE.format(today=_today_kr(), topic=topic.strip())
    buf = ""
    for chunk in content_generator.generate_chat_stream(
        prompt, history=[], system_prompt=SYSTEM_PROMPT
    ):
        if chunk:
            buf += chunk
    model = _normalize(_extract_json(buf))
    if not model["sections"]:
        raise ValueError("LLM 이 섹션을 생성하지 못했습니다.")
    return model


TEMPLATE_FILL_GUIDE = """다음 JSON 스키마로만 출력해라. 코드펜스/설명 금지.

이 보고서는 '기본 보고서 양식'의 고정 구조를 채우는 것이다. 반드시 아래 모양을 지켜라.

{{
  "org":   "발행 기관/부서명 (모르면 '담당 부서')",
  "title": "보고서 제목 (간결한 명사구, 번호 붙이지 말 것)",
  "date":  "{today}",
  "sections": [
    {{"title": "Ⅰ 섹션 제목", "lines": [["□","대주제"],["○","설명"],["―","세부"]]}},
    {{"title": "Ⅱ 섹션 제목", "lines": [["□","대주제1"],["○","설명"],["―","세부"],["※","보충"],
                                       ["□","대주제2"],["○","설명"],["―","세부"],["※","보충"],
                                       ["□","대주제3"],["○","설명"],["―","세부"],["※","보충"]]}},
    {{"title": "Ⅲ 섹션 제목", "lines": [["□","대주제1"],["○","설명"],["―","세부"],["※","보충"],
                                       ["□","대주제2"],["○","설명"],["―","세부"],["※","보충"],
                                       ["□","대주제3"],["○","설명"],["―","세부"],["※","보충"]]}},
    {{"title": "Ⅳ 섹션 제목", "lines": [["□","대주제"],["○","설명"],["―","세부"],["※","보충"]]}}
  ]
}}

엄격한 규칙:
- sections 는 정확히 4개. 보고서 흐름: Ⅰ 추진 배경 → Ⅱ 현황 및 문제점 → Ⅲ 개선/추진 방안 → Ⅳ 추진 계획(또는 기대 효과).
- 각 섹션의 lines 개수와 마커 순서를 위 모양과 정확히 동일하게: Ⅰ=3줄(□○―), Ⅱ=12줄, Ⅲ=12줄, Ⅳ=4줄.
- 모든 텍스트는 개조식(명사형 종결, 간결). 제목/본문에 번호나 마커(□○―※)를 직접 쓰지 말 것(자동 부여됨).
- JSON 외 어떤 텍스트도 출력하지 마라.

주제: {topic}
"""


def generate_template_model(content_generator, topic: str) -> dict[str, Any]:
    """양식의 고정 슬롯(4섹션, 3/12/12/4줄)에 맞춘 콘텐츠 모델."""
    prompt = TEMPLATE_FILL_GUIDE.format(today=_today_kr(), topic=topic.strip())
    buf = ""
    for chunk in content_generator.generate_chat_stream(
        prompt, history=[], system_prompt=SYSTEM_PROMPT
    ):
        if chunk:
            buf += chunk
    model = _normalize(_extract_json(buf))
    if not model["sections"]:
        raise ValueError("LLM 이 섹션을 생성하지 못했습니다.")
    return model


def generate_hwpx(content_generator, topic: str, out_path: str | Path,
                  template_path: Optional[str | Path] = None) -> tuple[Path, dict[str, Any]]:
    """토픽 → hwpx 파일. (경로, 모델) 반환."""
    model = generate_content_model(content_generator, topic)
    kwargs = {"template_path": template_path} if template_path else {}
    path = build_hwpx(model, out_path, **kwargs)
    return path, model


if __name__ == "__main__":
    import sys
    from modules.gemini_generator import GeminiContentGenerator
    topic = sys.argv[1] if len(sys.argv) > 1 else "청년 1인 가구 주거 지원 사업 추진 계획"
    gen = GeminiContentGenerator()
    out = Path.home() / "Downloads" / "claude_llm_report.hwpx"
    path, model = generate_hwpx(gen, topic, out)
    print("주제:", topic)
    print("제목:", model["title"], "/ 기관:", model["org"], "/ 날짜:", model["date"])
    print("섹션:", [s["title"] for s in model["sections"]])
    print("총 본문 줄:", sum(len(s["lines"]) for s in model["sections"]))
    print("생성:", path, path.stat().st_size, "bytes")
