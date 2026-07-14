/**
 * Project Manager Suite plugin for OpenCode.ai
 *
 * Injects ai-project-manager bootstrap context via system prompt transform.
 * Skills are discovered via OpenCode's native skill tool from symlinked directory.
 */

import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import { buildOpenCodeBootstrap } from '../../lib/bootstrap/index.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Normalize a path: trim whitespace, expand ~, resolve to absolute
const normalizePath = (p, homeDir) => {
  if (!p || typeof p !== 'string') return null;
  let normalized = p.trim();
  if (!normalized) return null;
  if (normalized.startsWith('~/')) {
    normalized = path.join(homeDir, normalized.slice(2));
  } else if (normalized === '~') {
    normalized = homeDir;
  }
  return path.resolve(normalized);
};

export const ProjectManagerSuitePlugin = async ({ client, directory }) => {
  const homeDir = os.homedir();
  const skillsDir = path.resolve(__dirname, '../../skills');
  const envConfigDir = normalizePath(process.env.OPENCODE_CONFIG_DIR, homeDir);
  const configDir = envConfigDir || path.join(homeDir, '.config/opencode');

  return {
    'experimental.chat.system.transform': async (_input, output) => {
      const bootstrap = buildOpenCodeBootstrap({
        suiteRoot: path.resolve(__dirname, '..', '..'),
        configDir
      });
      if (bootstrap) {
        (output.system ||= []).push(bootstrap);
      }
    }
  };
};
