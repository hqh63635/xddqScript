#!/usr/bin/env node

import fs from 'fs/promises';
import os from 'os';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, '..');
const configRoot = path.join(projectRoot, 'src', 'game', 'config');
const backupRoot = path.join(projectRoot, '.game-config-backups');

const DB_FILES = [
    'AttributeDB.json',
    'EquipmentDB.json',
    'EquipmentQualityDB.json',
    'GameSkillDB.json',
    'LanguageWordDB.json',
    'SpiritsDB.json',
];
const GRPC_JSON_FILES = ['CityMsgInfo', 'cmdList.json', 'resvCmdList.json'];

function usage(exitCode = 0) {
    console.log(`Usage:
  npm run update-game-config -- <exported-directory> [options]

Options:
  --scope <all|db|grpc>  Update scope (default: all)
  --dry-run              Locate and validate files without changing anything
  --help                 Show this help

The input must be an unpacked/exported Alipay mini-program resource directory,
or a directory containing the already extracted db and grpc dictionaries.`);
    process.exit(exitCode);
}

function parseArgs(argv) {
    let source;
    let scope = 'all';
    let dryRun = false;

    for (let index = 0; index < argv.length; index += 1) {
        const arg = argv[index];
        if (arg === '--help' || arg === '-h') usage();
        if (arg === '--dry-run') {
            dryRun = true;
        } else if (arg === '--scope') {
            scope = argv[++index];
            if (!scope) throw new Error('--scope requires a value');
        } else if (arg.startsWith('--scope=')) {
            scope = arg.slice('--scope='.length);
        } else if (arg.startsWith('-')) {
            throw new Error(`Unknown option: ${arg}`);
        } else if (!source) {
            source = arg;
        } else {
            throw new Error(`Unexpected argument: ${arg}`);
        }
    }

    if (!source) throw new Error('Missing exported-directory');
    if (!['all', 'db', 'grpc'].includes(scope)) {
        throw new Error(`Invalid scope: ${scope}`);
    }
    return { source: path.resolve(source), scope, dryRun };
}

async function isDirectory(value) {
    try {
        return (await fs.stat(value)).isDirectory();
    } catch {
        return false;
    }
}

async function isFile(value) {
    try {
        return (await fs.stat(value)).isFile();
    } catch {
        return false;
    }
}

function decodeCocosUuid(value) {
    if (value.length !== 22) return value;
    const keys = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    let hex = value.slice(0, 2);
    for (let index = 2; index < 22; index += 2) {
        const left = keys.indexOf(value[index]);
        const right = keys.indexOf(value[index + 1]);
        hex += (left >> 2).toString(16);
        hex += (((left & 3) << 2) | (right >> 4)).toString(16);
        hex += (right & 15).toString(16);
    }
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function decodeGameText(value) {
    const input = value.startsWith('12345') ? value.slice(5) : value;
    const bytes = Buffer.from(input, 'utf8');
    for (let index = 0; index < bytes.length; index += 1) bytes[index] ^= 1;
    return bytes.toString('utf8');
}

async function fetchText(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status} while downloading ${url}`);
    return response.text();
}

function cocosTextAsset(importJson, expectedName) {
    const visit = (value) => {
        if (!Array.isArray(value)) return null;
        if (value.length >= 3 && value[1] === expectedName && typeof value[2] === 'string') {
            return value[2];
        }
        for (const child of value) {
            const result = visit(child);
            if (result !== null) return result;
        }
        return null;
    };
    const result = visit(importJson);
    if (result === null) throw new Error(`TextAsset ${expectedName} was not found in Cocos import data`);
    return result;
}

function cocosImportUrl(server, config, resourcePath) {
    const pathEntry = Object.entries(config.paths).find(([, value]) => value[0] === resourcePath);
    if (!pathEntry) throw new Error(`Resource is missing from Cocos index: ${resourcePath}`);
    const assetIndex = Number(pathEntry[0]);
    const uuid = decodeCocosUuid(config.uuids[assetIndex]);
    let version;
    for (let index = 0; index < config.versions.import.length; index += 2) {
        if (Number(config.versions.import[index]) === assetIndex) {
            version = config.versions.import[index + 1];
            break;
        }
    }
    if (!version) throw new Error(`Import version is missing for: ${resourcePath}`);
    return `${server}/remote/resources/import/${uuid.slice(0, 2)}/${uuid}.${version}.json`;
}

function parseDbTable(table, name) {
    if (!Array.isArray(table) || table.length < 2 || !Array.isArray(table[0]) || !Array.isArray(table[1])) {
        throw new Error(`Unexpected table format: ${name}`);
    }
    const primaryKey = table[0][0];
    const columns = table[1];
    const primaryIndex = columns.indexOf(primaryKey);
    if (primaryIndex < 0) throw new Error(`Primary key is missing from table: ${name}`);
    const result = {};
    for (const row of table.slice(2)) {
        const record = {};
        for (let index = 0; index < columns.length; index += 1) record[columns[index]] = row[index];
        result[String(row[primaryIndex]).trim()] = record;
    }
    return result;
}

async function findWebGameJs(source) {
    const candidates = [path.join(source, 'game.js'), path.join(source, 'package', 'game.js')];
    for (const candidate of candidates) {
        if (await isFile(candidate)) return candidate;
    }
    return null;
}

async function extractWebDb(source) {
    const gameJs = await findWebGameJs(source);
    if (!gameJs) return null;
    const code = await fs.readFile(gameJs, 'utf8');
    const server = code.match(/server:"(https:\/\/[^" ]+)"/)?.[1];
    const resourcesVersion = code.match(/bundleVers:\{[^}]*resources:"([^"]+)"/)?.[1];
    if (!server || !resourcesVersion) {
        throw new Error(`Could not read Cocos server metadata from ${gameJs}`);
    }

    console.log(`Web game detected: ${gameJs}`);
    console.log(`Cocos server: ${server} (resources ${resourcesVersion})`);
    const configUrl = `${server}/remote/resources/config.${resourcesVersion}.json`;
    const config = JSON.parse(await fetchText(configUrl));
    const allJsonUrl = cocosImportUrl(server, config, 'cn/allJson/AllJson0');
    const languageUrl = cocosImportUrl(server, config, 'cn/zh_cn/json/LanguageWordDB');
    const [allJsonImport, languageImport] = await Promise.all([
        fetchText(allJsonUrl).then(JSON.parse),
        fetchText(languageUrl).then(JSON.parse),
    ]);

    const allJsonOuter = JSON.parse(cocosTextAsset(allJsonImport, 'AllJson0'));
    const tables = {};
    for (const encodedGroup of Object.values(allJsonOuter)) {
        const group = JSON.parse(decodeGameText(encodedGroup));
        Object.assign(tables, group);
    }
    const languageAsset = cocosTextAsset(languageImport, 'LanguageWordDB');
    const languageRaw = JSON.parse(decodeGameText(languageAsset));
    const languageTable = languageRaw.LanguageWordDB || languageRaw;

    const output = await fs.mkdtemp(path.join(os.tmpdir(), 'xddq-game-config-'));
    const dbOutput = path.join(output, 'db');
    await fs.mkdir(dbOutput, { recursive: true });
    const generated = {
        EquipmentDB: parseDbTable(tables.EquipmentDB, 'EquipmentDB'),
        GameSkillDB: parseDbTable(tables.GameSkillDB, 'GameSkillDB'),
        SpiritsDB: parseDbTable(tables.SpiritsDB, 'SpiritsDB'),
        LanguageWordDB: parseDbTable(languageTable, 'LanguageWordDB'),
    };
    for (const [name, value] of Object.entries(generated)) {
        await fs.writeFile(path.join(dbOutput, `${name}.json`), `${JSON.stringify(value, null, 2)}\n`);
        console.log(`Extracted ${name}: ${Object.keys(value).length} rows`);
    }
    for (const name of ['AttributeDB.json', 'EquipmentQualityDB.json']) {
        await fs.copyFile(path.join(configRoot, 'db', name), path.join(dbOutput, name));
    }
    return output;
}

async function findMatchingDirectory(root, requiredNames, preferredName) {
    const matches = [];
    const queue = [root];

    while (queue.length > 0) {
        const current = queue.shift();
        let entries;
        try {
            entries = await fs.readdir(current, { withFileTypes: true });
        } catch {
            continue;
        }

        const names = new Set(entries.filter((entry) => entry.isFile()).map((entry) => entry.name));
        if (requiredNames.every((name) => names.has(name))) matches.push(current);

        for (const entry of entries) {
            if (entry.isDirectory() && !['node_modules', '.git'].includes(entry.name)) {
                queue.push(path.join(current, entry.name));
            }
        }
    }

    if (matches.length === 0) return null;
    matches.sort((a, b) => {
        const aPreferred = path.basename(a).toLowerCase() === preferredName ? 1 : 0;
        const bPreferred = path.basename(b).toLowerCase() === preferredName ? 1 : 0;
        return bPreferred - aPreferred || a.length - b.length;
    });
    if (matches.length > 1 && matches[0].length === matches[1].length) {
        throw new Error(`Multiple possible ${preferredName} directories found:\n${matches.join('\n')}`);
    }
    return matches[0];
}

async function validateJsonFiles(directory, names) {
    for (const name of names) {
        const file = path.join(directory, name);
        const text = (await fs.readFile(file, 'utf8')).replace(/^\uFEFF/, '');
        try {
            JSON.parse(text);
        } catch (error) {
            throw new Error(`Invalid JSON ${file}: ${error.message}`);
        }
    }
}

async function validateProtobufDirectory(directory) {
    if (!(await isDirectory(directory))) {
        throw new Error(`Protobuf directory not found: ${directory}`);
    }
    const entries = (await fs.readdir(directory, { withFileTypes: true }))
        .filter((entry) => entry.isFile());
    if (entries.length === 0) throw new Error(`Protobuf directory is empty: ${directory}`);

    let definitions = 0;
    for (const entry of entries) {
        const text = await fs.readFile(path.join(directory, entry.name), 'utf8');
        if (/\b(?:message|enum)\s+[A-Za-z_]\w*/.test(text)) definitions += 1;
    }
    if (definitions === 0) {
        throw new Error(`No protobuf message definitions found in: ${directory}`);
    }
}

function timestamp() {
    return new Date().toISOString().replace(/[:.]/g, '-');
}

function pathsOverlap(first, second) {
    const relative = path.relative(path.resolve(first), path.resolve(second));
    return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

async function copySelectedFiles(source, target, names) {
    await fs.mkdir(target, { recursive: true });
    for (const name of names) {
        await fs.copyFile(path.join(source, name), path.join(target, name));
    }
}

async function main() {
    const options = parseArgs(process.argv.slice(2));
    if (!(await isDirectory(options.source))) {
        throw new Error(`Source directory does not exist: ${options.source}`);
    }

    const webGameJs = await findWebGameJs(options.source);
    if (webGameJs && options.scope !== 'db') {
        throw new Error('Web/Cocos packages currently support --scope db only');
    }
    const effectiveSource = webGameJs ? await extractWebDb(options.source) : options.source;
    const updateDb = options.scope === 'all' || options.scope === 'db';
    const updateGrpc = options.scope === 'all' || options.scope === 'grpc';
    const dbSource = updateDb
        ? await findMatchingDirectory(effectiveSource, DB_FILES, 'db')
        : null;
    const grpcJsonSource = updateGrpc
        ? await findMatchingDirectory(effectiveSource, GRPC_JSON_FILES, 'json')
        : null;

    if (updateDb && !dbSource) {
        throw new Error(`Could not find a directory containing all DB files: ${DB_FILES.join(', ')}`);
    }
    if (updateGrpc && !grpcJsonSource) {
        throw new Error(`Could not find a directory containing: ${GRPC_JSON_FILES.join(', ')}`);
    }

    let protobufSource = null;
    if (updateGrpc) {
        const candidates = [
            path.join(path.dirname(grpcJsonSource), 'protobuf'),
            path.join(effectiveSource, 'protobuf'),
        ];
        protobufSource = candidates.find((candidate) => path.resolve(candidate) !== path.resolve(grpcJsonSource)
            && candidate !== path.join(configRoot, 'grpc', 'protobuf'));
        if (!(await isDirectory(protobufSource))) {
            protobufSource = await findMatchingDirectory(effectiveSource, ['Common'], 'protobuf');
        }
    }

    if (updateDb) await validateJsonFiles(dbSource, DB_FILES);
    if (updateGrpc) {
        await validateJsonFiles(grpcJsonSource, GRPC_JSON_FILES);
        await validateProtobufDirectory(protobufSource);
    }

    console.log(`Source: ${options.source}`);
    if (dbSource) console.log(`DB: ${dbSource}`);
    if (grpcJsonSource) console.log(`gRPC JSON: ${grpcJsonSource}`);
    if (protobufSource) console.log(`Protobuf: ${protobufSource}`);
    console.log('Validation passed.');

    if (options.dryRun) {
        console.log('Dry run complete; no files changed.');
        if (webGameJs) await fs.rm(effectiveSource, { recursive: true, force: true });
        return;
    }

    if ((dbSource && pathsOverlap(configRoot, dbSource))
        || (grpcJsonSource && pathsOverlap(configRoot, grpcJsonSource))
        || (protobufSource && pathsOverlap(configRoot, protobufSource))) {
        throw new Error('The project config directory cannot be used as the update source');
    }

    const backup = path.join(backupRoot, timestamp());
    if (updateDb) {
        await copySelectedFiles(path.join(configRoot, 'db'), path.join(backup, 'db'), DB_FILES);
        await copySelectedFiles(dbSource, path.join(configRoot, 'db'), DB_FILES);
    }
    if (updateGrpc) {
        await copySelectedFiles(
            path.join(configRoot, 'grpc', 'json'),
            path.join(backup, 'grpc', 'json'),
            GRPC_JSON_FILES,
        );
        await fs.cp(path.join(configRoot, 'grpc', 'protobuf'), path.join(backup, 'grpc', 'protobuf'), {
            recursive: true,
        });
        await copySelectedFiles(grpcJsonSource, path.join(configRoot, 'grpc', 'json'), GRPC_JSON_FILES);
        await fs.rm(path.join(configRoot, 'grpc', 'protobuf'), { recursive: true, force: true });
        await fs.cp(protobufSource, path.join(configRoot, 'grpc', 'protobuf'), { recursive: true });
    }

    console.log(`Update complete. Backup: ${backup}`);
    if (webGameJs) await fs.rm(effectiveSource, { recursive: true, force: true });
}

main().catch((error) => {
    console.error(`Update failed: ${error.message}`);
    process.exitCode = 1;
});
