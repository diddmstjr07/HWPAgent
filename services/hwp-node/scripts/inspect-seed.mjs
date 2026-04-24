import './bootstrap.mjs';
import { openHwp } from './hwp-helper.mjs';

const seedPath = process.env.SEED_HWP || '../../output/templates/1766728379269_2.hwp';
const doc = await openHwp(seedPath);

console.log(`Seed: ${seedPath}`);
console.log(`Section count: ${doc.raw.getSectionCount()}`);
console.log(`Paragraphs in section 0: ${doc.raw.getParagraphCount(0)}`);

const paraCount = doc.raw.getParagraphCount(0);
for (let i = 0; i < Math.min(paraCount, 30); i++) {
  const text = doc.getText(0, i, 0, 120);
  console.log(`  para[${i}] (${text.length} chars): "${text.slice(0, 100)}"`);
}

const fields = JSON.parse(doc.raw.getFieldList());
console.log(`Fields: ${fields.length} — ${JSON.stringify(fields).slice(0, 500)}`);
