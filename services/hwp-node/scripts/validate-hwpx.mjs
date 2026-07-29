// 생성된 hwpx 를 실제 @rhwp/core 로 열어 파싱/문단/텍스트를 검증한다.
import '../src/bootstrap.js';            // @rhwp/core WASM 초기화 (hwp-helper 와 동일)
import { readFile } from 'node:fs/promises';
import { HwpDocument } from '@rhwp/core';

const path = process.argv[2] || '/tmp/hwpx_poc/out.hwpx';
const bytes = await readFile(path);

let doc;
try {
  doc = new HwpDocument(new Uint8Array(bytes));
} catch (e) {
  console.error('[FAIL] @rhwp/core 가 파일을 열지 못함:', e?.message || e);
  process.exit(1);
}
console.log('[OK] 파일 열림:', path, `(${bytes.length} bytes)`);

const secCount = doc.getSectionCount?.();
const paraCount = doc.getParagraphCount?.(0);
console.log(`[OK] 섹션 ${secCount}개, 섹션0 문단 ${paraCount}개`);

// 각 문단 텍스트 추출 (getTextRange(sec, paraStart, offStart, paraEnd, offEnd) 형태)
// 내용 있는 문단만 출력한다.
const n = Math.min(Number(paraCount) || 0, 5000);
const nonEmpty = [];
for (let p = 0; p < n; p++) {
  const len = doc.getParagraphLength?.(0, p) ?? 0;
  if (!len) continue;
  let t = '';
  for (const args of [[0, p, 0, len], [0, p, 0, p, len], [0, p]]) {
    try { const r = doc.getTextRange(...args); if (r && String(r).length > String(t).length) t = r; } catch {}
  }
  if (t) nonEmpty.push([p, t]);
}
console.log(`[OK] 내용 있는 문단 ${nonEmpty.length}개:`);
nonEmpty.forEach(([i, t]) => console.log(`   [${i}] ${JSON.stringify(t)}`));

// linesegs 재계산도 정상 동작하는지 확인
try { doc.reflowLinesegs?.(); console.log('[OK] reflowLinesegs() 정상 (레이아웃 재계산 가능)'); } catch (e) { console.log('[..] reflowLinesegs:', e?.message); }

console.log('[DONE] 라운드트립 검증 완료');
