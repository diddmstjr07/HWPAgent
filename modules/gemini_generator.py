"""
Gemini API 기반 콘텐츠 생성 모듈 (REST API 버전)
"""
import os
import json
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import re
from modules.preset_templates import get_random_template

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

    def _safe_error_message(self, error: Exception) -> str:
        """
        요청/스트림 에러 메시지에서 API 키 등 민감 정보를 마스킹
        """
        message = str(error) if error else ''
        if not message:
            return "알 수 없는 오류"
        if self.api_key:
            message = message.replace(self.api_key, "***")
        message = re.sub(r"key=[A-Za-z0-9_-]+", "key=***", message)
        return message
    
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
                timeout=60
            )
            
            # 429 Too Many Requests 처리
            if response.status_code == 429:
                raise Exception("Google Gemini API 사용량 한도 초과 (Quota Exceeded). 잠시 후 다시 시도하거나 요금제를 확인하세요.")
            
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
                
        except requests.exceptions.RequestException as e:
            safe_msg = self._safe_error_message(e)
            print(f"[Gemini API Failed] {safe_msg}. Attempting fallback...")
            # Fallback to LM Studio
            return self._call_lm_studio(prompt)
        except KeyError as e:
            raise Exception(f"응답 파싱 오류 - 누락된 키: {str(e)}. 응답: {result if 'result' in locals() else 'N/A'}")
    
    def _call_api_stream(self, prompt: str, headers: dict, data: dict):
        """스트리밍 API 호출 (Generator)"""
        try:
            # streamGenerateContent 엔드포인트 사용
            stream_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:streamGenerateContent"
            
            response = requests.post(
                f"{stream_url}?key={self.api_key}&alt=sse",
                headers=headers,
                json=data,
                stream=True,
                timeout=120
            )
            
            if response.status_code == 429:
                raise Exception("Google Gemini API 사용량 한도 초과 (Quota Exceeded)")
                
            response.raise_for_status()
            
            # SSE 스트림 파싱
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        json_str = line_str[6:]
                        if json_str.strip() == '[DONE]':
                            print(f"[GEMINI STREAM] Received [DONE] signal")
                            break
                        try:
                            chunk = json.loads(json_str)
                            if 'candidates' in chunk and len(chunk['candidates']) > 0:
                                candidate = chunk['candidates'][0]
                                if 'content' in candidate and 'parts' in candidate['content']:
                                    text = candidate['content']['parts'][0].get('text', '')
                                    if text:
                                        yield text
                        except json.JSONDecodeError as e:
                            print(f"[GEMINI STREAM] JSON decode error: {e}")
                            continue
            
        except Exception as e:
            safe_msg = self._safe_error_message(e)
            error_str = str(e)
            if "Quota Exceeded" in error_str or "429" in error_str:
                print(f"[GEMINI STREAM ERROR] {safe_msg}. Quota exceeded, skipping fallback.")
                raise e # Re-raise to stop and notify caller
            
            print(f"[GEMINI STREAM ERROR] {safe_msg}. Attempting fallback...")
            # Fallback to LM Studio (Generator yield from)
            yield from self._call_lm_studio_stream(prompt, gemini_data=data)

    def _call_lm_studio(self, prompt: str, gemini_data: dict = None) -> str:
        """LM Studio (OpenAI 호환) API 호출 - 일반 (Non-streaming)"""
        print("[Fallback] Switching to LM Studio API (Non-stream)...")
        url = "http://localhost:1234/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        
        payload = self._build_lm_studio_payload(prompt, stream=False, gemini_data=gemini_data)

        try:
            response = requests.post(url, headers=headers, json=payload, stream=False, timeout=120)
            response.raise_for_status()

            result = response.json()
            return result['choices'][0]['message']['content']

        except Exception as e:
            print(f"[LM Studio Error] {e}")
            raise Exception("AI 서비스 연결 실패 (Gemini & LM Studio)")

    def _call_lm_studio_stream(self, prompt: str, gemini_data: dict = None):
        """LM Studio (OpenAI 호환) API 호출 - 스트리밍 (Generator)"""
        print("[Fallback] Switching to LM Studio API (Stream)...")
        url = "http://localhost:1234/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        
        payload = self._build_lm_studio_payload(prompt, stream=True, gemini_data=gemini_data)

        try:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith('data: ') and line_str != 'data: [DONE]':
                        try:
                            json_str = line_str[6:]
                            chunk = json.loads(json_str)
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            pass

        except Exception as e:
            print(f"[LM Studio Stream Error] {e}")
            raise Exception("AI 서비스 연결 실패 (Gemini & LM Studio)")

    def _build_lm_studio_payload(self, prompt: str, stream: bool, gemini_data: dict = None) -> dict:
        """LM Studio용 페이로드 생성"""
        messages = []
        if gemini_data and 'contents' in gemini_data:
            system_instruction = gemini_data.get("systemInstruction") or {}
            system_parts = system_instruction.get("parts") or []
            if system_parts:
                system_text = system_parts[0].get("text", "")
                if system_text:
                    messages.append({"role": "system", "content": system_text})
            # Gemini 포맷을 OpenAI 포맷으로 변환
            for content in gemini_data['contents']:
                role = content.get('role', 'user')
                if role == 'model': role = 'assistant'
                
                parts = content.get('parts', [])
                text = ""
                if parts:
                    text = parts[0].get('text', '')
                
                messages.append({"role": role, "content": text})
        else:
            messages.append({"role": "user", "content": prompt})

        return {
            "model": "local-model", 
            "messages": messages,
            "temperature": self.temperature,
            "stream": stream
        }

    def classify_intent(self, prompt: str) -> str:
        """
        사용자의 의도가 문서 생성인지 단순 채팅인지 분류
        Returns: 'document' or 'chat'
        """
        system_prompt = """
        Analyze the user's request and determine if they want to generate a formal document/report/article or if they are just chatting/asking a question.
        
        If the user asks to "write", "create", "draft", "generate" a "report", "document", "blog post", "article", "essay", "letter", "proposal", etc., return "document".
        If the user says "hello", asks a question like "what is...", "explain...", "translate...", or just chats, return "chat".
        
        Output ONLY one word: "document" or "chat".
        """
        
        try:
            # 동기식 호출 사용
            response = self._call_api(f"{system_prompt}\n\nUser Request: {prompt}")
            result = response.strip().lower()
            if "document" in result:
                return "document"
            return "chat"
        except Exception as e:
            print(f"[Intent Classification Failed] {e}")
            return "chat"  # 기본값

    def generate_chat_stream(self, prompt: str, history: list = None, system_prompt: Optional[str] = None):
        """이전 대화 맥락을 포함하여 스트리밍"""
        headers = {
            'Content-Type': 'application/json',
        }
        
        contents = []
        if history:
            for msg in history:
                # API expects 'user' or 'model' roles
                role = "user" if msg.get("role") == "user" else "model"
                text = msg.get("text", "")
                if text:
                    contents.append({
                        "role": role,
                        "parts": [{"text": text}]
                    })
        
        # Add current prompt
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "topP": 0.95,
                "topK": 40,
            }
        }
        if system_prompt:
            data["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        # [Fix] Pass the constructed data payload to the stream handler
        return self._call_api_stream(prompt, headers, data=data)
    
    def generate_document_content(
        self,
        user_request: str,
        context: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        document_template: Optional[str] = None
    ):
        """
        사용자 요청에 따라 문서 콘텐츠 생성
        
        Args:
            user_request: 사용자의 문서 생성 요청
            context: 추가 컨텍스트 정보
            
        Returns:
            생성된 콘텐츠와 메타데이터
        """
        context_str = str(context) if context else "없음"

        def _escape_braces(value: str) -> str:
            return value.replace('{', '{{').replace('}', '}}') if value else value

        # 템플릿 처리 로직: 사용자가 제공한 템플릿이 없으면 랜덤 프리셋 적용
        template_name = "사용자 지정"
        if not document_template:
            template_name, document_template = get_random_template()
            print(f"[TEMPLATE] Selected preset: {template_name}")

        safe_context = _escape_braces(context_str)
        safe_request = _escape_braces(user_request)
        safe_template_text = _escape_braces(document_template)
        
        structure_guide = f"선택된 문서 양식인 '{template_name}'의 구조와 목차를 반드시 따르세요. 제공된 양식에 맞춰 내용을 작성해야 합니다."

        template_block = f"""
📋 **적용할 문서 양식: {template_name}**
{safe_template_text}

위 내용은 문서 작성을 위한 '필수 양식(Template)'입니다.
- 이 구조와 항목을 그대로 유지하면서 내용을 채우세요.
- 양식에 있는 대제목(#), 중제목(##) 등의 구조를 변경하지 마세요.
"""

        prompt_template = f"""당신은 전문적인 문서 작성 AI입니다. 사용자의 요청에 따라 한글 문서에 들어갈 내용을 생성합니다.

사용자 요청: {{user_request}}

추가 컨텍스트: {{context}}

⚠️ **절대적 규칙:**
1. 문서를 반드시 끝까지 완성하세요
2. 문장을 중간에 끝내지 마세요
3. **문체: 반드시 '~한다', '~이다', '~된다' 등의 해라체(평어)를 사용하세요.** ('~합니다', '~해요', '~습니다' 절대 사용 금지)

📝 **문서 구조 가이드:**
{structure_guide}

{template_block}

응답 형식:
1. 제목: [문서 제목]

2. 본문: [상세 내용 - 마크다운 형식 사용]
   - # 를 사용하여 주요 제목 표시
   - ## 를 사용하여 소제목 표시
   - **굵게** 를 사용하여 중요한 내용 강조
   - *기울임* 을 사용하여 부가 설명
   - 이미지 추가: [gen_img]검색 키워드[/gen_img] 태그 사용

전문적이고 명확하며 체계적인 문서를 작성하세요."""
        prompt = prompt_template.format(user_request=safe_request, context=safe_context)

        if stream:
            # 스트리밍 모드: generator 반환
            return self._call_api(prompt, stream=True)
        else:
            # 일반 모드
            result = self._call_api(prompt)
            parsed_content = self._parse_generated_content(result)
            return parsed_content

    def edit_html_stream(self, html: str, instruction: str):
        """HTML 템플릿을 사용자의 지시에 맞게 편집 (스트리밍)"""
        prompt = f"""당신은 한글 문서 양식 HTML을 자동으로 채우는 편집 AI입니다.

다음 규칙을 반드시 지키세요:
1. 출력은 **수정된 HTML only** 이어야 합니다. (설명/마크다운/코드펜스 금지)
2. 기존 HTML 구조, 태그, 클래스, id를 최대한 유지하세요.
3. 표와 레이아웃 구조를 삭제하지 말고, 빈 항목을 자연스럽게 채워주세요.
4. 이미지/링크/스타일 참조 경로는 가능한 한 유지하세요.

[현재 HTML]
{html}

[사용자 지시]
{instruction}

수정된 HTML만 출력하세요."""

        return self._call_api(prompt, stream=True)

    def edit_html_fragment_stream(self, fragment: str, instruction: str):
        """HTML 조각을 사용자의 지시에 맞게 편집 (스트리밍)"""
        prompt = f"""당신은 한글 문서 양식 HTML 조각을 편집하는 AI입니다.

다음 규칙을 반드시 지키세요:
1. 출력은 **수정된 HTML fragment only** 이어야 합니다. (설명/마크다운/코드펜스 금지)
2. fragment의 최상위 태그와 속성(id/class)은 유지하세요. 내부 텍스트만 자연스럽게 채워주세요.
3. 표/레이아웃 구조를 삭제하지 말고, 빈 항목만 채우세요.
4. 이미지/링크/스타일 참조 경로는 유지하세요.

[현재 HTML fragment]
{fragment}

[사용자 지시]
{instruction}

수정된 HTML fragment만 출력하세요."""

        return self._call_api(prompt, stream=True)
    
    def _parse_generated_content(self, content: str) -> Dict[str, Any]:
        """생성된 컨테츠를 구조화된 형탌로 파싱 ([gen_img] 태그 처리 포함)"""
        # 먼저 [gen_img] 태그 추출
        import re
        # [Fix] Regex corrected to match [gen_img]keyword[/gen_img] without expecting backslashes
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
            
            # 제목 찾기 (Regex로 유연하게 처리: 1. 1. 제목: 등)
            title_match = re.match(r'^(\d+\.\s*)*제목\s*:\s*(.*)', stripped)
            if not title_found:
                if title_match:
                    title_text = title_match.group(2).strip().strip('*').strip('[]')
                    # 숫자 제거 (1., 2. 등)
                    title_text = re.sub(r'^\d+\.\s*', '', title_text)
                    parsed['title'] = title_text
                    title_found = True
                    continue
                elif i == 0 or (i == 1 and not lines[0].strip()):
                    # 첫 번째 비지 않은 줄을 제목으로 (단, 다른 섹션 시작이 아닐 경우)
                    if not re.match(r'^(\d+\.\s*)*본문\s*:', stripped):
                        parsed['title'] = stripped.strip('#').strip('*').strip()
                        title_found = True
                        continue
            
            # 본문 섹션 시작 표시 건너뛰기
            body_match = re.match(r'^(\d+\.\s*)*본문\s*:\s*(.*)', stripped)
            if body_match:
                body_started = True
                in_body_section = True
                # 콜론 뒤에 내용이 있으면 추가
                after_colon = body_match.group(2).strip()
                if after_colon:
                    body_lines.append(after_colon)
                continue
            
            # 이미지/표 섹션 시작하면 본문 섹션 종료 표시 (하지만 루프는 계속)
            # 3. 필요한 이미지: or 3. 3. 필요한 이미지: 등
            if re.match(r'^(\d+\.\s*)*(필요한 이미지|이미지)\s*:', stripped):
                in_body_section = True
                in_image_section = True
                continue
            if re.match(r'^(\d+\.\s*)*(표|데이터)\s*:', stripped) or re.match(r'^(\d+\.\s*)*표/데이터\s*:', stripped):
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
