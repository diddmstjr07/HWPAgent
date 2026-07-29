"""
HWP Node v2 프록시 엔드포인트
FastAPI에서 Node 서버(services/hwp-node)로 요청을 전달합니다.
"""
import os
import io
import json
import re
from urllib.parse import quote, unquote
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
import requests
from pathlib import Path
# 문서 생성 AI는 ChatGPT(Codex) 계정을 우선 사용하고, 연결이 없으면 Gemini로 폴백한다.
from modules.codex_generator import CodexTextGenerator

# Node 서버 설정
HWP_NODE_URL = os.getenv('HWP_NODE_URL', 'http://localhost:3100')
HWP_NODE_API_KEY = os.getenv('HWP_NODE_API_KEY', 'dev-api-key')

router = APIRouter(prefix='/api/v2/hwp', tags=['HWP v2'])

STYLE_PROFILE_PATH = Path(__file__).resolve().parent / 'data' / 'hwp_corpus' / 'kma_press' / 'style_profile.md'
STYLE_KIT_PATH = Path(__file__).resolve().parent / 'data' / 'hwp_corpus' / 'kma_press' / 'style_kit.json'
HWP_OFFICIAL_SKILL_PATH = Path(__file__).resolve().parent / 'docs' / 'HWP_OFFICIAL_SKILL.md'


def _load_style_profile() -> str:
    try:
        if STYLE_PROFILE_PATH.exists():
            return STYLE_PROFILE_PATH.read_text(encoding='utf-8')[:8000]
    except Exception as exc:
        print(f'[HWP v2] style profile load failed: {exc}')
    return ''


def _load_hwp_official_skill() -> str:
    try:
        if HWP_OFFICIAL_SKILL_PATH.exists():
            return HWP_OFFICIAL_SKILL_PATH.read_text(encoding='utf-8')[:10000]
    except Exception as exc:
        print(f'[HWP v2] official skill load failed: {exc}')
    return ''


def _load_style_kit() -> dict:
    try:
        if STYLE_KIT_PATH.exists():
            return json.loads(STYLE_KIT_PATH.read_text(encoding='utf-8'))
    except Exception as exc:
        print(f'[HWP v2] style kit load failed: {exc}')
    return {}


def _style_kit_prompt_text() -> str:
    kit = _load_style_kit()
    if not kit:
        return ''
    compact = {
        'reusable_symbols': kit.get('reusable_symbols'),
        'toc_templates': kit.get('toc_templates'),
        'table_templates': kit.get('table_templates'),
        'component_library': kit.get('component_library'),
        'table_style_variants': kit.get('table_style_variants'),
        'document_recipes': kit.get('document_recipes'),
        'design_patterns': kit.get('design_patterns') or [
            {
                'id': 'attachment_header_bar',
                'description': '왼쪽 파란 붙임 번호 라벨, 좁은 구분선, 오른쪽 큰 제목, 하단 실선으로 구성된 공식 문서 제목 바',
                'marker': '[[DESIGN:attachment_header_bar:붙임 1:문서 제목]]',
            }
        ],
        'style_presets': kit.get('style_presets'),
        'selection_policy': kit.get('selection_policy'),
    }
    return json.dumps(compact, ensure_ascii=False)[:10000]

def _node_headers() -> dict:
    """Node 서버 인증 헤더"""
    return {'X-API-Key': HWP_NODE_API_KEY}


def _content_disposition_attachment(filename: str) -> str:
    fallback = re.sub(r'[^\x20-\x7E]', '_', filename or '').replace('\\', '_').replace('"', '').strip() or 'document.hwp'
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename or "document.hwp")}'


def _filename_from_content_disposition(value: str) -> str:
    if not value:
        return 'document.hwp'
    star_match = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if star_match:
        return unquote(star_match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', value, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return 'document.hwp'


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _tool_status_text(name: str, args: dict) -> str:
    labels = {
        'get_document_structure': '문서 구조를 확인합니다.',
        'search_text': f'"{args.get("query", "")}" 위치를 찾습니다.',
        'search_deep': f'"{args.get("query", "")}"를 필드와 표 셀까지 넓게 찾습니다.',
        'get_paragraph_text': '문단 내용을 확인합니다.',
        'insert_text': '확인한 위치에 텍스트를 삽입합니다.',
        'delete_text': '지정한 텍스트 범위를 삭제합니다.',
        'replace_text': '확인한 위치의 텍스트를 교체합니다.',
        'search_replace_all': f'"{args.get("query", "")}" 전체 치환을 준비합니다.',
        'split_paragraph': '삽입할 위치에 문단을 나눕니다.',
        'set_char_format': '글자 서식을 적용합니다.',
        'set_para_format': '문단 서식을 적용합니다.',
        'set_field': f'"{args.get("fieldName", "")}" 필드 값을 수정합니다.',
        'create_table': f'{args.get("rows", "")}행 {args.get("cols", "")}열 표를 삽입합니다.',
        'get_table_info': '표 구조와 속성을 확인합니다.',
        'get_text_in_cell': '표 셀 내용을 확인합니다.',
        'insert_text_in_cell': '표 셀에 텍스트를 삽입합니다.',
        'delete_text_in_cell': '표 셀의 텍스트를 삭제합니다.',
        'insert_table_row': '표에 행을 추가합니다.',
        'insert_table_column': '표에 열을 추가합니다.',
        'delete_table_row': '표의 행을 삭제합니다.',
        'delete_table_column': '표의 열을 삭제합니다.',
        'set_table_properties': '표 속성을 변경합니다.',
        'set_cell_properties': '셀 속성을 변경합니다.',
        'get_hwp_function_catalog': 'Node 함수 목록을 확인합니다.',
        'call_hwp_function': f'Node 함수 {args.get("method", "")}를 호출합니다.',
    }
    return labels.get(name, f'{name} 도구를 호출합니다.')


def _looks_like_edit_request(user_message: str) -> bool:
    text = _clean_edit_text(user_message)
    return bool(re.search(
        r'(추가|넣어|삽입|작성|생성|채워|입력|바꿔|변경|수정|삭제|지워|정리|다듬|서식|표|셀|행|열|빈\s*부분|비어\s*있는|상세|설명)',
        text,
    ))


def _node_get_json(path: str, timeout: int = 15) -> dict:
    resp = requests.get(f'{HWP_NODE_URL}{path}', headers=_node_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _node_post_json(path: str, payload: dict, timeout: int = 15) -> dict:
    resp = requests.post(f'{HWP_NODE_URL}{path}', json=payload, headers=_node_headers(), timeout=timeout)
    if resp.status_code >= 400:
      try:
          detail = resp.json().get('error') or resp.text
      except Exception:
          detail = resp.text
      raise RuntimeError(detail)
    return resp.json()


READ_TOOLS = {
    'get_document_structure', 'get_paragraph_text', 'search_text', 'search_deep',
    'get_table_info', 'get_text_in_cell', 'get_hwp_function_catalog', 'read_document'
}
WRITE_TOOLS = {
    'fill_report_template', 'set_document_font', 'set_font_size', 'edit_paragraphs',
    'restructure_document', 'design_template',
    'insert_text', 'delete_text', 'replace_text', 'split_paragraph',
    'set_char_format', 'set_para_format', 'set_char_format_in_cell', 'set_para_format_in_cell',
    'set_field', 'search_replace_all', 'create_table',
    'insert_text_in_cell', 'delete_text_in_cell',
    'insert_table_row', 'insert_table_column', 'delete_table_row', 'delete_table_column',
    'set_table_properties', 'set_cell_properties', 'call_hwp_function'
}


def _hwp_function_catalog_text(limit: int = 160) -> str:
    dts_path = Path(__file__).resolve().parent / 'services' / 'hwp-node' / 'node_modules' / '@rhwp' / 'core' / 'rhwp.d.ts'
    if not dts_path.exists():
        return ''
    text = dts_path.read_text(encoding='utf-8', errors='ignore')
    rows = []
    for match in re.finditer(r'^\s{4}([A-Za-z_]\w*)\(([^)]*)\):\s*([^;]+);', text, re.MULTILINE):
        name, params, ret = match.groups()
        if name in {'free', 'constructor'}:
            continue
        rows.append(f"- {name}({params}) -> {ret.strip()}")
        if len(rows) >= limit:
            break
    return '\n'.join(rows)


def _tool_declarations() -> list:
    integer = {"type": "integer"}
    string = {"type": "string"}
    boolean = {"type": "boolean"}
    string_matrix = {
        "type": "array",
        "items": {"type": "array", "items": {"type": "string"}}
    }
    object_props = {"type": "object"}
    props = {
        "type": "object",
        "properties": {
            "bold": {"type": "boolean"},
            "italic": {"type": "boolean"},
            "underline": {"type": "boolean"},
            "fontSize": {"type": "integer"},
            "fontName": {"type": "string"},
            "textColor": {"type": "integer"},
            "align": {"type": "string"},
            "lineSpacing": {"type": "integer"}
        }
    }
    return [{
        "functionDeclarations": [
            {"name": "fill_report_template", "description": "기본 보고서 양식(표지/목차/Ⅰ~Ⅳ/□○―※ 슬롯)에 주제에 맞는 내용을 채운다. '새 문서/보고서/계획서 작성', 'OO 주제로 써줘/바꿔줘' 요청에는 insert_text 대신 반드시 이 도구를 사용한다. 양식 구조를 100% 유지하고 슬롯 텍스트만 채운다.", "parameters": {"type": "object", "properties": {"topic": string}, "required": ["topic"]}},
            {"name": "set_document_font", "description": "문서 전체 글꼴(폰트 패밀리)을 바꾼다. 예: 함초롬바탕, 맑은 고딕, 휴먼명조, 굴림. '문서 전체 폰트 변경'에는 set_char_format 대신 이 도구를 사용한다.", "parameters": {"type": "object", "properties": {"fontName": string}, "required": ["fontName"]}},
            {"name": "set_font_size", "description": "지정 영역의 글자 크기(pt)를 바꾼다. region: title(표지 제목), toc(목차), headings(Ⅰ~Ⅳ 섹션 제목), body(본문 □○―※), all(전체). 제목/목차 등은 표 셀 안이라 search_text로 못 찾으므로 크기 변경에는 이 도구를 사용한다.", "parameters": {"type": "object", "properties": {"region": {"type": "string", "enum": ["title", "toc", "headings", "body", "all"]}, "sizePt": integer}, "required": ["region", "sizePt"]}},
            {"name": "design_template", "description": "AI(너)가 템플릿 디자인을 직접 설계해 문서를 처음부터 생성한다. 표지(기관/제목/부제/날짜), 글자 크기·색·굵기, 섹션 번호 방식, 마커 문자를 모두 네가 정한다. 새 문서·새 템플릿·디자인 요청에 우선 사용한다. 섹션 본문(lines)도 직접 충실히 작성해서 전달한다.", "parameters": {"type": "object", "properties": {"title": string, "subtitle": string, "org": string, "date": string, "numbering": {"type": "string", "enum": ["roman", "arabic", "none"]}, "style": {"type": "object", "properties": {"titleSizePt": integer, "subtitleSizePt": integer, "headingSizePt": integer, "bodySizePt": integer, "titleColor": {"type": "string", "description": "#RRGGBB"}, "headingColor": string, "bodyColor": string, "headingBold": boolean}}, "sections": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "lines": {"type": "array", "items": {"type": "object", "properties": {"marker": {"type": "string", "description": "줄 머리 기호(자유: □ ○ ― ▶ • 등)"}, "text": {"type": "string"}, "indent": {"type": "integer", "description": "들여쓰기 0~4"}}, "required": ["text"]}}}, "required": ["title", "lines"]}}}, "required": ["title", "sections"]}},
            {"name": "restructure_document", "description": "문서 구조를 재구성한다(섹션 개수·제목·본문 줄을 자유롭게 정의). '논문/IEEE/다른 형식으로 재구성', '섹션 추가/삭제', '목차 바꿔줘' 같은 구조 변경 요청에 사용한다. 표지/목차 박스/Ⅰ Ⅱ Ⅲ 번호/□○― 마커 등 양식의 시각 스타일은 유지되며, 목차는 섹션에 맞게 자동 재생성된다. 섹션 내용(lines)은 호출 전에 직접 작성해서 전달한다.", "parameters": {"type": "object", "properties": {"title": string, "org": string, "date": string, "appendix": {"type": "array", "items": string}, "sections": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "lines": {"type": "array", "items": {"type": "object", "properties": {"marker": {"type": "string", "enum": ["□", "○", "―", "※"]}, "text": {"type": "string"}}, "required": ["text"]}}}, "required": ["title", "lines"]}}}, "required": ["title", "sections"]}},
            {"name": "read_document", "description": "현재 문서의 모든 문단(표 셀 내부 포함)을 id+텍스트 목록으로 반환한다. 내용 수정·문구 변경·문장 교체 전에 반드시 이 도구로 수정할 문단 id를 확인한다. search_text가 못 찾는 표 셀 안 텍스트도 모두 보인다.", "parameters": {"type": "object", "properties": {}}},
            {"name": "edit_paragraphs", "description": "read_document가 반환한 문단 id의 텍스트를 교체한다. 여러 문단을 한 번에 수정할 수 있고, 양식·서식·마커(□○―※)·표 구조는 자동 보존된다. 내용 수정/문구 변경/문장 교체/빈 슬롯 채우기에는 insert_text·replace_text 대신 반드시 이 도구를 사용한다.", "parameters": {"type": "object", "properties": {"edits": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "read_document가 반환한 문단 id (예: '23' 또는 '5.0.1.0')"}, "text": {"type": "string", "description": "해당 문단의 새 전체 텍스트"}}, "required": ["id", "text"]}}}, "required": ["edits"]}},
            {"name": "get_document_structure", "description": "현재 HWP 문서의 필드, 단락 outline, 메타데이터를 JSON으로 반환한다.", "parameters": {"type": "object", "properties": {}}},
            {"name": "get_paragraph_text", "description": "특정 단락의 전체 텍스트를 반환한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer}, "required": ["sec", "para"]}},
            {"name": "search_text", "description": "문서에서 텍스트를 검색해 위치 배열을 반환한다.", "parameters": {"type": "object", "properties": {"query": string, "caseSensitive": boolean}, "required": ["query"]}},
            {"name": "search_deep", "description": "본문 search_text로 못 찾는 라벨을 필드명, 필드값, 표 셀 내부, 공백 제거 텍스트까지 넓게 검색한다. 성명/이름/날짜처럼 양식 라벨을 찾을 때 사용한다.", "parameters": {"type": "object", "properties": {"query": string, "caseSensitive": boolean}, "required": ["query"]}},
            {"name": "insert_text", "description": "지정 위치에 텍스트를 삽입한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "offset": integer, "text": string}, "required": ["sec", "para", "offset", "text"]}},
            {"name": "delete_text", "description": "지정 위치의 텍스트를 삭제한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "offset": integer, "length": integer}, "required": ["sec", "para", "offset", "length"]}},
            {"name": "replace_text", "description": "지정 위치의 텍스트를 교체한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "offset": integer, "length": integer, "newText": string}, "required": ["sec", "para", "offset", "length", "newText"]}},
            {"name": "split_paragraph", "description": "지정 위치에서 문단을 분리한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "offset": integer}, "required": ["sec", "para", "offset"]}},
            {"name": "set_char_format", "description": "글자 서식을 변경한다. props는 bold, italic, fontSize, fontName, textColor 등을 포함한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "start": integer, "end": integer, "props": props}, "required": ["sec", "para", "start", "end", "props"]}},
            {"name": "set_para_format", "description": "문단 서식을 변경한다. props는 align, lineSpacing 등을 포함한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "props": props}, "required": ["sec", "para", "props"]}},
            {"name": "set_char_format_in_cell", "description": "표 셀 내부 글자 서식을 변경한다. 공문형 표/디자인 컴포넌트의 셀 텍스트에 사용한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "cellIdx": integer, "cellPara": integer, "start": integer, "end": integer, "props": props}, "required": ["sec", "para", "controlIdx", "cellIdx", "cellPara", "start", "end", "props"]}},
            {"name": "set_para_format_in_cell", "description": "표 셀 내부 문단 서식을 변경한다. 셀 정렬과 줄간격 조정에 사용한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "cellIdx": integer, "cellPara": integer, "props": props}, "required": ["sec", "para", "controlIdx", "cellIdx", "cellPara", "props"]}},
            {"name": "set_field", "description": "이름 있는 양식 필드를 채운다.", "parameters": {"type": "object", "properties": {"fieldName": string, "value": string}, "required": ["fieldName", "value"]}},
            {"name": "search_replace_all", "description": "문서 전체 문자열을 치환한다.", "parameters": {"type": "object", "properties": {"query": string, "replacement": string, "caseSensitive": boolean}, "required": ["query", "replacement"]}},
            {"name": "create_table", "description": "지정 문단 위치에 실제 HWP 표를 삽입한다. cells로 셀 텍스트까지 한 번에 채울 수 있다. 반환값의 paraIdx/controlIdx가 이후 표·셀 편집 좌표다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "offset": integer, "rows": integer, "cols": integer, "cells": string_matrix}, "required": ["sec", "para", "offset", "rows", "cols"]}},
            {"name": "get_table_info", "description": "표의 행/열/속성을 조회한다. 문서 구조 tables 또는 create_table 반환값의 sec/para/controlIdx를 사용한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer}, "required": ["sec", "para", "controlIdx"]}},
            {"name": "get_text_in_cell", "description": "표 셀 내부 텍스트를 읽는다. cellIdx는 0부터 시작하며 행 우선(row-major) 인덱스다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "cellIdx": integer, "cellPara": integer, "offset": integer, "count": integer}, "required": ["sec", "para", "controlIdx", "cellIdx"]}},
            {"name": "insert_text_in_cell", "description": "표 셀 내부 지정 위치에 텍스트를 삽입한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "cellIdx": integer, "cellPara": integer, "offset": integer, "text": string}, "required": ["sec", "para", "controlIdx", "cellIdx", "cellPara", "offset", "text"]}},
            {"name": "delete_text_in_cell", "description": "표 셀 내부 지정 범위의 텍스트를 삭제한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "cellIdx": integer, "cellPara": integer, "offset": integer, "length": integer}, "required": ["sec", "para", "controlIdx", "cellIdx", "cellPara", "offset", "length"]}},
            {"name": "insert_table_row", "description": "기존 표에 행을 추가한다. rowIdx 기준 아래(below=true) 또는 위에 추가한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "rowIdx": integer, "below": boolean}, "required": ["sec", "para", "controlIdx", "rowIdx"]}},
            {"name": "insert_table_column", "description": "기존 표에 열을 추가한다. colIdx 기준 오른쪽(right=true) 또는 왼쪽에 추가한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "colIdx": integer, "right": boolean}, "required": ["sec", "para", "controlIdx", "colIdx"]}},
            {"name": "delete_table_row", "description": "기존 표의 행을 삭제한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "rowIdx": integer}, "required": ["sec", "para", "controlIdx", "rowIdx"]}},
            {"name": "delete_table_column", "description": "기존 표의 열을 삭제한다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "colIdx": integer}, "required": ["sec", "para", "controlIdx", "colIdx"]}},
            {"name": "set_table_properties", "description": "표 전체 속성을 변경한다. props는 rhwp table properties JSON이다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "props": object_props}, "required": ["sec", "para", "controlIdx", "props"]}},
            {"name": "set_cell_properties", "description": "특정 셀의 속성을 변경한다. props는 rhwp cell properties JSON이다.", "parameters": {"type": "object", "properties": {"sec": integer, "para": integer, "controlIdx": integer, "cellIdx": integer, "props": object_props}, "required": ["sec", "para", "controlIdx", "cellIdx", "props"]}},
            {"name": "get_hwp_function_catalog", "description": "현재 Node/@rhwp HwpDocument 인스턴스에서 호출 가능한 raw 함수 목록을 조회한다.", "parameters": {"type": "object", "properties": {}}},
            {"name": "call_hwp_function", "description": "Node/@rhwp HwpDocument raw 함수를 직접 호출한다. method는 함수명, args는 위치 인자 배열이다. 문서를 바꾸는 함수면 affectsDocument=true로 둔다. Uint8Array 인자는 {\"__base64\":\"...\"} 형태로 전달할 수 있다.", "parameters": {"type": "object", "properties": {"method": string, "args": {"type": "array", "items": {}}, "affectsDocument": boolean}, "required": ["method", "args"]}},
        ]
    }]


def _build_system_prompt(structure: dict) -> str:
    outline = json.dumps(structure, ensure_ascii=False)[:4000]
    official_skill = _load_hwp_official_skill()
    return f"""당신은 HWP 한글 문서 편집 AI 에이전트입니다. 사용자는 미리보기를 보며 자연어로 편집을 요청합니다.

# HWP 공식 문서 생성 Skill
아래 규칙은 공문/보고서/계획서/회의록/제안서 생성 시 반드시 따르는 내부 작업 지침입니다.
{official_skill}

# 고수준 도구 (이것부터 우선 사용 — 가장 안정적)
이 양식(표지/목차/Ⅰ~Ⅳ/□○―※)은 제목·목차·섹션 제목이 모두 '표 셀 안'에 있어 search_text/set_char_format 로는 못 찾거나 적용이 안 됩니다. 아래 요청은 반드시 고수준 도구를 쓰세요.
- **새 문서/새 템플릿/디자인 생성(현재 기본 경로 — 임시 정책)**: `design_template(...)` — 너가 표지·글자 크기/색/굵기·섹션 번호 방식·마커까지 직접 설계해서 처음부터 생성한다. 문서 성격에 어울리는 디자인(보고서=네이비+로마숫자, 논문=차분한 색+아라비아숫자, 안내문=밝은 포인트색 등)을 스스로 정해라. 섹션당 3~8줄 본문도 직접 작성.
- 사용자가 "기본 보고서 양식/공공기관 양식 그대로"를 명시한 경우에만: `fill_report_template(topic)`  (insert_text 금지)
- **문서 구조 변경** ("논문/IEEE/회의록 형식으로 재구성", "섹션 5개로", "결론 섹션 추가", "목차 재구성"): `restructure_document(title, sections=[{{title, lines:[{{marker, text}}]}}...])` — 섹션 개수 자유(1~12), 목차 자동 재생성. **fill_report_template 은 구조를 못 바꾸니 구조 변경에는 반드시 이 도구를 사용.** 섹션 본문(lines)은 너가 직접 충실히 작성해서 전달해라(섹션당 3~8줄, marker는 □=소제목, ○=내용, ―=세부, ※=참고).
- **내용 수정·문구 변경·문장 교체·특정 부분 보강·빈 슬롯 채우기** ("X를 Y로 바꿔줘", "Ⅱ장 내용 고쳐줘", "이 줄 다시 써줘", "결론 보완해줘"): ① `read_document()` 로 문단 id·텍스트 목록 확인 → ② `edit_paragraphs([{{id, text}}])` 로 해당 문단만 교체. 여러 문단도 한 번에 가능.
- 문서 전체 글꼴 변경: `set_document_font(fontName)`  (set_char_format 금지)
- 글자 크기 변경(제목/목차/섹션제목/본문/전체): `set_font_size(region, sizePt)` — region=title|toc|headings|body|all  (search_text 로 제목·목차 찾으려 하지 말 것)
이 도구들은 한 번 호출로 끝나며 결과 ok=true 면 완료입니다. 같은 작업을 set_char_format 등으로 반복하지 마세요.
**이 양식 문서에서 insert_text/replace_text/delete_text/split_paragraph/search_replace_all 사용 금지** — 양식이 깨지고, 이후 글꼴·크기 변경 시 그 수정이 사라집니다. 본문 텍스트 변경은 전부 read_document → edit_paragraphs 경로를 사용하세요.

# 핵심 행동 원칙
1. **계획 먼저 말하기**: 도구를 호출하기 전에 한국어 한 문장으로 무엇을 할지 짧게 설명하세요.
   예: "양은석을 찾아 김두혁으로 바꾸겠습니다."
2. **위치는 근거 기반으로 결정**: 텍스트 수정 위치는 read_document()의 문단 id로 확인하세요(표 셀 내부까지 전부 보임). 기존 표의 행/열 편집처럼 구조 기반 요청은 현재 문서 구조의 outline/tables 좌표를 사용하세요.
3. **읽은 후 반드시 편집**: read_document가 문단 목록을 반환하면 같은 턴 안에 또는 즉시 다음 턴에 edit_paragraphs를 호출하세요. 읽기만 하고 멈추지 마세요.
4. **실패하면 변형으로 재시도**: search_text나 search_replace_all 결과가 비어 있으면 다른 검색어 또는 search_deep로 다시 시도하세요. 한 번에 포기 금지.
   - 라벨+값 묶음 → 값만: "성명 양은석" → "양은석"
   - 띄어쓰기 변형: "양은석" / "양 은 석" / "양은 석"
   - 짧은 핵심 단어로 축약
   - 단, "회", "성" 같은 한 글자 검색어는 금지. 사용자가 정확히 한 글자 자체를 바꾸라고 한 경우에만 사용.
5. **단계별 진행**: 한 턴에 하나의 도구만 호출. 결과 보고 다음 단계 결정.
6. **완료 보고**: 작업 끝나면 한 줄로 무엇이 변경됐는지 요약.

# 자주 나오는 패턴
- "X를 Y로 바꿔줘": read_document() → X가 포함된 문단 id 확인 → edit_paragraphs([{{id, text: X를 Y로 바꾼 전체 문단 텍스트}}])
- **"라벨 값을 새값으로 바꿔줘"** (예: "성명 양은석을 김두혁으로 바꿔줘"): read_document()로 해당 라벨/값이 있는 문단(셀 포함) id 확인 → edit_paragraphs로 교체.
- "X 채워줘"/"X에 Y 입력해줘": read_document()로 빈 문단·라벨 문단 id 확인 → edit_paragraphs로 채움.
- "성명/이름/날짜 같은 양식 라벨을 못 찾음": search_deep(라벨) → field match면 set_field, cell match면 insert_text_in_cell, paragraph match면 get_paragraph_text 후 insert/replace.
- "전반적/전문적/깔끔하게 서식": 문구 치환 금지. set_char_format/set_para_format만 사용.
- "표 만들어줘/표 추가해줘": 필요하면 split_paragraph로 삽입 위치를 만든 뒤 create_table 호출. 행/열 언급이 없으면 3x3.
- "방금 만든 표/아래 표에 입력": 직전 create_table 결과의 paraIdx/controlIdx를 사용하고, 셀은 0부터 시작하는 행 우선 cellIdx로 insert_text_in_cell 호출.
- "공문/보고서/계획서/붙임 양식": DESIGN 컴포넌트와 official table 스타일을 우선 사용. 일반 텍스트 제목만 삽입하지 말 것.
- "표에 행/열 추가/삭제": 문서 구조 tables 또는 직전 tool_result의 sec/para/controlIdx를 사용해 insert_table_row/insert_table_column/delete_table_row/delete_table_column 호출.
- "빈 부분/비어 있는 부분을 임의 내용으로 채워줘": read_document()로 text가 빈 문단 id들을 확인하고 문맥에 맞는 내용을 생성해 edit_paragraphs로 채움.
- "빈 HWP/새 문서/주제로 보고서·계획서 작성·내용 채우기/바꾸기": **insert_text 로 직접 쓰지 말고 반드시 `fill_report_template(topic)` 도구를 호출**하세요. 이 도구가 양식 구조를 유지한 채 주제에 맞는 제목/목차/섹션/본문을 한 번에 채웁니다. (offset=0 일괄 삽입 금지 — 양식이 깨집니다.)

# 도구 사용 가이드
- search_text({{query, caseSensitive?}}): 위치 확인 전용. 결과 firstMatch.{{sec, para, offset, length}}를 다음 편집 도구에 그대로 사용.
- search_deep({{query, caseSensitive?}}): search_text 실패 시 사용. fields/cells/공백 제거 텍스트까지 검색. 결과 type이 field면 set_field, cell이면 insert_text_in_cell, paragraph면 get_paragraph_text 후 편집.
- get_paragraph_text({{sec, para}}): 문단 전체 텍스트. 빈칸/오프셋 계산용.
- replace_text({{sec, para, offset, length, newText}}): 정확한 좌표 필수. 좌표는 search_text 결과에서.
- insert_text({{sec, para, offset, text}}): 지정 위치에 삽입.
- delete_text({{sec, para, offset, length}}): 지정 영역 삭제.
- search_replace_all({{query, replacement}}): 단순 문자열 치환. response.data.replacedCount=0이면 실패 → 다른 검색어로 재시도.
- create_table({{sec, para, offset, rows, cols, cells?}}): 실제 HWP 표 삽입. 반환 data.paraIdx/controlIdx를 이후 표 편집에 사용.
- set_cell_properties / set_char_format_in_cell / set_para_format_in_cell: 공문형 디자인 컴포넌트의 색, 선, 셀 여백, 셀 내부 글자 서식에 사용.
- get_table_info({{sec, para, controlIdx}}): 표 행/열/속성 확인.
- get_text_in_cell/insert_text_in_cell/delete_text_in_cell: 셀 내부 텍스트 읽기/삽입/삭제. cellIdx = row * colCount + col.
- insert_table_row/insert_table_column/delete_table_row/delete_table_column: 기존 표의 행/열 편집.
- set_table_properties/set_cell_properties: 표/셀 속성 변경.
- set_char_format/set_para_format: 서식 변경 (fontSize는 HWP 단위: 10pt=1000, 11pt=1100, 18pt=1800).
- get_hwp_function_catalog(): Node/@rhwp raw 함수 목록 확인.
- call_hwp_function({{method, args, affectsDocument?}}): HwpDocument raw 함수를 직접 호출. 고수준 도구가 없는 기능에만 사용하고, 함수 목록은 먼저 get_hwp_function_catalog()로 조회하세요. 문자열 JSON 인자가 필요한 함수는 JSON.stringify된 문자열로 전달하세요.

# 오류 회복
- 도구가 hint 필드를 반환하면 그 힌트를 따라 다음 행동을 결정하세요.
- 동일 호출이 거부되면("repeated_call") 즉시 다른 변형/도구로 전환.
- 3번 실패하면 사용자에게 무엇이 잘못됐는지 보고하고 명확한 문구를 요청.

# 작업 메모와 검증 (필수로 활용)
- 모든 함수 응답에는 다음 두 필드가 함께 옵니다. 반드시 활용하세요.
  - `_verify`: 직전 쓰기 도구의 적용 여부 검증. `ok=true`면 성공, `ok=false`면 실제 단락/셀에 변경이 들어가지 않았다는 뜻이니 다른 좌표·다른 도구로 즉시 재시도하세요. `paragraphAfter`/`cellAfter`/`actualValue`로 현재 상태를 확인할 수 있습니다.
  - `_runningMemory`: 이번 대화에서 이미 확인한 위치(findings), 직전까지의 편집(writes ✓/✗), 읽은 단락 요약. 같은 정보를 다시 검색하지 말고 메모의 좌표를 바로 다음 도구에 사용하세요.
- 쓰기 후 `_verify.ok=false`이면: 좌표·검색어·도구 종류 중 하나를 바꿔 재시도. 같은 인자로 다시 호출하지 마세요.
- "끝났다"고 보고하기 전에 가장 최근 쓰기의 `_verify.ok`가 true인지 스스로 확인하세요. 검증 실패가 남아 있으면 보고 대신 한 번 더 수정하세요.

현재 문서 구조 (참고용 - 실제 문단 id/텍스트는 read_document로 확인):
{outline}
"""


def _clean_edit_text(value: str) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    text = text.strip(' "\'`“”‘’')
    return text


def _label_candidates(label: str) -> list[str]:
    raw = _clean_edit_text(label)
    compact = re.sub(r'\s+', '', raw)
    candidates = [raw]
    if 2 <= len(compact) <= 4:
        candidates.append(' '.join(compact))
    candidates.append(compact)
    result: list[str] = []
    seen: set[str] = set()
    for base in candidates:
        if not base:
            continue
        for item in (base, f'{base}:', f'{base} :', f'{base}：'):
            if item not in seen:
                seen.add(item)
                result.append(item)
    return result


def _find_label_span(text: str, label: str) -> Optional[tuple[int, int]]:
    """Find a label even when HWP text has spaces between Korean chars."""
    source = str(text or '')
    for candidate in _label_candidates(label):
        idx = source.find(candidate)
        if idx >= 0:
            return idx, idx + len(candidate)

    compact_label = re.sub(r'\s+', '', _clean_edit_text(label))
    if not compact_label:
        return None

    compact_chars: list[str] = []
    original_indexes: list[int] = []
    for idx, ch in enumerate(source):
        if ch.isspace():
            continue
        compact_chars.append(ch)
        original_indexes.append(idx)

    compact_source = ''.join(compact_chars)
    compact_idx = compact_source.find(compact_label)
    if compact_idx < 0:
        return None
    start = original_indexes[compact_idx]
    end = original_indexes[compact_idx + len(compact_label) - 1] + 1
    return start, end


def _fill_paragraph_op(sec: int, para: int, paragraph_text: str, label: str, value: str) -> Optional[tuple[str, dict]]:
    span = _find_label_span(paragraph_text, label)
    if not span:
        return None
    _, end = span
    ins_off = end
    rest = paragraph_text[ins_off:]
    # Skip only label separators before/at a colon. Spaces after the colon are
    # usually the writable blank area in Korean forms, so keep them replaceable.
    pre_colon = 0
    while pre_colon < min(len(rest), 4) and rest[pre_colon] in (' ', '\t', '　'):
        pre_colon += 1
    if pre_colon < len(rest) and rest[pre_colon] in (':', '：'):
        ins_off += pre_colon + 1

    rest2 = paragraph_text[ins_off:]
    blank = 0
    while blank < len(rest2) and rest2[blank] in (' ', '_', ' ', '　', '.', '·', '-'):
        blank += 1

    if blank > 0:
        return 'replace_text', {'sec': sec, 'para': para, 'offset': ins_off, 'length': blank, 'newText': value}
    return 'insert_text', {'sec': sec, 'para': para, 'offset': ins_off, 'text': value}


def _is_professional_format_request(user_message: str) -> bool:
    text = _clean_edit_text(user_message)
    has_format_scope = re.search(r'(서식|표|디자인|레이아웃|정렬|간격|문단|글자)', text)
    has_direction = re.search(r'(전반|전체|전문|격식|깔끔|정돈|보기\s*좋|다듬|수정|변경|조정)', text)
    return bool(has_format_scope and has_direction)


def _extract_direct_replace(user_message: str, history: list) -> Optional[tuple[str, str]]:
    """Handle common short follow-up edits deterministically before asking Gemini.

    Examples:
    - `" ? 회"를 "5회"로 바꿔줘`
    - previous: `? 회 이 부분 수정해줘`, current: `5회`
    """
    msg = _clean_edit_text(user_message)
    if not msg:
        return None
    if _is_professional_format_request(msg) or _is_style_rewrite_request(msg):
        return None

    quoted = re.search(r'["“”\'](.+?)["“”\']\s*(?:을|를)?\s*["“”\'](.+?)["“”\']\s*(?:으?로|로)?\s*(?:바꿔|변경|수정|교체)', msg)
    if quoted:
        return _clean_edit_text(quoted.group(1)), _clean_edit_text(quoted.group(2))

    pattern = re.search(r'(.+?)\s*(?:을|를)\s*(.+?)\s*(?:으?로|로)\s*(?:바꿔|변경|교체)', msg)
    if pattern:
        return _clean_edit_text(pattern.group(1)), _clean_edit_text(pattern.group(2))

    # Short answer after the assistant asked what to replace the selected/mentioned part with.
    if len(msg) <= 20:
        for item in reversed(history[-6:]):
            if item.get('role') != 'user':
                continue
            prev = _clean_edit_text(item.get('text') or item.get('content') or '')
            if not prev or prev == msg:
                continue
            if not re.search(r'(부분|이 부분|수정|바꿔|변경|교체)', prev):
                continue
            target = re.sub(r'(이\s*)?부분.*$', '', prev).strip()
            target = re.sub(r'(을|를)?\s*(수정|바꿔|변경|교체).*$','', target).strip()
            target = _clean_edit_text(target)
            if target:
                return target, msg
    return None


def _try_fill_field(session_id: str, user_message: str) -> Optional[list[str]]:
    """'성명 양은석으로 채워줘' / 'X에 Y 넣어줘' 패턴을 처리.

    직접 치환(search_replace_all)으로 해결 안 되는 경우:
    라벨 텍스트를 search_text로 찾고, 이후 공백/밑줄을 value로 replace_text.
    """
    msg = _clean_edit_text(user_message)
    if not msg:
        return None
    if _is_professional_format_request(msg) or _is_style_rewrite_request(msg):
        return None
    # Broad document-writing requests must go through the agent. A deterministic
    # "X에 Y 입력" parser can otherwise mistake "회의록 ..." as label "회".
    if len(msg) > 45 or re.search(r'(빈\s*칸|빈\s*부분|비어\s*있는|비어있는|공란|임의|알아서|생성|작성)', msg):
        return None

    fill_re = re.search(
        r'^(.{2,15}?)\s*(?:에|:|：)\s*(.{1,40}?)\s*(?:으?로|로)?\s*'
        r'(?:채워|입력|넣어|써\s*줘|적어|써)(?:줘|주세요|주시오|달라|달라고)?',
        msg,
    )
    if not fill_re:
        return None

    raw_label = _clean_edit_text(fill_re.group(1))
    value = _clean_edit_text(fill_re.group(2))
    if not raw_label or not value or raw_label == value:
        return None
    if len(raw_label) < 2 or len(raw_label) > 15 or len(value) > 60:
        return None
    if re.search(r'(있잖아|부분|내용|생성|작성|임의|알아서)', value):
        return None

    events: list[str] = []

    for label_q in _label_candidates(raw_label):
        events.append(_sse({"type": "tool_start", "name": "search_text", "args": {"query": label_q}}))
        try:
            data, _ = _tool_result(session_id, 'search_text', {"query": label_q})
        except Exception as e:
            events.append(_sse({"type": "tool_error", "name": "search_text", "error": str(e)}))
            continue

        events.append(_sse({"type": "tool_result", "name": "search_text", "result": data, "affected": []}))
        matches = (data or {}).get('matches') or []
        if not matches:
            continue

        hit = matches[0]
        sec = hit.get('sec')
        para = hit.get('para')
        hit_offset = hit.get('offset')
        hit_length = hit.get('length', len(label_q))
        if sec is None or para is None or hit_offset is None:
            continue

        # Read raw paragraph text for positional math (do NOT clean — must preserve spaces)
        para_text_raw = ''
        try:
            pd, _ = _tool_result(session_id, 'get_paragraph_text', {'sec': sec, 'para': para})
            para_text_raw = (pd.get('text') if isinstance(pd, dict) else '') or ''
        except Exception:
            pass

        op = None
        if para_text_raw:
            op = _fill_paragraph_op(int(sec), int(para), para_text_raw, raw_label, value)
        if op:
            op_name, op_args = op
        else:
            ins_off = int(hit_offset) + int(hit_length)
            op_name = 'insert_text'
            op_args = {'sec': int(sec), 'para': int(para), 'offset': ins_off, 'text': value}

        events.append(_sse({"type": "tool_start", "name": op_name, "args": op_args}))
        try:
            result, affected = _tool_result(session_id, op_name, op_args)
            events.append(_sse({"type": "tool_result", "name": op_name, "result": result, "affected": affected}))
            events.append(_sse({"type": "text", "delta": f'"{raw_label}"에 "{value}"을(를) 입력했습니다.'}))
            events.append(_sse({"type": "done"}))
            return events
        except Exception as e:
            events.append(_sse({"type": "tool_error", "name": op_name, "error": str(e)}))
            continue  # try next candidate

    # 모든 후보 실패 — Gemini agent로 fallthrough (지금까지의 events는 폐기)
    return None


def _try_fill_profile_fields(session_id: str, user_message: str) -> Optional[list[str]]:
    """Fill common applicant/contact fields without waiting for the LLM.

    This covers requests like "이름 소속 연락처 임의로 채워줘", where the model
    often finds the label but stops before issuing the write tool.
    """
    msg = _clean_edit_text(user_message)
    if not msg or not re.search(r'(채워|입력|넣어|써|적어|임의|일단)', msg):
        return None
    if not re.search(r'(이름|성명|성\s*명|소속|연락처|전화|휴대폰|이메일)', msg):
        return None

    requested: list[tuple[str, list[str], str]] = []
    specs = [
        ('성명', ['성명', '성 명', '이름'], '홍길동'),
        ('소속', ['소속', '부서', '기관'], 'AI전략팀'),
        ('연락처', ['연락처', '전화번호', '전화', '휴대폰'], '010-1234-5678'),
        ('이메일', ['이메일', '메일', 'email'], 'hong@example.com'),
    ]
    for canonical, labels, value in specs:
        if any(re.search(re.escape(label).replace('\\ ', r'\s*'), msg, re.IGNORECASE) for label in labels):
            requested.append((canonical, labels, value))

    if not requested:
        return None

    events: list[str] = []
    filled: list[str] = []

    for canonical, labels, value in requested:
        done = False
        for label in labels:
            for query in _label_candidates(label):
                events.append(_sse({"type": "tool_start", "name": "search_deep", "args": {"query": query}}))
                try:
                    data, _ = _tool_result(session_id, 'search_deep', {"query": query})
                except Exception as e:
                    events.append(_sse({"type": "tool_error", "name": "search_deep", "error": str(e)}))
                    continue
                events.append(_sse({"type": "tool_result", "name": "search_deep", "result": data, "affected": []}))

                matches = (data or {}).get('matches') or []
                if not matches:
                    continue

                for hit in matches:
                    hit_type = hit.get('type')
                    try:
                        if hit_type == 'field' and hit.get('fieldName'):
                            op_name = 'set_field'
                            op_args = {'fieldName': hit.get('fieldName'), 'value': value}
                        elif hit_type == 'cell':
                            op_name = 'insert_text_in_cell'
                            op_args = {
                                'sec': int(hit.get('sec')),
                                'para': int(hit.get('para')),
                                'controlIdx': int(hit.get('controlIdx')),
                                'cellIdx': int(hit.get('cellIdx')),
                                'cellPara': 0,
                                'offset': max(0, int(hit.get('offset') or 0) + int(hit.get('length') or len(query))),
                                'text': value,
                            }
                        elif hit_type == 'paragraph':
                            sec = int(hit.get('sec'))
                            para = int(hit.get('para'))
                            pd, _ = _tool_result(session_id, 'get_paragraph_text', {'sec': sec, 'para': para})
                            paragraph_text = (pd.get('text') if isinstance(pd, dict) else '') or ''
                            op = _fill_paragraph_op(sec, para, paragraph_text, label, value)
                            if not op:
                                continue
                            op_name, op_args = op
                        else:
                            continue

                        events.append(_sse({"type": "tool_start", "name": op_name, "args": op_args}))
                        result, affected = _tool_result(session_id, op_name, op_args)
                        events.append(_sse({"type": "tool_result", "name": op_name, "result": result, "affected": affected}))
                        filled.append(canonical)
                        done = True
                        break
                    except Exception as e:
                        events.append(_sse({"type": "tool_error", "name": hit_type or "fill_profile_field", "error": str(e)}))
                        continue
                if done:
                    break
            if done:
                break

    if not filled:
        return None
    events.append(_sse({"type": "text", "delta": f'{", ".join(filled)} 항목을 임의 값으로 채웠습니다.'}))
    events.append(_sse({"type": "done"}))
    return events


# 시드된 '기본 보고서 양식'의 플레이스홀더 시그니처. 이게 본문에 남아 있으면
# 아직 양식이 채워지지 않은 상태 → 결정적 빌더로 한 번에 채운다.
_TEMPLATE_SIGNATURE = re.compile(r'(헤드라인M|휴면명조|기본 보고서 양식)')
# 미작성 양식 위에서의 '작성/채움' 의도(넓게). 양식이 비어 있으므로 이 정도면 채운다.
_FILL_INTENT = re.compile(
    r'(보고서|계획서|기획|제안서|회의록|보고|문서|초안|내용|작성|만들|써|쓰|'
    r'생성|채워|채우|꾸며|정리|넣어|완성|적어)'
)
# 순수 질문/메타·확인 요청은 제외(채우지 않음)
_META_ONLY = re.compile(r'^(이게?\s*)?(뭐|무엇|어떻게|왜|설명|알려|help|도움말)')
# 확인/상태 질문: "생성했어?", "됐어?", "다 했어?", "안 바뀌는데?" 등
_CONFIRM_Q = re.compile(
    r'(했어|했나|했니|했냐|했지|됐어|됐나|됐니|됐냐|끝났|바뀌|반영|맞아|맞지|'
    r'안\s*돼|안\s*된|안\s*나|왜\s*안)'
)


# 결정적 '문서 전체 글꼴 변경'. 엔진 폰트 op(applyCharFormat)가 WASM 크래시/무반응이라
# header.xml 의 폰트 face 를 직접 교체하는 방식으로 우회한다.
_FONT_INTENT = re.compile(r'(폰트|글꼴|글씨체|서체|글자체|글씨)')
# 별칭 → 실제 face 이름
_FONT_ALIASES = {
    "함초롬바탕": ["함초롬바탕", "함초롬 바탕"],
    "함초롬돋움": ["함초롬돋움", "함초롬 돋움"],
    "휴먼명조": ["휴먼명조", "휴면명조", "휴먼 명조", "휴면 명조"],
    "맑은 고딕": ["맑은고딕", "맑은 고딕"],
    "굴림": ["굴림체", "굴림"],
    "바탕": ["바탕체", "바탕"],
    "돋움": ["돋움체", "돋움"],
    "궁서": ["궁서체", "궁서"],
    "중고딕": ["중고딕"],
    "신명조": ["신명조"],
    "나눔고딕": ["나눔고딕", "나눔 고딕"],
    "나눔명조": ["나눔명조", "나눔 명조"],
    "HCR Batang": ["hcr batang"],
}


def _detect_font(msg: str) -> Optional[str]:
    low = msg.lower()
    # 더 긴 별칭부터 매칭(휴먼명조 > 명조 등 오탐 방지)
    pairs = sorted(((face, a) for face, al in _FONT_ALIASES.items() for a in al),
                   key=lambda x: -len(x[1]))
    for face, alias in pairs:
        if alias.lower() in low:
            return face
    return None


# 글자 '크기' 변경이나 '부분' 지정은 에이전트(set_char_format)가 처리하도록 양보한다.
_FONT_SIZE_HINT = re.compile(r'(크기|사이즈|포인트|\bpt\b|\d+\s*[pP]\b|줄여|키워|작게|크게|size)')
_WHOLE_DOC = re.compile(r'(전체|전부|모두|문서|모든|다\b)')
_PART_SCOPE = re.compile(r'(제목|소제목|머리말|꼬리말|본문만|이\s*부분|선택|특정|표\b|셀\b)')


def _try_global_font(session_id: str, user_message: str) -> Optional[list[str]]:
    """문서 '전체 글꼴(패밀리)' 변경만 결정적으로 처리한다.
    글자 크기·부분 서식·폰트명 미지정은 모두 에이전트(Gemini 툴)로 넘긴다.
    """
    msg = (user_message or '').strip()
    if not msg:
        return None
    # 크기 변경은 에이전트에게 (예: "제목 폰트 크기 20p로 줄여줘")
    if _FONT_SIZE_HINT.search(msg):
        return None
    font = _detect_font(msg)
    if not font:
        return None  # 폰트명이 없으면 에이전트가 처리(되묻기 포함)
    # 특정 부분 지정인데 '전체' 표시가 없으면 부분 변경 → 에이전트
    if _PART_SCOPE.search(msg) and not _WHOLE_DOC.search(msg):
        return None

    events: list[str] = []
    events.append(_sse({"type": "status", "phase": "font_change",
                        "text": f"문서 전체 글꼴을 '{font}'(으)로 변경하는 중…"}))
    try:
        from modules.hwpx_builder import change_fonts_in_hwpx
        # @rhwp/core 의 exportHwpx 는 표를 손실하므로 export 하지 않는다.
        # 우리가 import 했던 '정상 hwpx'(표 보존) 캐시에 폰트만 바꿔 재주입한다.
        base_hwpx = _get_cached_hwpx(session_id)
        if base_hwpx is None:
            # 캐시가 없으면(직접 업로드 등) 부득이 export-hwpx 폴백
            r = requests.get(f'{HWP_NODE_URL}/sessions/{session_id}/export-hwpx',
                             headers=_node_headers(), timeout=30)
            r.raise_for_status()
            base_hwpx = r.content
        new_bytes = change_fonts_in_hwpx(base_hwpx, font)
        put = requests.put(f'{HWP_NODE_URL}/sessions/{session_id}/import',
                           data=new_bytes,
                           headers={**_node_headers(), 'Content-Type': 'application/octet-stream'},
                           timeout=40)
        put.raise_for_status()
        _cache_session_hwpx(session_id, new_bytes)  # 변경된 정상 hwpx 로 캐시 갱신
        page_count = (put.json() or {}).get('pageCount') or 5
        events.append(_sse({
            "type": "tool_result", "name": "change_fonts",
            "result": {"ok": True, "font": font},
            "affected": list(range(int(page_count))), "live": True,
        }))
        events.append(_sse({"type": "text",
                            "delta": f"문서 전체 글꼴을 '{font}'(으)로 변경했습니다."}))
        events.append(_sse({"type": "done"}))
        return events
    except Exception as e:
        print(f"[HWP v2] 글꼴 변경 실패: {e}")
        events.append(_sse({"type": "tool_error", "name": "change_fonts", "error": str(e)}))
        events.append(_sse({"type": "text", "delta": f"글꼴 변경 중 오류가 발생했습니다: {e}"}))
        events.append(_sse({"type": "done"}))
        return events


def _try_title_format(session_id: str, user_message: str) -> Optional[list[str]]:
    """'제목 크기 Npt' 같은 제목 글자 크기 변경을 결정적으로 처리한다.
    제목은 표 셀 안이라 에이전트(search_text/set_char_format)가 못 잡는다."""
    msg = (user_message or '').strip()
    if '제목' not in msg or not _FONT_SIZE_HINT.search(msg):
        return None
    m = re.search(r'(\d+)\s*(?:pt|px|포인트|픽셀|p|P)?', msg)
    if not m:
        return None
    pt = int(m.group(1))
    if pt < 4 or pt > 120:
        return None
    base = _get_cached_hwpx(session_id)
    if base is None:
        return None  # 캐시 없으면 에이전트로

    events: list[str] = [_sse({"type": "status", "phase": "title_format",
                               "text": f"제목 글자 크기를 {pt}pt 로 변경하는 중…"})]
    try:
        from modules.hwpx_builder import set_charpr_height_in_hwpx, TITLE_CHARPR_IDS
        new_bytes = set_charpr_height_in_hwpx(base, TITLE_CHARPR_IDS, pt * 100)
        put = requests.put(f'{HWP_NODE_URL}/sessions/{session_id}/import',
                           data=new_bytes,
                           headers={**_node_headers(), 'Content-Type': 'application/octet-stream'},
                           timeout=40)
        put.raise_for_status()
        _cache_session_hwpx(session_id, new_bytes)
        page_count = (put.json() or {}).get('pageCount') or 5
        events.append(_sse({"type": "tool_result", "name": "set_title_size",
                            "result": {"ok": True, "pt": pt},
                            "affected": list(range(int(page_count))), "live": True}))
        events.append(_sse({"type": "text", "delta": f"제목 글자 크기를 {pt}pt 로 변경했습니다."}))
        events.append(_sse({"type": "done"}))
        return events
    except Exception as e:
        print(f"[HWP v2] 제목 크기 변경 실패: {e}")
        events.append(_sse({"type": "tool_error", "name": "set_title_size", "error": str(e)}))
        events.append(_sse({"type": "text", "delta": f"제목 크기 변경 중 오류: {e}"}))
        events.append(_sse({"type": "done"}))
        return events


def _try_template_report(session_id: str, user_message: str) -> Optional[list[str]]:
    """'빈 문서(=기본 보고서 양식)'에서 작성/채움 요청이면, 에이전트의 일괄삽입
    대신 결정적 in-place 채움으로 양식 슬롯만 채워 세션을 교체한다(구조 보존).
    양식 플레이스홀더가 남아 있을 때만 발동한다.
    """
    msg = (user_message or '').strip()
    if not msg or _META_ONLY.match(msg) or _CONFIRM_Q.search(msg):
        return None

    # 현재 세션이 '미작성 양식'인지 먼저 확인 (시그니처 존재)
    try:
        structure = _node_get_json(f'/sessions/{session_id}/structure')
    except Exception:
        return None
    outline = structure.get('outline') or []
    blob = ' '.join(
        (it.get('preview') or it.get('text') or '') if isinstance(it, dict) else str(it)
        for it in outline
    )
    if not _TEMPLATE_SIGNATURE.search(blob):
        return None  # 이미 채워진/다른 문서 → 일반 에이전트 경로로
    # 미작성 양식 위에서는 '주제/작성 요청'을 폭넓게 채움으로 처리한다.
    # 동사 없는 주제(예: "인공지능 ... 분석 연구")도 잡아야 하므로, 순수 질문/확인만
    # 제외하고 그 외 실질 입력은 모두 양식 채움으로 본다. (에이전트의 offset-0 산문
    # 삽입이 양식을 망가뜨리므로, 미작성 양식에서는 에이전트로 넘기지 않는다.)
    if len(msg) < 2:
        return None

    events: list[str] = []
    events.append(_sse({"type": "status", "phase": "template_fill",
                        "text": "기본 보고서 양식에 맞춰 내용을 생성하는 중…"}))
    try:
        import tempfile
        from pathlib import Path as _Path
        from modules.codex_generator import CodexTextGenerator
        from modules.hwpx_generator import generate_template_model
        from modules.hwpx_builder import fill_template_inplace

        # 토픽 = 사용자 메시지에서 명령어 군더더기 제거
        topic = re.sub(r'(보고서|계획서|기획안|제안서|회의록|문서)?\s*'
                       r'(좀)?\s*(만들어|작성해|써|생성|초안|꾸며|채워)\s*(줘|주세요|줄래|봐)?\.?$',
                       '', msg).strip() or msg

        # 양식의 고정 슬롯(4섹션, 3/12/12/4줄)에 맞춘 내용 생성
        model = generate_template_model(CodexTextGenerator(temperature=0.4), topic)

        # 양식 구조를 100% 유지하고 슬롯 텍스트만 채움(새 문서 X)
        out = _Path(tempfile.gettempdir()) / f"tmpl_{session_id}.hwpx"
        fill_template_inplace(model, out)
        data = out.read_bytes()

        # 세션 문서를 채워진 양식으로 교체
        resp = requests.put(
            f'{HWP_NODE_URL}/sessions/{session_id}/import',
            data=data,
            headers={**_node_headers(), 'Content-Type': 'application/octet-stream'},
            timeout=40,
        )
        resp.raise_for_status()
        _cache_session_hwpx(session_id, data)  # 채운 정상 hwpx 캐시(폰트 변경 등에 사용)
        page_count = (resp.json() or {}).get('pageCount') or 5

        # 캔버스 강제 리로드 트리거: 프론트(vibe-editor)는 tool_result 가 와야
        # changed=true 가 되어 refreshAfterAgent(forceReload) 로 캔버스를 다시 그린다.
        events.append(_sse({
            "type": "tool_result",
            "name": "fill_template",
            "result": {"ok": True, "pageCount": page_count},
            "affected": list(range(int(page_count))),
            "live": True,
        }))

        secs = ", ".join(s['title'] for s in model.get('sections', []))
        events.append(_sse({"type": "text",
                            "delta": f"'{model.get('title')}' 보고서를 양식에 맞춰 작성했습니다. "
                                     f"(섹션: {secs})\n필요한 부분은 이어서 수정해 드릴게요."}))
        events.append(_sse({"type": "done"}))
        return events
    except Exception as e:
        print(f"[HWP v2] 양식 보고서 생성 실패: {e}")
        # 미작성 양식에서는 에이전트로 폴백하면 양식 위에 산문을 덮어써 망가진다.
        # 따라서 폴백하지 않고 에러로 종료한다(사용자가 다시 시도).
        events.append(_sse({"type": "tool_error", "name": "fill_template",
                            "error": f"양식 생성 중 오류: {e}"}))
        events.append(_sse({"type": "text",
                            "delta": "양식 채우기에 실패했어요. 주제를 조금 더 구체적으로 다시 입력해 주세요."}))
        events.append(_sse({"type": "done"}))
        return events


def _replace_candidates(text: str) -> list[str]:
    candidates = [_clean_edit_text(text)]
    compact = re.sub(r'\s+', '', candidates[0])
    spaced = re.sub(r'\s+', ' ', candidates[0])
    for candidate in (compact, spaced):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _try_direct_replace(session_id: str, user_message: str, history: list) -> Optional[list[str]]:
    """Verify-first 직접 치환. 후보 중 하나라도 search_text로 발견되어야 진행.
    하나도 못 찾으면 None 반환 → Gemini agent로 fallthrough.
    """
    pair = _extract_direct_replace(user_message, history)
    if not pair:
        return None

    query, replacement = pair
    if not query or not replacement or query == replacement:
        return None

    # 1단계: 후보 중 실제 문서에 존재하는 것 검증
    candidates = _replace_candidates(query)
    found_candidate: Optional[str] = None
    for candidate in candidates:
        try:
            data, _ = _tool_result(session_id, 'search_text', {"query": candidate})
            matches = (data or {}).get('matches') if isinstance(data, dict) else None
            if matches:
                found_candidate = candidate
                break
        except Exception:
            continue

    if not found_candidate:
        # 못 찾았으면 Gemini가 더 똑똑한 분해(라벨 vs 값)를 시도하도록 양보
        return None

    # 2단계: 검증된 후보로 실제 치환
    events = [
        _sse({"type": "text", "delta": f'"{found_candidate}"를 "{replacement}"로 바꾸겠습니다.'}),
        _sse({"type": "tool_start", "name": "search_replace_all", "args": {"query": found_candidate, "replacement": replacement}}),
    ]
    result, affected = _tool_result(session_id, 'search_replace_all', {"query": found_candidate, "replacement": replacement})
    replaced = int((result.get('data') or {}).get('replacedCount') or 0)
    events.append(_sse({"type": "tool_result", "name": "search_replace_all", "result": result, "affected": affected}))
    if replaced > 0:
        events.append(_sse({"type": "text", "delta": f' {replaced}건 치환 완료.'}))
        events.append(_sse({"type": "done"}))
        return events

    # search_text는 발견했는데 search_replace_all이 0건? — Gemini로 fallthrough
    return None


def _format_profile(preview: str, index: int) -> tuple[dict, dict]:
    text = _clean_edit_text(preview)
    is_title = index == 0 or bool(re.search(r'(회의록|요약서|보고서|계획서|신청서|서약서)$', text))
    is_heading = bool(re.match(r'^\s*(?:\d+[\.\)]|[가-힣]\.|제\s*\d+\s*[조항]|[IVX]+\.)', text))
    is_short_label = len(text) <= 18 and not re.search(r'(합니다|입니다|된다|한다|있다|없다|하였다|했다)', text)

    if is_title:
        return (
            {"fontName": "함초롬바탕", "fontSize": 1800, "bold": True},
            {"align": "center", "lineSpacing": 150},
        )
    if is_heading or is_short_label:
        return (
            {"fontName": "함초롬바탕", "fontSize": 1100, "bold": True},
            {"align": "center" if is_short_label else "left", "lineSpacing": 145},
        )
    return (
        {"fontName": "함초롬바탕", "fontSize": 1000},
        {"align": "justify", "lineSpacing": 160},
    )


def _try_professional_format(session_id: str, user_message: str) -> Optional[list[str]]:
    if not _is_professional_format_request(user_message):
        return None

    events = [_sse({"type": "tool_start", "name": "format_document", "args": {"style": "professional_table_document"}})]
    structure = _node_get_json(f'/sessions/{session_id}/structure')
    formatted = 0
    affected_pages = set()

    for index, item in enumerate(structure.get('outline') or []):
        sec = item.get('sec')
        para = item.get('para')
        length = int(item.get('length') or 0)
        preview = _clean_edit_text(item.get('preview') or '')
        if sec is None or para is None or length <= 0 or not preview:
            continue
        if not re.search(r'[가-힣A-Za-z0-9]', preview):
            continue

        char_props, para_props = _format_profile(preview, index)
        try:
            result, affected = _tool_result(session_id, 'set_char_format', {
                'sec': int(sec),
                'para': int(para),
                'start': 0,
                'end': length,
                'props': char_props
            })
            for page in affected or result.get('affectedPages') or []:
                affected_pages.add(page)

            result, affected = _tool_result(session_id, 'set_para_format', {
                'sec': int(sec),
                'para': int(para),
                'props': para_props
            })
            for page in affected or result.get('affectedPages') or []:
                affected_pages.add(page)
            formatted += 1
        except Exception:
            continue

        if formatted >= 80:
            break

    if formatted:
        events.append(_sse({
            "type": "tool_result",
            "name": "format_document",
            "result": {"formattedParagraphs": formatted},
            "affected": sorted(affected_pages) or [0]
        }))
        events.append(_sse({"type": "text", "delta": f"총 {formatted}개 문단의 표/본문 서식을 전문적인 문서 스타일로 정리했습니다."}))
    else:
        events.append(_sse({"type": "tool_error", "name": "format_document", "error": "서식을 적용할 문단을 찾지 못했습니다."}))
    events.append(_sse({"type": "done"}))
    return events


def _is_style_rewrite_request(user_message: str) -> bool:
    text = _clean_edit_text(user_message)
    has_style = re.search(r'(문체|어투|톤|말투|표현|느낌)', text)
    has_formal = re.search(r'(격식|딱딱|공식|공문|정중|보고서|행정|formal|포멀)', text, re.IGNORECASE)
    has_change = re.search(r'(변경|수정|바꿔|고쳐|다듬|정리)', text)
    return bool((has_style and (has_formal or has_change)) or (has_formal and has_change))


def _is_reference_draft_request(user_message: str) -> bool:
    text = _clean_edit_text(user_message)
    if not text:
        return False
    wants_document = re.search(
        r'(보고서|계획서|제안서|회의록|논문|논문형|연구|기획안|공문|안내문|요약서|문서)',
        text,
    )
    wants_create = re.search(r'(작성|생성|만들|써\s*줘|초안|채워|구성|시작)', text)
    return bool(wants_document and wants_create)


def _is_blankish_structure(structure: dict) -> bool:
    outline = structure.get('outline') or []
    if not outline:
        return True
    visible = [
        _clean_edit_text(item.get('preview') or '')
        for item in outline
        if _clean_edit_text(item.get('preview') or '')
    ]
    if not visible:
        return True
    joined = ''.join(visible)
    return len(joined) <= 12


def _reference_doc_kind(user_message: str) -> str:
    text = _clean_edit_text(user_message)
    if re.search(r'(논문|연구|분석|고찰|실험|방법론)', text):
        return 'research'
    if re.search(r'(계획|추진|일정|로드맵|사업|운영)', text):
        return 'plan'
    if re.search(r'(회의록|회의|안건|참석|결정사항)', text):
        return 'minutes'
    if re.search(r'(제안|기획안|제안서)', text):
        return 'proposal'
    if re.search(r'(공문|안내문|보도자료|공지)', text):
        return 'notice'
    return 'report'


def _reference_title(user_message: str, kind: str) -> str:
    text = _clean_edit_text(user_message)
    text = re.sub(r'(작성|생성|만들|써\s*줘|초안|채워|구성|시작|해줘|해주세요|전문적|고품질|임의의?\s*내용으로?)', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' .,')
    if len(text) >= 6:
        suffix = {
            'research': '연구 보고서',
            'plan': '추진 계획서',
            'minutes': '회의록',
            'proposal': '제안서',
            'notice': '안내문',
            'report': '보고서',
        }.get(kind, '보고서')
        if not text.endswith(('보고서', '계획서', '회의록', '제안서', '안내문', '문서', '논문')):
            text = f'{text} {suffix}'
        return text[:60]
    return {
        'research': '연구 분석 보고서',
        'plan': '세부 추진 계획서',
        'minutes': '회의 결과 보고서',
        'proposal': '정책 제안서',
        'notice': '공식 안내문',
        'report': '공식 업무 보고서',
    }.get(kind, '공식 업무 보고서')


def _reference_toc(kind: str) -> list[str]:
    kit = _load_style_kit()
    recipes = kit.get('document_recipes') or {}
    recipe = recipes.get(kind) or {}
    toc = recipe.get('toc') or []
    if isinstance(toc, list) and len(toc) >= 4:
        return [str(item) for item in toc[:7]]
    if kind == 'research':
        return ['Ⅰ. 연구 개요', 'Ⅱ. 연구 배경', 'Ⅲ. 연구 방법', 'Ⅳ. 분석 결과', 'Ⅴ. 결론 및 제언']
    if kind == 'plan':
        return ['Ⅰ. 목적', 'Ⅱ. 현황 및 필요성', 'Ⅲ. 세부 추진 계획', 'Ⅳ. 추진 일정', 'Ⅴ. 기대 효과']
    if kind == 'minutes':
        return ['Ⅰ. 회의 개요', 'Ⅱ. 주요 안건', 'Ⅲ. 논의 결과', 'Ⅳ. 결정 사항', 'Ⅴ. 후속 조치']
    if kind == 'proposal':
        return ['Ⅰ. 제안 개요', 'Ⅱ. 추진 배경', 'Ⅲ. 제안 내용', 'Ⅳ. 실행 방안', 'Ⅴ. 기대 효과']
    if kind == 'notice':
        return ['Ⅰ. 안내 개요', 'Ⅱ. 주요 내용', 'Ⅲ. 대상 및 절차', 'Ⅳ. 유의 사항', 'Ⅴ. 문의 및 후속 안내']
    return ['Ⅰ. 개요', 'Ⅱ. 추진 배경', 'Ⅲ. 주요 내용', 'Ⅳ. 기대 효과', 'Ⅴ. 향후 계획']


def _kit_table_by_id(table_id: str) -> Optional[dict]:
    kit = _load_style_kit()
    for table in kit.get('table_templates') or []:
        if str(table.get('id') or '') == table_id:
            return table
    return None


def _normalize_table_spec(table: dict, fallback_title: str = '핵심 내용 요약') -> dict:
    headers = [str(x).strip() for x in (table.get('headers') or []) if str(x).strip()]
    if len(headers) < 2:
        headers = ['구분', '주요 내용', '비고']
    return {
        'id': str(table.get('id') or 'summary_matrix'),
        'title': str(table.get('title') or fallback_title),
        # Keep generated tables compact. Wider corpus tables are useful as
        # references, but 5+ columns often overflow or reflow badly in canvas.
        'headers': headers[:4],
        'rows': max(3, min(5, int(table.get('rows') or 4))),
        'style': str(table.get('style') or 'blue_header'),
        'headerFill': str(table.get('headerFill') or '#e8eef6'),
    }


def _reference_table_specs(kind: str) -> list[dict]:
    kit = _load_style_kit()
    recipes = kit.get('document_recipes') or {}
    recipe = recipes.get(kind) or recipes.get('report') or {}
    table_ids = recipe.get('tables') or []
    specs = []
    for table_id in table_ids:
        table = _kit_table_by_id(str(table_id))
        if table:
            specs.append(_normalize_table_spec(table))
    if specs:
        return specs[:4]

    table_map = {
        'research': [
            {'id': 'analysis', 'title': '분석 결과', 'headers': ['항목', '분석 내용', '시사점'], 'rows': 4},
            {'id': 'summary_matrix', 'title': '핵심 내용 요약', 'headers': ['구분', '주요 내용', '비고'], 'rows': 4},
        ],
        'plan': [
            {'id': 'schedule', 'title': '추진 일정', 'headers': ['단계', '기간', '세부 내용', '담당'], 'rows': 5},
            {'id': 'checklist', 'title': '점검 항목', 'headers': ['확인 항목', '세부 내용', '상태'], 'rows': 4},
        ],
        'minutes': [
            {'id': 'summary_matrix', 'title': '안건별 논의 결과', 'headers': ['안건', '논의 내용', '결정 사항'], 'rows': 4},
            {'id': 'checklist', 'title': '후속 조치', 'headers': ['조치 항목', '담당', '기한'], 'rows': 4},
        ],
    }
    return table_map.get(kind, [
        {'id': 'summary_matrix', 'title': '핵심 내용 요약', 'headers': ['구분', '주요 내용', '비고'], 'rows': 4},
        {'id': 'schedule', 'title': '추진 일정', 'headers': ['단계', '기간', '세부 내용', '담당'], 'rows': 4},
    ])


def _reference_contact_payload() -> str:
    return '담당 부서:작성 필요|책임자:직위 이름 작성 필요|담당자:직위 이름 작성 필요'


def _table_block_from_spec(spec: dict, first_col_prefix: str = '항목') -> dict:
    normalized = _normalize_table_spec(spec)
    headers = normalized['headers']
    rows = [headers]
    for row_idx in range(1, normalized.get('rows', 4)):
        row = []
        for col_idx, header in enumerate(headers):
            if col_idx == 0:
                row.append(f'{first_col_prefix} {row_idx}')
            elif re.search(r'(기간|일정|시점|기한)', header):
                row.append('작성 필요')
            elif re.search(r'(담당|부서|책임)', header):
                row.append('작성 필요')
            elif re.search(r'(상태|확인|비고)', header):
                row.append('검토')
            else:
                row.append('작성 필요')
        rows.append(row)
    return {
        'type': 'table',
        'id': normalized['id'],
        'title': normalized['title'],
        'rows': rows,
        'style': normalized.get('style'),
        'headerFill': normalized.get('headerFill'),
    }


def _normalize_official_spacing(text: str) -> str:
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    replacements = {
        'AI기반': 'AI 기반',
        '인공지능기반': '인공지능 기반',
        '생산공정': '생산 공정',
        '공정최적화': '공정 최적화',
        '시스템개발': '시스템 개발',
        '스마트팩토리': '스마트 팩토리',
        '실시간데이터': '실시간 데이터',
        '데이터분석': '데이터 분석',
        '품질관리': '품질 관리',
        '생산성향상': '생산성 향상',
        '비용절감': '비용 절감',
        '불량률감소': '불량률 감소',
        '에너지절감': '에너지 절감',
        '가동률데이터': '가동률 데이터',
        '불량데이터': '불량 데이터',
    }
    for before, after in replacements.items():
        value = value.replace(before, after)
    value = re.sub(r'([,;])(?=\S)', r'\1 ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _fit_cell_text(text: str, *, is_header: bool = False, col_count: int = 3) -> str:
    value = _normalize_official_spacing(text)
    if not value:
        return ''
    limit = 12 if is_header else max(12, 30 - (col_count * 3))
    if is_header:
        return value[:limit]
    if len(value) <= limit:
        return value

    parts = re.split(r'\s*(?:,|/|·|;| 및 | 또는 | 그리고 )\s*', value)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= 2:
        compact = ', '.join(parts[:2])
        if len(compact) <= limit + 4:
            return compact

    return value[: max(8, limit - 1)].rstrip() + ' 등'


def _prepare_table_rows_for_canvas(rows: list[list[str]], max_cols: int = 4, max_rows: int = 5) -> list[list[str]]:
    if not rows:
        return []
    col_count = min(max_cols, max(len(row) for row in rows))
    prepared: list[list[str]] = []
    for row_idx, row in enumerate(rows[:max_rows]):
        current = []
        for col_idx in range(col_count):
            text = row[col_idx] if col_idx < len(row) else ''
            current.append(_fit_cell_text(text, is_header=(row_idx == 0), col_count=col_count))
        prepared.append(current)
    return prepared


def _default_reference_blocks(user_message: str) -> list[dict]:
    kind = _reference_doc_kind(user_message)
    title = _reference_title(user_message, kind)
    toc = _reference_toc(kind)
    table_specs = _reference_table_specs(kind)
    topic = re.sub(r'(보고서|계획서|제안서|회의록|논문|문서|작성|생성|만들|써\s*줘|초안|해줘|해주세요)', ' ', _clean_edit_text(user_message))
    topic = re.sub(r'\s+', ' ', topic).strip() or title
    blocks: list[dict] = [
        {'type': 'design_header', 'pattern': 'attachment_header_bar', 'label': '붙임 1', 'title': title},
        {'type': 'design_contact', 'pattern': 'contact_box', 'items': _parse_design_items(_reference_contact_payload())},
        {'type': 'paragraph', 'role': 'cover_meta', 'text': f'문서 목적: {topic}에 대한 공식 검토와 실행 방향을 구조화한다.'},
        {'type': 'paragraph', 'role': 'cover_meta', 'text': '작성일: 작성 필요'},
        {'type': 'paragraph', 'role': 'cover_meta', 'text': '작성자/부서: 작성 필요'},
        _table_block_from_spec(table_specs[0], '요약') if table_specs else {'type': 'paragraph', 'role': 'body', 'text': ''},
        {'type': 'paragraph', 'role': 'toc_heading', 'text': '목차'},
    ]
    blocks = [block for block in blocks if block.get('text') or block.get('type') != 'paragraph']
    blocks.extend({'type': 'paragraph', 'role': 'body', 'text': line} for line in toc)
    lead = f'본 문서는 {topic}의 필요성과 주요 내용을 정리하고, 실행 가능한 후속 조치를 제시하기 위해 작성한다.'
    blocks.append({'type': 'paragraph', 'role': 'body', 'text': f'□ {lead}'})
    blocks.append({'type': 'design_note', 'pattern': 'note_box', 'text': '※ 세부 수치, 담당자, 시행 일정은 최종 검토 단계에서 보완한다.'})
    section_body = {
        'Ⅰ': [
            f'{topic}의 목적은 관련 현황을 체계적으로 정리하고 의사결정에 필요한 기준을 제공하는 데 있다.',
            '본 문서는 핵심 쟁점, 실행 조건, 기대 효과를 한눈에 확인할 수 있도록 표지, 목차, 본문, 표 형식으로 구성한다.',
        ],
        'Ⅱ': [
            '추진 배경은 기존 업무 흐름의 한계, 이해관계자의 요구, 실행 여건의 변화에서 확인된다.',
            '따라서 단순한 설명보다 문제의 원인과 대응 방향을 구분하고, 후속 검토에 필요한 항목을 명확히 제시하는 것이 중요하다.',
        ],
        'Ⅲ': [
            '주요 내용은 핵심 과제, 세부 실행 항목, 관리 기준으로 구분하여 검토한다.',
            '각 항목은 담당 주체, 실행 시점, 산출물, 확인 기준을 함께 관리해야 하며, 필요 시 표를 활용해 비교 가능성을 높인다.',
        ],
        'Ⅳ': [
            '기대 효과는 업무 효율화, 판단 근거의 명확화, 후속 관리 체계 확보로 정리할 수 있다.',
            '성과 평가는 정량 지표와 정성 판단을 함께 고려하되, 실제 운영 단계에서 확인 가능한 기준을 우선 적용한다.',
        ],
        'Ⅴ': [
            '향후 계획은 세부 자료 보완, 관계자 검토, 실행 일정 확정 순으로 추진한다.',
            '다음 단계에서는 작성 필요 항목을 보완하고, 검토 결과를 반영해 최종본의 범위와 책임 체계를 확정한다.',
        ],
    }
    for idx, heading in enumerate(toc):
        blocks.append({'type': 'paragraph', 'role': 'section_heading', 'text': heading})
        marker = heading[:1]
        for body_idx, body_text in enumerate(section_body.get(marker, [f'{heading}에 대한 세부 내용은 관련 자료를 기준으로 보완한다.'])):
            prefix = '□ ' if body_idx == 0 else '○ '
            blocks.append({'type': 'paragraph', 'role': 'body', 'text': f'{prefix}{body_text}'})
        if idx == 1 and len(table_specs) > 1:
            blocks.append(_table_block_from_spec(table_specs[1], '단계'))
        if idx == 2 and len(table_specs) > 2:
            blocks.append(_table_block_from_spec(table_specs[2], '항목'))
        if idx == 3 and len(table_specs) > 3:
            blocks.append(_table_block_from_spec(table_specs[3], '구분'))
    return blocks


def _reference_quality(blocks: list[dict]) -> dict:
    paragraphs = [b for b in blocks if b.get('type') == 'paragraph' and b.get('text')]
    tables = [b for b in blocks if b.get('type') == 'table' and b.get('rows')]
    designs = [b for b in blocks if str(b.get('type') or '').startswith('design_')]
    section_count = sum(1 for b in paragraphs if b.get('role') == 'section_heading')
    toc_count = sum(1 for b in paragraphs if re.match(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]', b.get('text') or ''))
    text = '\n'.join(b.get('text') or '' for b in paragraphs)
    bad_tokens = len(re.findall(r'\*\*|```|#{1,6}\s|^\s*[-*]\s+', text, re.MULTILINE))
    body_chars = sum(len(b.get('text') or '') for b in paragraphs if b.get('role') == 'body')
    ok = (
        len(paragraphs) >= 14
        and len(designs) >= 1
        and section_count >= 4
        and toc_count >= 8
        and len(tables) >= 1
        and body_chars >= 450
        and bad_tokens == 0
    )
    return {
        'ok': ok,
        'paragraphs': len(paragraphs),
        'sectionCount': section_count,
        'tocCount': toc_count,
        'tables': len(tables),
        'designs': len(designs),
        'bodyChars': body_chars,
        'badTokens': bad_tokens,
    }


def _repair_reference_draft_prompt(user_message: str, draft: str, quality: dict) -> str:
    kind = _reference_doc_kind(user_message)
    title = _reference_title(user_message, kind)
    toc = '\n'.join(_reference_toc(kind))
    tables = json.dumps(_reference_table_specs(kind), ensure_ascii=False)
    return f"""아래 HWP 초안은 품질 기준을 통과하지 못했다. 같은 주제로 더 좋은 공식 HWP 문서 초안을 다시 작성하라.

사용자 요청:
{user_message}

문서 제목:
{title}

필수 목차:
{toc}

필수 표 템플릿:
{tables}

품질 실패 정보:
{json.dumps(quality, ensure_ascii=False)}

이전 초안:
{draft[:5000]}

재작성 규칙:
- 설명 없이 문서 본문만 출력한다.
- 마크다운 기호, 굵게 표시 기호, 코드블록을 절대 쓰지 않는다.
- 첫 줄은 반드시 `[[DESIGN:attachment_header_bar:붙임 1:{title}]]` 형식으로 쓴다.
- 작성 정보 다음에는 `[[DESIGN:contact_box:담당 부서:작성 필요|책임자:직위 이름 작성 필요|담당자:직위 이름 작성 필요]]`를 포함한다.
- 작성 정보, 목차, 본문 5개 대섹션을 반드시 포함한다.
- 각 본문 대섹션에는 2문장 이상의 구체적인 문단을 작성한다.
- 최소 1개 이상의 TABLE 블록을 포함한다.
- TABLE 블록은 `[[TABLE:id:title]]`와 `[[/TABLE]]` 사이에 파이프 구분 행을 넣는다.
- TABLE 셀은 짧은 명사형 문구로 작성하고, 긴 설명은 본문 문단에 둔다.
- 본문 대섹션 첫 문단은 `□`, 보조 설명은 `○` 기호로 시작한다.
- 공공기관 보고서 문체로 쓴다.
"""


def _reference_draft_prompt(user_message: str) -> str:
    style_profile = _load_style_profile()
    style_kit = _style_kit_prompt_text()
    official_skill = _load_hwp_official_skill()
    kind = _reference_doc_kind(user_message)
    title = _reference_title(user_message, kind)
    toc = '\n'.join(_reference_toc(kind))
    tables = json.dumps(_reference_table_specs(kind), ensure_ascii=False)
    return f"""다음 요청에 대해 HWP에 바로 삽입할 고품질 공식 문서 초안을 작성하세요.

사용자 요청:
{user_message}

반드시 아래 HWP 공식 문서 Skill을 따른다.
{official_skill}

문서 유형: {kind}
권장 제목: {title}
반드시 사용할 목차:
{toc}

반드시 사용할 표 템플릿:
{tables}

반드시 아래 공개 HWP 레퍼런스 양식 프로필을 따른다.
{style_profile}

반드시 아래 HWP 스타일 키트에서 목차 템플릿, 부호, 표 템플릿을 선택해 사용한다.
{style_kit}

출력 규칙:
- 설명, 마크다운 코드블록, JSON 없이 문서 본문 텍스트만 출력한다.
- 일반 에세이처럼 쓰지 말고 실제 HWP 문서처럼 쓴다.
- 표지는 가능한 경우 `[[DESIGN:attachment_header_bar:붙임 1:제목]]` 형식으로 시작한다. 이 디자인은 파란 "붙임 1" 라벨, 제목, 하단 실선으로 실제 HWP 양식 블록으로 변환된다.
- 담당 부서/책임자/담당자 정보는 `[[DESIGN:contact_box:담당 부서:...|책임자:...|담당자:...]]`로 만든다.
- 유의사항은 `[[DESIGN:note_box:※ ...]]`로 만든다.
- 작성 정보, 목차, 본문 5개 대섹션을 반드시 포함한다.
- 목차는 본문 제목과 정확히 대응한다.
- 본문 각 대섹션에는 최소 2문장 이상을 쓴다.
- 주요 내용에는 위 표 템플릿 중 하나 이상을 사용한다. 표는 나중에 실제 HWP 표로 변환할 수 있도록 `[[TABLE:id:title]]` 블록으로 표시한다.
- TABLE 블록 형식:
  [[TABLE:summary_matrix:핵심 내용 요약]]
  구분 | 주요 내용 | 비고
  목적 | ... | ...
  [[/TABLE]]
- DESIGN 블록 형식:
  [[DESIGN:attachment_header_bar:붙임 1:2026년 3월 우리나라 기온 분포도 및 일별 경향]]
  [[DESIGN:contact_box:담당 부서:작성 필요|책임자:과장 작성 필요|담당자:사무관 작성 필요]]
  [[DESIGN:note_box:※ 세부 수치와 담당자는 최종 검토 단계에서 보완한다.]]
- 표 헤더는 반드시 실제 열 제목으로 쓴다. "열1", "열2" 같은 임시 헤더 금지.
- 표 셀에는 긴 문장을 넣지 말고 12~20자 내외의 짧은 명사형 문구를 넣는다. 긴 설명은 표 밖 본문 문단에 작성한다.
- 본문 대섹션 첫 문단은 `□`, 보조 설명은 `○` 기호를 사용해 공공기관 보고서식 계층을 만든다.
- 사실이 불명확한 세부 수치/기관명만 "작성 필요"로 두고, 나머지는 요청 맥락에 맞춰 구체적으로 작성한다.
- 별표, 해시, markdown 리스트 기호를 쓰지 않는다. 필요한 목록은 `1.`, `2.`, `□`, `○`, `※`만 사용한다.
- 문체는 격식 있고 공식적인 문서체로 쓴다.
- 섹션 번호는 Ⅰ, Ⅱ, Ⅲ 형식을 사용한다.
"""


def _sanitize_reference_text(text: str) -> str:
    raw = str(text or '')
    raw = re.sub(r'^```(?:text|markdown|md)?\s*', '', raw.strip())
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.replace('**', '').replace('__', '')
    raw = re.sub(r'^\s{0,3}#{1,6}\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'^\s*[-*]\s+', '• ', raw, flags=re.MULTILINE)
    return raw.strip()


def _parse_design_items(payload: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for part in str(payload or '').split('|'):
        if ':' in part:
            key, value = part.split(':', 1)
            key = key.strip()
            value = value.strip()
            if key or value:
                items.append((key or '항목', value or '작성 필요'))
    return items or [('담당 부서', '작성 필요'), ('책임자', '작성 필요'), ('담당자', '작성 필요')]


def _parse_design_block(line: str) -> Optional[dict]:
    if not (line.startswith('[[DESIGN:') and line.endswith(']]')):
        return None
    inner = line[len('[[DESIGN:'):-2]
    parts = inner.split(':', 2)
    pattern = parts[0].strip() if parts else ''
    if pattern == 'attachment_header_bar' and len(parts) >= 3:
        return {'type': 'design_header', 'pattern': pattern, 'label': parts[1].strip(), 'title': parts[2].strip()}
    if pattern == 'contact_box' and len(parts) >= 2:
        payload = parts[1] if len(parts) == 2 else f'{parts[1]}:{parts[2]}'
        return {'type': 'design_contact', 'pattern': pattern, 'items': _parse_design_items(payload)}
    if pattern == 'note_box' and len(parts) >= 2:
        payload = parts[1] if len(parts) == 2 else f'{parts[1]}:{parts[2]}'
        return {'type': 'design_note', 'pattern': pattern, 'text': payload.strip()}
    if pattern == 'section_heading_rule' and len(parts) >= 2:
        payload = parts[1] if len(parts) == 2 else f'{parts[1]}:{parts[2]}'
        return {'type': 'paragraph', 'role': 'section_heading', 'text': payload.strip()}
    return None


def _parse_reference_blocks(draft: str) -> list[dict]:
    lines = _sanitize_reference_text(draft).splitlines()
    blocks: list[dict] = []
    toc_mode = False
    toc_entries: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        design_block = _parse_design_block(line)
        if design_block:
            blocks.append(design_block)
            i += 1
            continue
        table_match = re.match(r'^\[\[TABLE:([^:\]]+):([^\]]+)\]\]$', line)
        if table_match:
            table_id, title = table_match.groups()
            rows: list[list[str]] = []
            i += 1
            while i < len(lines) and lines[i].strip() != '[[/TABLE]]':
                raw_row = lines[i].strip()
                if re.match(r'^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$', raw_row):
                    i += 1
                    continue
                row = [cell.strip() for cell in raw_row.strip('|').split('|')]
                if any(row):
                    rows.append(row)
                i += 1
            blocks.append({'type': 'table', 'id': table_id, 'title': title.strip(), 'rows': rows})
        elif line:
            role = 'body'
            is_numbered_heading = bool(re.match(r'^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]|[0-9]+[.)]\s|[가-힣][.)]\s)', line))
            if toc_mode and not is_numbered_heading and line not in {'목차', '[목차]', '차례'}:
                toc_mode = False
            if not blocks:
                role = 'cover_title'
            elif line in {'목차', '[목차]', '차례'}:
                role = 'toc_heading'
                toc_mode = True
            elif is_numbered_heading:
                is_section = bool(re.match(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]', line))
                if toc_mode and is_section and line not in toc_entries:
                    role = 'body'
                    toc_entries.add(line)
                else:
                    if toc_mode and is_section and line in toc_entries:
                        toc_mode = False
                    role = 'section_heading' if is_section else 'sub_heading'
            elif re.match(r'^(작성일|작성자|부서|대상|문서 목적)\s*:', line):
                role = 'cover_meta'
                toc_mode = False
            blocks.append({'type': 'paragraph', 'role': role, 'text': line})
        i += 1
    return blocks


def _fallback_body_for_heading(heading: str) -> list[str]:
    clean = re.sub(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]*', '', str(heading or '')).strip() or '해당 항목'
    return [
        f'□ {clean}에서는 문서의 목적에 맞춰 검토 범위와 판단 기준을 정리한다.',
        '○ 관련 내용은 실행 가능성, 담당 주체, 확인 방법을 함께 제시하여 후속 검토에 바로 활용할 수 있도록 구성한다.',
    ]


def _ensure_reference_block_flow(blocks: list[dict]) -> list[dict]:
    flowed: list[dict] = []
    table_count = 0
    max_tables = 3
    body_after_heading = 0
    for idx, block in enumerate(blocks or []):
        block = dict(block)
        if block.get('type') == 'table':
            if table_count >= max_tables:
                continue
            rows = block.get('rows') or []
            if rows:
                col_count = min(4, max(len(row) for row in rows))
                normalized_rows = []
                for row in rows[:5]:
                    normalized_rows.append([str(cell).strip() for cell in row[:col_count]] + [''] * max(0, col_count - len(row)))
                normalized_rows = _prepare_table_rows_for_canvas(normalized_rows)
                table_count += 1
                raw_title = str(block.get('title') or '표').strip()
                if not re.match(r'^(?:〈표\s*\d+〉|표\s*\d+[.)])', raw_title):
                    raw_title = f'〈표 {table_count}〉 {raw_title}'
                block = {**block, 'title': raw_title, 'rows': normalized_rows}
            else:
                continue

        if block.get('type') == 'paragraph' and block.get('role') == 'body':
            text = str(block.get('text') or '').strip()
            if body_after_heading > 0 and text and not re.match(r'^(?:□|○|[-ㆍ※])\s*', text):
                prefix = '□ ' if body_after_heading == 1 else '○ '
                block['text'] = prefix + text
            if body_after_heading > 0:
                body_after_heading += 1

        flowed.append(block)

        if block.get('type') == 'paragraph' and block.get('role') in {'section_heading', 'sub_heading'}:
            body_after_heading = 1
            next_block = blocks[idx + 1] if idx + 1 < len(blocks) else {}
            next_is_body = next_block.get('type') == 'paragraph' and next_block.get('role') == 'body' and bool(next_block.get('text'))
            if not next_is_body:
                for text in _fallback_body_for_heading(block.get('text') or ''):
                    flowed.append({'type': 'paragraph', 'role': 'body', 'text': text})
                body_after_heading = 3
        elif block.get('type') == 'paragraph' and block.get('role') not in {'body'}:
            body_after_heading = 0
    return flowed


def _generate_reference_blocks(user_message: str) -> tuple[list[dict], dict]:
    generator = CodexTextGenerator(temperature=0.12)
    draft = _sanitize_reference_text(generator._call_api(_reference_draft_prompt(user_message), stream=False))
    blocks = _parse_reference_blocks(draft) if draft else []
    blocks = _ensure_reference_block_flow(blocks)
    quality = _reference_quality(blocks)
    if quality.get('ok'):
        return blocks, {**quality, 'source': 'model'}

    if draft:
        repaired = _sanitize_reference_text(generator._call_api(_repair_reference_draft_prompt(user_message, draft, quality), stream=False))
        repaired_blocks = _parse_reference_blocks(repaired) if repaired else []
        repaired_blocks = _ensure_reference_block_flow(repaired_blocks)
        repaired_quality = _reference_quality(repaired_blocks)
        if repaired_quality.get('ok'):
            return repaired_blocks, {**repaired_quality, 'source': 'model_repaired'}
        quality = {**repaired_quality, 'previous': quality}

    fallback_blocks = _ensure_reference_block_flow(_default_reference_blocks(user_message))
    return fallback_blocks, {**_reference_quality(fallback_blocks), 'source': 'deterministic_fallback', 'modelQuality': quality}


def _preset_for_role(role: str) -> tuple[dict, dict]:
    kit = _load_style_kit()
    presets = (kit.get('style_presets') or {}) if isinstance(kit, dict) else {}
    preset = presets.get(role) or presets.get('body') or {}
    char = dict(preset.get('char') or {})
    para = dict(preset.get('para') or {})
    if role == 'cover_meta':
        para.update({'align': 'Left', 'lineSpacing': 145, 'spacingAfter': 40})
        char.setdefault('fontSize', 1000)
    elif role == 'toc_heading':
        para.update({'align': 'Left', 'lineSpacing': 145, 'spacingBefore': 180, 'spacingAfter': 120})
        char.update({'fontSize': 1500, 'bold': True})
    elif role == 'section_heading':
        para.update({'align': 'Left', 'lineSpacing': 145, 'spacingBefore': 260, 'spacingAfter': 140})
        char.update({'fontSize': 1450, 'bold': True})
    elif role == 'body':
        para.update({'align': 'Justify', 'lineSpacing': 165, 'spacingAfter': 70})
        char.setdefault('fontSize', 1000)
    elif role == 'table_caption':
        para.update({'align': 'Left', 'lineSpacing': 135, 'spacingBefore': 180, 'spacingAfter': 70})
        char.update({'fontSize': 950, 'bold': True})
    return char, para


def _insert_paragraph_after(session_id: str, para: int, text: str) -> tuple[int, list]:
    _tool_result(session_id, 'split_paragraph', {'sec': 0, 'para': para, 'offset': 0})
    result, affected = _tool_result(session_id, 'insert_text', {'sec': 0, 'para': para, 'offset': 0, 'text': text})
    return para + 1, affected


def _border(line_type: int = 1, width: int = 1, color: str = '#000000') -> dict:
    return {'type': line_type, 'width': width, 'color': color}


def _insert_attachment_header_bar(session_id: str, para: int, label: str, title: str) -> tuple[int, set]:
    affected_pages = set()
    label = label or '붙임 1'
    title = title or '문서 제목'

    _tool_result(session_id, 'split_paragraph', {'sec': 0, 'para': para, 'offset': 0})
    result, affected = _tool_result(session_id, 'create_table', {
        'sec': 0,
        'para': para,
        'offset': 0,
        'rows': 1,
        'cols': 3,
        'cells': [[label, '', title]],
    })
    for page in affected or result.get('affectedPages') or []:
        affected_pages.add(page)
    data = result.get('data') or {}
    table_para = data.get('paraIdx', para)
    control_idx = data.get('controlIdx', 0)

    no_border = _border(0, 0, '#ffffff')
    bottom = _border(1, 2, '#000000')
    thick = _border(1, 2, '#000000')
    cell_props = [
        {
            'width': 5400,
            'height': 1700,
            'paddingLeft': 180,
            'paddingRight': 180,
            'paddingTop': 120,
            'paddingBottom': 120,
            'verticalAlign': 1,
            'fillType': 'solid',
            'fillColor': '#005a9c',
            'borderLeft': thick,
            'borderRight': thick,
            'borderTop': thick,
            'borderBottom': thick,
        },
        {
            'width': 650,
            'height': 1700,
            'paddingLeft': 0,
            'paddingRight': 0,
            'paddingTop': 0,
            'paddingBottom': 0,
            'verticalAlign': 1,
            'fillType': 'none',
            'borderLeft': no_border,
            'borderRight': thick,
            'borderTop': no_border,
            'borderBottom': bottom,
        },
        {
            'width': 32000,
            'height': 1700,
            'paddingLeft': 650,
            'paddingRight': 200,
            'paddingTop': 120,
            'paddingBottom': 120,
            'verticalAlign': 1,
            'fillType': 'none',
            'borderLeft': no_border,
            'borderRight': no_border,
            'borderTop': no_border,
            'borderBottom': bottom,
        },
    ]
    for cell_idx, props in enumerate(cell_props):
        try:
            r, a = _tool_result(session_id, 'set_cell_properties', {
                'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx, 'props': props
            })
            for page in a or r.get('affectedPages') or []:
                affected_pages.add(page)
        except Exception as exc:
            print(f'[HWP v2] attachment header cell style failed: {exc}')

    cell_formats = [
        (0, label, {'fontName': '함초롬돋움', 'fontSize': 1700, 'bold': True, 'textColor': 0xFFFFFF}, {'align': 'Center', 'lineSpacing': 120}),
        (2, title, {'fontName': '함초롬돋움', 'fontSize': 1700, 'bold': True, 'textColor': 0x000000}, {'align': 'Left', 'lineSpacing': 120}),
    ]
    for cell_idx, text, char_props, para_props in cell_formats:
        try:
            r, a = _tool_result(session_id, 'set_char_format_in_cell', {
                'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx,
                'cellPara': 0, 'start': 0, 'end': max(1, len(text)), 'props': char_props
            })
            for page in a or r.get('affectedPages') or []:
                affected_pages.add(page)
            r, a = _tool_result(session_id, 'set_para_format_in_cell', {
                'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx,
                'cellPara': 0, 'props': para_props
            })
            for page in a or r.get('affectedPages') or []:
                affected_pages.add(page)
        except Exception as exc:
            print(f'[HWP v2] attachment header text style failed: {exc}')

    return para + 1, affected_pages


def _format_cell_text(session_id: str, table_para: int, control_idx: int, cell_idx: int, text: str, char_props: dict, para_props: dict) -> set:
    affected_pages = set()
    try:
        r, a = _tool_result(session_id, 'set_char_format_in_cell', {
            'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx,
            'cellPara': 0, 'start': 0, 'end': max(1, len(text)), 'props': char_props
        })
        for page in a or r.get('affectedPages') or []:
            affected_pages.add(page)
        r, a = _tool_result(session_id, 'set_para_format_in_cell', {
            'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx,
            'cellPara': 0, 'props': para_props
        })
        for page in a or r.get('affectedPages') or []:
            affected_pages.add(page)
    except Exception as exc:
        print(f'[HWP v2] cell text format failed: {exc}')
    return affected_pages


def _style_official_table(session_id: str, table_para: int, control_idx: int, rows: list[list[str]], header_fill: str = '#e8eef6') -> set:
    affected_pages = set()
    if not rows:
        return affected_pages
    row_count = len(rows)
    col_count = max(len(row) for row in rows)
    table_width = 30000
    base_width = max(5600, int(table_width / max(1, col_count)))
    line = _border(1, 1, '#6f7f92')
    header_line = _border(1, 2, '#344256')
    for row_idx in range(row_count):
        for col_idx in range(col_count):
            cell_idx = row_idx * col_count + col_idx
            is_header = row_idx == 0
            props = {
                'width': base_width,
                'height': 980 if is_header else 1350,
                'paddingLeft': 180,
                'paddingRight': 180,
                'paddingTop': 150,
                'paddingBottom': 150,
                'verticalAlign': 1,
                'fillType': 'solid' if is_header else 'none',
                'fillColor': header_fill if is_header else '#ffffff',
                'borderLeft': line,
                'borderRight': line,
                'borderTop': header_line if is_header else line,
                'borderBottom': header_line if is_header else line,
            }
            try:
                r, a = _tool_result(session_id, 'set_cell_properties', {
                    'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx, 'props': props
                })
                for page in a or r.get('affectedPages') or []:
                    affected_pages.add(page)
            except Exception as exc:
                print(f'[HWP v2] official table cell style failed: {exc}')
            text = rows[row_idx][col_idx] if col_idx < len(rows[row_idx]) else ''
            affected_pages.update(_format_cell_text(
                session_id,
                table_para,
                control_idx,
                cell_idx,
                text,
                {'fontName': '함초롬돋움' if is_header else '함초롬바탕', 'fontSize': 850 if is_header else 820, 'bold': is_header},
                {'align': 'Center' if is_header else 'Left', 'lineSpacing': 130},
            ))
    return affected_pages


def _insert_contact_box(session_id: str, para: int, items: list[tuple[str, str]]) -> tuple[int, set]:
    affected_pages = set()
    rows = [[key, value] for key, value in (items or _parse_design_items(_reference_contact_payload()))[:4]]

    _tool_result(session_id, 'split_paragraph', {'sec': 0, 'para': para, 'offset': 0})
    result, affected = _tool_result(session_id, 'create_table', {
        'sec': 0, 'para': para, 'offset': 0, 'rows': len(rows), 'cols': 2, 'cells': rows,
    })
    for page in affected or result.get('affectedPages') or []:
        affected_pages.add(page)
    data = result.get('data') or {}
    table_para = data.get('paraIdx', para)
    control_idx = data.get('controlIdx', 0)
    line = _border(1, 1, '#7f8ea3')
    for row_idx, row in enumerate(rows):
        for col_idx in range(2):
            cell_idx = row_idx * 2 + col_idx
            is_label = col_idx == 0
            props = {
                'width': 5200 if is_label else 23500,
                'height': 820,
                'paddingLeft': 220,
                'paddingRight': 220,
                'paddingTop': 100,
                'paddingBottom': 100,
                'verticalAlign': 1,
                'fillType': 'solid' if is_label else 'none',
                'fillColor': '#e8eef6' if is_label else '#ffffff',
                'borderLeft': line,
                'borderRight': line,
                'borderTop': line,
                'borderBottom': line,
            }
            r, a = _tool_result(session_id, 'set_cell_properties', {
                'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': cell_idx, 'props': props
            })
            for page in a or r.get('affectedPages') or []:
                affected_pages.add(page)
            affected_pages.update(_format_cell_text(
                session_id, table_para, control_idx, cell_idx, row[col_idx],
                {'fontName': '함초롬돋움', 'fontSize': 900, 'bold': is_label},
                {'align': 'Center' if is_label else 'Left', 'lineSpacing': 140},
            ))
    return para + 1, affected_pages


def _insert_note_box(session_id: str, para: int, text: str) -> tuple[int, set]:
    affected_pages = set()
    text = text or '※ 작성 필요'
    _tool_result(session_id, 'split_paragraph', {'sec': 0, 'para': para, 'offset': 0})
    result, affected = _tool_result(session_id, 'create_table', {
        'sec': 0, 'para': para, 'offset': 0, 'rows': 1, 'cols': 1, 'cells': [[text]],
    })
    for page in affected or result.get('affectedPages') or []:
        affected_pages.add(page)
    data = result.get('data') or {}
    table_para = data.get('paraIdx', para)
    control_idx = data.get('controlIdx', 0)
    line = _border(1, 1, '#b7c4d6')
    r, a = _tool_result(session_id, 'set_cell_properties', {
        'sec': 0, 'para': table_para, 'controlIdx': control_idx, 'cellIdx': 0,
        'props': {
            'width': 36000,
            'height': 900,
            'paddingLeft': 320,
            'paddingRight': 320,
            'paddingTop': 130,
            'paddingBottom': 130,
            'verticalAlign': 1,
            'fillType': 'solid',
            'fillColor': '#f2f6fb',
            'borderLeft': line,
            'borderRight': line,
            'borderTop': line,
            'borderBottom': line,
        }
    })
    for page in a or r.get('affectedPages') or []:
        affected_pages.add(page)
    affected_pages.update(_format_cell_text(
        session_id, table_para, control_idx, 0, text,
        {'fontName': '함초롬바탕', 'fontSize': 920},
        {'align': 'Left', 'lineSpacing': 145},
    ))
    return para + 1, affected_pages


def _apply_preset(session_id: str, para: int, text: str, role: str) -> set:
    affected_pages = set()
    char_props, para_props = _preset_for_role(role)
    if char_props:
        result, affected = _tool_result(session_id, 'set_char_format', {
            'sec': 0, 'para': para, 'start': 0, 'end': max(1, len(text)), 'props': char_props
        })
        for page in affected or result.get('affectedPages') or []:
            affected_pages.add(page)
    if para_props:
        result, affected = _tool_result(session_id, 'set_para_format', {
            'sec': 0, 'para': para, 'props': para_props
        })
        for page in affected or result.get('affectedPages') or []:
            affected_pages.add(page)
    return affected_pages


def _insert_reference_blocks(session_id: str, blocks: list[dict]) -> tuple[int, set]:
    current_para = 0
    affected_pages = set()
    inserted = 0

    # Remove placeholder text if any, then use paragraph 0 as first insertion point.
    for block in blocks:
        if block.get('type') == 'design_header':
            next_para, affected = _insert_attachment_header_bar(
                session_id,
                current_para,
                block.get('label') or '붙임 1',
                block.get('title') or '문서 제목',
            )
            affected_pages.update(affected)
            current_para = next_para
            inserted += 1
        elif block.get('type') == 'design_contact':
            next_para, affected = _insert_contact_box(session_id, current_para, block.get('items') or [])
            affected_pages.update(affected)
            current_para = next_para
            inserted += 1
        elif block.get('type') == 'design_note':
            next_para, affected = _insert_note_box(session_id, current_para, block.get('text') or '')
            affected_pages.update(affected)
            current_para = next_para
            inserted += 1
        elif block.get('type') == 'paragraph':
            text = block.get('text') or ''
            if not text:
                continue
            next_para, affected = _insert_paragraph_after(session_id, current_para, text)
            for page in affected or []:
                affected_pages.add(page)
            affected_pages.update(_apply_preset(session_id, current_para, text, block.get('role') or 'body'))
            current_para = next_para
            inserted += 1
        elif block.get('type') == 'table':
            title = block.get('title') or '표'
            next_para, affected = _insert_paragraph_after(session_id, current_para, title)
            for page in affected or []:
                affected_pages.add(page)
            affected_pages.update(_apply_preset(session_id, current_para, title, 'table_caption'))
            current_para = next_para
            rows = block.get('rows') or []
            if rows:
                normalized = _prepare_table_rows_for_canvas(rows)
                col_count = max(len(row) for row in normalized)
                result, affected = _tool_result(session_id, 'create_table', {
                    'sec': 0,
                    'para': current_para,
                    'offset': 0,
                    'rows': len(normalized),
                    'cols': col_count,
                    'cells': normalized,
                })
                for page in affected or result.get('affectedPages') or []:
                    affected_pages.add(page)
                data = result.get('data') or {}
                affected_pages.update(_style_official_table(
                    session_id,
                    data.get('paraIdx', current_para),
                    data.get('controlIdx', 0),
                    normalized,
                    block.get('headerFill') or '#e8eef6',
                ))
                current_para = int(data.get('paraIdx', current_para)) + 1
                inserted += 1
    return inserted, affected_pages


def _stream_reference_block_inserts(session_id: str, blocks: list[dict]):
    current_para = 0
    inserted = 0
    total = len(blocks)

    yield _sse({"type": "tool_start", "name": "apply_reference_blocks", "args": {"blocks": total}})
    for index, block in enumerate(blocks, start=1):
        affected_pages = set()
        if block.get('type') == 'design_header':
            next_para, affected = _insert_attachment_header_bar(
                session_id,
                current_para,
                block.get('label') or '붙임 1',
                block.get('title') or '문서 제목',
            )
            affected_pages.update(affected)
            current_para = next_para
            inserted += 1
            yield _sse({
                "type": "tool_result",
                "name": "apply_reference_design",
                "result": {
                    "insertedBlocks": inserted,
                    "sourceBlocks": total,
                    "blockIndex": index,
                    "blockType": "design_header",
                    "pattern": block.get('pattern') or 'attachment_header_bar',
                    "label": block.get('label') or '붙임 1',
                    "title": block.get('title') or '문서 제목',
                },
                "affected": sorted(affected_pages) or [0],
                "live": True,
            })
        elif block.get('type') == 'design_contact':
            next_para, affected = _insert_contact_box(session_id, current_para, block.get('items') or [])
            affected_pages.update(affected)
            current_para = next_para
            inserted += 1
            yield _sse({
                "type": "tool_result",
                "name": "apply_reference_design",
                "result": {
                    "insertedBlocks": inserted,
                    "sourceBlocks": total,
                    "blockIndex": index,
                    "blockType": "design_contact",
                    "pattern": "contact_box",
                },
                "affected": sorted(affected_pages) or [0],
                "live": True,
            })
        elif block.get('type') == 'design_note':
            next_para, affected = _insert_note_box(session_id, current_para, block.get('text') or '')
            affected_pages.update(affected)
            current_para = next_para
            inserted += 1
            yield _sse({
                "type": "tool_result",
                "name": "apply_reference_design",
                "result": {
                    "insertedBlocks": inserted,
                    "sourceBlocks": total,
                    "blockIndex": index,
                    "blockType": "design_note",
                    "pattern": "note_box",
                },
                "affected": sorted(affected_pages) or [0],
                "live": True,
            })
        elif block.get('type') == 'paragraph':
            text = block.get('text') or ''
            if not text:
                continue
            next_para, affected = _insert_paragraph_after(session_id, current_para, text)
            for page in affected or []:
                affected_pages.add(page)
            affected_pages.update(_apply_preset(session_id, current_para, text, block.get('role') or 'body'))
            result = {
                "insertedBlocks": inserted + 1,
                "sourceBlocks": total,
                "blockIndex": index,
                "blockType": "paragraph",
                "role": block.get('role') or 'body',
                "preview": text[:80],
            }
            current_para = next_para
            inserted += 1
            yield _sse({
                "type": "tool_result",
                "name": "apply_reference_block",
                "result": result,
                "affected": sorted(affected_pages) or [0],
                "live": True,
            })
        elif block.get('type') == 'table':
            title = block.get('title') or '표'
            next_para, affected = _insert_paragraph_after(session_id, current_para, title)
            for page in affected or []:
                affected_pages.add(page)
            affected_pages.update(_apply_preset(session_id, current_para, title, 'table_caption'))
            current_para = next_para
            rows = block.get('rows') or []
            table_result = {}
            if rows:
                normalized = _prepare_table_rows_for_canvas(rows)
                col_count = max(len(row) for row in normalized)
                table_result, affected = _tool_result(session_id, 'create_table', {
                    'sec': 0,
                    'para': current_para,
                    'offset': 0,
                    'rows': len(normalized),
                    'cols': col_count,
                    'cells': normalized,
                })
                for page in affected or table_result.get('affectedPages') or []:
                    affected_pages.add(page)
                data = table_result.get('data') or {}
                affected_pages.update(_style_official_table(
                    session_id,
                    data.get('paraIdx', current_para),
                    data.get('controlIdx', 0),
                    normalized,
                    block.get('headerFill') or '#e8eef6',
                ))
                current_para = int(data.get('paraIdx', current_para)) + 1
            inserted += 1
            yield _sse({
                "type": "tool_result",
                "name": "apply_reference_block",
                "result": {
                    "insertedBlocks": inserted,
                    "sourceBlocks": total,
                    "blockIndex": index,
                    "blockType": "table",
                    "tableId": block.get('id'),
                    "title": title,
                    "table": table_result.get('data') if isinstance(table_result, dict) else None,
                },
                "affected": sorted(affected_pages) or [0],
                "live": True,
            })

    yield _sse({
        "type": "tool_result",
        "name": "apply_reference_blocks",
        "result": {"insertedBlocks": inserted, "sourceBlocks": total},
        "affected": [0],
        "live": True,
    })


def _format_inserted_reference_draft(session_id: str) -> tuple[int, set]:
    affected_pages = set()
    formatted = 0
    try:
        structure = _node_get_json(f'/sessions/{session_id}/structure') or {}
    except Exception:
        return formatted, affected_pages

    for index, item in enumerate(structure.get('outline') or []):
        sec = item.get('sec')
        para = item.get('para')
        length = int(item.get('length') or 0)
        preview = _clean_edit_text(item.get('preview') or '')
        if sec is None or para is None or length <= 0 or not preview:
            continue

        is_cover_title = index == 0
        is_major_heading = bool(re.match(r'^(?:\[.+\]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s])', preview))
        is_toc_line = bool(re.match(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]', preview)) and len(preview) < 40

        if is_cover_title:
            char_props = {"fontName": "함초롬바탕", "fontSize": 2200, "bold": True}
            para_props = {"align": "Center", "lineSpacing": 150, "spacingAfter": 400}
        elif is_major_heading:
            char_props = {"fontName": "함초롬바탕", "fontSize": 1300, "bold": True}
            para_props = {"align": "Left", "lineSpacing": 150, "spacingBefore": 220, "spacingAfter": 100}
        elif is_toc_line:
            char_props = {"fontName": "함초롬바탕", "fontSize": 1050}
            para_props = {"align": "Left", "lineSpacing": 145}
        else:
            char_props = {"fontName": "함초롬바탕", "fontSize": 1000}
            para_props = {"align": "Justify", "lineSpacing": 160}

        try:
            result, affected = _tool_result(session_id, 'set_char_format', {
                'sec': int(sec), 'para': int(para), 'start': 0, 'end': length, 'props': char_props
            })
            for page in affected or result.get('affectedPages') or []:
                affected_pages.add(page)
            result, affected = _tool_result(session_id, 'set_para_format', {
                'sec': int(sec), 'para': int(para), 'props': para_props
            })
            for page in affected or result.get('affectedPages') or []:
                affected_pages.add(page)
            formatted += 1
        except Exception:
            continue
    return formatted, affected_pages


def _try_reference_draft(session_id: str, user_message: str):
    if not _is_reference_draft_request(user_message):
        return None
    structure = _node_get_json(f'/sessions/{session_id}/structure')
    if not _is_blankish_structure(structure):
        return None

    blocks, quality = _generate_reference_blocks(user_message)
    if not blocks:
        return None

    def events():
        yield _sse({
            "type": "status",
            "phase": "reference_draft",
            "text": "레퍼런스 HWP 양식 기준으로 구조 품질을 검사한 뒤 표지·목차·본문 초안을 구성합니다.",
            "quality": quality,
        })
        for event in _stream_reference_block_inserts(session_id, blocks):
            yield event
        yield _sse({"type": "text", "delta": "레퍼런스 HWP 키트에서 목차·부호·표·서식 패턴을 선택해 문서 구조로 삽입했습니다."})
        yield _sse({"type": "done"})
    return events()


def _extract_json_array(text: str) -> list:
    raw = str(text or '').strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        parsed = json.loads(raw)
    except Exception:
        start = raw.find('[')
        end = raw.rfind(']')
        if start < 0 or end < start:
            raise
        parsed = json.loads(raw[start:end + 1])
    if not isinstance(parsed, list):
        raise ValueError('JSON array expected')
    return parsed


def _style_instruction(user_message: str) -> str:
    text = _clean_edit_text(user_message)
    if re.search(r'(격식|딱딱|공식|공문|행정|보고서|formal|포멀)', text, re.IGNORECASE):
        return '격식 있고 공식적인 공문/회의록 문체로, 간결하고 딱딱한 표현을 사용'
    if re.search(r'(정중)', text):
        return '정중하고 격식 있는 표현을 사용'
    return '격식 있고 딱딱한 문체로 표현을 정리'


def _collect_rewrite_targets(session_id: str, structure: dict) -> list[dict]:
    targets = []
    for item in structure.get('outline') or []:
        sec = item.get('sec')
        para = item.get('para')
        length = int(item.get('length') or 0)
        preview = _clean_edit_text(item.get('preview') or '')
        if sec is None or para is None or length < 8 or not preview:
            continue
        if not re.search(r'[가-힣]', preview):
            continue
        try:
            data, _ = _tool_result(session_id, 'get_paragraph_text', {'sec': sec, 'para': para})
            text = _clean_edit_text((data or {}).get('text') if isinstance(data, dict) else data)
        except Exception:
            text = preview
        if len(text) < 8:
            continue
        # Keep short labels, names, dates, and pure headings mostly intact.
        if len(text) <= 12 and not re.search(r'(입니다|합니다|된다|한다|있다|없다|위해|대한|하며|하고)', text):
            continue
        targets.append({'sec': int(sec), 'para': int(para), 'text': text, 'length': len(text)})
        if len(targets) >= 40:
            break
    return targets


def _try_style_rewrite(session_id: str, user_message: str) -> Optional[list[str]]:
    if not _is_style_rewrite_request(user_message):
        return None

    events = [_sse({"type": "tool_start", "name": "rewrite_style", "args": {"style": _style_instruction(user_message)}})]
    structure = _node_get_json(f'/sessions/{session_id}/structure')
    targets = _collect_rewrite_targets(session_id, structure)
    if not targets:
        events.append(_sse({"type": "tool_error", "name": "rewrite_style", "error": "수정할 본문 문단을 찾지 못했습니다."}))
        events.append(_sse({"type": "done"}))
        return events

    prompt = f"""다음 HWP 문서 문단들을 사용자의 요청에 맞게 문체만 고쳐 쓰세요.

사용자 요청: {user_message}
문체 목표: {_style_instruction(user_message)}

규칙:
- 의미, 사실관계, 날짜, 이름, 숫자, 항목 순서는 보존합니다.
- 제목/표 라벨처럼 이미 짧은 항목은 꼭 필요할 때만 최소 수정합니다.
- 과장하거나 내용을 추가하지 않습니다.
- 출력은 JSON 배열만 반환합니다.
- 각 원소 형식: {{"sec": 0, "para": 0, "text": "수정된 문단"}}

문단 목록:
{json.dumps(targets, ensure_ascii=False)}
"""
    generator = CodexTextGenerator(temperature=0.15)
    rewritten = generator._call_api(prompt, stream=False)
    rows = _extract_json_array(rewritten)

    by_key = {(t['sec'], t['para']): t for t in targets}
    changed = 0
    affected_pages = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            sec = int(row.get('sec'))
            para = int(row.get('para'))
        except Exception:
            continue
        original = by_key.get((sec, para))
        if not original:
            continue
        new_text = _clean_edit_text(row.get('text') or '')
        if not new_text or new_text == original['text']:
            continue
        result, affected = _tool_result(session_id, 'replace_text', {
            'sec': sec,
            'para': para,
            'offset': 0,
            'length': original['length'],
            'newText': new_text
        })
        changed += 1
        for page in affected or result.get('affectedPages') or []:
            affected_pages.add(page)

    if changed:
        events.append(_sse({
            "type": "tool_result",
            "name": "rewrite_style",
            "result": {"changedParagraphs": changed},
            "affected": sorted(affected_pages) or [0]
        }))
        events.append(_sse({"type": "text", "delta": f"총 {changed}개 문단의 문체를 격식 있고 공식적인 표현으로 정리했습니다."}))
    else:
        events.append(_sse({"type": "tool_error", "name": "rewrite_style", "error": "AI가 변경 가능한 문단을 반환하지 않았습니다."}))
    events.append(_sse({"type": "done"}))
    return events


# ---- 고수준 결정적 툴 (에이전트가 호출) -------------------------------------
def _import_cache_pages(session_id: str, new_bytes: bytes) -> int:
    put = requests.put(f'{HWP_NODE_URL}/sessions/{session_id}/import',
                       data=new_bytes,
                       headers={**_node_headers(), 'Content-Type': 'application/octet-stream'},
                       timeout=40)
    put.raise_for_status()
    _cache_session_hwpx(session_id, new_bytes)
    return int((put.json() or {}).get('pageCount') or 5)


def _tool_fill_report(session_id: str, args: dict) -> tuple[dict, list]:
    import tempfile
    from pathlib import Path as _P
    from modules.codex_generator import CodexTextGenerator
    from modules.hwpx_generator import generate_template_model
    from modules.hwpx_builder import fill_template_inplace
    topic = (args.get('topic') or '').strip() or '보고서'
    model = generate_template_model(CodexTextGenerator(temperature=0.4), topic)
    out = _P(tempfile.gettempdir()) / f'tool_fill_{session_id}.hwpx'
    fill_template_inplace(model, out)
    pc = _import_cache_pages(session_id, out.read_bytes())
    aff = list(range(pc))
    return {"ok": True, "title": model.get('title'),
            "sections": [s['title'] for s in model.get('sections', [])],
            "affectedPages": aff}, aff


def _tool_set_document_font(session_id: str, args: dict) -> tuple[dict, list]:
    from modules.hwpx_builder import change_fonts_in_hwpx
    font = (args.get('fontName') or '').strip()
    if not font:
        return {"ok": False, "error": "fontName 이 필요합니다."}, []
    base = _get_cached_hwpx(session_id)
    if base is None:
        return {"ok": False, "error": "문서 캐시가 없어 글꼴을 바꿀 수 없습니다."}, []
    pc = _import_cache_pages(session_id, change_fonts_in_hwpx(base, font))
    aff = list(range(pc))
    return {"ok": True, "font": font, "affectedPages": aff}, aff


_FONT_REGIONS = {'title', 'toc', 'headings', 'body', 'all'}


def _tool_set_font_size(session_id: str, args: dict) -> tuple[dict, list]:
    from modules.hwpx_builder import set_font_size_in_hwpx
    region = (args.get('region') or 'all').strip().lower()
    if region not in _FONT_REGIONS:
        region = 'all'
    try:
        pt = int(args.get('sizePt'))
    except (TypeError, ValueError):
        return {"ok": False, "error": "sizePt(정수 pt)가 필요합니다."}, []
    if pt < 4 or pt > 120:
        return {"ok": False, "error": "sizePt 는 4~120 범위여야 합니다."}, []
    base = _get_cached_hwpx(session_id)
    if base is None:
        return {"ok": False, "error": "문서 캐시가 없어 글자 크기를 바꿀 수 없습니다."}, []
    pc = _import_cache_pages(session_id, set_font_size_in_hwpx(base, region, pt * 100))
    aff = list(range(pc))
    return {"ok": True, "region": region, "pt": pt, "affectedPages": aff}, aff


def _get_session_hwpx(session_id: str) -> bytes | None:
    """세션의 정상 hwpx: 캐시 우선, 없으면 Node export-hwpx 폴백."""
    data = _get_cached_hwpx(session_id)
    if data is not None:
        return data
    try:
        r = requests.get(f'{HWP_NODE_URL}/sessions/{session_id}/export-hwpx',
                         headers=_node_headers(), timeout=30)
        if r.ok and r.content:
            return r.content
    except Exception:
        pass
    return None


def _tool_read_document(session_id: str, args: dict) -> tuple[dict, list]:
    from modules.hwpx_builder import read_paragraphs_in_hwpx
    data = _get_session_hwpx(session_id)
    if data is None:
        return {"ok": False, "error": "문서를 읽을 수 없습니다."}, []
    paras = read_paragraphs_in_hwpx(data)
    for p in paras:
        if len(p.get("text") or "") > 300:
            p["text"] = p["text"][:300] + "…"
    return {"ok": True, "count": len(paras), "paragraphs": paras}, []


def _tool_edit_paragraphs(session_id: str, args: dict) -> tuple[dict, list]:
    from modules.hwpx_builder import edit_paragraphs_in_hwpx
    edits = args.get('edits') or []
    if not isinstance(edits, list) or not edits:
        return {"ok": False, "error": "edits 배열([{id, text}])이 필요합니다."}, []
    data = _get_session_hwpx(session_id)
    if data is None:
        return {"ok": False, "error": "문서를 읽을 수 없습니다."}, []
    new_bytes, results = edit_paragraphs_in_hwpx(data, edits)
    applied = sum(1 for r in results if r.get('ok'))
    if not applied:
        return {"ok": False, "results": results,
                "hint": "read_document 로 문단 id 를 다시 확인하세요."}, []
    pc = _import_cache_pages(session_id, new_bytes)
    aff = list(range(pc))
    return {"ok": True, "applied": applied, "results": results,
            "affectedPages": aff}, aff


def _tool_restructure_document(session_id: str, args: dict) -> tuple[dict, list]:
    """문서 구조 재구성: 섹션 수/제목/본문을 에이전트가 정의한 대로 양식 스타일로 재조립."""
    import tempfile
    from pathlib import Path as _P
    from modules.hwpx_builder import build_hwpx
    from modules.hwpx_generator import _today_kr, _clean_title, _clean_line
    title = (args.get('title') or '').strip()
    sections_in = args.get('sections') or []
    if not title or not isinstance(sections_in, list) or not sections_in:
        return {"ok": False, "error": "title 과 sections(1개 이상)가 필요합니다."}, []
    sections = []
    for s in sections_in:
        lines = []
        for ln in (s.get('lines') or []):
            if isinstance(ln, dict):
                # 마커는 별도 인자이므로 본문 텍스트의 선두 번호/마커는 제거(이중 표기 방지)
                lines.append((ln.get('marker') or '○', _clean_line(str(ln.get('text') or ''))))
            else:
                lines.append(('○', _clean_line(str(ln))))
        sections.append({'title': _clean_title(str(s.get('title') or '')), 'lines': lines})
    model = {
        'org': (args.get('org') or '').strip(),
        'title': title,
        'date': (args.get('date') or '').strip() or _today_kr(),
        'sections': sections,
        'appendix': [str(a) for a in (args.get('appendix') or [])],
    }
    out = _P(tempfile.gettempdir()) / f'tool_restructure_{session_id}.hwpx'
    build_hwpx(model, out)
    pc = _import_cache_pages(session_id, out.read_bytes())
    aff = list(range(pc))
    return {"ok": True, "title": title,
            "sections": [s['title'] for s in sections],
            "affectedPages": aff}, aff


def _tool_design_template(session_id: str, args: dict) -> tuple[dict, list]:
    """AI 가 디자인 스펙(스타일·구성)을 직접 설계해 템플릿을 raw OWPML 로 생성."""
    import tempfile
    from pathlib import Path as _P
    from modules.hwpx_builder import build_ai_design_hwpx
    from modules.hwpx_generator import _today_kr, _clean_title
    title = (args.get('title') or '').strip()
    sections = args.get('sections') or []
    if not title or not isinstance(sections, list) or not sections:
        return {"ok": False, "error": "title 과 sections(1개 이상)가 필요합니다."}, []
    design = dict(args)
    design.setdefault('date', _today_kr())
    # 빌더가 섹션 번호를 붙이므로 제목의 자체 번호는 제거(이중 번호 방지)
    design['sections'] = [{**s, 'title': _clean_title(str(s.get('title') or ''))}
                          for s in sections]
    out = _P(tempfile.gettempdir()) / f'tool_design_{session_id}.hwpx'
    build_ai_design_hwpx(design, out)
    pc = _import_cache_pages(session_id, out.read_bytes())
    aff = list(range(pc))
    return {"ok": True, "title": title,
            "sections": [str(s.get('title') or '') for s in sections],
            "style": design.get('style') or {}, "affectedPages": aff}, aff


_HIGHLEVEL_TOOLS = {
    'fill_report_template': _tool_fill_report,
    'set_document_font': _tool_set_document_font,
    'set_font_size': _tool_set_font_size,
    'read_document': _tool_read_document,
    'edit_paragraphs': _tool_edit_paragraphs,
    'restructure_document': _tool_restructure_document,
    'design_template': _tool_design_template,
}


def _tool_result(session_id: str, name: str, args: dict) -> tuple[dict, list]:
    if name in _HIGHLEVEL_TOOLS:
        return _HIGHLEVEL_TOOLS[name](session_id, args)
    if name == 'get_document_structure':
        return _node_get_json(f'/sessions/{session_id}/structure'), []
    if name == 'get_paragraph_text':
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": "get_paragraph_text", **args})
        return result.get('data') or result, []
    if name == 'search_text':
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": "search_text", **args})
        data = result.get('data') or result
        if isinstance(data, dict):
            matches = data.get('matches') or []
            if matches:
                data['firstMatch'] = matches[0]
        return data, []
    if name == 'search_deep':
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": "search_deep", **args})
        data = result.get('data') or result
        if isinstance(data, dict):
            matches = data.get('matches') or []
            if matches:
                data['firstMatch'] = matches[0]
        return data, []
    if name == 'get_table_info':
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": "get_table_info", **args})
        return result.get('data') or result, []
    if name == 'get_text_in_cell':
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": "get_text_in_cell", **args})
        return result.get('data') or result, []
    if name == 'get_hwp_function_catalog':
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": "get_hwp_function_catalog", **args})
        return result.get('data') or result, []
    if name in WRITE_TOOLS:
        result = _node_post_json(f'/sessions/{session_id}/ops', {"kind": name, **args})
        return result, result.get('affectedPages') or []
    raise RuntimeError(f'Unknown tool: {name}')


def _verify_write(session_id: str, name: str, args: dict, result: dict) -> dict:
    """Read evidence that a write actually applied. Returns a compact report attached to the function response."""
    verify: dict = {"tool": name}
    try:
        if name == 'search_replace_all':
            replaced = int(((result or {}).get('data') or {}).get('replacedCount') or 0)
            verify['replacedCount'] = replaced
            verify['ok'] = replaced > 0
            return verify
        if name in ('replace_text', 'insert_text', 'delete_text', 'split_paragraph'):
            sec, para = args.get('sec'), args.get('para')
            if sec is None or para is None:
                return verify
            pdata, _ = _tool_result(session_id, 'get_paragraph_text', {'sec': sec, 'para': para})
            paragraph_text = (pdata or {}).get('text') or ''
            verify['paragraphAfter'] = paragraph_text[:240]
            expected = args.get('newText') or args.get('text') or ''
            if expected:
                verify['expectedFound'] = expected in paragraph_text
                verify['ok'] = expected in paragraph_text
            else:
                verify['ok'] = True
            return verify
        if name == 'set_field':
            verify['fieldName'] = args.get('fieldName')
            verify['expectedValue'] = args.get('value')
            try:
                struct = _node_get_json(f'/sessions/{session_id}/structure') or {}
                fields = struct.get('fields') or []
                hit = next((f for f in fields if f.get('name') == args.get('fieldName')), None)
                if hit is not None:
                    actual = hit.get('value')
                    verify['actualValue'] = actual
                    verify['ok'] = (actual or '').strip() == (args.get('value') or '').strip()
            except Exception:
                pass
            return verify
        if name in ('insert_text_in_cell', 'delete_text_in_cell'):
            cell_args = {k: args.get(k) for k in ('sec', 'para', 'controlIdx', 'cellIdx', 'cellPara') if args.get(k) is not None}
            try:
                cdata, _ = _tool_result(session_id, 'get_text_in_cell', cell_args)
                cell_text = (cdata or {}).get('text') or ''
                verify['cellAfter'] = cell_text[:240]
                expected = args.get('text') or ''
                if expected:
                    verify['expectedFound'] = expected in cell_text
                    verify['ok'] = expected in cell_text
                else:
                    verify['ok'] = True
            except Exception:
                pass
            return verify
        if name in ('fill_report_template', 'set_document_font', 'set_font_size', 'edit_paragraphs', 'restructure_document', 'design_template'):
            verify['ok'] = bool((result or {}).get('ok'))
            return verify
        if name in ('set_char_format', 'set_para_format',
                    'set_char_format_in_cell', 'set_para_format_in_cell',
                    'set_table_properties', 'set_cell_properties'):
            # /ops 성공 응답은 {affectedPages, data} 형태로 'ok' 필드가 없다.
            # 여기까지 도달했다는 것은 op 가 예외 없이 적용됐다는 뜻(실패 시 _tool_result 가 422→예외).
            # 따라서 'ok' 부재를 실패로 보지 말고, 에러가 없으면 적용된 것으로 판단한다.
            r = result if isinstance(result, dict) else {}
            verify['ok'] = ('error' not in r)
            if 'affectedPages' in r:
                verify['affectedPages'] = r.get('affectedPages')
            return verify
        if name == 'create_table':
            data = (result or {}).get('data') or {}
            verify['paraIdx'] = data.get('paraIdx')
            verify['controlIdx'] = data.get('controlIdx')
            verify['ok'] = data.get('controlIdx') is not None
            return verify
    except Exception as exc:
        verify['verifyError'] = str(exc)[:200]
    return verify


def _short_match(match: dict) -> str:
    if not isinstance(match, dict):
        return ''
    keys = ('sec', 'para', 'offset', 'length', 'type', 'fieldName', 'cellIdx', 'controlIdx')
    parts = [f"{k}={match[k]}" for k in keys if k in match]
    return ', '.join(parts)


def _format_running_memory(work_memory: dict) -> str:
    if not work_memory:
        return ''
    lines: list[str] = []
    findings = work_memory.get('findings') or {}
    if findings:
        lines.append('확인된 위치:')
        for query, match in list(findings.items())[-6:]:
            short = _short_match(match)
            if short:
                lines.append(f"- {query!r} → {short}")
    writes = work_memory.get('writes') or []
    if writes:
        lines.append('최근 편집:')
        for entry in writes[-6:]:
            tool = entry.get('tool')
            target = entry.get('target') or {}
            tgt = ', '.join(f"{k}={v}" for k, v in target.items() if v not in (None, ''))
            verify = entry.get('verify') or {}
            ok = verify.get('ok')
            mark = '✓' if ok is True else ('✗' if ok is False else '·')
            note = ''
            if 'replacedCount' in verify:
                note = f" replaced={verify['replacedCount']}"
            elif verify.get('expectedFound') is False and verify.get('paragraphAfter'):
                note = f" 단락='{verify['paragraphAfter'][:80]}…'"
            lines.append(f"- {mark} {tool}({tgt}){note}")
    paragraphs = work_memory.get('paragraphs') or {}
    if paragraphs:
        lines.append('읽은 단락:')
        for key, text in list(paragraphs.items())[-3:]:
            lines.append(f"- {key} → '{(text or '')[:80]}…'")
    return '\n'.join(lines)


def _update_work_memory(work_memory: dict, name: str, args: dict, result: dict, verify: Optional[dict]) -> None:
    findings = work_memory.setdefault('findings', {})
    paragraphs = work_memory.setdefault('paragraphs', {})
    writes = work_memory.setdefault('writes', [])

    if name in ('search_text', 'search_deep'):
        first = None
        if isinstance(result, dict):
            matches = result.get('matches') or []
            if matches:
                first = matches[0]
        query = args.get('query') or ''
        if first and query:
            findings[query] = first
    elif name == 'get_paragraph_text':
        sec, para = args.get('sec'), args.get('para')
        text = (result or {}).get('text') if isinstance(result, dict) else None
        if sec is not None and para is not None and isinstance(text, str):
            paragraphs[f"sec={sec},para={para}"] = text[:240]
    elif name in WRITE_TOOLS:
        target = {k: args.get(k) for k in ('sec', 'para', 'offset', 'length', 'fieldName', 'controlIdx', 'cellIdx', 'query') if args.get(k) not in (None, '')}
        writes.append({
            'tool': name,
            'target': target,
            'expected': args.get('newText') or args.get('value') or args.get('text') or args.get('replacement'),
            'verify': verify or {},
        })
        # cap length
        if len(writes) > 20:
            del writes[:-20]


@router.post('/sessions')
async def upload_hwp_session(file: UploadFile = File(...)):
    """
    HWP/HWPX 파일 업로드 → Node 세션 생성
    
    Returns:
        {
            "sessionId": "session-uuid",
            "pageCount": 10,
            "fileName": "document.hwp"
        }
    """
    try:
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail='파일을 업로드해주세요.')
        
        # 파일 타입 검증
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {'.hwp', '.hwpx'}:
            raise HTTPException(status_code=400, detail='HWP 또는 HWPX 파일만 지원합니다.')
        
        # Node 서버로 업로드
        url = f'{HWP_NODE_URL}/sessions'
        files = {'file': (file.filename, await file.read(), 'application/octet-stream')}
        
        resp = requests.post(
            url,
            files=files,
            headers=_node_headers(),
            timeout=30
        )
        resp.raise_for_status()
        
        result = resp.json()
        return {
            'success': True,
            'sessionId': result.get('sessionId'),
            'pageCount': result.get('pageCount'),
            'fileName': file.filename
        }
    
    except requests.RequestException as e:
        print(f'[HWP v2] Node 서버 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')
    except Exception as e:
        print(f'[HWP v2] 업로드 오류: {e}')
        raise HTTPException(status_code=500, detail=str(e))


BASE_FORM_HWPX = Path(__file__).resolve().parent / 'assets' / 'hwpx' / 'base.hwpx'

# 세션별 '정상 hwpx' 캐시. @rhwp/core 의 exportHwpx 가 표를 손실하므로,
# 우리가 import 한 마지막 정상 hwpx 바이트를 보관해 폰트 변경 등 XML 작업에 사용한다.
import tempfile as _tempfile
_SESSION_HWPX_DIR = Path(_tempfile.gettempdir()) / 'hwp_session_cache'


def _cache_session_hwpx(session_id: str, data: bytes) -> None:
    try:
        _SESSION_HWPX_DIR.mkdir(parents=True, exist_ok=True)
        (_SESSION_HWPX_DIR / f'{session_id}.hwpx').write_bytes(data)
    except Exception as e:
        print(f'[HWP v2] hwpx 캐시 저장 실패: {e}')


def _get_cached_hwpx(session_id: str) -> Optional[bytes]:
    try:
        p = _SESSION_HWPX_DIR / f'{session_id}.hwpx'
        return p.read_bytes() if p.exists() else None
    except Exception:
        return None


@router.post('/sessions/blank')
async def create_blank_hwp_session():
    """'빈 문서' 세션 생성.

    기본 보고서 양식(assets/hwpx/base.hwpx)을 시드해서 시작한다. 채팅 에이전트가
    이 양식의 슬롯(제목/목차/Ⅰ~Ⅴ/□○―※)을 채우게 된다. 양식 파일이 없으면
    진짜 빈 HWP 로 폴백한다.
    """
    try:
        if BASE_FORM_HWPX.exists():
            url = f'{HWP_NODE_URL}/sessions'
            base_bytes = BASE_FORM_HWPX.read_bytes()
            files = {'file': ('기본 보고서 양식.hwpx', base_bytes, 'application/octet-stream')}
            resp = requests.post(url, files=files, headers=_node_headers(), timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if result.get('sessionId'):
                _cache_session_hwpx(result['sessionId'], base_bytes)  # 정상 hwpx 캐시
            return {
                'success': True,
                'sessionId': result.get('sessionId'),
                'pageCount': result.get('pageCount') or 1,
                'fileName': '기본 보고서 양식.hwpx',
                'seeded': True,
            }
        # 폴백: 진짜 빈 문서
        url = f'{HWP_NODE_URL}/sessions/blank'
        resp = requests.post(url, headers=_node_headers(), timeout=20)
        resp.raise_for_status()
        result = resp.json()
        return {
            'success': True,
            'sessionId': result.get('sessionId'),
            'pageCount': result.get('pageCount') or 1,
            'fileName': result.get('fileName') or '새 문서.hwp',
            'seeded': False,
        }
    except requests.RequestException as e:
        print(f'[HWP v2] 빈 문서 생성 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.put('/sessions/{session_id}/import')
async def import_document(session_id: str, request: Request):
    """브라우저 HOP식 편집기에서 내보낸 HWP bytes로 기존 세션을 교체한다."""
    try:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=400, detail='HWP 파일 본문이 비어 있습니다.')

        url = f'{HWP_NODE_URL}/sessions/{session_id}/import'
        resp = requests.put(
            url,
            data=content,
            headers={
                **_node_headers(),
                'Content-Type': request.headers.get('content-type') or 'application/octet-stream',
            },
            timeout=30,
        )

        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        if resp.status_code >= 400:
            detail = 'Node 서버에서 HWP 가져오기에 실패했습니다.'
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get('error'):
                    detail = str(body.get('error'))
            except Exception:
                body_text = (resp.text or '').strip()
                if body_text:
                    detail = body_text[:300]
            raise HTTPException(status_code=resp.status_code, detail=detail)
        return resp.json()
    except HTTPException:
        raise
    except requests.RequestException as e:
        print(f'[HWP v2] 가져오기 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.delete('/sessions/{session_id}')
async def delete_hwp_session(session_id: str):
    """세션 삭제"""
    try:
        url = f'{HWP_NODE_URL}/sessions/{session_id}'
        resp = requests.delete(
            url,
            headers=_node_headers(),
            timeout=10
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')

        if resp.status_code >= 400:
            detail = 'Node 서버에서 세션 삭제에 실패했습니다.'
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get('error'):
                    detail = str(body.get('error'))
            except Exception:
                body_text = (resp.text or '').strip()
                if body_text:
                    detail = body_text[:300]
            raise HTTPException(status_code=resp.status_code, detail=detail)
        return {'success': True}
    
    except requests.RequestException as e:
        print(f'[HWP v2] 세션 삭제 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.get('/sessions/{session_id}/pages/{page_index}')
async def render_page(session_id: str, page_index: int):
    """
    문서 페이지를 SVG로 렌더링
    
    Returns: SVG 이미지 (image/svg+xml)
    """
    try:
        if page_index < 0:
            raise HTTPException(status_code=400, detail='페이지 인덱스가 유효하지 않습니다.')
        
        url = f'{HWP_NODE_URL}/sessions/{session_id}/pages/{page_index}'
        resp = requests.get(
            url,
            headers=_node_headers(),
            timeout=15
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션 또는 페이지를 찾을 수 없습니다.')
        
        resp.raise_for_status()
        
        return StreamingResponse(
            iter([resp.content]),
            media_type='image/svg+xml; charset=utf-8'
        )
    
    except requests.RequestException as e:
        print(f'[HWP v2] 렌더링 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.get('/sessions/{session_id}/structure')
async def get_structure(session_id: str):
    """AI 편집용 문서 구조 조회"""
    try:
        return _node_get_json(f'/sessions/{session_id}/structure')
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')
    except requests.RequestException:
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.get('/sessions/{session_id}/document')
async def get_web_document(session_id: str):
    """웹 에디터용 전체 문서 모델 조회"""
    try:
        return _node_get_json(f'/sessions/{session_id}/document')
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')
    except requests.RequestException:
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


def _forward_node_overlay_request(session_id: str, path: str, body: dict, timeout: int = 15) -> dict:
    try:
        resp = requests.post(
            f'{HWP_NODE_URL}/sessions/{session_id}/{path}',
            json=body,
            headers=_node_headers(),
            timeout=timeout,
        )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        if resp.status_code == 400:
            detail = resp.json().get('error', '요청이 유효하지 않습니다.')
            raise HTTPException(status_code=400, detail=detail)
        if resp.status_code == 422:
            detail = resp.json().get('error', 'HWP overlay API 실행 실패')
            raise HTTPException(status_code=422, detail=detail)
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except requests.RequestException as e:
        print(f'[HWP v2] overlay API 오류({path}): {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.post('/sessions/{session_id}/page-info')
async def get_page_info(session_id: str, request: Request):
    """overlay 좌표 계산용 페이지 정보 조회"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='JSON body required')
    return _forward_node_overlay_request(session_id, 'page-info', body)


@router.post('/sessions/{session_id}/hit-test')
async def hit_test(session_id: str, request: Request):
    """페이지 좌표를 HWP 문서 위치로 변환"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='JSON body required')
    return _forward_node_overlay_request(session_id, 'hit-test', body)


@router.post('/sessions/{session_id}/cursor-rect')
async def get_cursor_rect(session_id: str, request: Request):
    """HWP 문서 위치의 caret rectangle 조회"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='JSON body required')
    return _forward_node_overlay_request(session_id, 'cursor-rect', body)


@router.post('/sessions/{session_id}/selection-rects')
async def get_selection_rects(session_id: str, request: Request):
    """HWP 선택 범위의 overlay rectangle 조회"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='JSON body required')
    return _forward_node_overlay_request(session_id, 'selection-rects', body)


@router.post('/sessions/{session_id}/edit')
async def edit_document(session_id: str, request: Request):
    """
    문서 편집 연산 적용
    
    Request body:
        {
            "kind": "insert_text",
            "sec": 0,
            "para": 0,
            "offset": 0,
            "text": "추가될 텍스트"
        }
    
    Returns:
        {
            "affectedPages": [0, 1],
            "data": null or any
        }
    """
    try:
        body = await request.json()
        
        url = f'{HWP_NODE_URL}/sessions/{session_id}/ops'
        resp = requests.post(
            url,
            json=body,
            headers=_node_headers(),
            timeout=15
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        elif resp.status_code == 422:
            detail = resp.json().get('error', '연산 실행 실패')
            raise HTTPException(status_code=422, detail=detail)
        
        resp.raise_for_status()
        return resp.json()
    
    except requests.RequestException as e:
        print(f'[HWP v2] 편집 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')
    except Exception as e:
        print(f'[HWP v2] 요청 처리 오류: {e}')
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/sessions/{session_id}/chat')
async def hwp_chat(session_id: str, request: Request):
    """Gemini function calling 기반 HWP 편집 SSE."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='JSON body required')

    user_message = (data.get('message') or '').strip()
    history = data.get('history') or []
    if not user_message:
        raise HTTPException(status_code=400, detail='message is required')

    def generate():
        try:
            # 가로채기 제거: 위 요청들은 이제 에이전트가 고수준 도구
            # (fill_report_template / set_document_font / set_font_size)로 직접 처리한다.
            reference_draft_events = _try_reference_draft(session_id, user_message)
            if reference_draft_events:
                for event in reference_draft_events:
                    yield event
                return

            style_events = _try_style_rewrite(session_id, user_message)
            if style_events:
                for event in style_events:
                    yield event
                return

            profile_events = _try_fill_profile_fields(session_id, user_message)
            if profile_events:
                for event in profile_events:
                    yield event
                return

            fill_events = _try_fill_field(session_id, user_message)
            if fill_events:
                for event in fill_events:
                    yield event
                return

            direct_events = _try_direct_replace(session_id, user_message, history)
            if direct_events:
                for event in direct_events:
                    yield event
                return

            structure = _node_get_json(f'/sessions/{session_id}/structure')
            system_prompt = _build_system_prompt(structure)
            contents = []
            for item in history[-12:]:
                role = 'user' if item.get('role') == 'user' else 'model'
                text = item.get('text') or item.get('content') or ''
                if text:
                    contents.append({"role": role, "parts": [{"text": text}]})
            contents.append({"role": "user", "parts": [{"text": user_message}]})

            generator = CodexTextGenerator(temperature=0.2)
            tools = _tool_declarations()
            max_turns = 12
            recent_calls: list[str] = []  # 동일 호출 반복 감지

            forced_tool_retries = 0
            write_count = 0
            last_read_tool: Optional[str] = None
            work_memory: dict = {'findings': {}, 'paragraphs': {}, 'writes': []}
            verify_failures = 0
            for _ in range(max_turns):
                saw_call = False
                turn_text = ''
                for event in generator.generate_with_tools(contents, tools, system_prompt, stream=True):
                    if event.get('type') == 'text':
                        text = event.get('text') or ''
                        if text:
                            turn_text += text
                            yield _sse({"type": "text", "delta": text})
                    elif event.get('type') == 'function_call':
                        name = event.get('name')
                        args = event.get('args') or {}
                        saw_call = True
                        fc = {"name": name, "args": args}

                        call_sig = f"{name}|{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                        is_repeat = call_sig in recent_calls[-3:]
                        recent_calls.append(call_sig)

                        yield _sse({"type": "status", "phase": "tool_plan", "name": name, "text": _tool_status_text(name, args)})
                        yield _sse({"type": "tool_start", "name": name, "args": args})

                        if is_repeat:
                            err = "repeated_call: 동일한 호출이 반복되었습니다. 다른 변형(축약, 띄어쓰기 변경, 라벨 제외, 핵심 단어만)으로 재시도하세요."
                            result = {"error": "repeated_call", "hint": err}
                            yield _sse({"type": "tool_error", "name": name, "error": err})
                        else:
                            try:
                                result, affected = _tool_result(session_id, name, args)
                                verify_info: Optional[dict] = None
                                if name in WRITE_TOOLS:
                                    if name == 'search_replace_all':
                                        replaced = int((result.get('data') or {}).get('replacedCount') or 0)
                                        if replaced > 0:
                                            write_count += 1
                                    else:
                                        write_count += 1
                                    # Plan→Execute→Verify: read evidence right after each write.
                                    verify_info = _verify_write(session_id, name, args, result)
                                    if isinstance(result, dict):
                                        result = {**result, "_verify": verify_info}
                                    if verify_info.get('ok') is False:
                                        verify_failures += 1
                                        yield _sse({
                                            "type": "status", "phase": "verify_failed", "name": name,
                                            "text": f"{name} 적용 확인 실패 — 재시도 필요"
                                        })
                                    elif verify_info.get('ok') is True:
                                        yield _sse({
                                            "type": "status", "phase": "verify_ok", "name": name,
                                            "text": f"{name} 적용 확인됨"
                                        })
                                elif name in READ_TOOLS:
                                    last_read_tool = name
                                # Tool result enrichment: 0건일 때 힌트 주입
                                if isinstance(result, dict):
                                    if name == 'search_text':
                                        matches = result.get('matches') or []
                                        if not matches:
                                            result = {**result, "hint": "0건 발견. 양식 라벨/필드/표 셀일 수 있으니 같은 query로 search_deep를 호출하세요. 그래도 없으면 띄어쓰기 변형이나 다른 라벨명으로 재시도하세요."}
                                    elif name == 'search_deep':
                                        matches = result.get('matches') or []
                                        if matches:
                                            result = {**result, "hint": "검색 결과 type에 따라 field는 set_field, cell은 insert_text_in_cell, paragraph는 get_paragraph_text 후 insert/replace를 호출하세요."}
                                    elif name == 'search_replace_all':
                                        replaced = int((result.get('data') or {}).get('replacedCount') or 0)
                                        if replaced == 0:
                                            result = {**result, "hint": "0건 치환됨. 검색어 변형으로 재시도하거나 search_text → replace_text 조합을 사용하세요."}

                                # Update running work memory with this turn's evidence.
                                _update_work_memory(
                                    work_memory,
                                    name,
                                    args,
                                    result if isinstance(result, dict) else {},
                                    verify_info,
                                )
                                memory_snippet = _format_running_memory(work_memory)
                                if memory_snippet and isinstance(result, dict):
                                    result = {**result, "_runningMemory": memory_snippet}
                                yield _sse({"type": "tool_result", "name": name, "result": result, "affected": affected})
                            except Exception as e:
                                result = {"error": str(e)}
                                yield _sse({"type": "tool_error", "name": name, "error": str(e)})

                        contents.append({"role": "model", "parts": [{"functionCall": fc}]})
                        contents.append({
                            "role": "function",
                            "parts": [{"functionResponse": {"name": name, "response": result}}]
                        })

                if not saw_call:
                    last_write_failed = bool(work_memory.get('writes')) and (work_memory['writes'][-1].get('verify') or {}).get('ok') is False
                    needs_retry_for_edit = _looks_like_edit_request(user_message) and write_count == 0
                    needs_retry_for_verify = last_write_failed and forced_tool_retries < 3

                    if (needs_retry_for_edit or needs_retry_for_verify) and forced_tool_retries < 4:
                        forced_tool_retries += 1
                        memory_snippet = _format_running_memory(work_memory)
                        if needs_retry_for_verify:
                            yield _sse({
                                "type": "status",
                                "phase": "continue",
                                "name": "agent",
                                "text": "직전 편집의 검증이 실패해 다른 좌표/도구로 재시도합니다."
                            })
                            retry_hint = (
                                "직전 쓰기 도구의 _verify.ok=false 입니다. 같은 인자로 다시 호출하지 말고, "
                                "다음 중 하나로 전략을 바꾸세요: "
                                "(1) 다른 좌표(다른 sec/para/offset 또는 다른 cellIdx) 시도, "
                                "(2) 도구 변경(replace_text→search_replace_all, insert_text→insert_text_in_cell, set_field 등), "
                                "(3) 검색어/라벨 변형 후 search_deep로 위치 재확인. "
                                "지금 바로 쓰기 도구를 한 번 더 호출하세요."
                            )
                        else:
                            yield _sse({
                                "type": "status",
                                "phase": "continue",
                                "name": "agent",
                                "text": "실제 편집 도구 호출이 없어 다음 단계 실행을 다시 요청합니다."
                            })
                            retry_hint = (
                                "아직 문서에 실제 변경이 적용되지 않았습니다. "
                                "설명 문장으로 끝내지 말고 반드시 쓰기 도구를 호출하세요. "
                                "이미 search_deep/search_text/get_paragraph_text로 위치를 확인했다면 그 결과의 sec/para/offset을 사용해 "
                                "insert_text, replace_text, set_field, insert_text_in_cell 중 하나를 지금 호출하세요. "
                                "단락에 '성 명 : ____'처럼 라벨과 빈칸이 있으면 라벨 뒤 빈칸을 replace_text로 교체하세요. "
                                f"직전 읽기 도구: {last_read_tool or '없음'}."
                            )
                        if turn_text.strip():
                            contents.append({"role": "model", "parts": [{"text": turn_text}]})
                        memory_block = f"\n\n[작업 메모]\n{memory_snippet}\n[메모 끝]" if memory_snippet else ''
                        contents.append({
                            "role": "user",
                            "parts": [{"text": retry_hint + memory_block}]
                        })
                        continue
                    yield _sse({"type": "done"})
                    return

            yield _sse({"type": "tool_error", "name": "agent", "error": f"도구 호출 횟수 제한({max_turns})에 도달했습니다."})
            yield _sse({"type": "done"})
        except Exception as e:
            yield _sse({"type": "error", "error": str(e)})

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@router.get('/sessions/{session_id}/export')
async def export_document(session_id: str):
    """
    현재 세션의 HWP 파일 다운로드
    
    Returns: HWP 파일 (application/octet-stream)
    """
    try:
        url = f'{HWP_NODE_URL}/sessions/{session_id}/export'
        resp = requests.get(
            url,
            headers=_node_headers(),
            timeout=30,
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')

        if resp.status_code >= 400:
            detail = 'Node 서버에서 HWP 내보내기에 실패했습니다.'
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get('error'):
                    detail = str(body.get('error'))
            except Exception:
                body_text = (resp.text or '').strip()
                if body_text:
                    detail = body_text[:300]
            raise HTTPException(status_code=resp.status_code, detail=detail)
        
        # Content-Disposition 헤더에서 파일명 추출
        disp = resp.headers.get('Content-Disposition', '')
        filename = _filename_from_content_disposition(disp)
        content = resp.content or b''
        if len(content) == 0:
            raise HTTPException(status_code=502, detail='Node 서버가 빈 HWP 파일을 반환했습니다.')
        
        return StreamingResponse(
            iter([content]),
            media_type='application/octet-stream',
            headers={
                'Content-Disposition': _content_disposition_attachment(filename),
                'Content-Length': str(len(content)),
            }
        )
    
    except HTTPException:
        raise
    except requests.RequestException as e:
        print(f'[HWP v2] 내보내기 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.get('/health')
async def health_check():
    """Node 서버 상태 확인"""
    try:
        url = f'{HWP_NODE_URL}/health'
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except:
        raise HTTPException(status_code=503, detail='Node 서버 연결 불가')


@router.get('/version')
async def version_info():
    """Node 서버 버전 정보"""
    try:
        url = f'{HWP_NODE_URL}/version'
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except:
        raise HTTPException(status_code=503, detail='Node 서버 연결 불가')
