import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = resolve(__dirname, '../..');
const requireFromUi = createRequire(resolve(root, 'apps/ui/package.json'));
const httpSchemaSrc = resolve(root, 'apps/ui/src/contracts/http_api_schema.json');
const httpTypesDst = resolve(root, 'apps/ui/src/generated/http_api_contracts.ts');
const wsSchemaSrc = resolve(root, 'apps/ui/src/contracts/ws_payload_schema.json');
const wsTypesDst = resolve(root, 'apps/ui/src/contracts/ws_payload_types.ts');

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

function rewriteSchemaRefs(value) {
	if (Array.isArray(value)) {
		return value.map((item) => rewriteSchemaRefs(item));
	}
	if (!value || typeof value !== 'object') {
		return value;
	}
	const rewritten = {};
	for (const [key, entry] of Object.entries(value)) {
		if (key === '$ref' && typeof entry === 'string' && entry.startsWith('#/$defs/')) {
			rewritten[key] = `#/components/schemas/${entry.slice('#/$defs/'.length)}`;
			continue;
		}
		rewritten[key] = rewriteSchemaRefs(entry);
	}
	return rewritten;
}

function wsAliasBlock(schemaVersion) {
	return (
		'\n'
		+ `export const EXPECTED_SCHEMA_VERSION = ${JSON.stringify(schemaVersion)} as const;\n\n`
		+ 'type WsSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];\n\n'
		+ 'export type StrengthMetricPeak = WsSchema<"StrengthPeak">;\n'
		+ 'export type StrengthMetricsPayload = WsSchema<"StrengthMetricsPayload">;\n'
		+ 'export type WsSpectrumSeries = WsSchema<"SpectrumSeriesPayload">;\n'
		+ 'export type WsAlignmentInfo = WsSchema<"AlignmentInfoPayload">;\n'
		+ 'export type WsFrequencyWarning = WsSchema<"FrequencyWarningPayload">;\n'
		+ 'export type WsSpectraPayload = WsSchema<"SpectraPayload">;\n'
		+ 'export type WsRotationalSpeedValue = WsSchema<"RotationalSpeedValuePayload">;\n'
		+ 'export type WsOrderBand = WsSchema<"OrderBandPayload">;\n'
		+ 'export type WsRotationalSpeeds = WsSchema<"RotationalSpeedsPayload">;\n'
		+ 'export type WsClientInfo = WsSchema<"ClientApiRow">;\n'
		+ 'export type LiveWsPayload = WsSchema<"LiveWsPayload">;\n'
	);
}

async function generateWsTypes() {
	const openapiCliPath = requireFromUi.resolve('openapi-typescript/bin/cli.js');
	const wsSchema = JSON.parse(readFileSync(wsSchemaSrc, 'utf8'));
	const defs = wsSchema.$defs && typeof wsSchema.$defs === 'object' ? wsSchema.$defs : {};
	const schemaVersion = wsSchema.properties?.schema_version?.default ?? '1';
	const rootSchema = { ...wsSchema };
	delete rootSchema.$defs;
	const wrapped = {
		openapi: '3.1.0',
		info: {
			title: 'VibeSensor WebSocket Payload',
			version: String(schemaVersion),
		},
		paths: {},
		components: {
			schemas: {
				LiveWsPayload: rewriteSchemaRefs(rootSchema),
				...Object.fromEntries(
					Object.entries(defs).map(([name, schema]) => [name, rewriteSchemaRefs(schema)]),
				),
			},
		},
	};
	const tempDir = mkdtempSync(resolve(tmpdir(), 'vibesensor-ws-openapi-'));
	const tempSchemaPath = resolve(tempDir, 'ws_openapi.json');
	writeFileSync(tempSchemaPath, `${JSON.stringify(wrapped, null, 2)}\n`, 'utf8');
	const result = spawnSync(process.execPath, [openapiCliPath, tempSchemaPath], {
		encoding: 'utf8',
	});
	rmSync(tempDir, { recursive: true, force: true });
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || 'WS type generation failed');
	}
	return (
		'// Generated from apps/ui/src/contracts/ws_payload_schema.json\n'
		+ '// Do not edit manually; run tools/config/sync_shared_contracts_to_ui.mjs\n\n'
		+ result.stdout
		+ wsAliasBlock(String(schemaVersion))
	);
}

async function main() {
	const checkMode = process.argv.includes('--check');

	const httpGenerated = await generateHttpTypes();
	writeGenerated(httpTypesDst, httpGenerated, checkMode);

	const wsGenerated = await generateWsTypes();
	writeGenerated(wsTypesDst, wsGenerated, checkMode);

	if (checkMode) {
		console.log('Generated UI contract files are up to date.');
		return;
	}

	console.log(`Generated ${httpSchemaSrc} -> ${httpTypesDst}`);
	console.log(`Generated ${wsSchemaSrc} -> ${wsTypesDst}`);
}

await main();
