import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = resolve(__dirname, '../..');
const requireFromUi = createRequire(resolve(root, 'apps/ui/package.json'));
const sharedSrc = resolve(root, 'libs/shared/ts/contracts.ts');
const sharedDst = resolve(root, 'apps/ui/src/generated/shared_contracts.ts');
const httpSchemaSrc = resolve(root, 'apps/ui/src/contracts/http_api_schema.json');
const httpTypesDst = resolve(root, 'apps/ui/src/generated/http_api_contracts.ts');

function writeGenerated(filePath, content, checkMode) {
	mkdirSync(dirname(filePath), { recursive: true });
	if (checkMode) {
		const existing = readFileSync(filePath, 'utf8');
		if (existing !== content) {
			throw new Error(`Out of date generated file: ${filePath}`);
		}
		return;
	}
	writeFileSync(filePath, content, 'utf8');
}

async function generateHttpTypes() {
	const openapiCliPath = requireFromUi.resolve('openapi-typescript/bin/cli.js');
	const result = spawnSync(process.execPath, [openapiCliPath, httpSchemaSrc], {
		encoding: 'utf8',
	});
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || 'openapi-typescript generation failed');
	}
	return (
		'// Generated from apps/ui/src/contracts/http_api_schema.json\n'
		+ '// Do not edit manually; run tools/config/sync_shared_contracts_to_ui.mjs\n\n'
		+ result.stdout
	);
}

async function main() {
	const checkMode = process.argv.includes('--check');

	const sharedContent = readFileSync(sharedSrc, 'utf8');
	const sharedGenerated = `// Generated from libs/shared/ts/contracts.ts\n// Do not edit manually; run tools/config/sync_shared_contracts_to_ui.mjs\n\n${sharedContent}`;
	writeGenerated(sharedDst, sharedGenerated, checkMode);

	const httpGenerated = await generateHttpTypes();
	writeGenerated(httpTypesDst, httpGenerated, checkMode);

	if (checkMode) {
		console.log('Generated UI contract files are up to date.');
		return;
	}

	console.log(`Synced ${sharedSrc} -> ${sharedDst}`);
	console.log(`Generated ${httpSchemaSrc} -> ${httpTypesDst}`);
}

await main();
