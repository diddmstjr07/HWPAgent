import '../src/bootstrap.js';
import { readFile } from 'node:fs/promises';
import { HwpDocument } from '@rhwp/core';
const doc = new HwpDocument(new Uint8Array(await readFile('/tmp/fontswap.hwpx')));
let svg='';
try{ svg = doc.renderPageSvg(0);}catch(e){ try{svg=doc.renderPageHtml(0);}catch(e2){console.log('render fail',e2.message);} }
const fams=[...new Set((String(svg).match(/font-family\s*[:=][^;"'>]+/gi)||[]))].slice(0,8);
console.log('font-family in render:', fams.length?fams:'(none found)');
console.log('contains 맑은 고딕?', String(svg).includes('맑은 고딕'));
