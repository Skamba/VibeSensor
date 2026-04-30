import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveConfiguredPythonCommand } from './python_runtime.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = resolve(__dirname, '../..');
const pythonCmd = resolveConfiguredPythonCommand(root);
const contractReferenceScript = resolve(root, 'tools/config/generate_contract_reference_doc.py');
const uiDerivativeSyncScript = resolve(root, 'tools/config/sync_shared_contracts_to_ui.mjs');

function runCommand(label, command, args) {
	const result = spawnSync(command, args, {
		cwd: root,
		stdio: 'inherit',
		env: {
			...process.env,
			PYTHON: pythonCmd,
		},
	});
	if (result.error) {
		throw result.error;
	}
	if (result.status !== 0) {
		throw new Error(`${label} failed with exit code ${result.status ?? 1}`);
	}
}

async function main() {
	const checkMode = process.argv.includes('--check');
	const checkArgs = checkMode ? ['--check'] : [];

	runCommand('HTTP API schema export', pythonCmd, [
		'-m',
		'vibesensor.cli.http_api_schema_export',
		...checkArgs,
	]);
	runCommand('WS schema export', pythonCmd, [
		'-m',
		'vibesensor.cli.ws_schema_export',
		...checkArgs,
	]);
	runCommand('Contract reference document sync', pythonCmd, [
		contractReferenceScript,
		...checkArgs,
	]);
	runCommand('UI contract derivative sync', process.execPath, [
		uiDerivativeSyncScript,
		...checkArgs,
	]);

	if (checkMode) {
		console.log('All contract artifacts are up to date.');
		return;
	}
	console.log('Synchronized contract artifacts.');
}

await main();
