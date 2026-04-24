import { openHwp } from './hwp-helper.mjs';

const candidates = process.argv.slice(2);

for (const filePath of candidates) {
  try {
    const doc = await openHwp(filePath);
    console.log(`OK\t${filePath}\tsections=${doc.raw.getSectionCount()}\tpages=${doc.raw.pageCount()}`);
    process.exit(0);
  } catch (e) {
    console.log(`FAIL\t${filePath}\t${e.message}`);
  }
}

process.exit(1);
