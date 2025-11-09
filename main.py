#!/usr/bin/env python3
"""
HWP Agent - 한글 문서 자동 생성 시스템
Gemini API + LangChain을 사용한 지능형 문서 생성기
"""
import sys
import argparse
from pathlib import Path

# 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from modules import HWPAgent


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description='HWP Agent - AI 기반 한글 문서 자동 생성 시스템',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예제:
  # 간단한 문서 생성
  python main.py "회사 소개 문서를 작성해주세요"
  
  # 출력 형식 지정
  python main.py "프로젝트 제안서 작성" --format md
  
  # 컨텍스트 추가
  python main.py "2024년 1분기 보고서" --context "매출 증가율 15%, 신규 고객 200명"
"""
    )
    
    parser.add_argument(
        'request',
        type=str,
        nargs='?',  # make request optional
        help='문서 생성 요청 (예: "회사 소개서 작성")'
    )
    
    parser.add_argument(
        '--format', '-f',
        type=str,
        choices=['hwpx', 'md', 'markdown', 'rtf'],
        default='hwpx',
        help='출력 문서 형식 (기본값: hwpx)'
    )
    
    parser.add_argument(
        '--context', '-c',
        type=str,
        default=None,
        help='추가 컨텍스트 정보'
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        default='output',
        help='출력 디렉토리 (기본값: output)'
    )
    
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='대화형 모드로 실행'
    )
    
    args = parser.parse_args()
    
    # 대화형 모드
    if args.interactive:
        run_interactive_mode(args.output_dir)
        return
    
    # 단일 실행 모드
    if args.request is None:
        parser.error("request argument is required when not in interactive mode.")
    run_single_mode(
        request=args.request,
        output_format=args.format,
        context=args.context,
        output_dir=args.output_dir
    )


def run_single_mode(request: str, output_format: str, context: str = None, output_dir: str = "output"):
    """단일 요청 처리 모드"""
    print("=" * 60)
    print("HWP Agent - AI 기반 문서 자동 생성 시스템")
    print("=" * 60)
    print()
    
    try:
        # 에이전트 초기화
        agent = HWPAgent(output_dir=output_dir)
        
        # 컨텍스트 준비
        context_dict = {'additional_info': context} if context else None
        
        # 요청 처리
        print(f"📋 요청 내용: {request}")
        print(f"📝 출력 형식: {output_format.upper()}")
        print()
        
        result = agent.process_request(
            user_request=request,
            output_format=output_format,
            context=context_dict
        )
        
        # 결과 출력
        if result['success']:
            print()
            print("=" * 60)
            print("✅ 문서 생성 완료!")
            print("=" * 60)
            print(f"📄 제목: {result['title']}")
            print(f"💾 파일 경로: {result['output_path']}")
            print(f"📝 형식: {result['format'].upper()}")
            print()
            print("📖 내용 미리보기:")
            print("-" * 60)
            print(result['content_preview'])
            print("-" * 60)
        else:
            print()
            print("❌ 문서 생성 실패")
            print(f"오류: {result['error']}")
    
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_interactive_mode(output_dir: str = "output"):
    """대화형 모드"""
    print("=" * 60)
    print("HWP Agent - 대화형 문서 생성 모드")
    print("=" * 60)
    print("명령어:")
    print("  - 문서 생성 요청을 입력하세요")
    print("  - 'format <hwpx|md|rtf>' 로 출력 형식 변경")
    print("  - 'quit' 또는 'exit' 로 종료")
    print("=" * 60)
    print()
    
    agent = HWPAgent(output_dir=output_dir)
    current_format = "hwpx"
    
    while True:
        try:
            user_input = input("📝 요청 > ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 종료합니다.")
                break
            
            if user_input.lower().startswith('format '):
                new_format = user_input.split(' ', 1)[1].strip().lower()
                if new_format in ['hwpx', 'md', 'markdown', 'rtf']:
                    current_format = new_format
                    print(f"✅ 출력 형식을 {current_format.upper()}로 변경했습니다.")
                else:
                    print("❌ 지원하지 않는 형식입니다. (hwpx, md, rtf 중 선택)")
                continue
            
            # 문서 생성
            result = agent.process_request(
                user_request=user_input,
                output_format=current_format
            )
            
            if result['success']:
                print(f"\n✅ 생성 완료: {result['output_path']}\n")
            else:
                print(f"\n❌ 오류: {result['error']}\n")
        
        except KeyboardInterrupt:
            print("\n\n👋 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ 오류: {str(e)}\n")


if __name__ == "__main__":
    main()
