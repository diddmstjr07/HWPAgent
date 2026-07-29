#!/usr/bin/env python3
"""Download the official source corpus for the research-narrative feature.

The downloader intentionally keeps each notice/version separate.  It does not
transform or merge copyrighted documents; it stores originals and emits a
SHA-256 manifest so later import jobs can be reproducible.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "reference_sources"
RAW_ROOT = DATA_ROOT / "raw"
CATALOG_ROOT = DATA_ROOT / "catalog"
MANIFEST_PATH = DATA_ROOT / "manifest.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


@dataclasses.dataclass(frozen=True)
class DownloadTask:
    url: str
    relative_path: str
    authority: str
    source_page: str
    document_group: str
    notice_or_version: str
    effective_from: str | None = None
    license_note: str | None = None
    role: str = "source"


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "POST")),
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def safe_name(value: str, fallback: str = "document") -> str:
    value = unicodedata.normalize("NFC", value).strip()
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_file(path: Path) -> None:
    size = path.stat().st_size
    if size == 0:
        raise ValueError("empty response")

    suffix = path.suffix.lower()
    if suffix == ".part":
        suffix = path.with_suffix("").suffix.lower()
    with path.open("rb") as stream:
        prefix = stream.read(2048)
    lowered = prefix.lower().lstrip()

    if suffix == ".pdf" and b"%pdf" not in prefix[:1024].lower():
        raise ValueError("expected PDF magic")
    if suffix in {".zip", ".hwpx", ".pptx", ".docx", ".xlsx"} and not prefix.startswith(b"PK"):
        raise ValueError(f"expected ZIP-container magic for {suffix}")
    if suffix == ".hwp" and not (
        prefix.startswith(bytes.fromhex("d0cf11e0")) or prefix.startswith(b"PK")
    ):
        raise ValueError("expected HWP/OLE magic")
    if suffix == ".html" and not (
        lowered.startswith(b"<!doctype html")
        or b"<html" in lowered[:1024]
        or b"<link" in lowered[:1024]
        or b"<form" in lowered[:2048]
    ):
        raise ValueError("expected HTML document")
    if suffix not in {".html", ".txt", ".json"} and lowered.startswith((b"<!doctype html", b"<html")):
        raise ValueError("download returned an HTML error page")


def validate_task_file(task: DownloadTask, path: Path) -> None:
    """Run format checks plus source-specific sanity checks."""

    validate_file(path)
    match = re.search(r"ncic_achievement_level_index_page_(\d+)\.html$", task.relative_path)
    if not match:
        return

    expected_page = int(match.group(1))
    page_text = path.read_text(encoding="utf-8", errors="replace")
    current = re.search(r"현재\s+(\d+)페이지", page_text)
    if not current or int(current.group(1)) != expected_page:
        actual = current.group(1) if current else "unknown"
        raise ValueError(
            f"NCIC catalog cache mismatch: expected page {expected_page}, got {actual}"
        )


def task_record(task: DownloadTask, path: Path, status: str) -> dict[str, Any]:
    return {
        "status": status,
        "document_group": task.document_group,
        "role": task.role,
        "authority": task.authority,
        "notice_or_version": task.notice_or_version,
        "effective_from": task.effective_from,
        "license_note": task.license_note,
        "source_page": task.source_page,
        "download_url": task.url,
        "local_path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def download_one(task: DownloadTask) -> dict[str, Any]:
    path = REPO_ROOT / task.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            validate_task_file(task, path)
            return task_record(task, path, "verified_existing")
        except (OSError, ValueError):
            pass

    part_path = path.with_name(path.name + ".part")
    session = make_session()
    headers = {"Referer": task.source_page} if task.source_page else {}
    request_url = task.url
    request_params: dict[str, str] | None = None
    verify_tls = True
    parsed = urlsplit(task.url)
    if parsed.hostname == "api.prism.go.kr":
        # PRISM's file host currently omits an intermediate certificate in its
        # TLS chain.  Keep this exception host-scoped and retain HTTPS; all
        # downloaded files are subsequently checked by PDF magic + SHA-256.
        request_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        request_params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        verify_tls = False

    with session.get(
        request_url,
        params=request_params,
        headers=headers,
        stream=True,
        timeout=(20, 60),
        verify=verify_tls,
    ) as response:
        response.raise_for_status()
        with part_path.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    stream.write(chunk)

    validate_task_file(task, part_path)
    os.replace(part_path, path)
    return task_record(task, path, "downloaded")


def static_tasks() -> list[DownloadTask]:
    moe_page = (
        "https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=141&boardSeq=93458"
        "&lev=0&m=0404&opType=N&s=moe&statusYN=W"
    )
    tasks = [
        DownloadTask(
            "https://www.moe.go.kr/boardCnts/fileDown.do?fileSeq=978b3cd2352689b9d88edc0d1e7bed2e&m=0404&s=moe",
            "data/reference_sources/raw/curriculum_2022_original/moe_archives/moe_2022-33_annex_01-04.zip",
            "대한민국 교육부",
            moe_page,
            "2022 개정 교육과정 원고시",
            "교육부 고시 제2022-33호",
            "2025-03-01 (고1), 2026-03-01 (고2), 2027-03-01 (고3)",
        ),
        DownloadTask(
            "https://www.moe.go.kr/boardCnts/fileDown.do?fileSeq=1512facbda6c234a1641ac7e9c156ca2&m=0404&s=moe",
            "data/reference_sources/raw/curriculum_2022_original/moe_archives/moe_2022-33_annex_05-14.zip",
            "대한민국 교육부",
            moe_page,
            "2022 개정 교육과정 원고시",
            "교육부 고시 제2022-33호",
        ),
        DownloadTask(
            "https://www.moe.go.kr/boardCnts/fileDown.do?fileSeq=5b7e71c0de65bde9f7d3cd153db54813&m=0404&s=moe",
            "data/reference_sources/raw/curriculum_2022_original/moe_archives/moe_2022-33_annex_15-22.zip",
            "대한민국 교육부",
            moe_page,
            "2022 개정 교육과정 원고시",
            "교육부 고시 제2022-33호",
        ),
        DownloadTask(
            "https://www.moe.go.kr/boardCnts/fileDown.do?fileSeq=94bf7976b8dc554a4fe4fd29ee5fc64e&m=0404&s=moe",
            "data/reference_sources/raw/curriculum_2022_original/moe_archives/moe_2022-33_annex_23-39.zip",
            "대한민국 교육부",
            moe_page,
            "2022 개정 교육과정 원고시",
            "교육부 고시 제2022-33호",
        ),
        DownloadTask(
            "https://www.moe.go.kr/boardCnts/fileDown.do?fileSeq=6d933e445bd3a03ef247ccfb18bbb4f7&m=0404&s=moe",
            "data/reference_sources/raw/curriculum_2022_original/moe_archives/moe_2022-33_annex_40-41.zip",
            "대한민국 교육부",
            moe_page,
            "2022 개정 교육과정 원고시",
            "교육부 고시 제2022-33호",
        ),
        DownloadTask(
            "https://www.ne.go.kr/component/file/ND_fileDownload.do?q_fileId=00f33f46-d775-4f52-8273-23832dec5bfe&q_fileSn=310",
            "data/reference_sources/raw/curriculum_amendments/2024-3/nec_2024-3_notice.hwpx",
            "국가교육위원회",
            "https://www.ne.go.kr/new/user/bbs/BD_selectBbs.do?q_bbsDocNo=20240927163706792&q_bbsSn=1016",
            "2022 개정 교육과정 일부개정",
            "국가교육위원회 고시 제2024-3호",
            "2024-08-16",
            "공식 게시 페이지의 이용조건 확인 필요",
        ),
        DownloadTask(
            "https://www.ne.go.kr/component/file/ND_fileDownload.do?q_fileId=b741961e-773c-4f93-a396-1f3a9608ea11&q_fileSn=666",
            "data/reference_sources/raw/curriculum_current/2026-1/nec_2026-1_notice.pdf",
            "국가교육위원회",
            "https://www.ne.go.kr/user/bbs/BD_selectBbs.do?q_bbsDocNo=20260121102419070&q_bbsSn=1016",
            "2022 개정 교육과정 현행 일부개정",
            "국가교육위원회 고시 제2026-1호",
            "2026-03-01",
            "공공누리 출처표시 조건은 공식 게시 페이지에서 재확인",
        ),
        DownloadTask(
            "https://www.moe.go.kr/boardCnts/fileDown.do?fileSeq=6668402ed462e43bd1ff70123359bf50&m=030215&s=moe",
            "data/reference_sources/raw/student_record/2026/moe_2026_highschool_student_record_manual.pdf",
            "대한민국 교육부",
            "https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=316&boardSeq=105372&lev=0&m=030215&opType=N&s=moe&statusYN=W",
            "학교생활기록부",
            "2026학년도 학교생활기록부 기재요령(고등학교)",
            "2026학년도",
            "공공누리 제4유형(출처표시·비상업·변경금지)",
        ),
        DownloadTask(
            "https://star.moe.go.kr/afile/fileDownload/ZtLmn?menuName=m20900&bdId=107761",
            "data/reference_sources/raw/student_record/2026/star_2026_highschool_major_changes.pptx",
            "교육부 학생부종합지원포털",
            "https://star.moe.go.kr/web/contents/m20900.do?id=107761&schM=view",
            "학교생활기록부",
            "2026 학교생활기록부 훈령 및 기재요령 주요 개정사항(고등)",
            "2026학년도",
            "공식 자료의 이용조건 확인 필요",
        ),
        DownloadTask(
            "https://www.ice.go.kr/upload/ice/na/bbs_2088/2026/04/e63cde9d0e418e61d6a35f38de316933.pdf",
            "data/reference_sources/raw/student_record/2026/ice_2026_student_record_guide_highschool.pdf",
            "인천광역시교육청(교육부 STAR 자료 공개 미러)",
            "https://www.ice.go.kr/ice/na/ntt/selectNttInfo.do?nttSn=3368825&bbsId=2088&mi=12308",
            "학교생활기록부",
            "2026학년도 학교생활기록부 기재 길라잡이(고등학교)",
            "2026학년도",
            "공식 게시 페이지의 이용조건 확인 필요",
        ),
        DownloadTask(
            "https://www.goe.go.kr/resource/goe/na/bbs_2675/2026/05/34866f8c-3e6b-45c1-84fb-4b232c919650.pdf",
            "data/reference_sources/raw/student_assessment/2026/goe_2026_student_assessment_guide_highschool.pdf",
            "경기도교육청",
            "https://www.goe.go.kr/goe/na/ntt/selectNttInfo.do?mi=10961&nttSn=2349771",
            "학생평가",
            "2022 개정 교육과정에 따른 학생평가 톺아보기(고등학교), 2026 개정판",
            "2026-05-08",
            "공공누리 제4유형(출처표시·비상업·변경금지)",
        ),
        DownloadTask(
            "https://buseo.sen.go.kr/component/file/ND_fileDownload.do?q_fileId=94-9330-1&q_fileSn=1815680",
            "data/reference_sources/raw/student_record/legacy_reference/sen_2022_subject_detail_examples_2015_curriculum.pdf",
            "서울특별시교육청",
            "https://buseo.sen.go.kr/buseo/bu12/user/bbs/BD_selectBbs.do?q_bbsDocNo=20221227153855000&q_bbsSn=1266",
            "교과 세특 방법론 참고",
            "교과세특 기재 예시 도움 자료(2015 개정 교육과정 기반)",
            "2022-12-27",
            "2022 성취기준 DB에 혼합 금지; 방법론 참고 전용",
            "legacy_methodology_reference",
        ),
        DownloadTask(
            "https://www.gwe.go.kr/cmm/fileDown.do?encKey=MTE5MjI0&type=bbs",
            "data/reference_sources/raw/student_record/2026/gwe_2026_student_record_field_inspection_highschool.hwp",
            "강원특별자치도교육청(교육부 STAR 자료 공개 미러)",
            "https://www.gwe.go.kr/main/bbs/view.do?bbsSn=50967&key=m2307211198550",
            "학교생활기록부",
            "2026 학교생활기록부 현장점검 도움자료(고등학교)",
            "2026-05-21",
            "공식 게시 페이지의 이용조건 확인 필요",
        ),
        DownloadTask(
            "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulId=48643&admRulNm=%ED%95%99%EA%B5%90%EC%83%9D%ED%99%9C%EA%B8%B0%EB%A1%9D%EC%9E%91%EC%84%B1%EB%B0%8F%EA%B4%80%EB%A6%AC%EC%A7%80%EC%B9%A8&efYd=",
            "data/reference_sources/raw/student_record/2026/law_2026_moe_directive_555_student_record_management.html",
            "법제처 국가법령정보센터",
            "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulId=48643&admRulNm=%ED%95%99%EA%B5%90%EC%83%9D%ED%99%9C%EA%B8%B0%EB%A1%9D%EC%9E%91%EC%84%B1%EB%B0%8F%EA%B4%80%EB%A6%AC%EC%A7%80%EC%B9%A8&efYd=",
            "학교생활기록부 법적 근거",
            "학교생활기록 작성 및 관리지침, 교육부훈령 제555호",
            "2026-03-01",
            "국가법령정보센터 현행 행정규칙 원문",
            "legal_source",
        ),
    ]

    for page in range(1, 19):
        tasks.append(
            DownloadTask(
                (
                    "https://ncic.re.kr/bbs/standard/list.do"
                    f"?page={page}&catalog_snapshot_page={page}"
                ),
                f"data/reference_sources/catalog/ncic_achievement_level_index_page_{page:02d}.html",
                "NCIC 국가교육과정정보센터",
                "https://ncic.re.kr/bbs/standard/list.do",
                "성취수준 자료 카탈로그",
                "2026-07-23 조회 스냅샷",
                license_note="원문이 아닌 공개 목록 스냅샷",
                role="catalog_snapshot",
            )
        )
    return tasks


def ncic_inventory_tasks() -> list[DownloadTask]:
    session = make_session()
    source_page = "https://ncic.re.kr/inv/org/list.do"
    api_url = "https://ncic.re.kr/api/inv/inventoryNodeList.do"
    file_api_url = "https://ncic.re.kr/api/inv/invFileList.do"
    headers = {"Referer": source_page, "X-Requested-With": "XMLHttpRequest"}
    profiles = [
        {
            "class_code": "1004",
            "year": "2022",
            "month": "12",
            "folder": "curriculum_2022_original/ncic_highschool_individual",
            "group": "2022 개정 고등학교 과목별 교육과정",
            "notice": "교육부 고시 제2022-33호",
            "effective": "학년별 2025-03-01~2027-03-01",
            "license": "법정 성취기준 원천; 공식 게시 페이지 이용조건 확인",
        },
        {
            "class_code": "1016",
            "year": "2024",
            "month": "08",
            "folder": "curriculum_amendments/2024-3/ncic_consolidated_annexes",
            "group": "2022 개정 교육과정 2024 일부개정 별책",
            "notice": "국가교육위원회 고시 제2024-3호",
            "effective": "2024-08-16 (별책별 적용 범위 확인)",
            "license": "법정 성취기준 원천; 공식 게시 페이지 이용조건 확인",
        },
        {
            "class_code": "1004",
            "year": "2026",
            "month": "01",
            "folder": "curriculum_current/2026-1/highschool",
            "group": "2022 개정 고등학교 교육과정 현행본",
            "notice": "국가교육위원회 고시 제2026-1호",
            "effective": "2026-03-01 (고1·고2), 2027-03-01 (고3)",
            "license": "현행 총론·편제 원천; 공식 게시 페이지 이용조건 확인",
        },
        {
            "class_code": "1016",
            "year": "2026",
            "month": "01",
            "folder": "curriculum_current/2026-1/general",
            "group": "2022 개정 초·중등학교 교육과정 현행 총론",
            "notice": "국가교육위원회 고시 제2026-1호",
            "effective": "2026-03-01",
            "license": "현행 총론 원천; 공식 게시 페이지 이용조건 확인",
        },
    ]

    tasks: list[DownloadTask] = []
    for profile in profiles:
        node_response = session.post(
            api_url,
            headers=headers,
            data={
                "type": "ogi4",
                "nowTblType": "dwn",
                "menuType": "1",
                "invDepth": "3",
                "degreeCode": "1014",
                "classCode": profile["class_code"],
                "subjectCode": "",
                "subjectDefCode": "",
                "nationCode": "",
                "openYear": profile["year"],
                "openMonth": profile["month"],
                "ref": "",
                "isAdmin": "0",
            },
            timeout=(20, 60),
        )
        node_response.raise_for_status()
        nodes = node_response.json()

        for node in nodes:
            file_response = session.post(
                file_api_url,
                headers=headers,
                data={
                    "invSeq": node.get("ref") or "0",
                    "invYear": profile["year"],
                    "orgType": "ogi4",
                    "degreeCode": "1014",
                    "classCode": profile["class_code"],
                    "openYear": profile["year"],
                    "openMonth": profile["month"],
                    "subjectCode": node["subjectCode"],
                    "nationCode": "",
                    "type": "dwn",
                },
                timeout=(20, 60),
            )
            file_response.raise_for_status()
            files = file_response.json().get("data", {}).get("invFiles", [])
            subject_folder = safe_name(f"{node['subjectCode']}_{node['title']}")
            for item in files:
                filename = safe_name(item["fileOrg"])
                url = (
                    "https://ncic.re.kr/inv/org/download.do"
                    f"?year={item['openYear']}&seq={item['orgAttNo']}&orgType=org"
                )
                tasks.append(
                    DownloadTask(
                        url,
                        f"data/reference_sources/raw/{profile['folder']}/{subject_folder}/{filename}",
                        "국가교육위원회·한국교육과정평가원(NCIC)",
                        source_page,
                        profile["group"],
                        profile["notice"],
                        profile["effective"],
                        profile["license"],
                    )
                )
    return tasks


def prism_selection_report_tasks() -> list[DownloadTask]:
    source_page = (
        "https://nkis.re.kr/prism_api_info_view.do?otpSeq=0&popup=P"
        "&researchId=1342000-202400063"
    )
    session = make_session()
    response = session.get(source_page, timeout=(20, 60))
    response.raise_for_status()
    text = html.unescape(response.text)
    urls = re.findall(r"loginChk\('([^']*downloadFile\?[^']+)'\)", text)
    tasks: list[DownloadTask] = []
    seen: set[str] = set()
    for url in urls:
        url = url.replace("&amp;", "&")
        if url in seen:
            continue
        seen.add(url)
        query = parse_qs(urlsplit(url).query)
        filename = unquote(query.get("orgnlAtchFileNm", ["report.pdf"])[0])
        filename = safe_name(filename)
        tasks.append(
            DownloadTask(
                url,
                f"data/reference_sources/raw/achievement_levels_2022/selection_reports_2025/{filename}",
                "교육부·한국교육과정평가원(PRISM/NKIS)",
                source_page,
                "2022 개정 고등학교 선택과목 성취수준 개발 연구",
                "2025 최종보고서",
                "2025",
                "공공누리 제1유형(출처표시)",
                "achievement_level_support",
            )
        )
    if len(tasks) < 30:
        raise RuntimeError(f"PRISM attachment discovery returned only {len(tasks)} files")
    tasks.append(
        DownloadTask(
            source_page,
            "data/reference_sources/catalog/nkis_prism_selection_reports_project.html",
            "국가정책연구포털(NKIS/PRISM)",
            source_page,
            "성취수준 연구보고서 카탈로그",
            "2026-07-23 조회 스냅샷",
            license_note="원문 목록 및 공공누리 조건 스냅샷",
            role="catalog_snapshot",
        )
    )
    return tasks


def prism_common_report_tasks() -> list[DownloadTask]:
    source_page = (
        "https://nkis.re.kr/prism_api_info_view.do?otpSeq=0&popup=P"
        "&researchId=1342000-202300091"
    )
    session = make_session()
    response = session.get(source_page, timeout=(20, 60))
    response.raise_for_status()
    text = html.unescape(response.text)
    urls = re.findall(r"loginChk\('([^']*downloadFile\?[^']+)'\)", text)
    tasks: list[DownloadTask] = []
    seen: set[str] = set()
    for url in urls:
        url = url.replace("&amp;", "&")
        if url in seen:
            continue
        seen.add(url)
        query = parse_qs(urlsplit(url).query)
        filename = unquote(query.get("orgnlAtchFileNm", ["report.pdf"])[0])
        filename = safe_name(filename)
        tasks.append(
            DownloadTask(
                url,
                f"data/reference_sources/raw/achievement_levels_2022/common_reports_2024/{filename}",
                "교육부·한국교육과정평가원(PRISM/NKIS)",
                source_page,
                "2022 개정 고등학교 공통과목·중고 합본과목 성취수준 개발 연구",
                "2024 최종보고서",
                "2024",
                "공공누리 제1유형(출처표시)",
                "achievement_level_support",
            )
        )
    if len(tasks) != 9:
        raise RuntimeError(f"PRISM common-course discovery returned {len(tasks)} files, expected 9")
    tasks.append(
        DownloadTask(
            source_page,
            "data/reference_sources/catalog/nkis_prism_common_reports_project.html",
            "국가정책연구포털(NKIS/PRISM)",
            source_page,
            "공통과목·중고 합본과목 성취수준 연구보고서 카탈로그",
            "2026-07-23 조회 스냅샷",
            license_note="원문 목록 및 공공누리 제1유형 조건 스냅샷",
            role="catalog_snapshot",
        )
    )
    return tasks


def kcue_admission_tasks() -> list[DownloadTask]:
    pages = [
        (
            "https://www.kcue.or.kr/news/sub02/sub01.php?at=view&idx=2764740",
            "2028학년도 대학입학전형기본사항(2026-03 개정 포함)",
        ),
        (
            "https://www.kcue.or.kr/news/sub02/sub01.php?at=view&idx=2765091",
            "2028학년도 대학입학전형시행계획 주요사항",
        ),
    ]
    session = make_session()
    tasks: list[DownloadTask] = []
    for source_page, version in pages:
        response = session.get(source_page, timeout=(20, 60))
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        idx = parse_qs(urlsplit(source_page).query)["idx"][0]
        found = 0
        for anchor in soup.select("a[href*='at=download']"):
            href = urljoin(source_page, anchor.get("href", ""))
            label = " ".join(anchor.get_text(" ", strip=True).split())
            match = re.search(r"(.+?\.(?:pdf|hwp|hwpx|zip|docx|pptx))(?=\s|$)", label, re.I)
            if not match:
                continue
            filename = safe_name(match.group(1))
            tasks.append(
                DownloadTask(
                    href,
                    f"data/reference_sources/raw/admissions_2028/kcue_{idx}_{filename}",
                    "한국대학교육협의회",
                    source_page,
                    "2028학년도 대학입학전형",
                    version,
                    "2028학년도",
                    "대교협 공식 게시물; 재이용 조건 별도 확인",
                    "admission_policy_reference",
                )
            )
            found += 1
        if found == 0:
            raise RuntimeError(f"No KCUE attachments discovered at {source_page}")
        tasks.append(
            DownloadTask(
                source_page,
                f"data/reference_sources/catalog/kcue_{idx}.html",
                "한국대학교육협의회",
                source_page,
                "2028학년도 대학입학전형 카탈로그",
                "2026-07-23 조회 스냅샷",
                license_note="원문이 아닌 공식 게시 페이지 스냅샷",
                role="catalog_snapshot",
            )
        )
    return tasks


def deduplicate(tasks: Iterable[DownloadTask]) -> list[DownloadTask]:
    result: list[DownloadTask] = []
    seen_paths: set[str] = set()
    for task in tasks:
        if task.relative_path in seen_paths:
            continue
        seen_paths.add(task.relative_path)
        result.append(task)
    return result


def write_manifest(records: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": "2026-07-23",
        "corpus_root": str(DATA_ROOT.relative_to(REPO_ROOT)),
        "source_of_truth_rule": (
            "법정 성취기준 코드·문구는 교과 교육과정 별책을 기준으로 하며, "
            "성취수준 연구보고서는 평가·설계 보조 근거로만 사용한다."
        ),
        "current_curriculum_composition": (
            "2022-33 원고시 + 2024-3 일부개정 + 2026-1 현행 총론/고등학교 교육과정"
        ),
        "records": sorted(records, key=lambda item: item["local_path"]),
        "errors": errors,
        "totals": {
            "files": len(records),
            "bytes": sum(item["bytes"] for item in records),
            "errors": len(errors),
        },
    }
    temp_path = MANIFEST_PATH.with_suffix(".json.part")
    with temp_path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temp_path, MANIFEST_PATH)


def main() -> int:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    CATALOG_ROOT.mkdir(parents=True, exist_ok=True)

    tasks: list[DownloadTask] = []
    discovery_errors: list[dict[str, str]] = []
    for name, factory in (
        ("static", static_tasks),
        ("ncic_inventory", ncic_inventory_tasks),
        ("prism_common_reports", prism_common_report_tasks),
        ("prism_selection_reports", prism_selection_report_tasks),
        ("kcue_admissions", kcue_admission_tasks),
    ):
        try:
            discovered = factory()
            tasks.extend(discovered)
            print(f"[discover] {name}: {len(discovered)} files", flush=True)
        except Exception as exc:  # continue so already-known sources are still acquired
            discovery_errors.append({"stage": name, "error": str(exc)})
            print(f"[discover:error] {name}: {exc}", file=sys.stderr, flush=True)

    tasks = deduplicate(tasks)
    records: list[dict[str, Any]] = []
    errors = list(discovery_errors)
    print(f"[download] queued: {len(tasks)} files", flush=True)

    # NCIC's achievement-level list currently leaks page-selection state across
    # simultaneous requests.  Fetch only those catalog pages serially; source
    # documents can still be verified/downloaded in parallel.
    serial_tasks = [
        task
        for task in tasks
        if "catalog/ncic_achievement_level_index_page_" in task.relative_path
    ]
    parallel_tasks = [task for task in tasks if task not in serial_tasks]
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_task = {
            executor.submit(download_one, task): task for task in parallel_tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            completed += 1
            try:
                record = future.result()
                records.append(record)
                print(
                    f"[{completed}/{len(tasks)}] {record['status']}: {record['local_path']}",
                    flush=True,
                )
            except Exception as exc:
                errors.append(
                    {
                        "stage": "download",
                        "local_path": task.relative_path,
                        "url": task.url,
                        "error": str(exc),
                    }
                )
                print(
                    f"[{completed}/{len(tasks)}] ERROR: {task.relative_path}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    for task in serial_tasks:
        completed += 1
        try:
            record = download_one(task)
            records.append(record)
            print(
                f"[{completed}/{len(tasks)}] {record['status']}: {record['local_path']}",
                flush=True,
            )
        except Exception as exc:
            errors.append(
                {
                    "stage": "download",
                    "local_path": task.relative_path,
                    "url": task.url,
                    "error": str(exc),
                }
            )
            print(
                f"[{completed}/{len(tasks)}] ERROR: {task.relative_path}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    write_manifest(records, errors)
    print(
        f"[done] files={len(records)} bytes={sum(r['bytes'] for r in records)} "
        f"errors={len(errors)} manifest={MANIFEST_PATH}",
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
