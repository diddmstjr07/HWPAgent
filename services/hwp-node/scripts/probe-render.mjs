import { openHwp } from '../dist/hwp-helper.js';
import { writeFile, mkdir } from 'node:fs/promises';

const sample = process.argv[2] || '../../samples/text.hwp';
const outDir = 'render-probe';
await mkdir(outDir, { recursive: true });

const doc = await openHwp(sample);
const raw = doc.raw;

const methodCandidates = [
  'renderPageSvg',
  'renderPage',
  'toSvg',
  'pageToSvg',
  'renderToSvg',
  'svgForPage',
];

let methodUsed = null;
let output = null;
let lastError = null;

for (const name of methodCandidates) {
  if (typeof raw[name] !== 'function') continue;
  try {
    const attempts = [
      () => raw[name](0),
      () => raw[name](0, {}),
      () => raw[name](0, 1.0),
    ];
    for (const attempt of attempts) {
      try {
        output = attempt();
        methodUsed = name;
        break;
      } catch (e) {
        lastError = e;
      }
    }
    if (methodUsed) break;
  } catch (e) {
    lastError = e;
  }
}

if (!methodUsed) {
  const proto = Object.getPrototypeOf(raw);
  const allMethods = Object.getOwnPropertyNames(proto)
    .filter((n) => typeof raw[n] === 'function' && !n.startsWith('_'));
  console.log('No render method worked. All available methods on raw:');
  console.log(allMethods.join(', '));
  console.log(`Last error: ${lastError}`);
  process.exit(1);
}

console.log(`Method used: ${methodUsed}`);
console.log(`Output type: ${typeof output}`);

if (typeof output === 'string') {
  console.log(`Output length: ${output.length} chars`);
  console.log(`First 500 chars:\n${output.slice(0, 500)}`);
  await writeFile(`${outDir}/page0.svg`, output);
  console.log(`Saved SVG: ${outDir}/page0.svg`);
} else if (output instanceof Uint8Array) {
  console.log(`Output length: ${output.length} bytes (binary)`);
  await writeFile(`${outDir}/page0.bin`, output);
  console.log(`Saved binary: ${outDir}/page0.bin`);
} else {
  console.log('Unexpected output:', output);
}

try {
  const pc = raw.pageCount?.() ?? raw.getPageCount?.();
  console.log(`Page count: ${pc}`);
} catch (e) {
  console.log(`pageCount not available: ${e}`);
}
