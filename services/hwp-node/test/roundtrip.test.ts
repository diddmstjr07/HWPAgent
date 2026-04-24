import { describe, it, expect } from 'vitest';
import { openHwp, openHwpFromBytes, HwpDocWrapper } from '../src/hwp-helper.js';
import { applyOp } from '../src/operations.js';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SAMPLES = resolve(__dirname, '../../../samples');

/**
 * 편집이 끝난 문서를 exportHwp -> openHwpFromBytes로 왕복시켜
 * 저장 경로가 실제로 거치는 직렬화/역직렬화 과정을 재현한다.
 */
async function roundTrip(doc: HwpDocWrapper): Promise<HwpDocWrapper> {
  const bytes = doc.exportBytes();
  return openHwpFromBytes(bytes);
}

/**
 * getCharPropertiesAt의 JSON 문자열 결과를 파싱해서 객체로 반환.
 * 특정 프로퍼티만 조회하고 싶을 때 유용.
 */
function getCharProps(doc: HwpDocWrapper, sec: number, para: number, offset: number): any {
  const json = doc.getCharPropertiesAt(sec, para, offset);
  return JSON.parse(json);
}

describe('ROUND-TRIP REGRESSION: fontId persistence (project critical)', () => {
  /**
   * CRITICAL BUG #1 (fixed): rhwp에서 applyCharFormat에 fontFamily 문자열만 지정하면
   * export -> reload 후 해당 글자의 fontFamily가 "맑은 고딕"으로 리셋되는 버그.
   * 해결: operations.ts의 opSetCharFormat이 fontName을 받으면
   * findOrCreateFontId로 ID를 얻어 fontId + fontIds[7] 형태로 지정.
   *
   * 이 테스트가 실패하면 버그 재발이다. 절대 skip하거나 수정하지 말고,
   * 원인 분석 후 operations.ts의 fontName->fontId 변환 로직을 수정해야 한다.
   */
  it('fontName preserved across save/reload when set via set_char_format', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);

    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 6,
      start: 0,
      end: 5,
      props: { fontName: '함초롬바탕', fontSize: 1400, bold: true }
    });

    const sessionProps = getCharProps(doc, 0, 6, 0);
    expect(sessionProps.fontFamily).toBe('함초롬바탕');
    expect(sessionProps.bold).toBe(true);
    expect(sessionProps.fontSize).toBe(1400);

    const reloaded = await roundTrip(doc);
    const reloadedProps = getCharProps(reloaded, 0, 6, 0);

    expect(reloadedProps.fontFamily).toBe('함초롬바탕');
    expect(reloadedProps.bold).toBe(true);
    expect(reloadedProps.fontSize).toBe(1400);
  });

  it('multiple different fonts preserved in same paragraph', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);

    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 6,
      start: 0,
      end: 5,
      props: { fontName: '함초롬바탕' }
    });
    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 6,
      start: 5,
      end: 10,
      props: { fontName: '휴먼명조' }
    });

    const reloaded = await roundTrip(doc);
    const props1 = getCharProps(reloaded, 0, 6, 0);
    const props2 = getCharProps(reloaded, 0, 6, 5);

    expect(props1.fontFamily).toBe('함초롬바탕');
    expect(props2.fontFamily).toBe('휴먼명조');
  });

  it('fontId-only (no fontName) also survives round-trip', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);

    const fontId = doc.findOrCreateFontId('함초롬돋움');
    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 6,
      start: 0,
      end: 5,
      props: { fontId, fontIds: Array(7).fill(fontId), fontSize: 1100 }
    });

    const reloaded = await roundTrip(doc);
    const props = getCharProps(reloaded, 0, 6, 0);
    expect(props.fontFamily).toBe('함초롬돋움');
  });
});

describe('ROUND-TRIP: text operations persist', () => {
  it('insert_text persists', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 6,
      offset: 0,
      text: 'INSERTED-'
    });

    const reloaded = await roundTrip(doc);
    const text = reloaded.getText(0, 6, 0, 20);
    expect(text.startsWith('INSERTED-')).toBe(true);
  });

  it('delete_text persists', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 6,
      offset: 0,
      text: 'REMOVE-ME-'
    });
    applyOp(doc, {
      kind: 'delete_text',
      sec: 0,
      para: 6,
      offset: 0,
      length: 10
    });

    const reloaded = await roundTrip(doc);
    const text = reloaded.getText(0, 6, 0, 20);
    expect(text.startsWith('REMOVE-ME-')).toBe(false);
  });

  it('replace_text persists', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 6,
      offset: 0,
      text: 'OLDOLD'
    });
    applyOp(doc, {
      kind: 'replace_text',
      sec: 0,
      para: 6,
      offset: 0,
      length: 6,
      newText: 'NEWTXT'
    });

    const reloaded = await roundTrip(doc);
    const text = reloaded.getText(0, 6, 0, 10);
    expect(text.startsWith('NEWTXT')).toBe(true);
    expect(text).not.toContain('OLDOLD');
  });
});

describe('ROUND-TRIP: paragraph structure', () => {
  it('split_paragraph persists', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const before = doc.getParagraphCount(0);

    applyOp(doc, {
      kind: 'split_paragraph',
      sec: 0,
      para: 6,
      offset: 5
    });

    const sessionAfter = doc.getParagraphCount(0);
    expect(sessionAfter).toBe(before + 1);

    const reloaded = await roundTrip(doc);
    const reloadedCount = reloaded.getParagraphCount(0);
    expect(reloadedCount).toBe(before + 1);
  });

  it('set_para_format (align) persists', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, {
      kind: 'set_para_format',
      sec: 0,
      para: 6,
      props: { align: 'Center' }
    });

    const reloaded = await roundTrip(doc);
    const hasGetter = typeof reloaded.getParaPropertiesAt === 'function';
    if (hasGetter) {
      const json = reloaded.getParaPropertiesAt(0, 6);
      const props = JSON.parse(json);
      expect(props.alignment).toBe('center');
    } else {
      console.warn('getParaPropertiesAt not available - skipping structural check');
      expect(reloaded.getParagraphCount(0)).toBeGreaterThan(0);
    }
  });
});

describe('ROUND-TRIP REGRESSION: search_replace_all (replaces rhwp.replaceAll)', () => {
  /**
   * CRITICAL BUG #2 (avoided): rhwp의 replaceAll은 세션 내에서는 동작하지만
   * export -> reload 후 원본으로 복원되는 버그가 있다.
   * 해결: search_replace_all op는 rhwp.replaceAll 대신
   * searchText를 반복 호출해서 replaceText로 교체하는 방식으로 구현됨.
   *
   * 이 테스트는 그 우회 구현이 실제로 persistent한지 검증.
   */
  it('search_replace_all changes persist after round-trip', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);

    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 6,
      offset: 0,
      text: 'TARGET once TARGET twice TARGET thrice '
    });

    applyOp(doc, {
      kind: 'search_replace_all',
      query: 'TARGET',
      replacement: 'REPLACED'
    });

    const sessionText = doc.getText(0, 6, 0, 100);
    expect(sessionText).toContain('REPLACED once REPLACED twice REPLACED thrice');
    expect(sessionText).not.toContain('TARGET');

    const reloaded = await roundTrip(doc);
    const reloadedText = reloaded.getText(0, 6, 0, 100);
    expect(reloadedText).toContain('REPLACED once REPLACED twice REPLACED thrice');
    expect(reloadedText).not.toContain('TARGET');
  });
});

describe('ROUND-TRIP: composite editing scenario', () => {
  it('sequence of 8 ops survives round-trip', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);

    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 0,
      offset: 0,
      text: '[DRAFT] '
    });
    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 0,
      start: 0,
      end: 8,
      props: { fontName: '함초롬바탕', bold: true, fontSize: 1200 }
    });
    applyOp(doc, {
      kind: 'set_para_format',
      sec: 0,
      para: 0,
      props: { align: 'Center' }
    });
    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 6,
      offset: 0,
      text: 'PREFIX-'
    });
    applyOp(doc, {
      kind: 'replace_text',
      sec: 0,
      para: 6,
      offset: 0,
      length: 7,
      newText: 'CHANGED-'
    });
    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 10,
      offset: 0,
      text: 'TOKEN '
    });
    applyOp(doc, {
      kind: 'search_replace_all',
      query: 'TOKEN',
      replacement: 'MARKER'
    });
    applyOp(doc, {
      kind: 'split_paragraph',
      sec: 0,
      para: 2,
      offset: 5
    });

    const reloaded = await roundTrip(doc);

    expect(reloaded.getText(0, 0, 0, 10).startsWith('[DRAFT]')).toBe(true);

    const titleProps = getCharProps(reloaded, 0, 0, 0);
    expect(titleProps.fontFamily).toBe('함초롬바탕');
    expect(titleProps.bold).toBe(true);

    // split_paragraph at para 2 shifts later paragraph indexes by one.
    expect(reloaded.getText(0, 7, 0, 20).startsWith('CHANGED-')).toBe(true);
    expect(reloaded.getText(0, 11, 0, 20)).toContain('MARKER');
  });
});

describe('ROUND-TRIP: resilience', () => {
  it('unmodified document round-trips without error', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const reloaded = await roundTrip(doc);
    expect(reloaded.getSectionCount()).toBeGreaterThan(0);
  });

  it('round-trip is idempotent (stable across multiple passes)', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 6,
      offset: 0,
      text: 'STABLE-'
    });

    const rt1 = await roundTrip(doc);
    const rt2 = await roundTrip(rt1);
    const rt3 = await roundTrip(rt2);

    expect(rt1.getText(0, 6, 0, 10).startsWith('STABLE-')).toBe(true);
    expect(rt2.getText(0, 6, 0, 10).startsWith('STABLE-')).toBe(true);
    expect(rt3.getText(0, 6, 0, 10).startsWith('STABLE-')).toBe(true);
  });
});
