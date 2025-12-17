#!/usr/bin/env python3
"""
리로스쿨 크롤러 모듈
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import re
from datetime import datetime
from typing import Dict, Optional, Tuple, List
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class RiroSchoolCrawler:
    """리로스쿨 포트폴리오 크롤러"""
    
    def __init__(self):
        self.driver = None
        self.base_url: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/118.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        })
    
    def _setup_driver(self):
        """Chrome 드라이버 설정"""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        
        self.driver = webdriver.Chrome(options=options)
    
    def _parse_date(self, text: str) -> Optional[str]:
        """날짜 문자열 파싱 (MM-DD 형식 -> YYYY-MM-DD)"""
        m = re.match(r"(\d{2})-(\d{2})", text)
        if m:
            try:
                return datetime.strptime(
                    f"2025-{m.group(1)}-{m.group(2)}", 
                    "%Y-%m-%d"
                ).strftime("%Y-%m-%d")
            except:
                return None
        return None
    
    def login_and_get_events(
        self,
        school_name: str,
        username: str,
        password: str,
        grade: str = "1",
        year: str = "2025"
    ) -> Dict:
        """
        리로스쿨 로그인 후 포트폴리오/수행평가 일정 수집
        
        Args:
            school_name: 학교명 (예: "okgwa" - URL에서 사용)
            username: 학생 아이디
            password: 비밀번호
            grade: 학년 (기본값: "1")
            year: 년도 (기본값: "2025")
        
        Returns:
            성공 시: {"success": True, "events": [ ... ], "events_by_date": {...}}
            실패 시: {"success": False, "error": "..."}
        """
        cookies_snapshot: List[Dict] = []
        try:
            self._setup_driver()
            self.base_url = f"https://{school_name}.riroschool.kr/"
            
            # 리로스쿨 URL 생성
            url = (
                f"https://{school_name}.riroschool.kr/portfolio.php?"
                f"club=index&action=idx&db=1551&sort=dateup"
                f"&t_year={year}&t_grade={grade}"
            )
            
            print(f"[RIRO] Accessing URL: {url}")
            self.driver.get(url)
            
            # 페이지 로드 대기
            time.sleep(2)
            
            # 로그인
            print(f"[RIRO] Logging in as {username}...")
            id_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "id"))
            )
            id_input.send_keys(username)
            
            pw_input = self.driver.find_element(By.ID, "pw")
            pw_input.send_keys(password)
            
            login_btn = self.driver.find_element(By.CLASS_NAME, "button_normal")
            login_btn.click()
            
            # 로그인 후 페이지 로드 대기
            time.sleep(3)
            
            # 이벤트 정보 수집
            print("[RIRO] Collecting events...")

            try:
                titles = self.driver.find_elements(By.CLASS_NAME, "txt")[2:]
                dates = self.driver.find_elements(By.CSS_SELECTOR, ".robo strong")
                title_list = [t.text.strip() for t in titles]
                date_list = [d.text.strip() for d in dates]
                print(title_list)
                print(date_list)
            except:
                return {
                    "success": False,
                    "error": "로그인 실패: 아이디 또는 비밀번호를 확인해주세요."
                }
            
            events_by_date: Dict[str, List[Dict]] = {}
            target_grade = f"{grade}학년"
            
            for i in range(min(len(titles), len(dates))):
                title = titles[i].text.strip()
                date = dates[i].text.strip()
                href = titles[i].get_attribute("href")
                
                # 해당 학년 필터링
                if target_grade in title:
                    date_str = self._parse_date(date)
                    if date_str:
                        entry = {
                            "title": title,
                            "url": href,
                            "raw_date": date,
                            "type": "assessment"
                        }
                        events_by_date.setdefault(date_str, []).append(entry)
            
            event_count = sum(len(v) for v in events_by_date.values())
            print(f"[RIRO] Found {event_count} events")
            cookies_snapshot = self._export_cookies()
            self.set_session_cookies(cookies_snapshot)
            preloaded_guides = self.prefetch_event_guides(events_by_date)
            events_flat = self._flatten_events(events_by_date)
            
            return {
                "success": True,
                "events": events_flat,
                "events_by_date": events_by_date,
                "school": school_name,
                "grade": grade,
                "year": year,
                "base_url": self.base_url,
                "cookies": cookies_snapshot,
                "guides": preloaded_guides
            }
            
        except Exception as e:
            print(f"[RIRO ERROR] {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }
        
        finally:
            if self.driver:
                self.driver.quit()
    
    def _extract_assignment_path(self, onclick_value: str) -> Optional[str]:
        """onclick 문자열에서 이동 경로 추출"""
        if not onclick_value:
            return None
        match = re.search(r"M_location\('([^']+)'\)", onclick_value)
        if match:
            return match.group(1)
        return None
    
    def _clean_assignment_text(self, html_fragment: str) -> str:
        """과제 안내 HTML을 간단한 텍스트로 정제"""
        if not html_fragment:
            return ""
        soup = BeautifulSoup(html_fragment, "html.parser")
        lines = []
        for element in soup.find_all(['li', 'p']):
            text = element.get_text(separator=' ', strip=True)
            if not text:
                continue
            lines.append(text)
        if not lines:
            fallback = soup.get_text(separator='\n', strip=True)
            return fallback
        return "\n".join(f"- {line}" for line in lines)
    
    def _export_cookies(self) -> List[Dict]:
        """현재 드라이버의 쿠키를 리스트로 반환"""
        if not self.driver:
            return []
        try:
            return self.driver.get_cookies()
        except Exception:
            return []
    
    def set_session_cookies(self, cookies: Optional[List[Dict]]):
        """requests 세션에 쿠키 세팅"""
        if not cookies:
            return
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            domain = cookie.get("domain")
            if not name:
                continue
            kwargs = {}
            if domain:
                kwargs["domain"] = domain.lstrip(".")
            self.session.cookies.set(name, value, **kwargs)
    
    def set_base_url(self, base_url: Optional[str]):
        if base_url:
            self.base_url = base_url.rstrip("/") + "/"
    
    def fetch_assignment_brief(self, event_url: str) -> Dict:
        """
        이벤트 상세 페이지에서 과제 제출 안내를 추출
        """
        try:
            if not event_url:
                return {"success": False, "error": "이벤트 URL이 비어 있습니다."}
            
            detail_url = event_url
            if not detail_url.startswith("http"):
                if not self.base_url:
                    return {"success": False, "error": "기준 URL 정보가 없습니다."}
                detail_url = urljoin(self.base_url, detail_url)
            
            detail_resp = self.session.get(detail_url, timeout=12)
            detail_resp.raise_for_status()
            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
            
            assignment_btn = detail_soup.select_one("a.rd_btn.blue.medium")
            if not assignment_btn:
                return {"success": False, "error": "과제 제출 버튼을 찾을 수 없습니다."}
            
            target_path = self._extract_assignment_path(assignment_btn.get("onclick"))
            if not target_path:
                return {"success": False, "error": "과제 제출 경로를 파싱할 수 없습니다."}
            
            assignment_url = urljoin(detail_url, target_path)
            assignment_resp = self.session.get(assignment_url, timeout=12)
            assignment_resp.raise_for_status()
            assignment_soup = BeautifulSoup(assignment_resp.text, "html.parser")
            
            content_div = assignment_soup.select_one(".txt.txt_content.ck-content.ckeditor_view")
            if not content_div:
                content_div = assignment_soup.select_one(".txt_content")
            
            if not content_div:
                return {"success": False, "error": "과제 안내 본문을 찾을 수 없습니다."}
            
            guide_text = self._clean_assignment_text(str(content_div))
            return {
                "success": True,
                "guide": guide_text.strip(),
                "assignment_url": assignment_url
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def prefetch_event_guides(self, events: Dict[str, List[Dict]]) -> Dict[str, Dict]:
        """이벤트 목록에 과제 가이드라인을 미리 주입"""
        guides: Dict[str, Dict] = {}
        if not events:
            return guides
        for date_key, items in events.items():
            for info in items or []:
                url = (info or {}).get("url")
                if not url:
                    continue
                detail = self.fetch_assignment_brief(url)
                if detail.get("success") and detail.get("guide"):
                    guide_payload = {
                        "guide": detail["guide"],
                        "source": detail.get("assignment_url", url),
                        "date": date_key,
                        "title": info.get("title")
                    }
                    # URL 기반 키와 날짜 기반 키 둘 다 저장 (호환성)
                    guides[url] = guide_payload
                    guides.setdefault(date_key, guide_payload)
                    info["guide"] = detail["guide"]
                    info["guide_source"] = detail.get("assignment_url", url)
        return guides
    
    def get_event_detail(self, event_url: str) -> Dict:
        """
        특정 이벤트의 상세 정보 가져오기
        
        Args:
            event_url: 이벤트 상세 페이지 URL
        
        Returns:
            이벤트 상세 정보
        """
        try:
            if not self.driver:
                self._setup_driver()
            
            self.driver.get(event_url)
            time.sleep(2)
            
            # 상세 정보 수집 (실제 구조에 맞게 수정 필요)
            content = self.driver.find_element(By.CLASS_NAME, "content")
            
            return {
                "success": True,
                "content": content.text,
                "url": event_url
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _flatten_events(self, events_by_date: Dict[str, List[Dict]]) -> List[Dict]:
        """날짜별 이벤트 딕셔너리를 단일 리스트로 변환"""
        flat: List[Dict] = []
        for date_key, items in (events_by_date or {}).items():
            for item in items or []:
                entry = dict(item or {})
                entry.setdefault("date", date_key)
                flat.append(entry)
        # 날짜순 정렬
        try:
            flat.sort(key=lambda x: x.get("date") or "")
        except Exception:
            pass
        return flat
