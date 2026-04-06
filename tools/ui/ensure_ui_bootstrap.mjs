import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

function parseArgs(argv) {
	let checkMode = false;
	let skipNpmCi = false;
	let logPrefix = '[ui:bootstrap]';
	for (let index = 2; index < argv.length; index += 1) {
		const arg = argv[index];
		if (arg === '--check') {
			checkMode = true;
			continue;
		}
		if (arg === '--skip-npm-ci') {
			skipNpmCi = true;
			continue;
		}
		if (arg === '--log-prefix') {
			index += 1;
			const value = argv[index];
			if (!value) {
				throw new Error('--log-prefix requires a value');
			}
			logPrefix = value;
			continue;
		}
		throw new Error(`Unknown argument: ${arg}`);
	}
	return { checkMode, skipNpmCi, logPrefix };
}

function sha256File(filePath) {
	return createHash('sha256').update(readFileSync(filePath)).digest('hex');
}

function uiBootstrapStatus(uiDir, skipNpmCi) {
	const lockFile = resolve(uiDir, 'package-lock.json');
	const lockHashFile = resolve(uiDir, '.npm-ci-lock.sha256');
	const nodeModulesDir = resolve(uiDir, 'node_modules');
	const lockHash = sha256File(lockFile);
	const currentLockHash = existsSync(lockHashFile)
		? readFileSync(lockHashFile, 'utf8').trim()
		: '';
	return {
		lockHash,
		currentLockHash,
		nodeModulesExists: existsSync(nodeModulesDir),
		needsNpmCi:
			!skipNpmCi
			&& (!existsSync(nodeModulesDir) || lockHash !== currentLockHash),
		lockHashFile,
	};
}

function ensureUiBootstrap(uiDir, status, logPrefix) {
	if (!status.needsNpmCi) {
		return;
	}
	console.log(
		`${logPrefix} Running npm ci because node_modules is missing or package-lock.json changed.`,
	);
	const result = spawnSync('npm', ['ci'], {
		cwd: uiDir,
		stdio: 'inherit',
	});
	if (result.error) {
		throw result.error;
	}
	if (result.status !== 0) {
		throw new Error(`npm ci failed with exit code ${result.status ?? 1}`);
	}
	writeFileSync(status.lockHashFile, `${status.lockHash}\n`, 'utf8');
}

function main() {
	const { checkMode, skipNpmCi, logPrefix } = parseArgs(process.argv);
	const uiDir = process.cwd();
	const status = uiBootstrapStatus(uiDir, skipNpmCi);
	if (checkMode) {
		console.log(
			JSON.stringify({
				needs_npm_ci: status.needsNpmCi,
				lock_hash: status.lockHash,
				current_lock_hash: status.currentLockHash,
				node_modules_exists: status.nodeModulesExists,
			}),
		);
		return;
	}
	ensureUiBootstrap(uiDir, status, logPrefix);
}

try {
	main();
} catch (error) {
	const message = error instanceof Error ? error.message : String(error);
	console.error(message);
	process.exitCode = 1;
}
