#!/usr/bin/env python3
"""
이미지 검색 모듈 - BeautifulSoup/Selenium 기반 Google 이미지 검색
"""
import os
import requests
from typing import List, Dict, Optional
from pathlib import Path
import io
import json
import time
import re
from PIL import Image
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv
import random

# .env 파일 로드
load_dotenv()

class ImageSearcher:
    """BeautifulSoup/Selenium 기반 Google 이미지 검색 및 다운로드"""

    def __init__(self, use_selenium: bool = False):
        """
        초기화
        
        Args:
            use_selenium: True면 Selenium 사용 (느리지만 정확), False면 BeautifulSoup (빠름)
        """
        self.use_selenium = use_selenium
        self.output_dir = Path("output/images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[INIT] Image Searcher initialized (mode: {'Selenium' if use_selenium else 'BeautifulSoup'})")

    # -------------------------------
    # Google 이미지 검색 (메인 메서드)
    # -------------------------------
    def search_images_google(
        self,
        query: str,
        count: int = 3,
        rights: str = "cc_publicdomain,cc_attribute,cc_sharealike,cc_noncommercial"
    ) -> List[Dict]:
        """
        Google 이미지 검색 (BeautifulSoup 또는 Selenium)
        """
        try:
            if self.use_selenium:
                return self._search_with_selenium(query, count)
            else:
                return self._search_with_beautifulsoup(query, count)
        except Exception as e:
            print(f"[ERROR] 이미지 검색 실패: {str(e)}")
            return self._get_dummy_images(query, count)
    
    # -------------------------------
    # BeautifulSoup 기반 검색 (빠름)
    # -------------------------------
    def _search_with_beautifulsoup(self, query: str, count: int) -> List[Dict]:
        """
        BeautifulSoup으로 Google 이미지 검색 페이지 파싱
        """
        print(f"[BEAUTIFULSOUP] Searching: {query}")
        
        url = f"https://www.google.com/search?q={query}&tbm=isch&hl=ko"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            results = []
            image_urls = set()  # 중복 제거용
            
            # 방법 1: 페이지 소스에서 직접 이미지 URL 추출
            # Google 이미지 검색은 JavaScript에 데이터를 포함
            html_text = response.text
            
            # 패턴 1: ["https://..."] 형식의 URL
            pattern1 = r'\["(https?://[^"]+?)"(?:,|\])'
            matches1 = re.findall(pattern1, html_text)
            
            for match in matches1:
                # 이미지 파일인지 확인 (확장자 필수)
                lower_match = match.lower()
                if any(lower_match.endswith(ext) or f"{ext}?" in lower_match for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    # Google 내부 URL 및 불필요한 도메인 제외
                    if all(blocked not in match for blocked in ['gstatic', 'googleusercontent', 'pstatic.net', 'fbcdn', 'lookaside']):
                        if match not in image_urls:
                            image_urls.add(match)
                            if len(image_urls) >= count:
                                break
            
            # 패턴 2: "https://..." 형식의 URL (더 넓은 범위)
            if len(image_urls) < count:
                pattern2 = r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp|gif)[^"]*?)"'
                matches2 = re.findall(pattern2, html_text)
                
                for match in matches2:
                    # 불필요한 도메인 필터링
                    if all(blocked not in match for blocked in ['gstatic', 'googleusercontent', 'pstatic.net', 'fbcdn', 'lookaside']):
                        # URL 정리 (파라미터 제거)
                        clean_url = match.split('?')[0] if '?' in match else match
                        
                        # 확장자 확인 (jpg, jpeg, png, webp만)
                        lower_url = clean_url.lower()
                        if any(lower_url.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            if clean_url not in image_urls:
                                image_urls.add(clean_url)
                                if len(image_urls) >= count:
                                    break
            
            # 결과 포맷팅
            for i, img_url in enumerate(list(image_urls)[:count]):
                results.append({
                    "id": f"bs_{abs(hash(img_url))}_{i}",
                    "url": img_url,
                    "thumb_url": img_url,
                    "description": f"{query} 관련 이미지 #{i+1}",
                    "author": "Google Images",
                    "author_url": url,
                    "source": "Google Images (BeautifulSoup)"
                })
            
            if len(results) > 0:
                print(f"[BEAUTIFULSOUP] ✅ Found {len(results)} images")
                for i, r in enumerate(results):
                    print(f"  [{i+1}] {r['url'][:80]}...")
                    self.download_image(url=r['url'])
                return results
            else:
                print(f"[BEAUTIFULSOUP] ❌ No images found, using fallback")
                return self._get_dummy_images(query, count)
                
        except Exception as e:
            print(f"[BEAUTIFULSOUP ERROR] {str(e)}")
            import traceback
            traceback.print_exc()
            return self._get_dummy_images(query, count)
    
    # -------------------------------
    # Selenium 기반 검색 (느리지만 정확)
    # -------------------------------
    def _search_with_selenium(self, query: str, count: int) -> List[Dict]:
        """
        Selenium으로 Google 이미지 검색 결과 추출
        """
        print(f"[SELENIUM] Searching: {query}")
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')  # 백그라운드 실행
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            url = f"https://www.google.com/search?q={query}&tbm=isch&hl=ko"
            driver.get(url)
            
            # 페이지 로딩 대기
            time.sleep(2)
            
            # 이미지 썸네일 클릭하여 원본 URL 추출
            results = []
            thumbnails = driver.find_elements(By.CSS_SELECTOR, 'img.rg_i')
            
            for i, thumb in enumerate(thumbnails[:count * 2]):  # 여유있게 더 많이 시도
                if len(results) >= count:
                    break
                    
                try:
                    thumb.click()
                    time.sleep(0.5)
                    
                    # 큰 이미지 찾기
                    large_images = driver.find_elements(By.CSS_SELECTOR, 'img.n3VNCb')
                    for img in large_images:
                        src = img.get_attribute('src')
                        if src and src.startswith('http') and 'gstatic' not in src:
                            results.append({
                                "id": f"sel_{abs(hash(src))}_{i}",
                                "url": src,
                                "thumb_url": src,
                                "description": f"{query} 관련 이미지 #{len(results)+1}",
                                "author": "Google Images",
                                "author_url": url,
                                "source": "Google Images (Selenium)"
                            })
                            break
                except Exception as e:
                    continue
            
            print(f"[SELENIUM] Found {len(results)} images")
            return results if len(results) > 0 else self._get_dummy_images(query, count)
            
        except Exception as e:
            print(f"[SELENIUM ERROR] {str(e)}")
            return self._get_dummy_images(query, count)
        finally:
            if driver:
                driver.quit()

    # -------------------------------
    # Unsplash API 폴백 (무료, 키 불필요)
    # -------------------------------
    def _search_unsplash(self, query: str, count: int) -> List[Dict]:
        """Unsplash 무료 API로 이미지 검색"""
        print(f"[UNSPLASH] Searching: {query}")
        
        try:
            url = f"https://api.unsplash.com/search/photos"
            params = {
                "query": query,
                "per_page": count,
                "client_id": "hNDM9FlwP-xGQo5FNVdTYDqIgJ9d6YaJyL7R-pFT8yA"  # Demo key (공개)
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get('results', []):
                results.append({
                    "id": item['id'],
                    "url": item['urls']['regular'],
                    "thumb_url": item['urls']['thumb'],
                    "description": item.get('alt_description', query),
                    "author": item['user']['name'],
                    "author_url": item['user']['links']['html'],
                    "source": "Unsplash"
                })
            
            if len(results) > 0:
                print(f"[UNSPLASH] ✅ Found {len(results)} images")
                return results
            else:
                print(f"[UNSPLASH] No results, using Lorem Picsum")
                return self._get_lorem_picsum(query, count)
                
        except Exception as e:
            print(f"[UNSPLASH ERROR] {str(e)}")
            return self._get_lorem_picsum(query, count)
    
    # -------------------------------
    # Lorem Picsum 폴백 (항상 작동)
    # -------------------------------
    def _get_lorem_picsum(self, query: str, count: int) -> List[Dict]:
        """Lorem Picsum 랜덤 이미지"""
        print(f"[LOREM PICSUM] Generating {count} fallback images")
        dummy_images = []
        for i in range(count):
            seed = abs(hash(query + str(i))) % 1000
            dummy_images.append({
                "id": f"picsum_{seed}",
                "url": f"https://picsum.photos/seed/{seed}/800/600",
                "thumb_url": f"https://picsum.photos/seed/{seed}/400/300",
                "description": f"{query} 관련 이미지",
                "author": "Lorem Picsum",
                "author_url": "https://picsum.photos",
            })
        return dummy_images
    
    def _get_dummy_images(self, query: str, count: int) -> List[Dict]:
        """Unsplash 또는 Lorem Picsum 대체 이미지 (호환성용)"""
        # Unsplash 먼저 시도
        return self._search_unsplash(query, count)

    # -------------------------------
    # 이미지 다운로드
    # -------------------------------
    def download_image(
        self,
        url: str,
        save_path: Optional[str] = None,
        max_width: int = 1200,
        retry: int = 3
    ) -> Optional[str]:
        """이미지 다운로드 및 리사이징 (403 에러 자동 처리 포함)"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
        ]

        headers = {
            'User-Agent': random.choice(user_agents),
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': random.choice(['https://www.google.com/', 'https://images.google.com/', 'https://www.bing.com/images']),
            'Connection': 'keep-alive',
        }

        for attempt in range(retry):
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 403:
                    print(f"[WARN] 403 Forbidden ({attempt+1}/{retry}) → 재시도 중...")
                    time.sleep(1.5 * (attempt + 1))
                    headers['User-Agent'] = random.choice(user_agents)  # 다른 UA로 재시도
                    continue
                response.raise_for_status()

                img = Image.open(io.BytesIO(response.content))

                # 리사이징
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                # RGBA → RGB 변환 처리
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')

                # 저장 경로 생성
                if save_path:
                    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                    img.save(save_path, quality=85, optimize=True)
                    print(f"[SAVE] {save_path}")
                    return save_path

                return None

            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Image download attempt {attempt+1}/{retry} failed: {e}")
                time.sleep(1.0 * (attempt + 1))

        # 모든 재시도 실패 시 폴백 이미지 반환
        print(f"[FAIL] 이미지 다운로드 실패 (403 or network). Unsplash fallback 시도.")
        fallback = self._get_dummy_images("fallback", 1)
        return self.download_image(fallback[0]["url"], save_path) if fallback else None
    # -------------------------------
    # 문서용 이미지 일괄 다운로드
    # -------------------------------
    def download_images_for_document(
        self,
        queries: List[str],
        count_per_query: int = 1
    ) -> Dict[str, List[str]]:
        """여러 키워드에 대한 이미지 일괄 다운로드"""
        results = {}
        for query in queries:
            images = self.search_images_google(query, count=count_per_query)
            paths = []
            for i, img_info in enumerate(images):
                filename = f"{query.replace(' ', '_')}_{i+1}.jpg"
                save_path = str(self.output_dir / filename)
                saved = self.download_image(img_info["url"], save_path)
                if saved:
                    paths.append(saved)
            results[query] = paths
        return results


# -------------------------------
# 예시 실행
# -------------------------------
if __name__ == "__main__":
    searcher = ImageSearcher()
    results = searcher.search_images_google("End to End Deep learning model", count=3)
    for img in results:
        print(f"[{img['title']}] {img['url']}")
