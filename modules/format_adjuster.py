"""
LangChain 기반 서식 조정 모듈
사용자의 자연어 요청을 받아 문서 서식을 수정
"""
import os
import re
from typing import Dict, Any
from dotenv import load_dotenv
import requests
import json

load_dotenv()


class FormatAdjuster:
    """LangChain을 사용한 서식 조정 클래스"""
    
    def __init__(self, model_name: str = "gemini-2.0-flash-exp", temperature: float = 0.3):
        """
        Args:
            model_name: 사용할 Gemini 모델명
            temperature: 생성 온도 (낮을수록 일관성 있음)
        """
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY가 설정되지 않았습니다.")
        
        self.model_name = model_name
        self.temperature = temperature
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    
    def adjust_format(self, content: str, request: str) -> str:
        """
        사용자 요청에 따라 문서 서식 조정
        
        Args:
            content: 원본 마크다운 문서 내용
            request: 서식 조정 요청 (예: "1페이지 첫 문단 볼드처리")
        
        Returns:
            서식이 조정된 마크다운 문서
        """
        prompt = self._create_format_prompt(content, request)
        
        try:
            response = self._call_api(prompt)
            return self._extract_formatted_content(response, content)
        except Exception as e:
            print(f"[FORMAT ADJUSTER] Error: {e}")
            return content  # 실패 시 원본 반환
    
    def _create_format_prompt(self, content: str, request: str) -> str:
        """서식 조정 프롬프트 생성"""
        prompt = f"""당신은 문서 서식 전문가입니다. 사용자의 요청에 따라 마크다운 문서의 서식을 정확하게 수정하세요.

**원본 문서:**
```
{content}
```

**사용자 요청:**
{request}

**지시사항:**
1. 사용자의 요청을 정확히 이해하고 해당 부분만 수정하세요
2. 마크다운 문법을 사용하여 서식을 적용하세요:
   - **굵게**: `**텍스트**`
   - *기울임*: `*텍스트*`
   - 제목: `# 제목`, `## 제목`, `### 제목`
3. 요청하지 않은 부분은 절대 변경하지 마세요
4. 수정된 전체 문서를 출력하세요 (설명 없이 문서만)

**출력 형식:**
수정된 마크다운 문서만 출력하고, 어떤 설명도 추가하지 마세요.
"""
        return prompt
    
    def _call_api(self, prompt: str) -> str:
        """Gemini API 호출"""
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
                "maxOutputTokens": 8192,
            }
        }
        
        response = requests.post(
            f"{self.api_url}?key={self.api_key}",
            headers=headers,
            json=data,
            timeout=30
        )
        response.raise_for_status()
        
        result = response.json()
        
        if 'candidates' in result and len(result['candidates']) > 0:
            candidate = result['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                return candidate['content']['parts'][0]['text']
        
        raise Exception("API 응답이 비어있습니다")
    
    def _extract_formatted_content(self, response: str, original: str) -> str:
        """
        API 응답에서 서식이 적용된 문서 추출
        
        Args:
            response: API 응답
            original: 원본 문서 (실패 시 폴백용)
        
        Returns:
            추출된 문서
        """
        # 코드 블록으로 감싸진 경우 제거
        if '```' in response:
            # ```markdown ... ``` 또는 ``` ... ``` 패턴 찾기
            match = re.search(r'```(?:markdown)?\n(.*?)\n```', response, re.DOTALL)
            if match:
                return match.group(1).strip()
        
        # 코드 블록이 없으면 전체 응답 사용
        cleaned = response.strip()
        
        # 빈 응답이면 원본 반환
        if not cleaned or len(cleaned) < 10:
            return original
        
        return cleaned
