"""Execute web utilities against their real TypeScript modules."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


WEB_DIR = Path(__file__).resolve().parents[1] / "apps" / "web"


def run_web_module(entry: str):
    node = shutil.which("node")
    if not node or not (WEB_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("Node.js and the installed web dependencies are required")
    harness = """
const esbuild = require('esbuild');
const entry = process.argv[1];
const result = esbuild.buildSync({
  stdin: {contents: entry, resolveDir: process.cwd(), sourcefile: 'web-contract.ts'},
  bundle: true, platform: 'node', format: 'cjs', write: false,
  loader: {'.csv': 'text'}, define: {'import.meta.env': '{}'}, logLevel: 'silent',
});
new Function('require', result.outputFiles[0].text)(require);
"""
    result = subprocess.run(
        [node, "-e", harness, entry], cwd=WEB_DIR, text=True,
        encoding="utf-8", capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_business_error_reason_is_preserved_without_page_specific_guidance() -> None:
    messages = run_web_module("""
import {apiErrorText} from './src/utils/apiErrors';
import {ApiRequestError} from './src/api/client';
const errors = [
  new ApiRequestError(403, '仅全国范围管理员可执行全局操作', {code: 'GLOBAL_WRITE_REQUIRED', requestId: 'scope-request'}),
  new ApiRequestError(409, '幂等键已被其他内容使用', {code: 'IDEMPOTENCY_KEY_REUSED', requestId: 'retry-request'}),
  new ApiRequestError(500, 'internal SQL credentials', {code: 'INTERNAL_ERROR', requestId: 'server-request'}),
];
console.log(JSON.stringify(errors.map(error => apiErrorText(error, '操作失败'))));
""")
    assert messages[0] == "仅全国范围管理员可执行全局操作 错误码：GLOBAL_WRITE_REQUIRED 请求编号：scope-request"
    assert messages[1] == "幂等键已被其他内容使用 错误码：IDEMPOTENCY_KEY_REUSED 请求编号：retry-request"
    assert messages[2] == "操作失败 错误码：INTERNAL_ERROR 请求编号：server-request"


def test_page_specific_guidance_keeps_error_code_and_request_id() -> None:
    messages = run_web_module("""
import {apiErrorText} from './src/utils/apiErrors';
import {ApiRequestError} from './src/api/client';
const errors = [
  new ApiRequestError(403, 'Forbidden', {code: 'GLOBAL_WRITE_REQUIRED', requestId: 'scope-request'}),
  new ApiRequestError(409, 'Conflict', {code: 'VERSION_CONFLICT', requestId: 'retry-request'}),
];
console.log(JSON.stringify(errors.map(error => apiErrorText(error, '操作失败', {
  403: '请使用全国范围管理员账号', 409: '请重新读取当前版本后提交',
}))));
""")
    assert messages == [
        "请使用全国范围管理员账号 错误码：GLOBAL_WRITE_REQUIRED 请求编号：scope-request",
        "请重新读取当前版本后提交 错误码：VERSION_CONFLICT 请求编号：retry-request",
    ]


def test_demo_selected_stores_and_export_keep_explicit_empty_filter() -> None:
    result = run_web_module("""
import {ClueDemoRepository} from './src/demo/clueDemoRepository';
const repository = new ClueDemoRepository();
const list = filters => repository.getAssignmentRounds({filters, page: 1, pageSize: 100}).data;
const all = list({});
const selected = [...new Set(all.rows.map(row => row.assigned_store_id).filter(Boolean))].slice(0, 2);
const expected = selected.reduce((count, id) => count + list({assigned_store_id: id}).pagination.total, 0);
const filtered = list({assigned_store_ids: selected});
const empty = list({assigned_store_ids: []});
const cleared = list({assigned_store_ids: null});
const emptyCsv = repository.exportAssignmentRounds({assigned_store_ids: []}).content;
console.log(JSON.stringify({expected, total: filtered.pagination.total,
  rowStores: filtered.rows.map(row => row.assigned_store_id), selected,
  emptyTotal: empty.pagination.total, clearedTotal: cleared.pagination.total,
  allTotal: all.pagination.total, emptyCsvLines: emptyCsv.split('\\r\\n').length}));
""")
    assert result["expected"] > 0
    assert result["total"] == result["expected"]
    assert set(result["rowStores"]) <= set(result["selected"])
    assert result["emptyTotal"] == 0
    assert result["clearedTotal"] == result["allTotal"]
    assert result["emptyCsvLines"] == 1
