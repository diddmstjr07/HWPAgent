"""문서 양식 파일 파서"""
from pathlib import Path
from typing import Optional
import shutil

from docx import Document

SUPPORTED_TEMPLATE_EXTENSIONS = {'.docx', '.hwp', '.txt', '.md'}


def extract_template_text(file_path: Path) -> str:
    """주어진 파일에서 양식 텍스트를 추출"""
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise ValueError('지원하지 않는 파일 형식입니다. (.docx, .hwp, .txt, .md)')

    try:
        if suffix in {'.txt', '.md'}:
            return file_path.read_text(encoding='utf-8', errors='ignore').strip()

        return _extract_text_from_docx_like(file_path, treat_as_docx=(suffix == '.docx'))
    except Exception as exc:
        raise ValueError('양식 파일을 읽는 중 오류가 발생했습니다.') from exc


def _extract_text_from_docx_like(file_path: Path, treat_as_docx: bool = True) -> str:
    temp_docx: Optional[Path] = None
    docx_path = file_path

    if not treat_as_docx:
        temp_docx = file_path.with_suffix('.docx')
        shutil.copyfile(file_path, temp_docx)
        docx_path = temp_docx

    try:
        document = Document(str(docx_path))
        lines = [para.text.rstrip() for para in document.paragraphs]

        table_lines = []
        for table in document.tables:
            for row in table.rows:
                row_text = ' | '.join(cell.text.strip() for cell in row.cells).strip()
                if row_text:
                    table_lines.append(row_text)

        combined = '\n'.join(line for line in lines if line is not None)
        if table_lines:
            combined = f"{combined}\n" + '\n'.join(table_lines)
        return combined.strip()
    finally:
        if temp_docx and temp_docx.exists():
            temp_docx.unlink()
