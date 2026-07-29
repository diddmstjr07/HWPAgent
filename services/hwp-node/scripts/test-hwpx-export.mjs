import '../src/bootstrap.js';
import { readFile } from 'node:fs/promises';
import { HwpDocument } from '@rhwp/core';
const bytes = await readFile(process.env.HOME + '/Documents/hwp-agent/assets/hwpx/base.hwpx');
const doc = new HwpDocument(new Uint8Array(bytes));
console.log('opened, paras(sec0)=', doc.getParagraphCount(0));
for (const m of ['exportHwpx','exportHwp']) {
  try {
    const out = doc[m]();
    console.log(`[OK] ${m}() -> ${out.byteLength} bytes head=`, Buffer.from(out.slice(0,4)).toString('hex'));
  } catch(e){ console.log(`[FAIL] ${m}:`, e?.message); }
}
