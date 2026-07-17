import fs from 'fs';
import path from 'path';

const DEFAULT_DEVLOG_DIR = 'logs';
const PROFILE_ENTRY_PATTERN = /^\s*-\s*(?:最近)?状态入口\s*[:：]\s*(.+?)\s*$/m;
const PLACEHOLDER_PATTERN = /待确认|待填写|未配置|暂无/;

function sanitizeConfiguredValue(value) {
    return String(value || '')
        .replace(/【[^】]+】/g, '')
        .replace(/[`"']/g, '')
        .trim();
}

function extractPathToken(value) {
    const sanitized = sanitizeConfiguredValue(value);
    if (!sanitized || PLACEHOLDER_PATTERN.test(sanitized)) {
        return '';
    }

    if (/^(?:[A-Za-z]:[\\/]|\/)/.test(sanitized)) {
        return sanitized.split(/\s+/)[0];
    }

    const match = sanitized.match(
        /([A-Za-z0-9._\-\u4e00-\u9fff]+(?:[\\/][A-Za-z0-9._\-\u4e00-\u9fff]+)*[\\/]?)/
    );
    return match?.[1] || '';
}

function configuredDevlogPathFromProfile(hostRoot) {
    const profilePath = path.join(hostRoot, 'project-profile.md');
    if (!fs.existsSync(profilePath) || !fs.statSync(profilePath).isFile()) {
        return '';
    }

    const content = fs.readFileSync(profilePath, 'utf8');
    const match = content.match(PROFILE_ENTRY_PATTERN);
    return extractPathToken(match?.[1]);
}

function normalizeRelativeDevlogDirectory(hostRoot, configuredPath) {
    let relativePath = String(configuredPath || DEFAULT_DEVLOG_DIR).trim().replace(/\\/g, '/');
    relativePath = relativePath.replace(/^\.\//, '').replace(/\/+$/, '');

    if (!relativePath || path.posix.isAbsolute(relativePath) || path.win32.isAbsolute(relativePath)) {
        throw new Error('Configured devlog directory must be a non-empty host-relative path.');
    }

    if (path.posix.extname(relativePath).toLowerCase() === '.md') {
        relativePath = path.posix.dirname(relativePath);
    }

    const normalized = path.posix.normalize(relativePath);
    if (normalized === '.' || normalized === '..' || normalized.startsWith('../')) {
        throw new Error('Configured devlog directory must stay inside the host project root.');
    }

    const absolutePath = path.resolve(hostRoot, ...normalized.split('/'));
    const relativeToHost = path.relative(hostRoot, absolutePath);
    if (relativeToHost === '..' || relativeToHost.startsWith(`..${path.sep}`) || path.isAbsolute(relativeToHost)) {
        throw new Error('Configured devlog directory must stay inside the host project root.');
    }

    return { absolutePath, relativePath: normalized };
}

function resolveDevlogDirectory({ hostRoot, explicitPath = '' }) {
    const profilePath = configuredDevlogPathFromProfile(hostRoot);
    const configuredPath = explicitPath || profilePath || DEFAULT_DEVLOG_DIR;
    const source = explicitPath ? 'cli' : profilePath ? 'project-profile' : 'default';

    return {
        ...normalizeRelativeDevlogDirectory(hostRoot, configuredPath),
        source
    };
}

export {
    DEFAULT_DEVLOG_DIR,
    configuredDevlogPathFromProfile,
    normalizeRelativeDevlogDirectory,
    resolveDevlogDirectory
};
