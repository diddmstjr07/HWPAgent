---
name: hwp-official-document
description: "Use this skill whenever creating or editing Korean HWP/HWPX official documents, public-institution reports, press releases, attachments, memos, plans, minutes, proposals, or forms that must look like polished government/administrative documents."
---

# HWP Official Document Skill

## Goal

Create HWP documents that look like real Korean official/public-institution documents, not plain essays pasted into a page.

## Core Model

An official HWP document is assembled from reusable visual components:

- attachment header bar: blue `붙임 1` label + divider + large title + bottom rule
- department/contact box: 담당 부서, 책임자, 담당자 contact table
- section heading rule: numbered heading with strong typography and separator
- official table: thin borders, shaded header row, compact padding
- note box: `※` notice/caution block with light fill
- summary matrix: key points table near the top
- schedule/checklist table: action-oriented execution table
- role, budget, risk, and evaluation tables selected by document type

Do not rely on free-form prose generation alone.

## HWP Operation Rules

- Never insert multi-paragraph content with `\n`; use `split_paragraph`.
- Use `create_table` for visual components when native shape cloning is unavailable.
- After `create_table`, always set:
  - table/cell widths
  - cell borders
  - cell fill/shading
  - cell padding
  - cell paragraph alignment
  - cell character format
- Use `set_char_format_in_cell` and `set_para_format_in_cell` for table component text.
- Use Hangul-friendly fonts such as `함초롬돋움` for labels/headings and `함초롬바탕` for body.
- Use compact public document spacing: body line spacing 150-170%, section spacing before 160-260.

## Generation Pipeline

1. Classify document type: report, research, plan, minutes, proposal, notice.
2. Select layout components from `style_kit.design_patterns`.
3. Generate a block plan, not raw prose.
4. Insert visual components first.
5. Insert body content into the component structure.
6. Apply table and paragraph styles after insertion.
7. Render/refresh Canvas after each block.
8. Validate the final structure and visual component presence.

## Required Blocks For New Official Documents

- `[[DESIGN:attachment_header_bar:붙임 1:문서 제목]]`
- cover metadata or contact/department block
- `목차`
- 5 major sections using `Ⅰ, Ⅱ, Ⅲ, Ⅳ, Ⅴ`
- at least one official table
- at least one summary or note box when useful

## Design Markers

### Attachment Header Bar

```text
[[DESIGN:attachment_header_bar:붙임 1:2026년 3월 우리나라 기온 분포도 및 일별 경향]]
```

Implementation:
- 1x3 table surrogate
- cell 0: blue fill, white bold label
- cell 1: narrow divider, bottom rule
- cell 2: large bold title, bottom rule

### Contact Box

```text
[[DESIGN:contact_box:담당 부서:기상서비스진흥국|책임자:과장 작성 필요|담당자:사무관 작성 필요]]
```

Implementation:
- 3x2 or 3x4 compact table
- label cells shaded light blue-gray
- value cells white
- all borders thin gray

### Note Box

```text
[[DESIGN:note_box:※ 세부 수치와 담당자는 최종 검토 단계에서 보완한다.]]
```

Implementation:
- 1x1 table
- light blue-gray fill
- left aligned body text
- thin gray border

## Quality Validation

A generated HWP official document is not acceptable unless:

- it contains at least one visual design component
- it contains an official table with styled header row
- it has a readable title hierarchy
- no Markdown markers remain
- body content is organized by sections, not a single essay
- the Canvas preview is refreshed during generation

## Reference Style Kit Usage

Use `style_kit.json` as a reusable component and table recipe library:

- choose `document_recipes[doc_type]` first
- insert the listed visual components
- select the listed table templates, not just generic summary tables
- vary table style with `table_style_variants`
- use corpus-mined headings, bullets, contact boxes, note boxes, and official table shapes

Do not use raw HTML control cloning for generated documents. The `exportControlHtml` to `pasteHtml` route can corrupt exported page geometry in rhwp, so generated documents must use safe table/paragraph operations.
