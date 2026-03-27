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
const openapiCliPath = requireFromUi.resolve('openapi-typescript/bin/cli.js');
const generatorScript = 'tools/config/sync_shared_contracts_to_ui.mjs';
const httpSchemaSrc = resolve(root, 'apps/ui/src/contracts/http_api_schema.json');
const httpTypesDst = resolve(root, 'apps/ui/src/generated/http_api_contracts.ts');
const constantsGeneratorSrc = resolve(root, 'tools/config/generate_ui_shared_constants.py');
const constantsDst = resolve(root, 'apps/ui/src/constants.ts');
const wsSchemaSrc = resolve(root, 'apps/ui/src/contracts/ws_payload_schema.json');
const wsSchemaTsDst = resolve(root, 'apps/ui/src/contracts/ws_payload_schema.generated.ts');
const wsTypesDst = resolve(root, 'apps/ui/src/contracts/ws_payload_types.ts');

function generatedHeader(sourcePath) {
	return (
		`// Generated from ${sourcePath}\n`
		+ `// Do not edit manually; run ${generatorScript}\n\n`
	);
}

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

function runOpenApiGenerator(schemaPath, failureMessage) {
	const result = spawnSync(process.execPath, [openapiCliPath, schemaPath], {
		encoding: 'utf8',
	});
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || failureMessage);
	}
	return result.stdout;
}

async function generateHttpTypes() {
	return generatedHeader('apps/ui/src/contracts/http_api_schema.json')
		+ runOpenApiGenerator(httpSchemaSrc, 'openapi-typescript generation failed');
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
		+ 'export type StrengthMetricsPayload = WsSchema<"VibrationStrengthMetrics">;\n'
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
	let result;
	try {
		result = runOpenApiGenerator(tempSchemaPath, 'WS type generation failed');
	} finally {
		rmSync(tempDir, { recursive: true, force: true });
	}
	return (
		generatedHeader('apps/ui/src/contracts/ws_payload_schema.json')
		+ result
		+ wsAliasBlock(String(schemaVersion))
	);
}

function generateWsSchemaModule() {
	const wsSchema = JSON.parse(readFileSync(wsSchemaSrc, 'utf8'));
	return (
		generatedHeader('apps/ui/src/contracts/ws_payload_schema.json')
		+ 'export const wsPayloadSchema = '
		+ `${JSON.stringify(wsSchema, null, 2)}`
		+ ' as const;\n\n'
		+ 'export default wsPayloadSchema;\n'
	);
}

function generateSharedConstants() {
	const pythonCmd = process.env.PYTHON || 'python3';
	const result = spawnSync(pythonCmd, [constantsGeneratorSrc], {
		cwd: root,
		encoding: 'utf8',
	});
	if (result.error) {
		throw result.error;
	}
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || 'Shared constants generation failed');
	}
	return result.stdout;
}

async function main() {
	const checkMode = process.argv.includes('--check');

	const httpGenerated = await generateHttpTypes();
	writeGenerated(httpTypesDst, httpGenerated, checkMode);

	const wsGenerated = await generateWsTypes();
	writeGenerated(wsTypesDst, wsGenerated, checkMode);

	const wsSchemaModule = generateWsSchemaModule();
	writeGenerated(wsSchemaTsDst, wsSchemaModule, checkMode);

	const sharedConstants = generateSharedConstants();
	writeGenerated(constantsDst, sharedConstants, checkMode);

	if (checkMode) {
		console.log('Generated UI contract files are up to date.');
		return;
	}

	console.log(`Generated ${httpSchemaSrc} -> ${httpTypesDst}`);
	console.log(`Generated ${wsSchemaSrc} -> ${wsTypesDst}`);
	console.log(`Generated ${wsSchemaSrc} -> ${wsSchemaTsDst}`);
	console.log(`Generated ${constantsGeneratorSrc} -> ${constantsDst}`);
}

await main();
