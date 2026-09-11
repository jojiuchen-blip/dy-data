import shutil
import subprocess
from pathlib import Path

import pytest


def test_login_error_presenter_executes_chinese_recovery_mapping():
    root = Path(__file__).resolve().parents[1]
    if not shutil.which("node") or not (root / "apps/web/node_modules/typescript").exists():
        pytest.skip("Web TypeScript runtime is not installed")
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('./apps/web/node_modules/typescript');
const source = fs.readFileSync('apps/web/src/utils/userFacingLabels.ts', 'utf8')
  .replaceAll('import.meta.env.DEV', 'false');
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
const sandbox = {exports: {}};
vm.runInNewContext(code, sandbox);
const display = sandbox.exports.displaySyncFailureReason;
const expected = '抖音后台登录已失效，请在受保护的浏览器中重新登录后重试';
assert.equal(display('douyin_backend_login_required'), expected);
assert.equal(display('Douyin backend login required. Log in through the protected noVNC browser first.'), expected);
assert.equal(display('Backend aweme bind list API failed with HTTP 500.'), '任务执行失败，请查看服务日志');
assert.equal(display(null), '-');
"""
    subprocess.run(["node", "-e", script], cwd=root, check=True, capture_output=True, text=True)
