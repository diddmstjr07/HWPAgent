"""
DOCX (워드) 파일 생성 모듈 - 한글에서도 열리는 완전한 문서
"""
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn
from pathlib import Path
from typing import Optional, Dict, Any, List
import os


class DOCXHandler:
    """완전한 서식을 갖춘 DOCX 문서 생성"""
    
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def create_document(
        self,
        title: str,
        content: str,
        style_config: Optional[Dict[str, Any]] = None,
        filename: Optional[str] = None,
        images: Optional[List[str]] = None
    ) -> str:
        """
        완전한 서식을 갖춘 워드 문서 생성
        
        Args:
            title: 문서 제목
            content: 본문 내용
            style_config: 서식 설정 (폰트, 크기 등)
            filename: 출력 파일명
            images: 삽입할 이미지 경로 리스트 (선택)
        
        Returns:
            생성된 파일 경로
        """
        # 기본 설정 (개선된 스타일)
        base_style = {
            'font_name': '함초롬바탕',
            'font_name_english': 'HCR Batang',
            'heading_font_name': '함초롬바탕',
            'title_font_name': '함초롬바탕',
            'font_size': 11,
            'title_size': 22,
            'heading_level1_size': 16,
            'heading_level2_size': 14,
            'heading_level3_size': 13,
            'line_spacing': 1.6,
            'paragraph_spacing': 9,
            'margin_top': 2.5,
            'margin_bottom': 2.5,
            'margin_left': 2.5,
            'margin_right': 2.5,
            'treat_images_as_text': False,
            'image_placeholder_text': '※ 참고 이미지: {keyword}'
        }
        config = base_style.copy()
        if style_config:
            config.update(style_config)
        else:
            config.update(base_style)
        primary_font = config.get('font_name', base_style['font_name'])
        config['font_name'] = primary_font
        config['font_name_english'] = config.get('font_name_english', primary_font)
        config['heading_font_name'] = primary_font
        config['title_font_name'] = primary_font
        config['treat_images_as_text'] = bool(config.get('treat_images_as_text', False))
        config['image_placeholder_text'] = config.get('image_placeholder_text', '※ 참고 이미지: {keyword}')
        
        if filename is None:
            filename = f"{title}.docx"
        
        output_path = self.output_dir / filename
        
        # 문서 생성
        doc = Document()
        
        # 페이지 여백 설정
        self._set_page_margins(doc, config)

        # 기본 스타일 설정
        self._set_default_style(doc, config)

        # 표지 생성
        self._create_cover(doc, title, config)

        # 본문 추가
        self._add_content(doc, content, config, images)
        
        # 저장
        doc.save(output_path)
        
        return str(output_path)
    
    def _set_page_margins(self, doc: Document, config: Dict[str, Any]):
        """페이지 여백 설정 (표준 문서 형식)"""
        sections = doc.sections
        for section in sections:
            section.top_margin = Cm(config.get('margin_top', 2.5))
            section.bottom_margin = Cm(config.get('margin_bottom', 2.5))
            section.left_margin = Cm(config.get('margin_left', 2.5))
            section.right_margin = Cm(config.get('margin_right', 2.5))
    
    def _set_default_style(self, doc: Document, config: Dict[str, Any]):
        """기본 스타일 설정 (한글+영문 폰트 지원)"""
        style = doc.styles['Normal']
        
        # 폰트 설정
        font = style.font
        font.name = config.get('font_name_english', 'HCR Batang')  # 영문 폰트
        font.size = Pt(config.get('font_size', 11))
        
        # 한글 폰트 설정 (중요!)
        font_name_korean = config.get('font_name', '함초롬바탕')
        if hasattr(style._element, 'rPr') and style._element.rPr is not None:
            style._element.rPr.rFonts.set(qn('w:eastAsia'), font_name_korean)
        
        # 단락 스타일 (개선된 간격)
        paragraph_format = style.paragraph_format
        paragraph_format.line_spacing = config.get('line_spacing', 1.6)
        paragraph_format.space_after = Pt(config.get('paragraph_spacing', 8))
        paragraph_format.space_before = Pt(0)
        paragraph_format.first_line_indent = Pt(0)  # 들여쓰기 없음 (현대적 스타일)
    
    def _create_cover(self, doc: Document, title: str, config: Dict[str, Any]):
        """표지 페이지 생성 (세련된 디자인)"""
        # 상단 여백 (더 넓게)
        for _ in range(6):
            doc.add_paragraph()
        
        # 제목
        title_para = doc.add_paragraph()
        title_para.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        
        title_run = title_para.add_run(title)
        title_run.bold = True
        title_run.font.size = Pt(config.get('title_size', 22))
        title_run.font.name = config.get('title_font_name', config.get('heading_font_name', config.get('font_name_english', 'HCR Batang')))
        title_run.font.color.rgb = RGBColor(30, 30, 30)  # 부드러운 검정
        
        # 한글 폰트도 적용
        if hasattr(title_run._element.rPr, 'rFonts'):
            title_run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
        
        # 부제목 또는 여백
        for _ in range(2):
            doc.add_paragraph()
        
        # 페이지 나누기
        doc.add_page_break()
    
    def _add_content(self, doc: Document, content: str, config: Dict[str, Any], images: Optional[List[str]] = None):
        """본문 추가 (서식 + 이미지 텍스트 표현 지원)"""
        import re

        lines = content.split('\n')
        image_index = 0
        treat_images_as_text = bool(config.get('treat_images_as_text'))
        placeholder_only = treat_images_as_text
        tag_pattern = re.compile(r'\[gen_img\](.+?)\[/gen_img\]')

        for raw_line in lines:
            stripped = raw_line.strip()
            tag_matches = tag_pattern.findall(stripped)
            working_line = tag_pattern.sub('', stripped).strip() if tag_matches else stripped

            if not working_line and not tag_matches:
                doc.add_paragraph()
                continue

            if working_line:
                if working_line.startswith('#'):
                    is_level2_heading = working_line.startswith('##') and not working_line.startswith('###')
                    self._add_heading(doc, working_line, config)
                    if not placeholder_only and is_level2_heading and images and image_index < len(images):
                        self._add_image(doc, images[image_index], config)
                        image_index += 1
                elif working_line.startswith('- ') or working_line.startswith('* '):
                    self._add_list_item(doc, working_line[2:], config)
                elif working_line[0].isdigit() and '. ' in working_line:
                    self._add_numbered_item(doc, working_line, config)
                else:
                    self._add_paragraph(doc, working_line, config)
            elif not tag_matches:
                doc.add_paragraph()

            if tag_matches:
                for keyword in tag_matches:
                    if placeholder_only:
                        self._add_image_placeholder(doc, keyword.strip(), config)
                        continue
                    if images and image_index < len(images):
                        self._add_image(doc, images[image_index], config)
                        image_index += 1
                    else:
                        # 이미지가 부족하면 품격 있는 캡션으로 대체
                        self._add_image_placeholder(doc, keyword.strip(), config)
    
    def _add_heading(self, doc: Document, line: str, config: Dict[str, Any]):
        """제목 추가"""
        level = 0
        while line.startswith('#'):
            level += 1
            line = line[1:].strip()
        
        level = min(level, 3)  # 최대 레벨 3
        
        heading = doc.add_heading(line, level=level)
        heading_sizes = {
            1: config.get('heading_level1_size', config.get('heading_size', 16)),
            2: config.get('heading_level2_size', config.get('heading_level1_size', 15) - 1),
            3: config.get('heading_level3_size', config.get('heading_level2_size', 14) - 1)
        }
        target_font = config.get('heading_font_name', config.get('font_name', '함초롬바탕'))
        target_size = heading_sizes.get(level, heading_sizes[3])
        
        for run in heading.runs:
            run.font.name = target_font
            run.font.size = Pt(target_size)
            run.font.color.rgb = RGBColor(0, 0, 0)
    
    def _add_list_item(self, doc: Document, text: str, config: Dict[str, Any]):
        """리스트 아이템 추가"""
        para = doc.add_paragraph(text, style='List Bullet')
        
        for run in para.runs:
            run.font.name = config.get('font_name', '함초롬바탕')
            run.font.size = Pt(config.get('font_size', 11))
    
    def _add_numbered_item(self, doc: Document, text: str, config: Dict[str, Any]):
        """번호 리스트 추가"""
        para = doc.add_paragraph(text, style='List Number')
        
        for run in para.runs:
            run.font.name = config.get('font_name', '함초롬바탕')
            run.font.size = Pt(config.get('font_size', 11))
    
    def _add_paragraph(self, doc: Document, text: str, config: Dict[str, Any]):
        """일반 문단 추가"""
        para = doc.add_paragraph()
        paragraph_format = para.paragraph_format
        paragraph_format.line_spacing = config.get('line_spacing', 1.6)
        paragraph_format.space_after = Pt(config.get('paragraph_spacing', 8) / 2)
        paragraph_format.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY

        # 굵게/기울임 등 인라인 서식 처리
        self._add_formatted_text(para, text, config)
    
    def _add_formatted_text(self, para, text: str, config: Dict[str, Any]):
        """서식이 포함된 텍스트 추가 (한영 폰트 모두 적용)"""
        # **굵게**, *기울임* 등 마크다운 스타일 파싱
        import re

        # 간단한 파싱 (실제로는 더 복잡한 파서 필요)
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|__.*?__|_.*?_)', text)
        
        for part in parts:
            if not part:
                continue
            
            run = para.add_run(part.strip('*_'))
            run.font.name = config.get('font_name_english', 'HCR Batang')
            run.font.size = Pt(config.get('font_size', 11))
            
            # 한글 폰트 적용
            if hasattr(run._element.rPr, 'rFonts'):
                run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
            
            # 굵게
            if part.startswith('**') or part.startswith('__'):
                run.bold = True
            # 기울임
            elif part.startswith('*') or part.startswith('_'):
                run.italic = True

    def _add_image(self, doc: Document, image_path: str, config: Dict[str, Any]):
        """이미지 삽입 (자동 크기 조절)"""
        try:
            if not os.path.exists(image_path):
                print(f"[WARNING] Image not found: {image_path}")
                return
            
            # 이미지 단락 추가
            para = doc.add_paragraph()
            para.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            
            # 이미지 삽입 (너비 기준 자동 조절, 최대 6인치)
            run = para.add_run()
            run.add_picture(image_path, width=Inches(5.5))
            
            # 이미지 아래 여백
            para.paragraph_format.space_after = Pt(12)
            
        except Exception as e:
            print(f"[ERROR] Failed to add image {image_path}: {str(e)}")

    def _add_image_placeholder(self, doc: Document, keyword: str, config: Dict[str, Any]):
        """이미지 대신 텍스트 캡션을 추가하여 정갈한 느낌을 부여"""
        template = config.get('image_placeholder_text', '※ 참고 이미지: {keyword}') or '※ 참고 이미지: {keyword}'
        safe_keyword = keyword.strip() or '삽화'
        if '{keyword}' in template:
            placeholder = template.replace('{keyword}', safe_keyword)
        else:
            placeholder = f"{template} {safe_keyword}"

        para = doc.add_paragraph()
        para.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY
        para.paragraph_format.space_before = Pt(4)
        para.paragraph_format.space_after = Pt(8)
        run = para.add_run(placeholder)
        run.italic = True
        run.font.name = config.get('font_name_english', 'HCR Batang')
        run.font.size = Pt(config.get('font_size', 11))
        if hasattr(run._element.rPr, 'rFonts'):
            run._element.rPr.rFonts.set(qn('w:eastAsia'), config.get('font_name', '함초롬바탕'))
