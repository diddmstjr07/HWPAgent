# HWP Agent 🤖📄

**Gemini API + LangChain 기반 한글 문서 자동 생성 시스템**

AI가 자동으로 한글(HWP/HWPX) 문서를 생성하는 지능형 에이전트입니다. 사용자의 요청을 자연어로 받아 Gemini API로 콘텐츠를 생성하고, LangChain을 통해 워크플로우를 관리하며, 최종적으로 한글 문서 파일로 출력합니다.

## ✨ 주요 기능

- 🤖 **AI 기반 콘텐츠 생성**: Gemini API를 사용한 자연어 기반 문서 생성
- 📝 **다양한 출력 형식**: HWPX, Markdown, RTF 형식 지원
- 🔄 **LangChain 통합**: 체계적인 워크플로우 관리
- 🎨 **자동 문서 구조화**: 제목, 본문, 표, 이미지 자동 배치
- 💬 **대화형 모드**: 인터랙티브하게 문서 생성 가능
- 🌐 **컨텍스트 활용**: 추가 정보를 제공하여 더 정확한 문서 생성

## 🛠 기술 스택

- **AI/ML**: Google Gemini API, LangChain
- **문서 처리**: HWPX (한글 XML), RTF, Markdown
- **언어**: Python 3.8+

## 📦 설치 방법

### 1. 저장소 클론

```bash path=null start=null
cd hwp-agent
```

### 2. 가상환경 생성 및 활성화

```bash path=null start=null
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 또는
venv\Scripts\activate  # Windows
```

### 3. 패키지 설치

```bash path=null start=null
pip install -r requirements.txt
```

### 4. 환경 변수 설정

`.env.example`을 복사하여 `.env` 파일을 생성하고 Gemini API 키를 입력합니다:

```bash path=null start=null
cp .env.example .env
```

`.env` 파일을 편집:

```bash path=null start=null
GOOGLE_API_KEY=your_actual_api_key_here
```

> 💡 **Gemini API 키 받기**: [Google AI Studio](https://makersuite.google.com/app/apikey)에서 무료로 발급받을 수 있습니다.

## 🚀 사용 방법

### 기본 사용법

```bash path=null start=null
python main.py "회사 소개서를 작성해주세요"
```

### 출력 형식 지정

```bash path=null start=null
# HWPX 형식 (기본값)
python main.py "프로젝트 제안서 작성" --format hwpx

# 마크다운 형식
python main.py "기술 문서 작성" --format md

# RTF 형식 (MS Word 호환)
python main.py "보고서 작성" --format rtf
```

### 컨텍스트 추가

```bash path=null start=null
python main.py "2024년 1분기 보고서" --context "매출 15% 증가, 신규 고객 200명"
```

### 대화형 모드

```bash path=null start=null
python main.py --interactive
```

대화형 모드에서는 다음과 같은 명령을 사용할 수 있습니다:

- 문서 생성 요청을 자연어로 입력
- `format <hwpx|md|rtf>`: 출력 형식 변경
- `quit` 또는 `exit`: 종료

### 출력 디렉토리 변경

```bash path=null start=null
python main.py "문서 작성" --output-dir ./my_documents
```

## 📚 Python 코드로 사용하기

```python path=null start=null
from modules import HWPAgent

# 에이전트 초기화
agent = HWPAgent(output_dir="output")

# 문서 생성
result = agent.process_request(
    user_request="AI 기술 소개서를 작성해주세요",
    output_format="hwpx",
    context={'company': '테크컴퍼니', 'year': 2024}
)

if result['success']:
    print(f"문서 생성 완료: {result['output_path']}")
    print(f"제목: {result['title']}")
else:
    print(f"오류: {result['error']}")
```

## 📖 예제 실행

`examples` 디렉토리에 다양한 예제가 포함되어 있습니다:

```bash path=null start=null
cd examples
python example_usage.py
```

예제 내용:
1. **간단한 문서 생성**: 기본적인 회사 소개서
2. **컨텍스트 포함**: 프로젝트 제안서 (예산, 기간 포함)
3. **다중 형식 출력**: 같은 내용을 여러 형식으로 생성
4. **기술 문서**: 상세한 개발 가이드 문서

## 📂 프로젝트 구조

```bash path=null start=null
hwp-agent/
├── main.py                 # 메인 실행 스크립트
├── requirements.txt        # 필요 패키지 목록
├── .env.example           # 환경 변수 예제
├── .gitignore
├── README.md
├── modules/               # 핵심 모듈
│   ├── __init__.py
│   ├── gemini_generator.py    # Gemini API 콘텐츠 생성
│   ├── hwp_handler.py          # HWP 파일 생성/편집
│   └── hwp_agent.py            # LangChain Agent
├── examples/              # 사용 예제
│   └── example_usage.py
└── output/                # 생성된 문서 저장 위치
```

## 🔧 커스터마이징

### 1. Gemini 모델 변경

`modules/gemini_generator.py`에서 모델을 변경할 수 있습니다:

```python path=null start=null
generator = GeminiContentGenerator(
    model_name="gemini-pro",  # 또는 "gemini-1.5-pro"
    temperature=0.7           # 창의성 조절 (0.0 ~ 1.0)
)
```

### 2. 프롬프트 수정

`modules/gemini_generator.py`의 `generate_document_content` 메서드에서 프롬프트를 수정하여 문서 생성 스타일을 조정할 수 있습니다.

### 3. 문서 템플릿 추가

`modules/hwp_handler.py`에서 새로운 문서 형식이나 템플릿을 추가할 수 있습니다.

## 🎯 사용 시나리오

### 1. 비즈니스 문서
- 회사 소개서, 제안서, 보고서
- 사업 계획서, 마케팅 자료

### 2. 기술 문서
- API 문서, 개발 가이드
- 시스템 아키텍처 문서

### 3. 교육 자료
- 강의 자료, 튜토리얼
- 학습 가이드, 매뉴얼

### 4. 연구 문서
- 논문 초안, 실험 보고서
- 문헌 리뷰, 연구 계획서

## ⚠️ 주의사항

### macOS에서 HWP 파일

macOS에서는 한글 프로그램이 기본 설치되지 않습니다. 이 시스템은:

1. **HWPX 형식**을 생성합니다 (XML 기반, 한글 2010 이상에서 호환)
2. **대체 형식**도 제공합니다 (Markdown, RTF)
3. Windows 환경에서 한글 프로그램으로 HWPX 파일을 열 수 있습니다

### API 사용량

Gemini API는 무료 할당량이 있지만, 대량 사용 시 비용이 발생할 수 있습니다. [Google AI Studio 가격 정책](https://ai.google.dev/pricing)을 확인하세요.

### 콘텐츠 정확성

AI가 생성한 콘텐츠는 항상 검토가 필요합니다. 중요한 문서는 반드시 사람이 확인하고 수정하세요.

## 🐛 문제 해결

### "GOOGLE_API_KEY가 설정되지 않았습니다"

`.env` 파일을 생성하고 올바른 API 키를 입력했는지 확인하세요.

### 패키지 설치 오류

Python 3.8 이상이 설치되어 있는지 확인하고, 가상환경을 사용하는 것을 권장합니다.

### HWPX 파일이 열리지 않음

- Windows에서 한글 2010 이상 버전을 사용하세요
- 또는 Markdown/RTF 형식을 사용하세요

## 🤝 기여하기

버그 리포트, 기능 제안, Pull Request를 환영합니다!

## 📄 라이선스

MIT License

## 🔗 관련 링크

- [Google Gemini API](https://ai.google.dev/)
- [LangChain Documentation](https://python.langchain.com/)
- [한글 파일 형식 (HWPX)](https://www.hancom.com/cs_center/csDownload.do)

## 📞 문의

문제가 있거나 질문이 있으시면 Issue를 생성해주세요.

---

**Made with ❤️ using Gemini API & LangChain**
