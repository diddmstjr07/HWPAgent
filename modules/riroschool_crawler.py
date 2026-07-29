#!/usr/bin/env python3
"""
리로스쿨 크롤러 모듈
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoAlertPresentException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
)
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
        """디버깅할 수 있도록 화면에 표시되는 Chrome 드라이버를 설정합니다."""
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        
        self.driver = webdriver.Chrome(options=options)
    
    def _consume_alert(self, timeout: float = 0) -> Optional[str]:
        """떠 있는 alert의 문구를 읽고 닫는다. 없으면 None.

        리로 로그인은 실패는 물론 '이미 로그인' 같은 안내도 alert로 띄운다.
        닫지 않으면 이후 모든 Selenium 호출이 UnexpectedAlertPresentException으로
        스택트레이스째 터지므로, 진행 전에 반드시 걷어내야 한다.
        """
        try:
            if timeout:
                WebDriverWait(self.driver, timeout).until(EC.alert_is_present())
            alert = self.driver.switch_to.alert
            text = (alert.text or '').strip()
            alert.accept()
            return text
        except (TimeoutException, NoAlertPresentException):
            return None
        except Exception:
            return None

    @staticmethod
    def _is_login_failure_alert(text: str) -> bool:
        """로그인을 막는 alert인지(= 재시도해도 소용없는지) 판단."""
        blockers = ('맞지 않습니다', '없거나', '오류', '잠금', '차단', '제한', '탈퇴', '승인')
        return any(word in text for word in blockers)

    def _parse_date(self, text: str, year: Optional[str] = None) -> Optional[str]:
        """리로스쿨의 여러 날짜 표기를 ISO 형식으로 변환합니다."""
        value = str(text or '').strip()
        if not value:
            return None

        patterns = (
            (r'(?<!\d)(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?!\d)', 'full'),
            (r'(?<!\d)(\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)', 'short'),
            (r'(?<!\d)(\d{1,2})[-./](\d{1,2})(?![-./]\d)', 'month_day'),
        )

        for pattern, kind in patterns:
            match = re.search(pattern, value)
            if not match:
                continue
            try:
                if kind == 'full':
                    parsed_year, month, day = map(int, match.groups())
                elif kind == 'short':
                    short_year, month, day = map(int, match.groups())
                    parsed_year = 2000 + short_year
                else:
                    month, day = map(int, match.groups())
                    parsed_year = int(year or datetime.now().year)
                return datetime(parsed_year, month, day).strftime('%Y-%m-%d')
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _matches_grade(title: str, grade: str) -> bool:
        normalized = re.sub(r'\s+', '', str(title or ''))
        if f'{grade}학년' in normalized:
            return True
        return any(token in normalized for token in ('전학년', '전체학년', '전교생', '전체대상'))

    def _extract_events_from_current_page(self, grade: str, year: str) -> Tuple[List[Dict], int]:
        """현재 목록 페이지에서 일정 행을 추출합니다."""
        candidates: List[Tuple[object, object]] = []
        parse_failures = 0

        # 우선 일정 컨테이너 내부에서 제목과 날짜를 함께 읽어 인덱스 불일치를 방지합니다.
        for container in self.driver.find_elements(By.CSS_SELECTOR, '.robo'):
            try:
                date_elements = container.find_elements(By.CSS_SELECTOR, 'strong')
                title_elements = container.find_elements(By.CSS_SELECTOR, 'a.txt, .txt a, a[class*="txt"]')
                if date_elements and title_elements:
                    if len(title_elements) != len(date_elements):
                        print(
                            f'[RIRO] Container alignment warning - titles: {len(title_elements)}, '
                            f'dates: {len(date_elements)}'
                        )
                    candidates.extend(zip(title_elements, date_elements))
            except StaleElementReferenceException:
                continue

        # 기존 페이지 구조용 폴백입니다. 링크가 있는 제목만 사용해 장식용 .txt를 제외합니다.
        if not candidates:
            title_elements = []
            for element in self.driver.find_elements(By.CLASS_NAME, 'txt'):
                try:
                    if element.text.strip() and element.get_attribute('href'):
                        title_elements.append(element)
                except StaleElementReferenceException:
                    continue
            date_elements = self.driver.find_elements(By.CSS_SELECTOR, '.robo strong')
            if len(title_elements) != len(date_elements):
                print(
                    f'[RIRO] Row alignment warning - titles: {len(title_elements)}, '
                    f'dates: {len(date_elements)}'
                )
            candidates = list(zip(title_elements, date_elements))

        events: List[Dict] = []
        seen = set()
        grade_match_count = 0
        for title_element, date_element in candidates:
            try:
                title = title_element.text.strip()
                raw_date = date_element.text.strip()
                href = title_element.get_attribute('href')
            except StaleElementReferenceException:
                continue

            if not title or not self._matches_grade(title, grade):
                continue
            grade_match_count += 1
            date_value = self._parse_date(raw_date, year)
            if not date_value:
                parse_failures += 1
                continue

            event_key = href or f'{date_value}:{title}'
            if event_key in seen:
                continue
            seen.add(event_key)
            events.append({
                'title': title,
                'url': href,
                'raw_date': raw_date,
                'date': date_value,
                'type': 'assignment'
            })
        print(
            f'[RIRO] Page rows: candidates={len(candidates)}, '
            f'grade_matches={grade_match_count}, parsed_events={len(events)}'
        )
        return events, parse_failures

    def _page_signature(self) -> str:
        """페이지 이동 여부 확인용으로 첫 일정들의 텍스트를 요약합니다."""
        values = []
        for element in self.driver.find_elements(By.CSS_SELECTOR, '.robo strong')[:3]:
            try:
                values.append(element.text.strip())
            except StaleElementReferenceException:
                continue
        return '|'.join(values)

    def _is_server_error_page(self) -> bool:
        """리로스쿨의 자체 500 오류 안내 페이지인지 확인합니다."""
        try:
            body_text = self.driver.find_element(By.TAG_NAME, 'body').text
        except Exception:
            return False
        normalized = re.sub(r'\s+', ' ', body_text or '').upper()
        return '500 ERROR' in normalized or '서버 내부 오류가 발생하여' in normalized

    def _find_next_page_button(self):
        selectors = (
            'a[rel="next"]',
            '.pagination .next a',
            '.pagination a.next',
            '.paging .next a',
            '.paging a.next',
            'a.next',
            'button.next',
        )
        for selector in selectors:
            for element in self.driver.find_elements(By.CSS_SELECTOR, selector):
                try:
                    classes = (element.get_attribute('class') or '').lower()
                    if element.is_displayed() and element.is_enabled() and 'disabled' not in classes:
                        return element
                except StaleElementReferenceException:
                    continue

        xpath = (
            "//a[contains(normalize-space(.), '다음') or @title='다음' "
            "or normalize-space(.)='›' or normalize-space(.)='»']"
        )
        for element in self.driver.find_elements(By.XPATH, xpath):
            try:
                classes = (element.get_attribute('class') or '').lower()
                if element.is_displayed() and element.is_enabled() and 'disabled' not in classes:
                    return element
            except StaleElementReferenceException:
                continue
        return None
    
    def login_and_get_events(
        self,
        school_name: str,
        username: str,
        password: str,
        grade: str = "1",
        year: Optional[str] = None
    ) -> Dict:
        """
        리로스쿨 로그인 후 포트폴리오/수행평가 일정 수집
        
        Args:
            school_name: 학교명 (예: "okgwa" - URL에서 사용)
            username: 학생 아이디
            password: 비밀번호
            grade: 학년 (기본값: "1")
            year: 조회 학사연도
        
        Returns:
            성공 시: {"success": True, "events": [ ... ], "events_by_date": {...}}
            실패 시: {"success": False, "error": "..."}
        """
        cookies_snapshot: List[Dict] = []
        try:
            self._setup_driver()
            self.base_url = f"https://{school_name}.riroschool.kr/"
            
            requested_year = str(year or datetime.now().year)

            # 리로스쿨이 지원하는 정렬 값(dateup)을 사용해 목록 URL 생성
            url = (
                f"https://{school_name}.riroschool.kr/portfolio.php?"
                f"club=index&action=idx&db=1551&sort=dateup"
                f"&t_year={requested_year}&t_grade={grade}"
            )
            
            print(f"[RIRO] Accessing URL: {url}")
            self.driver.get(url)
            
            # 페이지 로드 대기
            time.sleep(2)
            
            # 로그인
            print("[RIRO] Submitting login form...")
            id_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "id"))
            )
            id_input.send_keys(username)
            
            pw_input = self.driver.find_element(By.ID, "pw")
            pw_input.send_keys(password)
            
            login_btn = self.driver.find_element(By.CLASS_NAME, "button_normal")
            login_btn.click()

            # 리로는 로그인 결과를 alert으로 알린다. 먼저 걷어내고 판단한다.
            alert_text = self._consume_alert(timeout=3)
            if alert_text:
                print(f"[RIRO] Login alert: {alert_text}")
                if self._is_login_failure_alert(alert_text):
                    return {'success': False, 'error': alert_text}
                # '이미 로그인' 등 안내성 alert은 닫고 그대로 진행한다.

            # 로그인 후 일정 목록이 나타날 때까지 대기
            try:
                WebDriverWait(self.driver, 12).until(
                    lambda driver: (
                        driver.find_elements(By.CSS_SELECTOR, '.robo strong')
                        or not driver.find_elements(By.ID, 'id')
                    )
                )
            except UnexpectedAlertPresentException:
                late_alert = self._consume_alert()
                if late_alert and self._is_login_failure_alert(late_alert):
                    return {'success': False, 'error': late_alert}
            except TimeoutException:
                return {
                    'success': False,
                    'error': '로그인에 실패했거나 일정 페이지를 불러오지 못했습니다.'
                }

            if self.driver.find_elements(By.ID, 'id'):
                return {
                    'success': False,
                    'error': '리로스쿨 아이디 또는 비밀번호를 확인해 주세요.'
                }

            # 로그인 리다이렉트와 저장된 사이트 쿠키가 과거 필터를 복원할 수 있으므로,
            # 인증 완료 후 요청한 학사연도/학년/최신순 URL을 한 번 더 명시적으로 적용합니다.
            self.driver.get(url)
            try:
                WebDriverWait(self.driver, 12).until(
                    lambda driver: driver.execute_script('return document.readyState') == 'complete'
                )
            except TimeoutException:
                return {
                    'success': False,
                    'error': '일정 페이지 로딩 시간이 초과되었습니다.'
                }

            if self.driver.find_elements(By.ID, 'id'):
                return {
                    'success': False,
                    'error': '로그인 세션을 유지하지 못했습니다. 다시 시도해 주세요.'
                }
            if self._is_server_error_page():
                return {
                    'success': False,
                    'error': '리로스쿨 일정 페이지에서 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'
                }

            print("[RIRO] Collecting events...")
            events_by_date: Dict[str, List[Dict]] = {}
            collected_keys = set()
            parse_failure_count = 0
            page_count = 0
            max_pages = 20

            while page_count < max_pages:
                page_count += 1
                page_events, page_parse_failures = self._extract_events_from_current_page(
                    str(grade), requested_year
                )
                parse_failure_count += page_parse_failures
                for event in page_events:
                    event_key = event.get('url') or f"{event.get('date')}:{event.get('title')}"
                    if event_key in collected_keys:
                        continue
                    collected_keys.add(event_key)
                    events_by_date.setdefault(event['date'], []).append(event)

                next_button = self._find_next_page_button()
                if not next_button:
                    break

                previous_url = self.driver.current_url
                previous_signature = self._page_signature()
                try:
                    self.driver.execute_script('arguments[0].click();', next_button)
                    WebDriverWait(self.driver, 8).until(
                        lambda driver: (
                            driver.current_url != previous_url
                            or self._page_signature() != previous_signature
                        )
                    )
                except (StaleElementReferenceException, TimeoutException):
                    break
            
            event_count = sum(len(v) for v in events_by_date.values())
            print(
                f"[RIRO] Found {event_count} events across {page_count} page(s); "
                f"date parse failures: {parse_failure_count}"
            )
            if event_count == 0:
                print(f"[RIRO] Empty result page: {self.driver.current_url}")
                print("[RIRO] Keeping the visible Chrome window open for 20 seconds for inspection.")
                time.sleep(20)
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
                "year": requested_year,
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
