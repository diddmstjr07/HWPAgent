#!/usr/bin/env python3
"""raw OWPML 로 내용 있는 hwpx 한 편을 생성해 ~/Downloads 에 저장."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from hwpx_poc_generate import (
    SEC_NS, extract_secpr, make_para, repackage, validate,
)
import zipfile, shutil
from xml.sax.saxutils import escape

SRC = Path("/Users/eunseokyang/Downloads/example.hwpx")
OUT = Path.home() / "Downloads" / "claude_generated.hwpx"
WORK = Path("/tmp/hwpx_make")

# (styleIDRef, paraPrIDRef, charPrIDRef, text)
# 자동번호 매기는 개요 스타일은 피하고 0=Normal / 1=본문 만 사용해 깔끔하게.
BLOCKS = [
    (0, None, None, "Claude 가 생성한 한글 문서"),
    (1, None, None, ""),
    (1, None, None, "이 문서는 example.hwpx 의 스타일(header.xml)을 재사용하고, "
                     "본문(section0.xml)을 raw OWPML 로 직접 작성해 만든 것입니다."),
    (1, None, None, ""),
    (0, None, None, "1. 생성 방식"),
    (1, None, None, "· 스타일 정의는 기존 문서의 것을 그대로 참조(styleIDRef)합니다."),
    (1, None, None, "· 줄바꿈 캐시(linesegarray)는 생략하고 한글이 열 때 재계산합니다."),
    (1, None, None, "· mimetype 무압축 규약과 manifest 무결성을 지킵니다."),
    (1, None, None, ""),
    (0, None, None, "2. 검증"),
    (1, None, None, "@rhwp/core 엔진으로 라운드트립 파싱을 통과했습니다."),
    (1, None, None, "한글에서 직접 열어 레이아웃을 확인해 주세요."),
]


def build_section(secpr: str) -> str:
    body = []
    first = True
    for style, para, char, text in BLOCKS:
        kw = {}
        if style is not None: kw["style"] = str(style)
        if para is not None: kw["para"] = str(para)
        if char is not None: kw["char"] = str(char)
        if first:
            body.append(make_para(text, extra_run_inner=secpr, **kw))
            first = False
        else:
            body.append(make_para(text, **kw))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<hs:sec {SEC_NS}>' + "".join(body) + "</hs:sec>")


def main():
    if WORK.exists(): shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    ext = WORK / "ext"
    with zipfile.ZipFile(SRC) as z:
        z.extractall(ext)
    orig = (ext / "Contents/section0.xml").read_text(encoding="utf-8")
    secpr = extract_secpr(orig)
    (ext / "Contents/section0.xml").write_text(build_section(secpr), encoding="utf-8")
    repackage(ext, OUT)

    texts = [t for *_ , t in BLOCKS if t]
    notes = validate(OUT, texts)
    print("생성 완료:", OUT, f"({OUT.stat().st_size:,} bytes)")
    for n in notes: print(" ", n)


if __name__ == "__main__":
    main()
