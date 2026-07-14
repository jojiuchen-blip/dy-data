#!/usr/bin/env node

import path from 'path';
import { fileURLToPath } from 'url';
import { buildClaudeHookPayload } from './index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const suiteRoot = path.resolve(__dirname, '..', '..');

const payload = buildClaudeHookPayload(suiteRoot);
console.log(JSON.stringify(payload, null, 2));
