import { openHwp } from '../dist/hwp-helper.js';
import { readdirSync } from 'node:fs';

for (const f of readdirSync('../../samples').filter((name) => name.endsWith('.hwp')).sort()) {
  const doc = await openHwp(`../../samples/${f}`);
  console.log(`\n=== ${f} ===`);
  console.log(`sections: ${doc.getSectionCount()}`);
  const paragraphCount = doc.getParagraphCount(0);
  console.log(`paragraphs: ${paragraphCount}`);
  console.log(`first text: "${doc.getText(0, 0, 0, 80)}"`);

  try {
    const fields = doc.raw.getFieldList?.();
    console.log(`fields: ${fields ? JSON.stringify(fields).slice(0, 200) : 'method not available'}`);
  } catch (e) {
    console.log(`fields: error - ${e.message}`);
  }

  let tableCount = 0;
  for (let para = 0; para < paragraphCount; para++) {
    try {
      doc.raw.getTableDimensions(0, para, 0);
      tableCount += 1;
    } catch {
      // no table control at control index 0 for this paragraph
    }
  }
  console.log(`tables detected: ${tableCount}`);
}
