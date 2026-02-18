import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = resolve(__dirname, '../..');
const src = resolve(root, 'libs/shared/ts/contracts.ts');
const dst = resolve(root, 'apps/ui/src/generated/shared_contracts.ts');

const content = readFileSync(src, 'utf8');
const generated = `// Generated from libs/shared/ts/contracts.ts\n// Do not edit manually; run tools/config/sync_shared_contracts_to_ui.mjs\n\n${content}`;
mkdirSync(dirname(dst), { recursive: true });
writeFileSync(dst, generated, 'utf8');
console.log(`Synced ${src} -> ${dst}`);
