import '../src/bootstrap.js';
import { readFile } from 'node:fs/promises';
import { HwpDocument } from '@rhwp/core';
import JSZipMod from 'jszip';
import re from 'node:module';
// 간단 zip 편집: jszip 없을 수 있으니 fflate 시도
let zipEdit;
try { const {unzipSync, zipSync, strToU8, strFromU8} = await import('fflate');
  zipEdit = { unzipSync, zipSync, strToU8, strFromU8 };
} catch(e){ console.log('no fflate', e.message); }

const home = process.env.HOME + '/Documents/hwp-agent';
const bytes = new Uint8Array(await readFile(home + '/assets/hwpx/base.hwpx'));
const doc = new HwpDocument(bytes);
const hwpx = doc.exportHwpx();

const files = zipEdit.unzipSync(new Uint8Array(hwpx));
let header = zipEdit.strFromU8(files['Contents/header.xml']);
const before = (header.match(/face="[^"]*"/g)||[]).slice(0,4);
const FONT='맑은 고딕';
header = header.replace(/(<hh:(?:font|substFont)\b[^>]*?\bface=")[^"]*(")/g, `$1${FONT}$2`);
files['Contents/header.xml'] = zipEdit.strToU8(header);
const after = (header.match(/face="[^"]*"/g)||[]).slice(0,4);
const newHwpx = zipEdit.zipSync(files);

const doc2 = new HwpDocument(new Uint8Array(newHwpx));
const svg = doc2.renderPageSvg ? doc2.renderPageSvg(0) : (doc2.renderPageHtml ? doc2.renderPageHtml(0) : '');
const fams = [...new Set((String(svg).match(/font-family:[^;"']+/g)||[]))].slice(0,6);
console.log('face before:', before);
console.log('face after :', after);
console.log('render font-family:', fams);
