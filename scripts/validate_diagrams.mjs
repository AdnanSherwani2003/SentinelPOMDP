// Development-only syntax check. Install with npm ci --prefix tools/diagrams.
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const requireTool = createRequire(new URL('../tools/diagrams/package.json', import.meta.url));
let JSDOM;
try {
  ({ JSDOM } = requireTool('jsdom'));
} catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
  throw new Error('Install locked diagram tools: npm ci --prefix tools/diagrams --include=dev --ignore-scripts');
}
const dom = new JSDOM('<!doctype html><html><body></body></html>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const { default: mermaid } = await import(pathToFileURL(requireTool.resolve('mermaid')));
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
let total = 0;
for (const file of ['README.md', 'docs/architecture.md']) {
  const text = await readFile(new URL('../' + file, import.meta.url), 'utf8');
  const blocks = [...text.matchAll(/```mermaid\r?\n([\s\S]*?)```/g)];
  if (!blocks.length) throw new Error('No Mermaid blocks found in ' + file);
  for (const block of blocks) await mermaid.parse(block[1]);
  total += blocks.length;
}
console.log(JSON.stringify({ mermaid_diagrams_parsed: total, github_remote_render: 'NOT RUN' }));
