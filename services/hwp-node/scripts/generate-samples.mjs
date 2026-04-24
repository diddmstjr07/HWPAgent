import './bootstrap.mjs';
import { openHwp } from './hwp-helper.mjs';
import path from 'node:path';
import { mkdir } from 'node:fs/promises';

const SEED_PATH = process.env.SEED_HWP || '../../output/templates/1766728379269_2.hwp';
const SAMPLES_DIR = path.resolve('../../samples');

function normalizeError(e) {
  if (e instanceof Error) return e;
  if (typeof e === 'string') return new Error(e);
  return new Error(String(e));
}

function splitParagraph(doc, sec, para, offset) {
  try {
    doc.raw.splitParagraph(sec, para, offset);
  } catch (e) {
    throw normalizeError(e);
  }
}

function insertLines(doc, lines) {
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].text.length > 0) {
      doc.insertText(0, i, 0, lines[i].text);
    }
    if (i < lines.length - 1) {
      splitParagraph(doc, 0, i, lines[i].text.length);
    }
  }
}

function applyFont(doc, paraIdx, text, extraProps = {}) {
  const fontId = doc.raw.findOrCreateFontId('함초롬바탕');
  const fontIds = [fontId, fontId, fontId, fontId, fontId, fontId, fontId];
  doc.setCharFormat(0, paraIdx, 0, text.length, {
    fontId,
    fontIds,
    fontSize: 1100,
    textColor: 0x000000,
    ...extraProps,
  });
}

async function makeTextSample() {
  const doc = await openHwp(SEED_PATH);
  const lines = [
    { text: '샘플 본문 문서', kind: 'title' },
    { text: '', kind: 'blank' },
    { text: '이 문서는 @rhwp/core 단위 테스트를 위한 샘플입니다.', kind: 'body' },
    { text: '여러 단락, 여러 서식 조합을 포함하여 편집 연산을 검증합니다.', kind: 'body' },
    { text: '', kind: 'blank' },
    { text: '첫 번째 섹션', kind: 'heading' },
    { text: '일반 본문 단락입니다. 이 문장은 insert_text와 replace_text 연산의 대상이 됩니다.', kind: 'body' },
    { text: '두 번째 단락입니다. split_paragraph로 쪼개는 테스트에 사용됩니다.', kind: 'body' },
    { text: '', kind: 'blank' },
    { text: '두 번째 섹션', kind: 'heading' },
    { text: '여기에 set_char_format 테스트를 위한 문장이 있습니다.', kind: 'body' },
    { text: '서식 변경 후 저장 재로드로 fontId 경로의 지속성을 확인합니다.', kind: 'body' },
  ];

  insertLines(doc, lines);

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].text.length === 0) continue;
    if (lines[i].kind === 'title') {
      applyFont(doc, i, lines[i].text, { fontSize: 1800, bold: true });
      doc.setParaFormat(0, i, { align: 'Center' });
    } else if (lines[i].kind === 'heading') {
      applyFont(doc, i, lines[i].text, { fontSize: 1400, bold: true });
    } else if (lines[i].kind === 'body') {
      applyFont(doc, i, lines[i].text);
      doc.setParaFormat(0, i, { align: 'Justify', lineSpacing: 180, lineSpacingType: 'Percent' });
    }
  }

  await doc.save(path.join(SAMPLES_DIR, 'text.hwp'));
  console.log('✓ samples/text.hwp generated');
}

async function makeTableSample() {
  const doc = await openHwp(SEED_PATH);
  const lines = [
    { text: '표 샘플', kind: 'title' },
    { text: '', kind: 'blank' },
    { text: '아래는 3x3 표입니다.', kind: 'body' },
    { text: '', kind: 'blank' },
  ];
  insertLines(doc, lines);

  try {
    doc.raw.createTable(0, lines.length - 1, 0, 3, 3);
  } catch (e) {
    console.warn('createTable failed - table sample skipped:', normalizeError(e).message);
    return false;
  }

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].text.length === 0) continue;
    if (lines[i].kind === 'title') {
      applyFont(doc, i, lines[i].text, { fontSize: 1800, bold: true });
      doc.setParaFormat(0, i, { align: 'Center' });
    } else {
      applyFont(doc, i, lines[i].text);
    }
  }

  await doc.save(path.join(SAMPLES_DIR, 'table.hwp'));
  console.log('✓ samples/table.hwp generated');
  return true;
}

async function makeFormSample() {
  const doc = await openHwp(SEED_PATH);

  const lines = [
    { text: '지원서 양식 (샘플)', kind: 'title' },
    { text: '', kind: 'blank' },
    { text: '이름: ', kind: 'label' },
    { text: '생년월일: ', kind: 'label' },
    { text: '연락처: ', kind: 'label' },
    { text: '지원 동기: ', kind: 'label' },
    { text: '', kind: 'blank' },
    { text: '※ 본 문서의 밑줄 영역은 실제 폼 필드 대신 빈 텍스트로 표현되어 있습니다.', kind: 'note' },
    { text: '※ 진짜 폼 필드가 있는 양식은 실제 HWP 파일을 업로드하여 테스트합니다.', kind: 'note' },
  ];

  insertLines(doc, lines);

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].text.length === 0) continue;
    if (lines[i].kind === 'title') {
      applyFont(doc, i, lines[i].text, { fontSize: 1800, bold: true });
      doc.setParaFormat(0, i, { align: 'Center' });
    } else if (lines[i].kind === 'label') {
      applyFont(doc, i, lines[i].text, { fontSize: 1200 });
    } else if (lines[i].kind === 'note') {
      applyFont(doc, i, lines[i].text, { fontSize: 900, italic: true, textColor: 0x666666 });
    }
  }

  await doc.save(path.join(SAMPLES_DIR, 'form.hwp'));
  console.log('✓ samples/form.hwp generated (without real form controls)');
}

await mkdir(SAMPLES_DIR, { recursive: true });
await makeTextSample();
await makeTableSample();
await makeFormSample();
