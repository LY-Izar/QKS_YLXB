import fs from 'node:fs';

const html = fs.readFileSync('index.html', 'utf8');
const lines = html.split('\n');

const topRe = /^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=/;
const anyFnRe = /\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/;

const units = [];
for (let i = 0; i < lines.length; i++) {
  const m = lines[i].match(topRe);
  const name = m && (m[1] || m[2]);
  if (name) { units.push({ name, start: i + 1, top: true }); continue; }
  const m2 = lines[i].match(anyFnRe);
  if (m2) units.push({ name: m2[1], start: i + 1, top: false });
}
units.sort((a, b) => a.start - b.start);

const nextOf = new Map();
for (let i = 0; i < units.length; i++) {
  const end = (i + 1 < units.length) ? units[i + 1].start - 1 : lines.length;
  nextOf.set(units[i].start, end);
}

const byName = new Map();
for (const u of units) {
  if (!byName.has(u.name)) byName.set(u.name, []);
  byName.get(u.name).push(u);
}

function lookup(docName) {
  const n = docName.replace(/\s*\([^)]*\)\s*$/, '').trim();
  const direct = byName.get(n);
  if (direct && direct.length) {
    const topIdx = direct.findIndex(u => u.top);
    return topIdx >= 0 ? direct.splice(topIdx, 1)[0] : direct.shift();
  }
  return null;
}

const doc = fs.readFileSync('MAINTENANCE.md', 'utf8');
const docLines = doc.split('\n');
let current = null;
let updated = 0;
let missing = 0;
const out = docLines.map(line => {
  const h = line.match(/^###\s+`([^`]+)`/);
  if (h) { current = h[1]; return line; }
  const r = line.match(/^-\s*行号:\s*L(\d+)\s*~\s*L(\d+)\s*\(共\s*(\d+)\s*行\)/);
  if (r && current) {
    const u = lookup(current);
    if (u) {
      const end = nextOf.get(u.start) || u.start;
      const len = Math.max(1, end - u.start + 1);
      updated++;
      return `- 行号: L${u.start} ~ L${end} (共 ${len} 行)`;
    }
    missing++;
    return line;
  }
  return line;
});

fs.writeFileSync('MAINTENANCE.md', out.join('\n'));
console.log(`units=${units.length} updated=${updated} missing=${missing}`);
