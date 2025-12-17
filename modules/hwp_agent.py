"""
LangChain 기반 HWP 문서 생성 에이전트 (문단별 연관 이미지 삽입)
"""
from typing import Dict, Any, List, Optional
from langchain.agents import Tool
from langchain_google_genai import ChatGoogleGenerativeAI

from .gemini_generator import GeminiContentGenerator
from .hwp_handler import HWPHandler
from .image_searcher import ImageSearcher

import os
from pathlib import Path
import requests
import re


class HWPAgent:
    """한글 문서 자동 생성 에이전트"""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.content_generator = GeminiContentGenerator()
        self.hwp_handler = HWPHandler(output_dir=output_dir)
        self.searcher = ImageSearcher()

        self.tools = self._create_hwpx_tools()

    # ---------------------------------------------------------------
    def _create_hwpx_tools(self) -> List[Tool]:
        tools = [
            Tool(
                name="generate_content",
                func=self._generate_content_tool,
                description="사용자 요청에 따라 문서 콘텐츠를 생성합니다."
            ),
            Tool(
                name="create_hwpx_document",
                func=self._create_hwpx_tools,
                description="HWPX 형식 문서를 생성합니다."
            ),
        ]
        return tools

    # ---------------------------------------------------------------
    def _generate_content_tool(self, user_request: str) -> str:
        try:
            result = self.content_generator.generate_document_content(user_request)
            return f"제목: {result['title']}\n본문: {result['body'][:200]}..."
        except Exception as e:
            return f"콘텐츠 생성 실패: {e}"

    # ---------------------------------------------------------------
    def _download_image(self, url: str, idx: int) -> Optional[str]:
        """이미지를 다운로드하고 로컬 경로 반환"""
        try:
            file_path = self.output_dir / f"paragraph_{idx}.png"
            saved = self.searcher.download_image(
                url,
                save_path=str(file_path),
                max_width=1200
            )
            if saved:
                print(f"📸 문단 {idx} 이미지 저장 완료: {saved}")
                return saved
        except Exception as e:
            print(f"⚠️ 이미지 다운로드 실패: {e}")
        return None

    # ---------------------------------------------------------------
    def process_request(
        self,
        user_request: str,
        output_format: str = "hwpx",
        context: Optional[Dict[str, Any]] = None,
        document_template: Optional[str] = None,
        input_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        본문 문단별 연관 이미지 삽입 + 문서 생성
        """
        try:
            # 컨텍스트 초기화
            if context is None:
                context = {}
            
            # 입력 파일 처리 및 컨텍스트 추가
            if input_files:
                print("📂 입력 파일 분석 중...")
                file_contents = []
                for file_path in input_files:
                    try:
                        print(f"   - 파일 읽는 중: {file_path}")
                        content = self.hwp_handler.read_hwp(file_path)
                        if content:
                            file_contents.append(f"--- 파일명: {Path(file_path).name} ---\n{content}\n---------------------------")
                        else:
                            print(f"   ⚠️ 파일 내용이 비어있거나 읽을 수 없습니다: {file_path}")
                    except Exception as e:
                        print(f"   ❌ 파일 읽기 실패 ({file_path}): {e}")
                
                if file_contents:
                    combined_content = "\n\n".join(file_contents)
                    # 컨텍스트에 추가 (기존 키가 있으면 병합하거나 새 키 사용)
                    context['reference_documents'] = combined_content
                    print(f"✅ {len(file_contents)}개 파일 내용 컨텍스트에 추가됨.")

            print("📝 Gemini API로 콘텐츠 생성 중...")
            result = self.content_generator.generate_document_content(
                user_request,
                context,
                document_template=document_template
            )

            title = result.get("title", "문서")
            body = result.get("body", "")
            tables = result.get("tables_needed", [])

            print(f"✅ 콘텐츠 생성 완료: {title}")

            # ---------------------------------------------------
            # 1️⃣ 문단 분리
            # ---------------------------------------------------
            paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]

            images_for_doc = []
            enhanced_body = ""

            # ---------------------------------------------------
            # 2️⃣ 각 문단에 대한 이미지 검색 및 삽입
            # ---------------------------------------------------
            for idx, para in enumerate(paragraphs):
                enhanced_body += para + "\n\n"

                # 문단별 핵심 키워드 추출 (앞부분 또는 명사 중심)
                keyword = self._extract_keyword_from_paragraph(para)
                print("------------------------------------------------------------------")
                print(keyword)
                print(f"🔍 문단 {idx+1} 키워드: {keyword}")

                search_results = self.searcher.search_images(query=keyword, count=1)
                if search_results:
                    img_url = search_results[0].get("url")
                    local_path = self._download_image(img_url, idx)
                    if local_path:
                        images_for_doc.append(local_path)
                        # 이미지 삽입 마커 추가
                        enhanced_body += f"##(image:{idx})\n\n"

            # ---------------------------------------------------
            # 3️⃣ HWP 문서 생성
            # ---------------------------------------------------
            print("📄 HWPX 문서 생성 중...")

            output_path = self.hwp_handler.create_hwpx_document(
                title=title,
                content=enhanced_body,
                images=images_for_doc,
                tables=tables,
                filename=f"{title}.hwpx"
            )

            print(f"✅ 문서 생성 완료: {output_path}")

            return {
                "success": True,
                "title": title,
                "output_path": output_path,
                "image_count": len(images_for_doc),
                "preview": enhanced_body[:250] + "..."
            }

        except Exception as e:
            print(f"❌ 오류 발생: {str(e)}")
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------
    def _extract_keyword_from_paragraph(self, text: str) -> str:
        """
        간단한 키워드 추출 (앞 문장 명사형 또는 핵심 단어)
        """
        # 문장 분리
        sentences = re.split(r"[.!?]", text)
        first_sentence = sentences[0].strip() if sentences else text

        # 명사 또는 주요 단어 추출
        words = re.findall(r"[가-힣a-zA-Z0-9]{2,}", first_sentence)
        if not words:
            return "일반 개념"
        # 2~3단어로 제한
        return " ".join(words[:3])


# ---------------------------------------------------------------
if __name__ == "__main__":
    agent = HWPAgent()
    result = agent.process_request(
        user_request="인공지능 기술이 의료 영상 진단 분야에서 어떻게 사용되는지에 대한 보고서 작성",
        output_format="hwpx"
    )
    print(result)
