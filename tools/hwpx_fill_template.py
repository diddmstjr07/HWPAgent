#!/usr/bin/env python3
"""
구조 보존형 HWPX 생성기.

example.hwpx("기본 보고서 양식")의 골격(표지/목차/Ⅰ~Ⅳ 박스헤더/□○―※ 계층/
표/이미지/스타일/페이지설정)을 그대로 유지한 채, 텍스트 슬롯만 새 내용으로 치환한다.

- header.xml(스타일) 및 기타 파트는 손대지 않음 → Quality/Structure 보존.
- section0.xml 의 <hp:t> 텍스트만 슬롯 단위로 교체.
- <hp:linesegarray>(레이아웃 캐시)는 모두 제거 → 한글이 열 때 재계산.
"""
from __future__ import annotations
import re, zipfile, shutil
from pathlib import Path
import xml.etree.ElementTree as ET

SRC = Path("/Users/eunseokyang/Downloads/example.hwpx")
OUT = Path.home() / "Downloads" / "claude_report_new.hwpx"
WORK = Path("/tmp/hwpx_fill")

P = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": P, "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
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
for k, v in NS.items():
    ET.register_namespace(k, v)


def q(t): return f"{{{P}}}{t}"

# ---------------- 새 콘텐츠 모델 (이 부분만 바꾸면 새 문서가 나온다) ----------------
ORG = "브라더 공기관"
TITLE = "재택근무 제도 도입 추진 계획"
DATE = "2026. 6. 1."
# 목차(Ⅰ~Ⅴ 슬롯). 본문은 Ⅰ~Ⅳ 이므로 Ⅴ는 마무리 항목으로.
TOC = ["추진 배경", "현황 및 문제점", "개선 방안", "추진 계획", "기대 효과"]

# 섹션: 각 그룹은 (□, ○, ―, ※?) — 원본 슬롯 패턴과 정확히 일치시킨다.
SECTIONS = [
    # Ⅰ 추진 배경 : 그룹 1개 (□, ○, ―) — ※ 없음
    {"title": "추진 배경", "groups": [
        ("코로나19 이후 유연근무에 대한 사회적 수요가 크게 증가",
         "직원 만족도 제고와 업무 생산성 향상을 위한 제도 개선 필요",
         "공공·민간 전반으로 재택근무 도입 사례가 빠르게 확산", None),
    ]},
    # Ⅱ 현황 및 문제점 : 그룹 3개 (□, ○, ―, ※)
    {"title": "현황 및 문제점", "groups": [
        ("현행 근무 제도 현황",
         "전 직원 사무실 출근을 원칙으로 운영 중",
         "유연근무제는 운영되나 실제 이용률은 저조",
         "재택근무에 대한 제도적 근거가 미비"),
        ("주요 문제점",
         "장거리 통근 직원의 출퇴근 시간 부담 가중",
         "재난·감염병 등 긴급 상황 시 업무 연속성 확보 한계",
         "원격 협업을 위한 디지털 인프라 부족"),
        ("직원 수요 조사 결과",
         "응답 직원의 78%가 재택근무 도입을 희망",
         "주 2일 형태의 부분 재택을 가장 선호",
         "정보 보안 및 근태 관리에 대한 우려도 상존"),
    ]},
    # Ⅲ 개선 방안 : 그룹 3개
    {"title": "개선 방안", "groups": [
        ("재택근무 제도 신설",
         "주 최대 2일 범위에서 재택근무 허용",
         "부서장 승인제로 운영하여 업무 공백 방지",
         "성과 중심 평가 체계와 연계하여 운영"),
        ("원격근무 인프라 구축",
         "VPN 및 보안 솔루션을 도입해 안전한 접속 환경 마련",
         "협업·메신저 도구를 표준화하여 소통 효율 제고",
         "전 직원 대상 정보보안 교육을 의무화"),
        ("운영 기준 마련",
         "근태·복무 관리 지침을 신규 제정",
         "정기 복무 점검 체계를 정비",
         "시범운영 결과를 반영해 단계적으로 확대"),
    ]},
    # Ⅳ 추진 계획 : 그룹 1개
    {"title": "추진 계획", "groups": [
        ("단계별 추진 일정 수립",
         "1단계(6~7월): 제도 설계 및 관련 규정 정비",
         "2단계(8~9월): 일부 부서 대상 시범운영 실시",
         "3단계(10월~): 평가·보완 후 전 부서 확대 시행"),
    ]},
]

# 원본 최상위 문단 인덱스 매핑 (slots 인벤토리 기준, 고정 양식)
SEC_HEADER_IDX = {0: 22, 1: 27, 2: 40, 3: 54}
SEC_BODY_GROUPS = {
    0: [(23, 24, 25, None)],
    1: [(28, 29, 30, 31), (32, 33, 34, 35), (36, 37, 38, 39)],
    2: [(41, 42, 43, 44), (45, 46, 47, 48), (49, 50, 51, 52)],
    3: [(55, 56, 57, 58)],
}
# -------------------------------------------------------------------------------


def nonempty_t(p):
    return [t for t in p.iter(q("t")) if (t.text or "").strip()]


def set_marker_line(tnode, new_text):
    """'  ○ 옛내용' → 마커/들여쓰기는 보존하고 본문만 교체."""
    m = re.match(r"^(\s*[□○―※]\s*)", tnode.text or "")
    prefix = m.group(1) if m else ""
    tnode.text = prefix + new_text


def fill(root):
    paras = root.findall(q("p"))

    def P_(i):  # i번째 최상위 문단
        return paras[i]

    # 표지 제목표 [5]: ['브라더 공기관','기본 보고서 양식']
    ne = nonempty_t(P_(5))
    if len(ne) >= 2:
        ne[0].text, ne[1].text = ORG, TITLE
    # 날짜 [11]
    ne = nonempty_t(P_(11))
    if ne: ne[0].text = DATE
    # 제 목 [21]
    ne = nonempty_t(P_(21))
    if ne: ne[0].text = TITLE
    # 목차 [20]: 숫자 런은 유지, '. 이름' 런만 교체
    for t in P_(20).iter(q("t")):
        s = t.text or ""
        m = re.match(r"^(\.\s*)(.+)$", s)
        if m:
            # 다음 TOC 이름 채우기 (순서대로)
            if fill._toc_i < len(TOC):
                t.text = ". " + TOC[fill._toc_i]
                fill._toc_i += 1

    # 섹션 헤더 + 본문
    for si, sec in enumerate(SECTIONS):
        hi = SEC_HEADER_IDX[si]
        ne = nonempty_t(P_(hi))  # ['Ⅰ', ' 추진 배경']
        if len(ne) >= 2:
            ne[-1].text = " " + sec["title"]
        groups = SEC_BODY_GROUPS[si]
        for gi, (sq, oc, dash, note) in enumerate(groups):
            if gi >= len(sec["groups"]):
                break
            head, sub, det, mark = sec["groups"][gi]
            # □ 문단: 런 2개 [' □ ', '본문'] → 본문 런만 교체
            sqs = nonempty_t(P_(sq))
            if sqs: sqs[-1].text = head
            # ○
            ocs = nonempty_t(P_(oc))
            if ocs and sub is not None: set_marker_line(ocs[0], sub)
            # ―
            ds = nonempty_t(P_(dash))
            if ds and det is not None: set_marker_line(ds[0], det)
            # ※ (있을 때만)
            if note is not None and mark is not None:
                ms = nonempty_t(P_(note))
                if ms: set_marker_line(ms[0], mark)


fill._toc_i = 0


def strip_linesegs(root):
    n = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag == q("linesegarray"):
                parent.remove(child); n += 1
    return n


def repackage(ext, out):
    files = [p for p in ext.rglob("*") if p.is_file()]
    files.sort(key=lambda p: (p.name != "mimetype",))
    if out.exists(): out.unlink()
    with zipfile.ZipFile(out, "w") as z:
        for f in files:
            arc = str(f.relative_to(ext))
            z.write(f, arc, zipfile.ZIP_STORED if arc == "mimetype" else zipfile.ZIP_DEFLATED)


def main():
    if WORK.exists(): shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    ext = WORK / "ext"
    with zipfile.ZipFile(SRC) as z:
        z.extractall(ext)

    sec_path = ext / "Contents/section0.xml"
    raw = sec_path.read_text(encoding="utf-8")
    root = ET.fromstring(raw)

    fill(root)
    removed = strip_linesegs(root)

    body = ET.tostring(root, encoding="unicode")
    out_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + body
    sec_path.write_text(out_xml, encoding="utf-8")

    repackage(ext, OUT)

    # 자체 검증
    ET.fromstring(out_xml)  # well-formed
    with zipfile.ZipFile(OUT) as z:
        assert z.infolist()[0].filename == "mimetype"
        assert z.read("mimetype") == b"application/hwp+zip"
    print(f"생성 완료: {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"linesegarray 제거: {removed}개 (한글이 재계산)")
    print(f"제목: {TITLE} / 날짜: {DATE} / 섹션 {len(SECTIONS)}개")


if __name__ == "__main__":
    main()
