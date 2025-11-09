#!/usr/bin/env python3
"""
PDF 파일 생성 모듈 - DOCX 변환 방식
"""
from pathlib import Path
from typing import Optional
import os
import subprocess
import sys


class PDFHandler:
    """한글을 지원하는 PDF 문서 생성 (DOCX 변환 방식)"""
    
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def convert_docx_to_pdf(
        self,
        docx_path: str,
        output_filename: Optional[str] = None
    ) -> str:
        """
        DOCX 파일을 PDF로 변환
        
        Args:
            docx_path: DOCX 파일 경로
            output_filename: 출력 PDF 파일명
        
        Returns:
            생성된 PDF 파일 경로
        """
        docx_path = Path(docx_path)
        if not docx_path.exists():
            raise FileNotFoundError(f"DOCX file not found: {docx_path}")
        
        if output_filename is None:
            output_filename = docx_path.stem + ".pdf"
        
        output_path = self.output_dir / output_filename
        
        print(f"[PDF] Converting {docx_path.name} to PDF...")
        
        # macOS: LibreOffice 사용
        if sys.platform == 'darwin':
            return self._convert_with_libreoffice(docx_path, output_path)
        # Windows: win32com (Microsoft Word) 사용
        elif sys.platform == 'win32':
            return self._convert_with_word(docx_path, output_path)
        # Linux: LibreOffice 사용
        else:
            return self._convert_with_libreoffice(docx_path, output_path)
    
    def _convert_with_libreoffice(self, docx_path: Path, output_path: Path) -> str:
        """
        LibreOffice를 사용하여 DOCX를 PDF로 변환 (macOS/Linux)
        """
        try:
            # LibreOffice 명령어 경로 찾기
            libreoffice_paths = [
                '/Applications/LibreOffice.app/Contents/MacOS/soffice',  # macOS
                '/usr/bin/libreoffice',  # Linux
                'libreoffice',  # PATH에 있는 경우
            ]
            
            soffice_cmd = None
            for path in libreoffice_paths:
                if Path(path).exists() or path == 'libreoffice':
                    soffice_cmd = path
                    break
            
            if not soffice_cmd:
                raise FileNotFoundError(
                    "LibreOffice not found. Please install:\n"
                    "  macOS: brew install --cask libreoffice\n"
                    "  Linux: sudo apt-get install libreoffice"
                )
            
            # LibreOffice로 변환
            cmd = [
                soffice_cmd,
                '--headless',
                '--convert-to', 'pdf',
                '--outdir', str(self.output_dir),
                str(docx_path)
            ]
            
            print(f"[PDF] Running LibreOffice conversion...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise Exception(f"LibreOffice conversion failed: {result.stderr}")
            
            # 생성된 PDF 파일 경로
            generated_pdf = self.output_dir / f"{docx_path.stem}.pdf"
            
            # 원하는 파일명으로 변경
            if generated_pdf != output_path:
                if output_path.exists():
                    output_path.unlink()
                generated_pdf.rename(output_path)
            
            # 임시 DOCX 파일 삭제
            if '_temp' in docx_path.name:
                docx_path.unlink()
                print(f"[PDF] Cleaned up temp DOCX: {docx_path.name}")
            
            print(f"[PDF] ✅ PDF created: {output_path.name}")
            return str(output_path)
            
        except subprocess.TimeoutExpired:
            raise Exception("PDF conversion timeout (30s)")
        except Exception as e:
            print(f"[PDF ERROR] {str(e)}")
            raise
    
    def _convert_with_word(self, docx_path: Path, output_path: Path) -> str:
        """
        Microsoft Word를 사용하여 DOCX를 PDF로 변환 (Windows)
        """
        try:
            import win32com.client
            
            word = win32com.client.Dispatch('Word.Application')
            word.Visible = False
            
            doc = word.Documents.Open(str(docx_path.absolute()))
            doc.SaveAs(str(output_path.absolute()), FileFormat=17)  # 17 = PDF
            doc.Close()
            word.Quit()
            
            # 임시 DOCX 파일 삭제
            if '_temp' in docx_path.name:
                docx_path.unlink()
                print(f"[PDF] Cleaned up temp DOCX: {docx_path.name}")
            
            print(f"[PDF] ✅ PDF created: {output_path.name}")
            return str(output_path)
            
        except Exception as e:
            print(f"[PDF ERROR] {str(e)}")
            raise
