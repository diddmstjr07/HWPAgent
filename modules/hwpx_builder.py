#!/usr/bin/env python3
"""
HWPX 빌더 — assets/hwpx/base.hwpx(=example.hwpx) '하나만 보고' raw OWPML 조립.

서식(스타일)은 base.hwpx/Contents/header.xml 을 그대로 사용하고,
본문 section0.xml 은 base 에서 추출한 조각(표지/섹션헤더/□○―※)으로 새로 짠다.
섹션·항목·목차 개수는 내용에 맞춰 가변. linesegarray 는 제거(한글이 재계산).

content 모델:
{
  "org":   "브라더 공기관",
  "title": "보고서 제목",
  "date":  "2026. 6. 1.",
  "sections": [
     {"title": "추진 배경",
      "lines": [["□","..."], ["○","..."], ["―","..."], ["※","..."]]},
     ...
  ],
  "appendix": ["붙임 1. ...", ...]   # 선택; 없으면 붙임/참고 미출력
}
"""
from __future__ import annotations
import re, copy, zipfile, shutil
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

BASE_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "hwpx" / "base.hwpx"

P = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app", "hp": P,
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf/",
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}
for _k, _v in NS.items():
    ET.register_namespace(_k, _v)
def q(t: str) -> str: return f"{{{P}}}{t}"

ROMAN = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ",
         "Ⅺ", "Ⅻ"]
MARKERS = {"□", "○", "―", "※"}

# base.hwpx 고정 양식의 조각 위치(최상위 문단 인덱스)
PREAMBLE_END = 22
IDX_HEADER, IDX_SQ, IDX_OC, IDX_DASH, IDX_NOTE, IDX_BLANK = 22, 23, 24, 25, 44, 26


def _nonempty_t(p):
    return [t for t in p.iter(q("t")) if (t.text or "").strip()]


def _set_marker(tnode, text: str):
    m = re.match(r"^(\s*[□○―※]\s*)", tnode.text or "")
    tnode.text = (m.group(1) if m else "") + text


def _strip_linesegs(el):
    for parent in el.iter():
        for child in list(parent):
            if child.tag == q("linesegarray"):
                parent.remove(child)


def _first_t(run):
    return run.find(q("t"))


def _rebuild_toc(toc_para, sections, appendix):
    """목차 셀 내부 문단을 섹션 수에 맞게 재구성."""
    cell = toc_para.find(".//" + q("subList"))
    if cell is None:
        return
    inner = cell.findall(q("p"))
    if not inner:
        return
    entry_frag = copy.deepcopy(inner[0])              # 'Ⅰ' + '. 개요' 형태
    # 붙임/참고 등 기존 부록 문단(숫자 항목 5개 이후)을 부록 프래그먼트로 보존
    appendix_frag = inner[5] if len(inner) > 5 else None

    for c in list(cell):
        if c.tag == q("p"):
            cell.remove(c)

    for i, sec in enumerate(sections):
        e = copy.deepcopy(entry_frag)
        runs = e.findall(q("run"))
        if runs:
            t0 = _first_t(runs[0])
            if t0 is not None:
                t0.text = ROMAN[i] if i < len(ROMAN) else str(i + 1)
        if len(runs) > 1:
            t1 = _first_t(runs[1])
            if t1 is not None:
                t1.text = ". " + sec["title"]
        cell.append(e)

    for item in (appendix or []):
        if appendix_frag is None:
            break
        e = copy.deepcopy(appendix_frag)
        t0 = _first_t(e.findall(q("run"))[0]) if e.findall(q("run")) else None
        if t0 is not None:
            t0.text = " " + item
        cell.append(e)


def build_section_xml(model: dict[str, Any], base_section_xml: str) -> str:
    root = ET.fromstring(base_section_xml)
    paras = root.findall(q("p"))

    frag = {
        "header": copy.deepcopy(paras[IDX_HEADER]),
        "□": copy.deepcopy(paras[IDX_SQ]),
        "○": copy.deepcopy(paras[IDX_OC]),
        "―": copy.deepcopy(paras[IDX_DASH]),
        "※": copy.deepcopy(paras[IDX_NOTE]),
        "blank": copy.deepcopy(paras[IDX_BLANK]),
    }

    org = model.get("org", "")
    title = model.get("title", "")
    date = model.get("date", "")
    sections = model.get("sections", [])
    appendix = model.get("appendix", [])

    # 표지/제목/날짜 치환
    def t_set(p, pairs):
        ne = _nonempty_t(p)
        for i, v in pairs:
            if v is not None and i < len(ne):
                ne[i].text = v
    if org or title:
        t_set(paras[5], [(0, org or None), (1, title or None)])
    if date:
        t_set(paras[11], [(0, date)])
    if title:
        t_set(paras[21], [(0, title)])

    # 목차 재구성
    _rebuild_toc(paras[20], sections, appendix)

    # 본문 = 표지(0..21) + 섹션
    new_children = [copy.deepcopy(paras[i]) for i in range(PREAMBLE_END)]
    for si, sec in enumerate(sections):
        if si > 0:
            new_children.append(copy.deepcopy(frag["blank"]))
        h = copy.deepcopy(frag["header"])
        ne = _nonempty_t(h)
        if len(ne) >= 2:
            ne[0].text = ROMAN[si] if si < len(ROMAN) else str(si + 1)
            ne[-1].text = " " + sec.get("title", "")
        new_children.append(h)
        for line in sec.get("lines", []):
            marker, text = (line[0], line[1]) if isinstance(line, (list, tuple)) else ("○", str(line))
            if marker not in MARKERS:
                marker = "○"
            f = copy.deepcopy(frag[marker])
            nf = _nonempty_t(f)
            if nf:
                if marker == "□":
                    nf[-1].text = text          # ' □ ' 마커 런 유지
                else:
                    _set_marker(nf[0], text)
            new_children.append(f)

    for c in list(root):
        if c.tag == q("p"):
            root.remove(c)
    for c in new_children:
        root.append(c)

    _strip_linesegs(root)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + body


def build_hwpx(model: dict[str, Any], out_path: str | Path,
               template_path: str | Path = BASE_TEMPLATE,
               workdir: str | Path | None = None) -> Path:
    """content 모델 → hwpx 파일 생성. 생성 경로 반환."""
    out_path = Path(out_path)
    template_path = Path(template_path)
    work = Path(workdir) if workdir else out_path.parent / f".hwpx_build_{out_path.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    ext = work / "ext"
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(ext)
            base_section = z.read("Contents/section0.xml").decode("utf-8")

        new_section = build_section_xml(model, base_section)
        ET.fromstring(new_section)  # well-formed 검증
        (ext / "Contents/section0.xml").write_text(new_section, encoding="utf-8")

        files = [p for p in ext.rglob("*") if p.is_file()]
        files.sort(key=lambda p: (p.name != "mimetype",))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        with zipfile.ZipFile(out_path, "w") as z:
            for f in files:
                arc = str(f.relative_to(ext))
                z.write(f, arc,
                        zipfile.ZIP_STORED if arc == "mimetype" else zipfile.ZIP_DEFLATED)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 산출물 무결성 간단 검증
    with zipfile.ZipFile(out_path) as z:
        assert z.infolist()[0].filename == "mimetype"
        assert z.read("mimetype") == b"application/hwp+zip"
    return out_path


# =====================================================================
# 구조 보존 in-place 채움 — 양식의 고정 슬롯 텍스트만 교체(새 문서 X)
# =====================================================================
# base.hwpx 고정 양식의 슬롯 위치(최상위 문단 인덱스). 섹션은 정확히 4개(Ⅰ~Ⅳ).
INPLACE_TITLE = 5     # 표지 제목표 (org, title)
INPLACE_DATE = 11
INPLACE_DOCTITLE = 21  # '제 목'
INPLACE_TOC = 20
# (헤더문단, [본문 슬롯 문단들])
INPLACE_SECTIONS = [
    (22, [23, 24, 25]),
    (27, list(range(28, 40))),
    (40, list(range(41, 53))),
    (54, [55, 56, 57, 58]),
]


def _set_body_slot(p, text: str):
    ne = _nonempty_t(p)
    if not ne:
        return
    if len(ne) >= 2 and re.fullmatch(r"\s*[□○―※]\s*", ne[0].text or ""):
        ne[-1].text = text            # ' □ ' 마커 런 유지, 본문 런만 교체
    else:
        _set_marker(ne[0], text)      # '  ○ …' 마커/들여쓰기 유지


def _package_section(new_section_xml: str, out_path, template_path) -> Path:
    out_path = Path(out_path)
    template_path = Path(template_path)
    work = out_path.parent / f".hwpx_pkg_{out_path.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    ext = work / "ext"
    try:
        with zipfile.ZipFile(template_path) as z:
            z.extractall(ext)
        ET.fromstring(new_section_xml)  # well-formed 검증
        (ext / "Contents/section0.xml").write_text(new_section_xml, encoding="utf-8")
        files = [p for p in ext.rglob("*") if p.is_file()]
        files.sort(key=lambda p: (p.name != "mimetype",))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        with zipfile.ZipFile(out_path, "w") as z:
            for f in files:
                arc = str(f.relative_to(ext))
                z.write(f, arc,
                        zipfile.ZIP_STORED if arc == "mimetype" else zipfile.ZIP_DEFLATED)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with zipfile.ZipFile(out_path) as z:
        assert z.infolist()[0].filename == "mimetype"
        assert z.read("mimetype") == b"application/hwp+zip"
    return out_path


def fill_template_inplace(model: dict[str, Any], out_path: str | Path,
                          template_path: str | Path = BASE_TEMPLATE) -> Path:
    """양식(base.hwpx)의 고정 구조를 100% 유지하고, 슬롯 텍스트만 채운다.

    문단/표/이미지/붙임·참고/슬롯 개수 모두 그대로. 새 문서를 만들지 않는다.
    내용이 슬롯보다 많으면 잘라내고, 적으면 남은 슬롯은 비운다.
    """
    template_path = Path(template_path)
    with zipfile.ZipFile(template_path) as z:
        base_section = z.read("Contents/section0.xml").decode("utf-8")
    root = ET.fromstring(base_section)
    paras = root.findall(q("p"))

    org = model.get("org", "")
    title = model.get("title", "")
    date = model.get("date", "")
    sections = model.get("sections", [])[:len(INPLACE_SECTIONS)]

    def t_set(p, pairs):
        ne = _nonempty_t(p)
        for i, v in pairs:
            if v is not None and i < len(ne):
                ne[i].text = v
    if org or title:
        t_set(paras[INPLACE_TITLE], [(0, org or None), (1, title or None)])
    if date:
        t_set(paras[INPLACE_DATE], [(0, date)])
    if title:
        t_set(paras[INPLACE_DOCTITLE], [(0, title)])

    # 목차: 기존 Ⅰ~Ⅴ 엔트리 이름만 교체(구조/붙임·참고 유지), 남는 엔트리는 비움
    cell = paras[INPLACE_TOC].find(".//" + q("subList"))
    if cell is not None:
        inner = cell.findall(q("p"))
        for i in range(min(5, len(inner))):
            runs = inner[i].findall(q("run"))
            name_t = runs[1].find(q("t")) if len(runs) > 1 else None
            num_t = runs[0].find(q("t")) if runs else None
            if i < len(sections):
                if name_t is not None:
                    name_t.text = ". " + sections[i].get("title", "")
            else:
                if name_t is not None:
                    name_t.text = ""
                if num_t is not None:
                    num_t.text = ""

    # 섹션 헤더 + 본문 슬롯 (고정 위치, in-place)
    for si, (hidx, body_idx) in enumerate(INPLACE_SECTIONS):
        if si < len(sections):
            sec = sections[si]
            ne = _nonempty_t(paras[hidx])
            if len(ne) >= 2:
                ne[-1].text = " " + sec.get("title", "")
            lines = sec.get("lines", [])
            texts = [(ln[1] if isinstance(ln, (list, tuple)) and len(ln) >= 2 else str(ln))
                     for ln in lines]
            for j, bi in enumerate(body_idx):
                _set_body_slot(paras[bi], texts[j] if j < len(texts) else "")
        else:
            # 사용 안 한 섹션 슬롯은 비움(구조는 유지)
            ne = _nonempty_t(paras[hidx])
            if len(ne) >= 2:
                ne[-1].text = ""
            for bi in body_idx:
                _set_body_slot(paras[bi], "")

    _strip_linesegs(root)
    new_section = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                   + ET.tostring(root, encoding="unicode"))
    return _package_section(new_section, out_path, template_path)


def set_charpr_height_in_hwpx(hwpx_bytes: bytes, charpr_ids, height_hwpunit: int) -> bytes:
    """header.xml 의 특정 charPr id 들의 height(글자 크기, 1pt=100)를 바꾼다.
    결정적 부분 서식(예: 제목 크기). charpr_ids: int 리스트."""
    import io
    ids = {str(i) for i in charpr_ids}
    zin = zipfile.ZipFile(io.BytesIO(hwpx_bytes))
    names = zin.namelist()
    datas = {n: zin.read(n) for n in names}
    zin.close()
    header_key = next((n for n in names if n.endswith("header.xml")), None)
    if header_key:
        h = datas[header_key].decode("utf-8")
        def repl(m):
            tag = m.group(0)
            mid = re.search(r'\bid="(\d+)"', tag)
            if mid and mid.group(1) in ids:
                return re.sub(r'(\bheight=")\d+(")', lambda mm: mm.group(1) + str(height_hwpunit) + mm.group(2), tag)
            return tag
        h = re.sub(r'<hh:charPr\b[^>]*?>', repl, h)
        datas[header_key] = h.encode("utf-8")
    buf = io.BytesIO()
    ordered = (["mimetype"] if "mimetype" in names else []) + [n for n in names if n != "mimetype"]
    with zipfile.ZipFile(buf, "w") as zout:
        for n in ordered:
            zout.writestr(n, datas[n],
                          zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# base.hwpx 양식에서 표지 제목이 쓰는 charPr id (height=3000=30pt).
TITLE_CHARPR_IDS = [22]

# 영역 → 최상위 문단 인덱스(고정 양식). 셀 내부 run 까지 포함해 charPr 를 수집한다.
REGION_PARAS = {
    "title": [5, 21],
    "toc": [18, 20],
    "headings": [22, 27, 40, 54],
    "body": [23, 24, 25] + list(range(28, 40)) + list(range(41, 53)) + [55, 56, 57, 58],
}


def set_font_size_in_hwpx(hwpx_bytes: bytes, region: str, height_hwpunit: int) -> bytes:
    """영역(title/toc/headings/body/all)의 글자 크기를 결정적으로 바꾼다.
    해당 영역 문단(셀 포함)의 run 이 참조하는 charPr 들의 height 를 조정한다."""
    import io
    zin = zipfile.ZipFile(io.BytesIO(hwpx_bytes))
    names = zin.namelist()
    datas = {n: zin.read(n) for n in names}
    zin.close()
    sec_key = next((n for n in names if n.endswith("section0.xml")), None)
    header_key = next((n for n in names if n.endswith("header.xml")), None)
    if not sec_key or not header_key:
        return hwpx_bytes
    root = ET.fromstring(datas[sec_key].decode("utf-8"))
    paras = root.findall(q("p"))
    if region == "all":
        idxs = range(len(paras))
    else:
        idxs = [i for i in REGION_PARAS.get(region, []) if i < len(paras)]
    ids = set()
    for i in idxs:
        for run in paras[i].iter(q("run")):
            cid = run.get("charPrIDRef")
            if cid:
                ids.add(cid)
    if not ids:
        return hwpx_bytes
    h = datas[header_key].decode("utf-8")
    def repl(m):
        tag = m.group(0)
        mid = re.search(r'\bid="(\d+)"', tag)
        if mid and mid.group(1) in ids:
            return re.sub(r'(\bheight=")\d+(")',
                          lambda mm: mm.group(1) + str(height_hwpunit) + mm.group(2), tag)
        return tag
    h = re.sub(r'<hh:charPr\b[^>]*?>', repl, h)
    datas[header_key] = h.encode("utf-8")
    buf = io.BytesIO()
    ordered = (["mimetype"] if "mimetype" in names else []) + [n for n in names if n != "mimetype"]
    with zipfile.ZipFile(buf, "w") as zout:
        for n in ordered:
            zout.writestr(n, datas[n],
                          zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def change_fonts_in_hwpx(hwpx_bytes: bytes, font_face: str) -> bytes:
    """hwpx 바이트의 header.xml 폰트(font/substFont)의 face 를 일괄 교체해서
    문서 전체 글꼴을 바꾼다. 결정적·즉시 반영(엔진 폰트 op 우회)."""
    import io
    zin = zipfile.ZipFile(io.BytesIO(hwpx_bytes))
    names = zin.namelist()
    datas = {n: zin.read(n) for n in names}
    zin.close()
    header_key = next((n for n in names if n.endswith("header.xml")), None)
    if header_key:
        h = datas[header_key].decode("utf-8")
        h = re.sub(r'(<hh:(?:font|substFont)\b[^>]*?\bface=")[^"]*(")',
                   lambda m: m.group(1) + font_face + m.group(2), h)
        datas[header_key] = h.encode("utf-8")
    buf = io.BytesIO()
    ordered = (["mimetype"] if "mimetype" in names else []) + [n for n in names if n != "mimetype"]
    with zipfile.ZipFile(buf, "w") as zout:
        for n in ordered:
            zout.writestr(n, datas[n],
                          zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# ---- 문단 단위 읽기/편집 (에이전트 read_document / edit_paragraphs 용) ------

def _repack_hwpx(names, datas) -> bytes:
    import io
    buf = io.BytesIO()
    ordered = (["mimetype"] if "mimetype" in names else []) + [n for n in names if n != "mimetype"]
    with zipfile.ZipFile(buf, "w") as zout:
        for n in ordered:
            zout.writestr(n, datas[n],
                          zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def _own_text(p) -> str:
    return "".join((t.text or "")
                   for run in p.findall(q("run")) for t in run.findall(q("t")))


def _para_tables(p):
    return [tbl for run in p.findall(q("run")) for tbl in run.findall(q("tbl"))]


def _table_cells(tbl):
    return [tc for tr in tbl.findall(q("tr")) for tc in tr.findall(q("tc"))]


def read_paragraphs_in_hwpx(hwpx_bytes: bytes) -> list[dict]:
    """모든 문단(표 셀 내부 포함)을 {id, text} 로 나열한다.
    id: "12"(최상위 문단) / "5.0.1.0"(문단5 의 표0, 셀1, 셀 내부 문단0)."""
    import io
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as z:
        sec_key = next(n for n in z.namelist() if n.endswith("section0.xml"))
        root = ET.fromstring(z.read(sec_key).decode("utf-8"))
    out = []
    for i, p in enumerate(root.findall(q("p"))):
        tbls = _para_tables(p)
        row = {"id": str(i), "text": _own_text(p).strip()}
        if tbls:
            row["table"] = True
        out.append(row)
        for ti, tbl in enumerate(tbls):
            for ci, tc in enumerate(_table_cells(tbl)):
                sub = tc.find(q("subList"))
                if sub is None:
                    continue
                for pi, ip in enumerate(sub.findall(q("p"))):
                    out.append({"id": f"{i}.{ti}.{ci}.{pi}",
                                "text": _own_text(ip).strip(), "cell": True})
    return out


# 선두 라벨 런(로마숫자/마커)과 새 텍스트의 중복 마커 제거용
_LABEL_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\s*[.)]?|[□○―※])\s*$")
_LEAD_RE = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\s*[.)]\s*|[□○―※]\s*)")


def _locate_para(root, pid: str):
    parts = str(pid).strip().split(".")
    paras = root.findall(q("p"))
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return None
    if not nums or not (0 <= nums[0] < len(paras)):
        return None
    p = paras[nums[0]]
    if len(nums) == 1:
        return p
    if len(nums) != 4:
        return None
    ti, ci, pi = nums[1], nums[2], nums[3]
    tbls = _para_tables(p)
    if not (0 <= ti < len(tbls)):
        return None
    cells = _table_cells(tbls[ti])
    if not (0 <= ci < len(cells)):
        return None
    sub = cells[ci].find(q("subList"))
    if sub is None:
        return None
    inner = sub.findall(q("p"))
    return inner[pi] if 0 <= pi < len(inner) else None


def _set_para_text(p, text: str):
    """문단 텍스트를 교체한다. 선두 마커(□○―※)/로마숫자 런과 서식은 보존."""
    ne = _nonempty_t(p)
    if not ne:
        ts = [t for run in p.findall(q("run")) for t in run.findall(q("t"))]
        if ts:
            ts[-1].text = text
        else:
            runs = p.findall(q("run"))
            if runs:
                t = ET.SubElement(runs[-1], q("t"))
                t.text = text
        return
    if len(ne) >= 2 and _LABEL_RE.fullmatch(ne[0].text or ""):
        body = _LEAD_RE.sub("", text)
        for t in ne[1:-1]:
            t.text = ""
        prefix = re.match(r"^[\s.)]*", ne[-1].text or "").group(0)
        ne[-1].text = prefix + body
        return
    if re.match(r"^\s*[□○―※]", ne[0].text or ""):
        for t in ne[1:]:
            t.text = ""
        _set_marker(ne[0], _LEAD_RE.sub("", text))
        return
    for t in ne[1:]:
        t.text = ""
    ne[0].text = text


def edit_paragraphs_in_hwpx(hwpx_bytes: bytes, edits) -> tuple[bytes, list[dict]]:
    """edits: [{"id": "...", "text": "..."}] — 해당 문단의 텍스트만 교체.
    구조(문단/표/마커/서식)는 그대로 유지된다. (새 bytes, 항목별 결과) 반환."""
    import io
    zin = zipfile.ZipFile(io.BytesIO(hwpx_bytes))
    names = zin.namelist()
    datas = {n: zin.read(n) for n in names}
    zin.close()
    sec_key = next((n for n in names if n.endswith("section0.xml")), None)
    if not sec_key:
        return hwpx_bytes, [{"id": str(e.get("id")), "ok": False,
                             "error": "section0.xml 없음"} for e in edits]
    root = ET.fromstring(datas[sec_key].decode("utf-8"))
    results, changed = [], False
    for e in edits:
        pid = str(e.get("id", "")).strip()
        node = _locate_para(root, pid)
        if node is None:
            results.append({"id": pid, "ok": False, "error": "문단 id 없음"})
            continue
        _set_para_text(node, str(e.get("text", "")))
        results.append({"id": pid, "ok": True})
        changed = True
    if not changed:
        return hwpx_bytes, results
    _strip_linesegs(root)
    datas[sec_key] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
                      + ET.tostring(root, encoding="unicode")).encode("utf-8")
    return _repack_hwpx(names, datas), results


# ---- AI 디자인 템플릿: 에이전트가 스타일·구성을 직접 설계 → raw OWPML 생성 ----
# base.hwpx 는 폰트/페이지 설정(secPr)/매니페스트의 '스타일 키트'로만 쓰고,
# 문단·표지·글자 스타일은 design 스펙대로 처음부터 만든다. (기존 경로와 독립)

_SEC_NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)


def _clone_charpr(header: str, src_id: str, new_id: int, *,
                  height=None, color=None, bold=False) -> str:
    block = re.search(rf'<hh:charPr id="{src_id}".*?</hh:charPr>', header, re.S).group(0)
    block = re.sub(r'(<hh:charPr id=")\d+(")', rf'\g<1>{new_id}\g<2>', block, count=1)
    if height is not None:
        block = re.sub(r'(\bheight=")\d+(")', rf'\g<1>{height}\g<2>', block, count=1)
    if color:
        block = re.sub(r'(\btextColor=")[^"]*(")', rf'\g<1>{color}\g<2>', block, count=1)
    if bold and '<hh:bold/>' not in block:
        block = block.replace('</hh:charPr>', '<hh:bold/></hh:charPr>')
    return block


def _clone_parapr(header: str, src_id: str, new_id: int, *, align=None) -> str:
    block = re.search(rf'<hh:paraPr id="{src_id}".*?</hh:paraPr>', header, re.S).group(0)
    block = re.sub(r'(<hh:paraPr id=")\d+(")', rf'\g<1>{new_id}\g<2>', block, count=1)
    if align:
        block = re.sub(r'(<hh:align horizontal=")[A-Z_]+(")', rf'\g<1>{align}\g<2>', block)
    return block


def _append_props(header: str, tag: str, blocks) -> str:
    """charProperties/paraProperties refList 에 블록 추가 + itemCnt 갱신."""
    header = header.replace(f'</hh:{tag}>', ''.join(blocks) + f'</hh:{tag}>')
    return re.sub(rf'(<hh:{tag} itemCnt=")(\d+)(")',
                  lambda m: m.group(1) + str(int(m.group(2)) + len(blocks)) + m.group(3),
                  header, count=1)


def _hex_color(v, default: str) -> str:
    v = str(v or '').strip()
    return v if re.fullmatch(r'#[0-9A-Fa-f]{6}', v) else default


def build_ai_design_hwpx(design: dict, out_path: str | Path,
                         template_path: str | Path = BASE_TEMPLATE) -> Path:
    """AI 디자인 스펙 → 새 템플릿 hwpx 생성.

    design = {title, subtitle?, org?, date?, numbering?(roman|arabic|none),
              style?: {titleSizePt, subtitleSizePt, headingSizePt, bodySizePt,
                       titleColor, headingColor, bodyColor, headingBold},
              sections: [{title, lines: [{marker?, text, indent?} | str]}]}
    """
    from xml.sax.saxutils import escape
    out_path = Path(out_path)
    zin = zipfile.ZipFile(Path(template_path))
    names = zin.namelist()
    datas = {n: zin.read(n) for n in names}
    zin.close()
    header = datas['Contents/header.xml'].decode('utf-8')
    base_sec = datas['Contents/section0.xml'].decode('utf-8')

    st = design.get('style') or {}

    def _pt(key, default):
        try:
            v = int(st.get(key) or default)
        except (TypeError, ValueError):
            v = default
        return max(6, min(72, v)) * 100

    ncp = int(re.search(r'<hh:charProperties itemCnt="(\d+)"', header).group(1))
    npp = int(re.search(r'<hh:paraProperties itemCnt="(\d+)"', header).group(1))
    CP_TITLE, CP_SUB, CP_HEAD, CP_BODY = ncp, ncp + 1, ncp + 2, ncp + 3
    PP_CENTER, PP_BODY = npp, npp + 1
    header = _append_props(header, 'charProperties', [
        _clone_charpr(header, '22', CP_TITLE, height=_pt('titleSizePt', 24),
                      color=_hex_color(st.get('titleColor'), '#1F3864'), bold=True),
        _clone_charpr(header, '0', CP_SUB, height=_pt('subtitleSizePt', 12),
                      color=_hex_color(st.get('subtitleColor'), '#595959')),
        _clone_charpr(header, '0', CP_HEAD, height=_pt('headingSizePt', 15),
                      color=_hex_color(st.get('headingColor'), '#1F3864'),
                      bold=bool(st.get('headingBold', True))),
        _clone_charpr(header, '0', CP_BODY, height=_pt('bodySizePt', 11),
                      color=_hex_color(st.get('bodyColor'), '#000000')),
    ])
    header = _append_props(header, 'paraProperties', [
        _clone_parapr(header, '0', PP_CENTER, align='CENTER'),
        _clone_parapr(header, '0', PP_BODY),
    ])

    secpr = re.search(r'<hp:secPr\b.*?</hp:secPr>', base_sec, re.S).group(0)

    def para(text, cp, pp, extra=''):
        return (f'<hp:p id="0" paraPrIDRef="{pp}" styleIDRef="0" '
                f'pageBreak="0" columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="{cp}">{extra}<hp:t>{escape(text)}</hp:t></hp:run></hp:p>')

    ps = [para('', CP_BODY, PP_BODY, extra=secpr)]   # secPr(페이지 설정) 보존
    if design.get('org'):
        ps.append(para(str(design['org']), CP_SUB, PP_CENTER))
    ps.append(para('', CP_BODY, PP_BODY))
    ps.append(para(str(design.get('title') or '제목'), CP_TITLE, PP_CENTER))
    if design.get('subtitle'):
        ps.append(para(str(design['subtitle']), CP_SUB, PP_CENTER))
    if design.get('date'):
        ps.append(para(str(design['date']), CP_SUB, PP_CENTER))
    ps.append(para('', CP_BODY, PP_BODY))

    numbering = str(design.get('numbering') or 'roman').lower()
    for si, sec in enumerate(design.get('sections') or []):
        if si > 0:
            ps.append(para('', CP_BODY, PP_BODY))
        if numbering == 'arabic':
            num = f'{si + 1}. '
        elif numbering == 'none':
            num = ''
        else:
            num = (ROMAN[si] if si < len(ROMAN) else str(si + 1)) + '. '
        ps.append(para(num + str(sec.get('title') or ''), CP_HEAD, PP_BODY))
        for ln in sec.get('lines') or []:
            if isinstance(ln, dict):
                marker = str(ln.get('marker') or '')
                text = str(ln.get('text') or '')
                try:
                    indent = max(0, min(4, int(ln.get('indent') or 0)))
                except (TypeError, ValueError):
                    indent = 0
            else:
                marker, text, indent = '', str(ln), 0
            prefix = '  ' * indent + (marker + ' ' if marker else '')
            ps.append(para(prefix + text, CP_BODY, PP_BODY))

    sec_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
               f'<hs:sec {_SEC_NS}>' + ''.join(ps) + '</hs:sec>')
    ET.fromstring(sec_xml)  # well-formed 검증
    datas['Contents/header.xml'] = header.encode('utf-8')
    datas['Contents/section0.xml'] = sec_xml.encode('utf-8')
    out_path.write_bytes(_repack_hwpx(names, datas))
    return out_path


# base.hwpx 양식의 슬롯 모양(LLM 프롬프트용). 섹션 4개, 섹션별 본문 줄 수 고정.
TEMPLATE_SHAPE = [
    {"marks": ["□", "○", "―"]},                       # Ⅰ: 3줄
    {"marks": ["□", "○", "―", "※"] * 3},              # Ⅱ: 12줄(3묶음)
    {"marks": ["□", "○", "―", "※"] * 3},              # Ⅲ: 12줄(3묶음)
    {"marks": ["□", "○", "―", "※"]},                  # Ⅳ: 4줄
]


if __name__ == "__main__":
    demo = {
        "org": "브라더 공기관",
        "title": "스마트 워크 환경 구축 기본계획",
        "date": "2026. 6. 1.",
        "sections": [
            {"title": "추진 배경", "lines": [
                ["□", "디지털 전환 가속화로 일하는 방식의 변화 요구"],
                ["○", "비대면·협업 중심 업무 환경 수요 증가"],
                ["―", "선도 기관의 스마트워크 성과 가시화"]]},
            {"title": "추진 계획", "lines": [
                ["□", "단계별 추진 로드맵"],
                ["○", "1단계(6~8월): 플랫폼 선정 및 파일럿"],
                ["―", "2단계(9~11월): 전사 확산"],
                ["※", "생산성 향상·비용 절감 기대"]]},
        ],
    }
    out = build_hwpx(demo, Path.home() / "Downloads" / "claude_module_demo.hwpx")
    print("OK ->", out, out.stat().st_size, "bytes")
