#!/usr/bin/env python3
"""
HWPX raw-XML 생성 PoC.

전략(사용자 선택: raw OWPML 직접 생성 + 스타일 키트 재사용):
  1) 기준 hwpx(example.hwpx)를 스타일 키트로 사용 — header.xml/settings.xml/version.xml/
     META-INF/content.hpf/BinData/Scripts/Preview 등은 그대로 유지.
  2) Contents/section0.xml 만 새로 raw OWPML 로 생성한다.
     - 루트 <hs:sec> + 네임스페이스 선언은 원본과 동일
     - 첫 문단의 첫 run 안에 원본 <hp:secPr> 블록을 그대로 삽입(페이지 설정 보존)
     - 이후 텍스트 문단들을 <hp:p><hp:run charPrIDRef><hp:t>…</hp:t></hp:run></hp:p> 로 추가
     - linesegarray(레이아웃 캐시)는 생략 — 한글이 열 때 재계산하도록 둔다.
  3) mimetype 을 맨 앞 stored 로, 나머지는 deflate 로 재압축.

검증:
  - 생성된 section0.xml 의 XML well-formed 여부
  - zip 의 mimetype 규약(맨 앞, 무압축)
  - 다시 파싱해서 우리가 넣은 문단 텍스트가 그대로 있는지
"""
from __future__ import annotations
import re, sys, zipfile, shutil
from pathlib import Path
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

SRC = Path("/Users/eunseokyang/Downloads/example.hwpx")
WORK = Path("/tmp/hwpx_poc")
OUT = Path("/tmp/hwpx_poc/out.hwpx")

SEC_NS = (
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

# 기준 문서가 정의해 둔 ID들(header.xml 에 존재) — 스타일 키트에서 골라 쓴다.
STYLE_IDREF = "0"   # styles: id0 Normal
PARA_BODY = "0"     # paraProperties: id0 (정렬 JUSTIFY)
CHAR_BODY = "0"     # charProperties: id0 (13pt 검정)


def extract_secpr(section_xml: str) -> str:
    m = re.search(r"<hp:secPr\b.*?</hp:secPr>", section_xml, re.S)
    if not m:
        raise RuntimeError("원본 section0.xml 에서 secPr 를 찾지 못했습니다.")
    return m.group(0)


def make_para(text: str, *, char=CHAR_BODY, para=PARA_BODY, style=STYLE_IDREF,
              extra_run_inner: str = "") -> str:
    t = f"<hp:t>{escape(text)}</hp:t>" if text else "<hp:t></hp:t>"
    return (
        f'<hp:p id="0" paraPrIDRef="{para}" styleIDRef="{style}" '
        f'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{char}">{extra_run_inner}{t}</hp:run>'
        f'</hp:p>'
    )


def build_section(secpr: str, paragraphs: list[str]) -> str:
    body = []
    # 첫 문단: secPr 를 첫 run 안에 넣고 첫 텍스트도 같이 담는다.
    first_text = paragraphs[0] if paragraphs else ""
    body.append(make_para(first_text, extra_run_inner=secpr))
    for p in paragraphs[1:]:
        body.append(make_para(p))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec {SEC_NS}>' + "".join(body) + "</hs:sec>"
    )


def repackage(extract_dir: Path, out: Path):
    # mimetype 은 반드시 맨 앞 + 무압축(stored)
    files = [p for p in extract_dir.rglob("*") if p.is_file()]
    files.sort(key=lambda p: (p.name != "mimetype",))  # mimetype first
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w") as z:
        for f in files:
            arc = str(f.relative_to(extract_dir))
            if arc == "mimetype":
                z.write(f, arc, compress_type=zipfile.ZIP_STORED)
            else:
                z.write(f, arc, compress_type=zipfile.ZIP_DEFLATED)


def validate(out: Path, paragraphs: list[str]) -> list[str]:
    notes = []
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        # 1) mimetype 규약
        info0 = z.infolist()[0]
        assert info0.filename == "mimetype", f"첫 엔트리가 mimetype 아님: {info0.filename}"
        assert info0.compress_type == zipfile.ZIP_STORED, "mimetype 이 압축됨"
        assert z.read("mimetype") == b"application/hwp+zip", "mimetype 내용 불일치"
        notes.append(f"[OK] mimetype 규약 통과 (엔트리 {len(names)}개)")
        # 2) section0 well-formed
        sec = z.read("Contents/section0.xml").decode("utf-8")
        root = ET.fromstring(sec)
        notes.append(f"[OK] section0.xml well-formed (root={root.tag.split('}')[-1]})")
        # 3) 텍스트 보존
        HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
        texts = [e.text or "" for e in root.iter(f"{HP}t")]
        for want in paragraphs:
            assert want in texts, f"문단 텍스트 누락: {want!r} (있는것: {texts})"
        notes.append(f"[OK] 문단 텍스트 {len(paragraphs)}개 모두 보존: {texts}")
        # 4) header/manifest 무결성 — content.hpf 가 가리키는 파일이 다 있는지
        hpf = z.read("Contents/content.hpf").decode("utf-8")
        hrefs = re.findall(r'href="([^"]+)"', hpf)
        missing = [h for h in hrefs if h not in names]
        assert not missing, f"manifest 가 가리키는 누락 파일: {missing}"
        notes.append(f"[OK] content.hpf manifest 무결성 ({len(hrefs)}개 항목 모두 존재)")
    return notes


def main():
    paragraphs = [
        "Claude 가 생성한 첫 번째 문단입니다. (raw OWPML)",
        "두 번째 문단 — header.xml 의 스타일 정의를 그대로 참조합니다.",
        "세 번째 문단. linesegarray 는 생략했고 한글이 열 때 재계산합니다.",
    ]
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    ext = WORK / "ext"
    with zipfile.ZipFile(SRC) as z:
        z.extractall(ext)

    orig_sec = (ext / "Contents/section0.xml").read_text(encoding="utf-8")
    secpr = extract_secpr(orig_sec)
    new_sec = build_section(secpr, paragraphs)
    (ext / "Contents/section0.xml").write_text(new_sec, encoding="utf-8")

    repackage(ext, OUT)
    notes = validate(OUT, paragraphs)
    print("=== HWPX raw 생성 PoC 결과 ===")
    print(f"입력 스타일 키트 : {SRC}")
    print(f"생성 파일        : {OUT}  ({OUT.stat().st_size:,} bytes)")
    print(f"새 section0.xml  : {len(new_sec):,} chars (원본 {len(orig_sec):,} chars)")
    for n in notes:
        print(" ", n)
    print("\n다음: 위 out.hwpx 를 한글에서 직접 열어 레이아웃을 눈으로 확인하세요.")


if __name__ == "__main__":
    main()
