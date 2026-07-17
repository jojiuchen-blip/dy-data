#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

import {
    calculateSuiteContentHash,
    collectHashableRelativeFiles,
    contentHashAlgorithm,
    readSuiteMetadata
} from './install-suite-into-host.mjs';

const __filename = fileURLToPath(import.meta.url);
const lockFileName = 'project-manager-suite.lock.json';
const expectedTargetPath = '.agent/project-manager-suite';
const manifestFileName = '.install-manifest.json';

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = { hostRoot: '', json: false };

    for (const arg of args) {
        if (arg === '--json') {
            options.json = true;
            continue;
        }

        if (!options.hostRoot) {
            options.hostRoot = arg;
            continue;
        }

        throw new Error(`Unknown argument: ${arg}`);
    }

    if (!options.hostRoot) {
        throw new Error('Missing host project root.');
    }

    return options;
}

function verifySuiteLock({ hostRoot }) {
    const resolvedHostRoot = path.resolve(process.cwd(), hostRoot);
    const suiteRoot = path.join(resolvedHostRoot, '.agent', 'project-manager-suite');
    const lockPath = path.join(resolvedHostRoot, '.agent', lockFileName);
    const manifestPath = path.join(suiteRoot, manifestFileName);

    if (!fs.existsSync(lockPath)) {
        return { status: 'lock_missing', valid: false };
    }

    if (!fs.existsSync(suiteRoot)) {
        return { status: 'suite_missing', valid: false };
    }

    if (!fs.existsSync(manifestPath)) {
        return { status: 'manifest_missing', valid: false };
    }

    const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
    if (lock.target_path !== expectedTargetPath || path.isAbsolute(lock.target_path || '')) {
        return { status: 'invalid_target_path', valid: false };
    }
    if (lock.content_hash_algorithm !== contentHashAlgorithm) {
        return {
            status: 'unsupported_hash_algorithm',
            valid: false,
            expected: contentHashAlgorithm,
            actual: lock.content_hash_algorithm || null
        };
    }

    const metadata = readSuiteMetadata(suiteRoot);
    if (lock.suite_name !== metadata.name || lock.suite_version !== metadata.version) {
        return {
            status: 'version_mismatch',
            valid: false,
            expected: `${metadata.name}@${metadata.version}`,
            actual: `${lock.suite_name || 'unknown'}@${lock.suite_version || 'unknown'}`
        };
    }

    const actualContentHash = calculateSuiteContentHash(suiteRoot);
    if (lock.content_sha256 !== actualContentHash) {
        return {
            status: 'content_mismatch',
            valid: false,
            expected_content_sha256: lock.content_sha256,
            actual_content_sha256: actualContentHash
        };
    }


    let manifest;
    try {
        manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    } catch {
        return { status: 'manifest_invalid', valid: false };
    }

    const manifestFields = [
        'schema_version',
        'suite_name',
        'suite_version',
        'target_path',
        'content_hash_algorithm',
        'content_sha256',
        'generated_by'
    ];
    const mismatchedManifestFields = manifestFields.filter((field) => manifest[field] !== lock[field]);
    if (mismatchedManifestFields.length > 0) {
        return {
            status: 'manifest_mismatch',
            valid: false,
            fields: mismatchedManifestFields
        };
    }

    const expectedInstalledFiles = collectHashableRelativeFiles(suiteRoot);
    if (
        !Array.isArray(manifest.installed_files) ||
        JSON.stringify(manifest.installed_files) !== JSON.stringify(expectedInstalledFiles)
    ) {
        return {
            status: 'manifest_file_list_mismatch',
            valid: false,
            expected_count: expectedInstalledFiles.length,
            actual_count: Array.isArray(manifest.installed_files) ? manifest.installed_files.length : null
        };
    }

    return {
        status: 'valid',
        valid: true,
        suite_name: metadata.name,
        suite_version: metadata.version,
        target_path: expectedTargetPath,
        content_sha256: actualContentHash,
        manifest_verified: true,
        installed_files: expectedInstalledFiles.length
    };
}

function formatTextReport(result) {
    if (result.valid) {
        return `Suite lock valid: ${result.suite_name}@${result.suite_version} (${result.content_sha256})`;
    }

    return `Suite lock invalid: ${result.status}`;
}

function main() {
    const options = parseArgs(process.argv);
    const result = verifySuiteLock(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
    } else {
        console.log(formatTextReport(result));
    }

    if (!result.valid) {
        process.exitCode = 1;
    }
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
    try {
        main();
    } catch (error) {
        console.error(error.message);
        process.exit(1);
    }
}

export { verifySuiteLock, formatTextReport };
