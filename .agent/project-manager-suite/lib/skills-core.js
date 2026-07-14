import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';

/**
 * Extract YAML frontmatter from a skill file.
 *
 * @param {string} filePath - Path to SKILL.md file
 * @returns {{name: string, description: string}}
 */
function extractFrontmatter(filePath) {
    try {
        const content = fs.readFileSync(filePath, 'utf8');
        const lines = content.split('\n');

        let inFrontmatter = false;
        let name = '';
        let description = '';

        for (const line of lines) {
            if (line.trim() === '---') {
                if (inFrontmatter) break;
                inFrontmatter = true;
                continue;
            }

            if (inFrontmatter) {
                const match = line.match(/^(\w+):\s*(.*)$/);
                if (match) {
                    const [, key, value] = match;
                    switch (key) {
                        case 'name':
                            name = value.trim();
                            break;
                        case 'description':
                            description = value.trim();
                            break;
                    }
                }
            }
        }

        return { name, description };
    } catch (error) {
        return { name: '', description: '' };
    }
}

/**
 * Find all SKILL.md files in a directory recursively.
 *
 * @param {string} dir - Directory to search
 * @param {string} sourceType - Source identifier for namespacing
 * @param {number} maxDepth - Maximum recursion depth (default: 3)
 * @returns {Array<{path: string, skillFile: string, name: string, description: string, sourceType: string}>}
 */
function findSkillsInDir(dir, sourceType, maxDepth = 3) {
    const skills = [];

    if (!fs.existsSync(dir)) return skills;

    function recurse(currentDir, depth) {
        if (depth > maxDepth) return;

        const entries = fs.readdirSync(currentDir, { withFileTypes: true });

        for (const entry of entries) {
            const fullPath = path.join(currentDir, entry.name);

            if (entry.isDirectory()) {
                const skillFile = path.join(fullPath, 'SKILL.md');
                if (fs.existsSync(skillFile)) {
                    const { name, description } = extractFrontmatter(skillFile);
                    skills.push({
                        path: fullPath,
                        skillFile: skillFile,
                        name: name || entry.name,
                        description: description || '',
                        sourceType: sourceType
                    });
                }

                recurse(fullPath, depth + 1);
            }
        }
    }

    recurse(dir, 0);
    return skills;
}

/**
 * Resolve a skill name to its file path.
 * Project skills override suite default skills.
 *
 * @param {string} skillName - Skill name
 * @param {string} suiteSkillsDir - Path to project-manager-suite skills directory
 * @param {string} projectSkillsDir - Path to project-level skills directory (optional)
 * @returns {{skillFile: string, sourceType: string, skillPath: string} | null}
 */
/**
 * Locate a skill directory inside `dir` by name.
 * Suite skill directories carry a `NN-NN-` reading-order prefix (e.g.
 * `04-03-prd-writer`), while callers keep using the bare skill name
 * (`prd-writer`), so an exact match is tried first and the prefixed
 * form second.
 *
 * @param {string} dir - Directory containing skill folders
 * @param {string} skillName - Bare skill name without number prefix
 * @returns {string | null} Matching folder name, or null
 */
function findSkillDirName(dir, skillName) {
    if (fs.existsSync(path.join(dir, skillName, 'SKILL.md'))) {
        return skillName;
    }
    try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
            if (!entry.isDirectory()) continue;
            if (entry.name.replace(/^\d{2}-\d{2}-/, '') !== skillName) continue;
            if (fs.existsSync(path.join(dir, entry.name, 'SKILL.md'))) {
                return entry.name;
            }
        }
    } catch (error) {
        return null;
    }
    return null;
}

function resolveSkillPath(skillName, suiteSkillsDir, projectSkillsDir) {
    const forceSuite = skillName.startsWith('project-manager-suite:');
    const actualSkillName = forceSuite ? skillName.replace(/^project-manager-suite:/, '') : skillName;

    // Try project-level skills first (unless explicitly prefixed)
    if (!forceSuite && projectSkillsDir) {
        const projectDirName = findSkillDirName(projectSkillsDir, actualSkillName);
        if (projectDirName) {
            return {
                skillFile: path.join(projectSkillsDir, projectDirName, 'SKILL.md'),
                sourceType: 'project',
                skillPath: projectDirName
            };
        }
    }

    // Try suite skills
    if (suiteSkillsDir) {
        const suiteDirName = findSkillDirName(suiteSkillsDir, actualSkillName);
        if (suiteDirName) {
            return {
                skillFile: path.join(suiteSkillsDir, suiteDirName, 'SKILL.md'),
                sourceType: 'project-manager-suite',
                skillPath: suiteDirName
            };
        }
    }

    return null;
}

/**
 * Check if a git repository has updates available.
 *
 * @param {string} repoDir - Path to git repository
 * @returns {boolean}
 */
function checkForUpdates(repoDir) {
    try {
        const output = execSync('git fetch origin && git status --porcelain=v1 --branch', {
            cwd: repoDir,
            timeout: 3000,
            encoding: 'utf8',
            stdio: 'pipe'
        });

        const statusLines = output.split('\n');
        for (const line of statusLines) {
            if (line.startsWith('## ') && line.includes('[behind ')) {
                return true;
            }
        }
        return false;
    } catch (error) {
        return false;
    }
}

/**
 * Strip YAML frontmatter from skill content, returning just the body.
 *
 * @param {string} content - Full content including frontmatter
 * @returns {string}
 */
function stripFrontmatter(content) {
    const lines = content.split('\n');
    let inFrontmatter = false;
    let frontmatterEnded = false;
    const contentLines = [];

    for (const line of lines) {
        if (line.trim() === '---') {
            if (inFrontmatter) {
                frontmatterEnded = true;
                continue;
            }
            inFrontmatter = true;
            continue;
        }

        if (frontmatterEnded || !inFrontmatter) {
            contentLines.push(line);
        }
    }

    return contentLines.join('\n').trim();
}

/**
 * Extract frontmatter and return both metadata and stripped content.
 *
 * @param {string} content - Full file content
 * @returns {{frontmatter: Object, content: string}}
 */
function extractAndStripFrontmatter(content) {
    const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
    if (!match) return { frontmatter: {}, content };

    const frontmatterStr = match[1];
    const body = match[2];
    const frontmatter = {};

    for (const line of frontmatterStr.split('\n')) {
        const colonIdx = line.indexOf(':');
        if (colonIdx > 0) {
            const key = line.slice(0, colonIdx).trim();
            const value = line.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, '');
            frontmatter[key] = value;
        }
    }

    return { frontmatter, content: body };
}

export {
    extractFrontmatter,
    findSkillsInDir,
    resolveSkillPath,
    checkForUpdates,
    stripFrontmatter,
    extractAndStripFrontmatter
};
