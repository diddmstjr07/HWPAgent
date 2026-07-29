import { readdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { openHwp } from '../dist/hwp-helper.js';
import { serializeWebDocument } from '../dist/serializer.js';

const root = resolve(process.cwd(), '../..');
const corpusDir = resolve(root, 'data/hwp_corpus/kma_press');
const outPath = join(corpusDir, 'style_kit.json');

const headingRe = /^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]|[0-9]+[.)]\s|[가-힣][.)]\s|제\s*\d+\s*[장절항]\s*)/;
const bulletRe = /^\s*([□■▪▫●○•\-–—※*]+)/;
const tocRe = /(목\s*차|CONTENTS?|차\s*례)/i;

function compactText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function count(map, key) {
  if (!key) return;
  map.set(key, (map.get(key) || 0) + 1);
}

function top(map, limit = 20) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}

function usefulBulletMarkers(markers) {
  const allowed = new Set(['□', '○', '※', '-']);
  return markers.map((x) => x.value).filter((value) => allowed.has(value));
}

function isUsefulGeneratedTable(template) {
  const headers = template.headers || [];
  if (headers.length < 2 || headers.length > 6) return false;
  if (headers.some((header) => /^열\d+$/.test(header))) return false;
  const joined = headers.join(' ');
  if (/보도자료|담당 부서|책임자|과 장|\d{2,4}-\d{3,4}-\d{4}|기상청 인사발령/.test(joined)) return false;
  return true;
}

function inferTableKind(cells) {
  const header = cells
    .filter((cell) => cell.row === 0)
    .sort((a, b) => a.col - b.col)
    .map((cell) => compactText(cell.text));
  const joined = header.join(' ');
  if (/일시|기간|일정|단계/.test(joined)) return 'schedule';
  if (/항목|분석|결과|시사점/.test(joined)) return 'analysis';
  if (/확인|점검/.test(joined)) return 'checklist';
  return 'summary_matrix';
}

const files = (await readdir(corpusDir))
  .filter((name) => name.toLowerCase().endsWith('.hwp'))
  .sort()
  .slice(0, 50);

const headingMarkers = new Map();
const bulletMarkers = new Map();
const styleSignatures = new Map();
const tocTemplates = [];
const tableShapes = new Map();
const tableTemplates = new Map();
const designPatternHits = new Map();
const sampleFiles = [];

for (const name of files) {
  const filePath = join(corpusDir, name);
  let doc;
  try {
    doc = await openHwp(filePath);
    const web = serializeWebDocument(doc);
    sampleFiles.push(name);

    for (const section of web.sections || []) {
      const paragraphs = section.paragraphs || [];
      const tocStart = paragraphs.findIndex((p) => tocRe.test(p.text || ''));
      if (tocStart >= 0) {
        const tocLines = [];
        for (const p of paragraphs.slice(tocStart + 1, tocStart + 12)) {
          const text = compactText(p.text);
          if (!text) continue;
          if (headingRe.test(text) || /^[0-9]+[.)]/.test(text)) tocLines.push(text.slice(0, 60));
        }
        if (tocLines.length >= 3) tocTemplates.push(tocLines.slice(0, 7));
      }

      for (const p of paragraphs) {
        const text = compactText(p.text);
        if (!text) continue;
        if (/붙임\s*\d+/.test(text) || /별첨\s*\d+/.test(text) || /부록\s*\d+/.test(text)) {
          count(designPatternHits, 'attachment_header_bar');
        }
        if (/담당\s*부서|책임자|담당자|문의/.test(text)) {
          count(designPatternHits, 'contact_box');
        }
        if (/^\s*※/.test(text)) {
          count(designPatternHits, 'note_box');
        }
        if (/^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]|[0-9]+[.)]\s)/.test(text)) {
          count(designPatternHits, 'section_heading_rule');
        }
        const heading = text.match(headingRe);
        if (heading) count(headingMarkers, heading[0].trim());
        const bullet = text.match(bulletRe);
        if (bullet) count(bulletMarkers, bullet[1].trim());
        if (p.style) count(styleSignatures, JSON.stringify(p.style));
      }

      for (const table of section.tables || []) {
        const shape = `${table.rowCount}x${table.colCount}`;
        count(tableShapes, shape);
        const header = (table.cells || [])
          .filter((cell) => cell.row === 0)
          .sort((a, b) => a.col - b.col)
          .map((cell) => compactText(cell.text) || `열${cell.col + 1}`);
        if (!header.length) continue;
        const kind = inferTableKind(table.cells || []);
        const key = `${kind}|${header.join('|')}`;
        if (!tableTemplates.has(key)) {
          tableTemplates.set(key, {
            id: kind,
            title: kind === 'schedule' ? '추진 일정' : kind === 'analysis' ? '분석 결과' : kind === 'checklist' ? '점검 항목' : '핵심 내용 요약',
            headers: header,
            rows: Math.max(3, Math.min(8, table.rowCount || 4)),
            sourceShape: shape,
            count: 0,
          });
        }
        tableTemplates.get(key).count += 1;
      }
    }
  } catch (error) {
    console.warn(`[style-kit] skip ${name}: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    try { doc?.raw?.free?.(); } catch {}
  }
}

const fallbackToc = [
  ['Ⅰ. 개요', 'Ⅱ. 추진 배경', 'Ⅲ. 주요 내용', 'Ⅳ. 기대 효과', 'Ⅴ. 향후 계획'],
  ['Ⅰ. 연구 개요', 'Ⅱ. 연구 배경', 'Ⅲ. 연구 방법', 'Ⅳ. 분석 결과', 'Ⅴ. 결론'],
  ['Ⅰ. 목적', 'Ⅱ. 현황 및 필요성', 'Ⅲ. 세부 추진 계획', 'Ⅳ. 일정', 'Ⅴ. 기대 효과'],
];

const tableList = [...tableTemplates.values()]
  .sort((a, b) => b.count - a.count)
  .filter(isUsefulGeneratedTable)
  .slice(0, 8);

const semanticTableTemplates = [
  { id: 'summary_matrix', title: '핵심 내용 요약', headers: ['구분', '주요 내용', '비고'], rows: 4, sourceShape: 'semantic:summary', style: 'blue_header', headerFill: '#dfeaf7' },
  { id: 'schedule', title: '추진 일정', headers: ['단계', '기간', '세부 내용', '담당'], rows: 5, sourceShape: 'semantic:schedule', style: 'gray_header', headerFill: '#eef2f6' },
  { id: 'analysis', title: '분석 결과', headers: ['항목', '분석 내용', '시사점'], rows: 4, sourceShape: 'semantic:analysis', style: 'navy_header', headerFill: '#d9e5f2' },
  { id: 'checklist', title: '점검 항목', headers: ['확인 항목', '세부 내용', '상태'], rows: 4, sourceShape: 'semantic:checklist', style: 'checklist', headerFill: '#edf4ec' },
  { id: 'risk_matrix', title: '위험 요인 및 대응', headers: ['위험 요인', '영향', '대응 방안', '관리 주체'], rows: 5, sourceShape: 'semantic:risk', style: 'gray_header', headerFill: '#f1f4f8' },
  { id: 'budget_matrix', title: '소요 자원', headers: ['구분', '세부 항목', '소요 규모', '산출 근거'], rows: 4, sourceShape: 'semantic:budget', style: 'blue_header', headerFill: '#e3edf8' },
  { id: 'role_matrix', title: '역할 분담', headers: ['담당 주체', '주요 역할', '협조 사항'], rows: 4, sourceShape: 'semantic:roles', style: 'gray_header', headerFill: '#eef2f6' },
  { id: 'evaluation_matrix', title: '평가 기준', headers: ['평가 항목', '판단 기준', '확인 자료'], rows: 4, sourceShape: 'semantic:evaluation', style: 'navy_header', headerFill: '#dfe8f4' },
  { id: 'monthly_matrix', title: '월별 현황', headers: ['구분', '1분기', '2분기', '3분기', '4분기'], rows: 5, sourceShape: 'mined:monthly-matrix', style: 'blue_header', headerFill: '#e5eef8' },
  { id: 'ranking_table', title: '순위 현황', headers: ['구분', '1위', '2위', '3위', '비고'], rows: 5, sourceShape: 'mined:ranking-table', style: 'gray_header', headerFill: '#f0f3f6' },
];

const kit = {
  version: 3,
  source: {
    name: 'kma_press_public_hwp',
    file_count: sampleFiles.length,
    files: sampleFiles,
  },
  reusable_symbols: {
    heading_markers: top(headingMarkers, 24).map((x) => x.value),
    bullet_markers: usefulBulletMarkers(top(bulletMarkers, 12)),
    toc_marker: '목차',
    table_caption_prefixes: ['<표 1>', '[표 1]', '표 1.'],
  },
  extracted_stats: {
    heading_markers: top(headingMarkers, 24),
    bullet_markers: top(bulletMarkers, 12),
    table_shapes: top(tableShapes, 12),
    paragraph_styles: top(styleSignatures, 12),
  },
  toc_templates: tocTemplates.slice(0, 8).length ? tocTemplates.slice(0, 8) : fallbackToc,
  table_templates: [...semanticTableTemplates, ...tableList].slice(0, 12),
  component_library: [
    { id: 'attachment_header_bar', use_when: '첨부, 부록, 공식 보고서 첫 페이지 제목', required: true },
    { id: 'contact_box', use_when: '공문, 보도자료, 안내문, 외부 공유 문서', required: false },
    { id: 'note_box', use_when: '유의사항, 전제, 작성 필요 항목 고지', required: false },
    { id: 'section_heading_rule', use_when: '대제목 구분과 시각적 계층 강화', required: true },
  ],
  table_style_variants: {
    blue_header: { headerFill: '#dfeaf7', line: '#5e748e', headerLine: '#2f4f74' },
    gray_header: { headerFill: '#eef2f6', line: '#6f7f92', headerLine: '#465568' },
    navy_header: { headerFill: '#d9e5f2', line: '#4d647f', headerLine: '#263f5f' },
    checklist: { headerFill: '#edf4ec', line: '#6e846c', headerLine: '#3f603f' },
  },
  design_patterns: [
    {
      id: 'attachment_header_bar',
      title: '붙임 제목 바',
      sourceHits: designPatternHits.get('attachment_header_bar') || 0,
      description: '왼쪽 파란 번호 라벨, 좁은 구분선, 오른쪽 큰 제목, 하단 실선으로 구성된 공식 문서 첨부/부록 제목 양식',
      marker: '[[DESIGN:attachment_header_bar:붙임 1:문서 제목]]',
      implementation: {
        type: 'table_surrogate',
        rows: 1,
        cols: 3,
        cells: ['label_blue_box', 'divider', 'title_with_bottom_rule'],
        colors: { labelFill: '#005a9c', line: '#000000' },
      },
    },
    {
      id: 'contact_box',
      title: '담당 부서 연락처 박스',
      sourceHits: designPatternHits.get('contact_box') || 0,
      description: '담당 부서, 책임자, 담당자를 표 형태로 정리하는 공문/보도자료 하단 또는 상단 연락처 양식',
      marker: '[[DESIGN:contact_box:담당 부서:부서명|책임자:직위 이름|담당자:직위 이름]]',
      implementation: {
        type: 'table_surrogate',
        rows: 3,
        cols: 2,
        colors: { labelFill: '#e8eef6', line: '#7f8ea3' },
      },
    },
    {
      id: 'note_box',
      title: '유의사항 박스',
      sourceHits: designPatternHits.get('note_box') || 0,
      description: '※ 문장이나 참고 사항을 얇은 테두리와 연한 배경으로 감싸는 안내 박스',
      marker: '[[DESIGN:note_box:※ 유의사항 또는 참고 문장]]',
      implementation: {
        type: 'table_surrogate',
        rows: 1,
        cols: 1,
        colors: { fill: '#f2f6fb', line: '#b7c4d6' },
      },
    },
    {
      id: 'section_heading_rule',
      title: '대제목 구분선',
      sourceHits: designPatternHits.get('section_heading_rule') || 0,
      description: '대제목을 굵게 보이게 하고 하단 구분선을 붙이는 본문 섹션 제목 양식',
      marker: '[[DESIGN:section_heading_rule:Ⅰ. 개요]]',
      implementation: {
        type: 'paragraph_style',
        rule: 'bold_heading_with_bottom_rule',
      },
    },
  ],
  style_presets: {
    cover_title: {
      char: { fontName: '함초롬바탕', fontSize: 2200, bold: true },
      para: { align: 'Center', lineSpacing: 150, spacingAfter: 500 },
    },
    cover_meta: {
      char: { fontName: '함초롬바탕', fontSize: 1050 },
      para: { align: 'Center', lineSpacing: 150 },
    },
    toc_heading: {
      char: { fontName: '함초롬바탕', fontSize: 1500, bold: true },
      para: { align: 'Center', lineSpacing: 150, spacingBefore: 240, spacingAfter: 180 },
    },
    section_heading: {
      char: { fontName: '함초롬바탕', fontSize: 1300, bold: true },
      para: { align: 'Left', lineSpacing: 150, spacingBefore: 240, spacingAfter: 100 },
    },
    sub_heading: {
      char: { fontName: '함초롬바탕', fontSize: 1100, bold: true },
      para: { align: 'Left', lineSpacing: 150, spacingBefore: 140, spacingAfter: 60 },
    },
    body: {
      char: { fontName: '함초롬바탕', fontSize: 1000 },
      para: { align: 'Justify', lineSpacing: 160 },
    },
    table_caption: {
      char: { fontName: '함초롬바탕', fontSize: 1000, bold: true },
      para: { align: 'Left', lineSpacing: 140, spacingBefore: 160 },
    },
  },
  selection_policy: {
    report: 'toc + attachment_header_bar + contact_box + summary_matrix + schedule + risk_matrix',
    research: 'toc + attachment_header_bar + analysis + evaluation_matrix + summary_matrix',
    plan: 'toc + attachment_header_bar + schedule + role_matrix + budget_matrix + checklist',
    minutes: 'toc + contact_box + summary_matrix + checklist + role_matrix',
    proposal: 'toc + attachment_header_bar + summary_matrix + budget_matrix + schedule + evaluation_matrix',
    notice: 'toc + attachment_header_bar + contact_box + summary_matrix + checklist + note_box',
  },
  document_recipes: {
    report: {
      toc: fallbackToc[0],
      components: ['attachment_header_bar', 'contact_box', 'note_box', 'section_heading_rule'],
      tables: ['summary_matrix', 'schedule', 'risk_matrix'],
    },
    research: {
      toc: fallbackToc[1],
      components: ['attachment_header_bar', 'note_box', 'section_heading_rule'],
      tables: ['analysis', 'evaluation_matrix', 'summary_matrix'],
    },
    plan: {
      toc: fallbackToc[2],
      components: ['attachment_header_bar', 'contact_box', 'note_box', 'section_heading_rule'],
      tables: ['schedule', 'role_matrix', 'budget_matrix', 'checklist'],
    },
    minutes: {
      toc: ['Ⅰ. 회의 개요', 'Ⅱ. 주요 안건', 'Ⅲ. 논의 결과', 'Ⅳ. 결정 사항', 'Ⅴ. 후속 조치'],
      components: ['contact_box', 'section_heading_rule'],
      tables: ['summary_matrix', 'role_matrix', 'checklist'],
    },
    proposal: {
      toc: ['Ⅰ. 제안 개요', 'Ⅱ. 추진 배경', 'Ⅲ. 제안 내용', 'Ⅳ. 실행 방안', 'Ⅴ. 기대 효과'],
      components: ['attachment_header_bar', 'contact_box', 'note_box', 'section_heading_rule'],
      tables: ['summary_matrix', 'budget_matrix', 'schedule', 'evaluation_matrix'],
    },
    notice: {
      toc: ['Ⅰ. 안내 개요', 'Ⅱ. 주요 내용', 'Ⅲ. 대상 및 절차', 'Ⅳ. 유의 사항', 'Ⅴ. 문의 및 후속 안내'],
      components: ['attachment_header_bar', 'contact_box', 'note_box', 'section_heading_rule'],
      tables: ['summary_matrix', 'checklist'],
    },
  },
};

await writeFile(outPath, JSON.stringify(kit, null, 2), 'utf8');
console.log(JSON.stringify({ ok: true, out: outPath, file_count: sampleFiles.length, tables: kit.table_templates.length }));
