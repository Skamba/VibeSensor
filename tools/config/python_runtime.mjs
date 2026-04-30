import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export function resolveConfiguredPythonCommand(root) {
	const envPython = process.env.PYTHON?.trim();
	if (envPython) {
		return envPython;
	}

	const version = readFileSync(resolve(root, '.python-version'), 'utf8').trim();
	const match = version.match(/^(\d+)\.(\d+)(?:\.\d+)?$/);
	if (!match) {
		throw new Error(`Unable to resolve Python command from .python-version: ${version}`);
	}
	return `python${match[1]}.${match[2]}`;
}
