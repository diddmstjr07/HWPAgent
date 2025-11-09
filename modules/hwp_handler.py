"""
HWP (워드 기반 한글 문서) 파일 생성 모듈 (함초롬바탕 버전)
- 내부는 DOCX 기반이지만 확장자만 .hwp로 저장됨
- 한글, 워드 모두에서 정상적으로 열림
- 줄간 간격 100pt, 본문 양쪽 정렬, 이미지 중앙 정렬
- 폰트: 함초롬바탕 (HCR Batang)
"""

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from pathlib import Path
from typing import Optional, Dict, Any, List
import os


class HWPHandler:
    """DOCX 기반 HWP 문서 생성기 (한글에서도 열림)"""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def create_hwp_document(
        self,
        title: str,
        content: str,
        style_config: Optional[Dict[str, Any]] = None,
        filename: Optional[str] = None,
        images: Optional[List[str]] = None
    ) -> str:
        """HWP 문서 생성 (DOCX 구조 기반, .hwp 확장자)"""
        if style_config is None:
            style_config = {
                'font_name': '함초롬바탕',
                'font_name_english': 'Times New Roman',
                'font_size': 11,
                'title_size': 22,
                'heading_size': 16,
                'line_spacing': 100,
                'paragraph_spacing': 8,
                'margin_top': 2.5,
                'margin_bottom': 2.5,
                'margin_left': 2.5,
                'margin_right': 2.5
            }

        if filename is None:
            filename = f"{title}.hwp"
        elif not filename.endswith(".hwp"):
            filename += ".hwp"

        output_path = self.output_dir / filename

        doc = Document()
        self._set_page_margins(doc, style_config)
        self._set_default_style(doc, style_config)

        self._create_cover(doc, title, style_config)
        self._add_content(doc, content, style_config, images)

        temp_path = output_path.with_suffix(".docx")
        doc.save(temp_path)
        temp_path.rename(output_path)

        print(f"✅ HWP 문서 생성 완료: {output_path}")
        return str(output_path)

    # --------------------------------------------------------------
    # 내부 메서드
    # --------------------------------------------------------------
    def _set_page_margins(self, doc: Document, config: Dict[str, Any]):
        for section in doc.sections:
            section.top_margin = Cm(config.get('margin_top', 2.5))
            section.bottom_margin = Cm(config.get('margin_bottom', 2.5))
            section.left_margin = Cm(config.get('margin_left', 2.5))
            section.right_margin = Cm(config.get('margin_right', 2.5))

    def _set_default_style(self, doc: Document, config: Dict[str, Any]):
        style = doc.styles['Normal']
        font = style.font
        font.name = config.get('font_name_english', 'Times New Roman')
        font.size = Pt(config.get('font_size', 11))

        font_name_korean = config.get('font_name', '함초롬바탕')
        if hasattr(style._element, 'rPr') and style._element.rPr is not None:
            style._element.rPr.rFonts.set(qn('w:eastAsia'), font_name_korean)

        paragraph_format = style.paragraph_format
        paragraph_format.line_spacing = Pt(config.get('line_spacing', 100))
        paragraph_format.space_after = Pt(config.get('paragraph_spacing', 8))
        paragraph_format.space_before = Pt(0)
        paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def _create_cover(self, doc: Document, title: str, config: Dict[str, Any]):
        for _ in range(6):
            doc.add_paragraph()

        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title_para.add_run(title)
        title_run.bold = True
        title_run.font.size = Pt(config.get('title_size', 22))
        title_run.font.name = config.get('font_name_english', 'Times New Roman')
        title_run.font.color.rgb = RGBColor(20, 20, 20)
        title_run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))

        subtitle = doc.add_paragraph("기술 보고서 / Research Report")
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = subtitle.add_run()
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor(100, 100, 100)
        run.font.name = config.get('font_name_english', 'Times New Roman')
        run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))

        for _ in range(2):
            doc.add_paragraph()
        doc.add_page_break()

    def _add_content(self, doc: Document, content: str, config: Dict[str, Any], images: Optional[List[str]] = None):
        lines = content.split('\n')
        image_index = 0
        for i, line in enumerate(lines):
            original_line = line
            line = line.strip()
            if not line:
                doc.add_paragraph()
                continue
            if line.startswith('#'):
                is_level2_heading = original_line.strip().startswith('##') and not original_line.strip().startswith('###')
                self._add_heading(doc, line, config)
                if images and image_index < len(images) and is_level2_heading:
                    self._add_image(doc, images[image_index], config)
                    image_index += 1
            elif line.startswith('- ') or line.startswith('* '):
                self._add_list_item(doc, line[2:], config)
            elif line[0].isdigit() and '. ' in line:
                self._add_numbered_item(doc, line, config)
            else:
                self._add_paragraph(doc, line, config)

    def _add_heading(self, doc: Document, line: str, config: Dict[str, Any]):
        level = line.count('#')
        text = line.strip('#').strip()
        heading = doc.add_heading(text, level=min(level, 3))
        heading.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for run in heading.runs:
            run.font.name = config.get('font_name', '함초롬바탕')
            run.font.size = Pt(config.get('heading_size', 16) - (level * 2))
            run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
            run.font.color.rgb = RGBColor(0, 0, 0)

    def _add_list_item(self, doc: Document, text: str, config: Dict[str, Any]):
        para = doc.add_paragraph(text, style='List Bullet')
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for run in para.runs:
            run.font.name = config.get('font_name', '함초롬바탕')
            run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
            run.font.size = Pt(config.get('font_size', 11))

    def _add_numbered_item(self, doc: Document, text: str, config: Dict[str, Any]):
        para = doc.add_paragraph(text, style='List Number')
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for run in para.runs:
            run.font.name = config.get('font_name', '함초롬바탕')
            run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
            run.font.size = Pt(config.get('font_size', 11))

    def _add_paragraph(self, doc: Document, text: str, config: Dict[str, Any]):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.line_spacing = Pt(config.get('line_spacing', 100))
        self._add_formatted_text(para, text, config)

    def _add_formatted_text(self, para, text: str, config: Dict[str, Any]):
        import re
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|__.*?__|_.*?_)', text)
        for part in parts:
            if not part:
                continue
            run = para.add_run(part.strip('*_'))
            run.font.name = config.get('font_name_english', 'Times New Roman')
            run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
            run.font.size = Pt(config.get('font_size', 11))
            if part.startswith('**') or part.startswith('__'):
                run.bold = True
            elif part.startswith('*') or part.startswith('_'):
                run.italic = True

    def _add_image(self, doc: Document, image_path: str, config: Dict[str, Any]):
        try:
            if not os.path.exists(image_path):
                print(f"[WARNING] Image not found: {image_path}")
                return
            para = doc.add_paragraph()
            run = para.add_run()
            run.add_picture(image_path, width=Inches(5.5))
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.line_spacing = Pt(config.get('line_spacing', 100))
        except Exception as e:
            print(f"[ERROR] Failed to add image {image_path}: {str(e)}")


# --------------------------------------------------------------
# 실행 예시
# --------------------------------------------------------------
if __name__ == "__main__":
    handler = HWPHandler()
    handler.create_hwp_document(
        title="Aphonia 프로젝트 보고서",
        content="# 개요\n\n본 문서는 Aphonia 시스템에 대한 기술 보고서입니다.\n\n## 실험 결과\n\n- EMG 데이터 처리\n- Lip-reading 기반 예측\n\n## 결론\n\n본 연구는 무성증 환자의 의사소통 가능성을 확장합니다.",
        images=["output/images/coral_reef.jpg"],
        filename="aphonia_report.hwp",
    )
