import { openHwp } from '../dist/hwp-helper.js';
import { readdirSync } from 'node:fs';

for (const f of readdirSync('../../samples').filter((n) => n.endsWith('.hwp'))) {
  const doc = await openHwp(`../../samples/${f}`);
  console.log(`\n=== ${f} ===`);
  const n = doc.getParagraphCount(0);
  for (let i = 0; i < n; i++) {
    const t = doc.getText(0, i, 0, 200);
    console.log(`  [${i}] len=${t.length} "${t.slice(0, 60)}"`);
  }
}
