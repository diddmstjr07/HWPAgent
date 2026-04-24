import './bootstrap.mjs';
import { openHwp } from './hwp-helper.mjs';

const files = ['text.hwp', 'form.hwp', 'table.hwp'];

for (const f of files) {
  try {
    const doc = await openHwp(`../../samples/${f}`);
    const paraCount = doc.raw.getParagraphCount(0);
    const firstPara = doc.getText(0, 0, 0, 100);
    console.log(`✓ ${f}: sections=${doc.raw.getSectionCount()}, paras=${paraCount}, first="${firstPara.slice(0, 40)}..."`);
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    console.error(`✗ ${f}: ${message}`);
  }
}
