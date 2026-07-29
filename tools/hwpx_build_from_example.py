#!/usr/bin/env python3
"""
example.hwpx 단 하나만 보고 raw OWPML 을 조립하는 생성기.

- 서식(스타일)은 example.hwpx/Contents/header.xml 을 그대로 사용(손대지 않음).
- 본문 section0.xml 은 example.hwpx 에서 추출한 '조각(fragment)'들로 새로 조립:
    · 표지/목차/제목 영역(문단 0~21)  → 그대로 재사용 + 텍스트만 치환
    · 섹션 헤더(1x3 박스, 문단 22)      → numeral/title 파라미터화
    · □(28), ○(29), ―(30), ※(44) 단락 → 마커 유지 + 본문 치환
    · 빈 줄(문단 26)                    → 섹션 간격
- 조각 개수에 얽매이지 않으므로 섹션/항목 수를 내용에 맞춰 자유롭게 생성.
- linesegarray(레이아웃 캐시)는 제거 → 한글이 열 때 재계산.

==> 즉 "오직 example.hwpx 만 보고" 모든 서식 바이트를 가져와 XML 을 짠다.
"""
from __future__ import annotations
import re, copy, zipfile, shutil
from pathlib import Path
import xml.etree.ElementTree as ET

SRC = Path("/Users/eunseokyang/Downloads/example.hwpx")
OUT = Path.home() / "Downloads" / "claude_built.hwpx"
WORK = Path("/tmp/hwpx_build")

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
for k, v in NS.items():
    ET.register_namespace(k, v)
def q(t): return f"{{{P}}}{t}"

ROMAN = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]

# 조각이 위치한 원본 최상위 문단 인덱스(고정 양식 기준)
PREAMBLE_END = 22          # 0..21 = 표지/목차/제목
IDX_HEADER, IDX_SQ, IDX_OC, IDX_DASH, IDX_NOTE, IDX_BLANK = 22, 23, 24, 25, 44, 26

# ----------------- 콘텐츠 모델 (여기만 바꾸면 새 문서) -----------------
ORG = "브라더 공기관"
TITLE = "스마트 워크 환경 구축 기본계획"
DATE = "2026. 6. 1."
# 각 줄: ("□"|"○"|"―"|"※", 텍스트). 개수 자유.
SECTIONS = [
    ("추진 배경", [
        ("□", "디지털 전환 가속화로 일하는 방식의 근본적 변화 요구"),
        ("○", "비대면·협업 중심 업무 환경에 대한 내부 수요 증가"),
        ("―", "선도 기관의 스마트워크 도입 성과가 가시화"),
    ]),
    ("현황 및 문제점", [
        ("□", "현행 업무 환경 현황"),
        ("○", "고정 좌석·대면 보고 중심으로 운영"),
        ("―", "협업 도구가 부서별로 분산되어 비효율 발생"),
        ("※", "원격 접속 시 보안 체계가 미흡"),
        ("□", "핵심 문제점"),
        ("○", "회의·문서 작업의 디지털 연속성 부족"),
        ("―", "데이터 공유 및 이력 관리의 한계"),
    ]),
    ("개선 방안", [
        ("□", "통합 협업 플랫폼 도입"),
        ("○", "메신저·화상회의·문서공유를 단일 환경으로 통합"),
        ("―", "표준 워크플로우와 권한 체계 정립"),
        ("※", "전 직원 대상 활용 교육 시행"),
        ("□", "보안 인프라 강화"),
        ("○", "제로트러스트 기반 접속 통제 적용"),
        ("―", "문서 등급별 접근 권한 자동화"),
    ]),
    ("추진 계획 및 기대 효과", [
        ("□", "단계별 추진 로드맵"),
        ("○", "1단계(6~8월): 플랫폼 선정 및 파일럿"),
        ("―", "2단계(9~11월): 전사 확산 및 안정화"),
        ("※", "업무 생산성 향상과 비용 절감 효과 기대"),
    ]),
]
# --------------------------------------------------------------------


def nonempty_t(p):
    return [t for t in p.iter(q("t")) if (t.text or "").strip()]


def set_marker(tnode, text):
    m = re.match(r"^(\s*[□○―※]\s*)", tnode.text or "")
    tnode.text = (m.group(1) if m else "") + text


def strip_linesegs(el):
    for parent in el.iter():
        for child in list(parent):
            if child.tag == q("linesegarray"):
                parent.remove(child)


def build():
    with zipfile.ZipFile(SRC) as z:
        sec_raw = z.read("Contents/section0.xml").decode("utf-8")
    root = ET.fromstring(sec_raw)
    paras = root.findall(q("p"))

    # 1) 조각 템플릿을 example.hwpx 에서 추출(깊은 복사)
    frag = {
        "header": copy.deepcopy(paras[IDX_HEADER]),
        "□": copy.deepcopy(paras[IDX_SQ]),
        "○": copy.deepcopy(paras[IDX_OC]),
        "―": copy.deepcopy(paras[IDX_DASH]),
        "※": copy.deepcopy(paras[IDX_NOTE]),
        "blank": copy.deepcopy(paras[IDX_BLANK]),
    }

    # 2) 표지/목차/제목(0~21) 텍스트 치환 (구조는 그대로)
    def t_set(p, new_pairs):
        ne = nonempty_t(p)
        for i, v in new_pairs:
            if i < len(ne) and v is not None:
                ne[i].text = v
    t_set(paras[5], [(0, ORG), (1, TITLE)])      # 표지 제목표
    t_set(paras[11], [(0, DATE)])                 # 날짜
    t_set(paras[21], [(0, TITLE)])                # '제 목'
    # 목차: 숫자런 유지, '. 이름' 런만 섹션 제목으로
    toc_names = [s[0] for s in SECTIONS]
    ti = 0
    for t in paras[20].iter(q("t")):
        if re.match(r"^\.\s*\S", t.text or "") and ti < len(toc_names):
            t.text = ". " + toc_names[ti]; ti += 1

    # 3) 새 본문 조립 = 표지(0..21) + 섹션들
    new_children = [copy.deepcopy(paras[i]) for i in range(PREAMBLE_END)]
    for si, (title, lines) in enumerate(SECTIONS):
        if si > 0:
            new_children.append(copy.deepcopy(frag["blank"]))
        # 섹션 헤더
        h = copy.deepcopy(frag["header"])
        ne = nonempty_t(h)
        if len(ne) >= 2:
            ne[0].text = ROMAN[si]
            ne[-1].text = " " + title
        new_children.append(h)
        # 본문 줄
        for marker, text in lines:
            f = copy.deepcopy(frag[marker])
            if marker == "□":
                nf = nonempty_t(f)
                if nf:
                    nf[-1].text = text          # 마커 런(' □ ')은 유지
            else:
                nf = nonempty_t(f)
                if nf:
                    set_marker(nf[0], text)
            new_children.append(f)

    # 4) root 의 자식(hp:p)을 새 목록으로 교체
    for c in list(root):
        if c.tag == q("p"):
            root.remove(c)
    for c in new_children:
        root.append(c)

    # 5) linesegarray 제거
    strip_linesegs(root)

    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + body


def repackage(ext, out):
    files = [p for p in ext.rglob("*") if p.is_file()]
    files.sort(key=lambda p: (p.name != "mimetype",))
    if out.exists(): out.unlink()
    with zipfile.ZipFile(out, "w") as z:
        for f in files:
            arc = str(f.relative_to(ext))
            z.write(f, arc, zipfile.ZIP_STORED if arc == "mimetype" else zipfile.ZIP_DEFLATED)


def main():
    new_sec = build()
    ET.fromstring(new_sec)  # well-formed 체크

    if WORK.exists(): shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    ext = WORK / "ext"
    with zipfile.ZipFile(SRC) as z:
        z.extractall(ext)
    (ext / "Contents/section0.xml").write_text(new_sec, encoding="utf-8")
    repackage(ext, OUT)

    with zipfile.ZipFile(OUT) as z:
        assert z.infolist()[0].filename == "mimetype"
        assert z.read("mimetype") == b"application/hwp+zip"
    nlines = sum(len(s[1]) for s in SECTIONS)
    print(f"생성 완료: {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"제목: {TITLE} / 섹션 {len(SECTIONS)}개 / 본문 {nlines}줄")
    print("조립 재료: example.hwpx 의 header.xml(스타일) + section0 조각(표지/헤더/□○―※)")


if __name__ == "__main__":
    main()
