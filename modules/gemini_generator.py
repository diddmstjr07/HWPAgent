"""
Gemini API 기반 콘텐츠 생성 모듈 (REST API 버전)
"""
import os
import json
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import re

load_dotenv()


class GeminiContentGenerator:
    """Gemini API를 사용한 콘텐츠 생성 클래스 (REST 버전)"""
    
    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.7):
        """
        Args:
            model_name: 사용할 Gemini 모델명
            temperature: 생성 온도 (0.0~1.0)
        """
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        
        self.model_name = model_name
        self.temperature = temperature
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    
    def _call_api(self, prompt: str, stream: bool = False):
        """Gemini REST API 호출"""
        headers = {
            'Content-Type': 'application/json',
        }
        
        data = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }],
            "generationConfig": {
                "temperature": self.temperature,
                "topP": 0.95,
                "topK": 40,
            }
        }
        
        if stream:
            return self._call_api_stream(prompt, headers, data)
        
        try:
            response = requests.post(
                f"{self.api_url}?key={self.api_key}",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            
            # 디버그: 응답 구조 출력
            if 'candidates' in result and len(result['candidates']) > 0:
                candidate = result['candidates'][0]
                if 'content' in candidate and 'parts' in candidate['content']:
                    return candidate['content']['parts'][0]['text']
                else:
                    raise Exception(f"응답 구조 오류. 받은 데이터: {result}")
            elif 'error' in result:
                raise Exception(f"API 에러: {result['error'].get('message', '알 수 없는 오류')}")
            else:
                raise Exception(f"예상치 못한 응답 형식: {result}")
                
        except requests.exceptions.Timeout:
            raise Exception("API 요청 시간 초과 (30초)")
        except requests.exceptions.RequestException as e:
            raise Exception(f"API 요청 실패: {str(e)}")
        except KeyError as e:
            raise Exception(f"응답 파싱 오류 - 누락된 키: {str(e)}. 응답: {result if 'result' in locals() else 'N/A'}")
    
    def _call_api_stream(self, prompt: str, headers: dict, data: dict):
        """스트리밍 API 호출 (Generator)"""
        chunk_count = 0
        total_chars = 0
        last_finish_reason = None
        
        try:
            # streamGenerateContent 엔드포인트 사용
            stream_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:streamGenerateContent"
            
            response = requests.post(
                f"{stream_url}?key={self.api_key}&alt=sse",
                headers=headers,
                json=data,
                stream=True,
                timeout=120  # 2분으로 연장
            )
            response.raise_for_status()
            
            # SSE 스트림 파싱
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        json_str = line_str[6:]  # 'data: ' 제거
                        if json_str.strip() == '[DONE]':
                            print(f"[GEMINI STREAM] Received [DONE] signal")
                            break
                        try:
                            chunk = json.loads(json_str)
                            if 'candidates' in chunk and len(chunk['candidates']) > 0:
                                candidate = chunk['candidates'][0]
                                
                                # finishReason 확인
                                if 'finishReason' in candidate:
                                    last_finish_reason = candidate['finishReason']
                                    print(f"[GEMINI STREAM] Finish reason: {last_finish_reason}")
                                
                                if 'content' in candidate and 'parts' in candidate['content']:
                                    text = candidate['content']['parts'][0].get('text', '')
                                    if text:
                                        chunk_count += 1
                                        total_chars += len(text)
                                        yield text
                        except json.JSONDecodeError as e:
                            print(f"[GEMINI STREAM] JSON decode error: {e}")
                            continue
            
            # 종료 후 로그
            print(f"[GEMINI STREAM] Stream ended")
            print(f"[GEMINI STREAM] Total chunks: {chunk_count}")
            print(f"[GEMINI STREAM] Total characters: {total_chars}")
            print(f"[GEMINI STREAM] Last finish reason: {last_finish_reason}")
            
        except Exception as e:
            print(f"[GEMINI STREAM ERROR] {str(e)}")
            raise Exception(f"스트리밍 오류: {str(e)}")
    
    def generate_document_content(self, user_request: str, context: Optional[Dict[str, Any]] = None, stream: bool = False):
        """
        사용자 요청에 따라 문서 콘텐츠 생성
        
        Args:
            user_request: 사용자의 문서 생성 요청
            context: 추가 컨텍스트 정보
            
        Returns:
            생성된 콘텐츠와 메타데이터
        """
        context_str = str(context) if context else "없음"
        
        prompt_template = """당신은 전문적인 문서 작성 AI입니다. 사용자의 요청에 따라 한글 문서에 들어갈 내용을 생성합니다.

사용자 요청: {user_request}

추가 컨텍스트: {context}

⚠️ **절대적 규칙:**
1. 문서를 반드시 끝까지 완성하세요
2. 문장을 중간에 끝내지 마세요
3. 결론을 반드시 포함하세요
4. "이상입니다", "끝", "완료" 등의 마무리로 끝내세요

다음 형식으로 응답하세요:

1. 제목: [문서 제목]

2. 본문: [상세 내용 - 마크다운 형식 사용]
   - # 를 사용하여 주요 제목 표시
   - ## 를 사용하여 소제목 표시
   - **굵게** 를 사용하여 중요한 내용 강조
   - *기울임* 을 사용하여 부가 설명
   - 이미지 추가: [gen_img]검색 키워드[/gen_img] 태그 사용

📝 **문서 구조 가이드:**
- 서론 (1-2 단락)
- 본론 (2-3개 소제목, 각 2 단락)
- 결론 (1-2 단락)
- 총 분량: 1,500-2,500자 범위 (진짜 짧게 작성)

✅ **마무리 필수:**
문서 끝에 반드시 "이상으로 [제목]에 대한 설명을 마칩니다." 추가

전문적이고 명확하며 체계적인 문서를 작성하세요."""
        # 프롬프트 생성
        prompt = prompt_template.format(user_request=user_request, context=context_str)

        if stream:
            # 스트리밍 모드: generator 반환
            return self._call_api(prompt, stream=True)
        else:
            # 일반 모드
            result = self._call_api(prompt)
            parsed_content = self._parse_generated_content(result)
            return parsed_content
    
    def _parse_generated_content(self, content: str) -> Dict[str, Any]:
        """생성된 컨테츠를 구조화된 형탌로 파싱 ([gen_img] 태그 처리 포함)"""
        # 먼저 [gen_img] 태그 추출
        import re
        gen_img_pattern = r'\[gen_img\](.+?)\[/gen_img\]'
        image_keywords = re.findall(gen_img_pattern, content)
        
        lines = content.split('\n')
        parsed = {
            'title': '',
            'body': '',
            'images_needed': image_keywords if image_keywords else [],  # gen_img 태그에서 추출
            'tables_needed': []
        }
        
        current_section = None
        body_lines = []
        image_lines = []
        title_found = False
        body_started = False
        in_body_section = True  # 본문 섹션 내부인지 추적
        in_image_section = False  # 이미지 섹션 내부인지 추적
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 빈 줄은 본문에 포함 (가독성을 위해)
            if not stripped:
                if body_started and in_body_section:
                    body_lines.append('')
                continue
            
            # 제목 찾기
            if not title_found:
                if (stripped.startswith('1. 제목:') or stripped.startswith('제목:')):
                    title_text = stripped.split(':', 1)[1].strip().strip('*').strip('[]')
                    # 숫자 제거 (1., 2. 등)
                    title_text = re.sub(r'^\d+\.\s*', '', title_text)
                    parsed['title'] = title_text
                    title_found = True
                    continue
                elif i == 0 or (i == 1 and not lines[0].strip()):
                    # 첫 번째 비지 않은 줄을 제목으로
                    if not stripped.startswith('2. 본문:') and not stripped.startswith('본문:'):
                        parsed['title'] = stripped.strip('#').strip('*').strip()
                        title_found = True
                        continue
            
            # 본문 섹션 시작 표시 건너뛰기
            if stripped.startswith('2. 본문:') or stripped.startswith('본문:'):
                body_started = True
                in_body_section = True
                # 콜론 뒤에 내용이 있으면 추가
                after_colon = stripped.split(':', 1)[1].strip() if ':' in stripped else ''
                if after_colon:
                    body_lines.append(after_colon)
                continue
            
            # 이미지/표 섹션 시작하면 본문 섹션 종료 표시 (하지만 루프는 계속)
            if stripped.startswith('3. 필요한 이미지:') or stripped.startswith('필요한 이미지:'):
                in_body_section = True
                in_image_section = True
                continue
            if stripped.startswith('4. 표/데이터:') or stripped.startswith('표/데이터:'):
                in_body_section = True
                in_image_section = False
                continue
            
            # 이미지 섹션 내용 수집
            if in_image_section:
                image_lines.append(stripped)
                continue
            
            # 본문 내용 추가 (본문 섹션 내부일 때만)
            if in_body_section and (title_found or body_started):
                body_lines.append(line.rstrip())  # 원본 인덴트 보존
                body_started = True
        
        # 본문 조립
        if body_lines:
            # 연속된 빈 줄 제거
            cleaned_body = []
            prev_empty = False
            for line in body_lines:
                if not line.strip():
                    if not prev_empty and cleaned_body:  # 첫 번째 빈 줄만 유지
                        cleaned_body.append('')
                    prev_empty = True
                else:
                    cleaned_body.append(line)
                    prev_empty = False
            
            parsed['body'] = '\n'.join(cleaned_body).strip()
        
        # 이미지 키워드 추출
        if image_lines:
            parsed['images_needed'] = self._extract_image_keywords(image_lines)
        
        # 비어있으면 전체 컨텐츠 사용
        if not parsed['title']:
            # 첫 줄을 제목으로
            first_line = content.split('\n')[0].strip()
            parsed['title'] = first_line[:100] if first_line else '문서'
        
        if not parsed['body']:
            # 제목을 제외한 나머지를 본문으로
            body_content = content
            if parsed['title'] in content:
                body_content = content.split(parsed['title'], 1)[1].strip()
            parsed['body'] = body_content if body_content else content
        
        return parsed
    
    def _extract_image_keywords(self, image_lines: list) -> list:
        """이미지 설명에서 간단한 검색 키워드 추출 (영어로 변환)"""
        keywords = []
        
        # 합쳐진 텍스트
        full_text = ' '.join(image_lines)
        
        # 한영 변환 매핑 (주요 단어들)
        keyword_map = {
            '사람': 'people',
            '사람들': 'people',
            '인종': 'diverse people',
            '성별': 'people',
            '인사': 'greeting',
            '악수': 'handshake',
            '비즈니스': 'business',
            '복장': 'professional',
            '전문적': 'professional',
            '문서': 'document',
            '서론': 'introduction',
            '돋보기': 'magnifying glass',
            '아이콘': 'icon',
            '그래픽': 'graphic',
            '이메일': 'email',
            '회의': 'meeting',
            '대면': 'meeting',
            '보고서': 'report',
            '커뮤니케이션': 'communication',
            '인포그래픽': 'infographic',
            '협업': 'teamwork',
            '팀': 'team',
            '사무실': 'office',
            '기술': 'technology',
            '데이터': 'data',
            '분석': 'analysis'
        }
        
        # 키워드 추출
        found_terms = []
        for korean, english in keyword_map.items():
            if korean in full_text:
                found_terms.append(english)
                if len(found_terms) >= 3:
                    break
        
        # 각 이미지별로 분리되어 있으면 구분하여 추출
        import re
        image_items = re.split(r'[•‣\*\-]?\s*이미지\s*\d+:', full_text)
        
        for i, item in enumerate(image_items[1:], 1):  # 첫 번째는 비어있을 수 있음
            if not item.strip():
                continue
            
            # 각 이미지 설명에서 키워드 찾기
            image_keywords = []
            for korean, english in keyword_map.items():
                if korean in item:
                    if english not in image_keywords:
                        image_keywords.append(english)
            
            # 최대 2개 단어 조합
            if image_keywords:
                keywords.append(' '.join(image_keywords[:2]))
            
            if len(keywords) >= 3:
                break
        
        # 키워드가 없으면 기본값
        if not keywords:
            keywords = found_terms[:3] if found_terms else ['business', 'professional', 'teamwork']
        
        # 최대 5개
        return keywords[:5] if keywords else ['business', 'professional', 'teamwork']
    
    def refine_content(self, original_content: str, refinement_request: str) -> str:
        """
        기존 콘텐츠를 수정/개선
        
        Args:
            original_content: 원본 콘텐츠
            refinement_request: 수정 요청 사항
            
        Returns:
            수정된 콘텐츠
        """
        prompt = f"""다음 내용을 수정해주세요.

원본 내용:
{original_content}

수정 요청:
{refinement_request}

**중요 규칙:**
1. 수정된 내용만 출력하세요.
2. 원본에 [gen_img]키워드[/gen_img] 형식의 이미지 태그가 있다면, 수정된 내용에도 **반드시 동일한 위치에 동일한 형식으로** 포함시켜야 합니다.
3. 이미지 태그는 절대 삭제하거나 변경하지 마세요.

수정된 내용:"""

        result = self._call_api(prompt)
        return result.strip()
    
    def refine_content_stream(self, original_content: str, refinement_request: str):
        """
        기존 콘텐츠를 수정/개선 (스트리밍)
        
        Args:
            original_content: 원본 콘텐츠
            refinement_request: 수정 요청 사항
            
        Yields:
            수정된 콘텐츠 청크
        """
        prompt = f"""다음 내용을 수정해주세요.

원본 내용:
{original_content}

수정 요청:
{refinement_request}

**중요 규칙:**
1. 수정된 내용만 출력하세요.
2. 반드시 완성된 문장으로 끝내야 합니다.
3. 원본에 [gen_img]키워드[/gen_img] 형식의 이미지 태그가 있다면, 수정된 내용에도 **반드시 동일한 위치에 동일한 형식으로** 포함시켜야 합니다.
4. 이미지 태그는 절대 삭제하거나 변경하지 마세요.

예시:
원본: "## 환경 보호\n[gen_img]environment protection[/gen_img]\n환경을 보호해야 합니다."
수정 시: "## 환경 보호의 중요성\n[gen_img]environment protection[/gen_img]\n우리는 환경을 보호해야 합니다."

수정된 내용:"""

        # REST API 스트리밍 호출
        headers = {
            'Content-Type': 'application/json',
        }
        
        data = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "topK": 40,
                "maxOutputTokens": 8192,
            }
        }
        
        # _call_api_stream 메서드 사용
        for chunk in self._call_api_stream(prompt, headers, data):
            yield chunk
