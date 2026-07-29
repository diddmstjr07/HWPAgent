# HWP Public Document Style Profile

Source corpus: 50 public `.hwp` files collected from Korea Meteorological Administration press-release attachments.

This profile is not a model fine-tune. It is a persistent style target for the HWP Agent to apply when creating or editing blank HWP documents.

## Target Document Character

- Korean public-institution report style.
- Clear title, concise opening summary, structured body, and factual closing.
- Prefer evidence, dates, numbers, organizations, and responsible departments over broad claims.
- Avoid casual tone, emotional praise, marketing language, and unsupported assertions.

## Structure Pattern

1. Title
2. Cover metadata block when useful: 작성일, 작성자/부서, 대상, 문서 목적
3. Table of contents
4. One-paragraph lead summary
5. Body sections with short headings
6. Details grouped by topic, schedule, target, background, expected effect, or action items
7. Tables only when comparison, schedule, checklist, or numeric arrangement is clearer than prose
8. Closing or contact/source note when relevant

## Reference Design Pattern

When the user asks to create a document from a blank HWP, prefer this high-quality layout:

```text
[표지]
문서 제목
부제 또는 목적 한 줄
작성일:
작성자/부서:

[목차]
Ⅰ. 개요
Ⅱ. 추진 배경 또는 연구 배경
Ⅲ. 주요 내용
  1. 핵심 항목
  2. 세부 추진 내용
  3. 일정 또는 비교
Ⅳ. 기대 효과 또는 분석 결과
Ⅴ. 결론 및 향후 계획

[본문]
Ⅰ. 개요
핵심 목적과 결론을 먼저 제시한다.

Ⅱ. 추진 배경 또는 연구 배경
문제 상황, 필요성, 근거를 정리한다.

Ⅲ. 주요 내용
항목별로 소제목을 두고, 필요하면 표 형태의 비교/일정/체크리스트를 넣는다.

Ⅳ. 기대 효과 또는 분석 결과
정량/정성 효과, 판단 근거, 한계를 정리한다.

Ⅴ. 결론 및 향후 계획
실행 가능한 다음 단계로 마무리한다.
```

Design intent:
- A reader should understand the document by scanning the cover title, contents, section headings, and tables.
- Do not output a plain essay when a formal HWP document is requested.
- Always include a `목차` for documents longer than three sections.
- Use roman Korean section numbers `Ⅰ, Ⅱ, Ⅲ...` for major sections and `1, 2, 3...` for subsections.
- Place summary and tables before long prose when possible.

## Paragraph Rules

- Start each section with the key point, then give support or context.
- Keep paragraphs compact: one main claim per paragraph.
- Use objective declarative Korean endings such as `한다`, `이다`, `밝혔다`, `추진한다`.
- Do not use conversational endings such as `해요`, `같아요`, `좋습니다`.
- Do not pad with abstract filler. Every sentence should add a fact, condition, reason, result, or next action.

## Formatting Rules

- Main title: centered, bold, larger than body.
- Section headings: bold, separated from body text.
- Body: readable Korean document font, normal weight, consistent line spacing.
- Lists: use numbered or bullet structure for procedures, criteria, schedules, and deliverables.
- Tables: include a short title or surrounding sentence explaining what the table summarizes.

## Agent Generation Policy

- When starting from a blank HWP, first create a structured draft with cover, table of contents, and body sections instead of free-form chat text.
- If the user asks for a report, proposal, announcement, research summary, plan, or minutes, follow the structure pattern above by default.
- If the user gives no format details, use: title, overview, background/purpose, main content, expected effect/next steps.
- After drafting, apply title/heading/body formatting through HWP tools when possible.
- Preserve existing HWP layout if editing an uploaded form; do not overwrite templates unnecessarily.
