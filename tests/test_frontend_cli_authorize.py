from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
HELPER_PATH = WEB_ROOT / "src" / "utils" / "cliAuthorization.ts"


def _read_user_codes(*searches: str) -> list[str]:
    assert HELPER_PATH.is_file(), "CLI authorization query helper is missing"
    source_path = json.dumps(str(HELPER_PATH))
    cases = json.dumps(searches)
    script = f"""
import {{ readFileSync }} from "node:fs";
import ts from "typescript";
const source = readFileSync({source_path}, "utf8");
const output = ts.transpileModule(source, {{ compilerOptions: {{
  module: ts.ModuleKind.ESNext,
  target: ts.ScriptTarget.ES2022,
}} }}).outputText;
const module = await import(`data:text/javascript,${{encodeURIComponent(output)}}`);
console.log(JSON.stringify({cases}.map(module.readCliAuthorizationCode)));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        cwd=WEB_ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _current_request_results() -> list[bool]:
    source_path = json.dumps(str(HELPER_PATH))
    script = f"""
import {{ readFileSync }} from "node:fs";
import ts from "typescript";
const source = readFileSync({source_path}, "utf8");
const output = ts.transpileModule(source, {{ compilerOptions: {{
  module: ts.ModuleKind.ESNext,
  target: ts.ScriptTarget.ES2022,
}} }}).outputText;
const module = await import(`data:text/javascript,${{encodeURIComponent(output)}}`);
const first = {{ userCode: "FIRST-CODE", generation: 4 }};
const second = {{ userCode: "SECOND-CODE", generation: 5 }};
console.log(JSON.stringify([
  module.isCurrentCliAuthorizationRequest(first, second, "FIRST-CODE"),
  module.isCurrentCliAuthorizationRequest(first, second),
  module.isCurrentCliAuthorizationRequest(second, second, "SECOND-CODE"),
  module.isCurrentCliAuthorizationRequest(second, second, "FIRST-CODE"),
]));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        cwd=WEB_ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _normalize_user_codes(*codes: str) -> list[str]:
    source_path = json.dumps(str(HELPER_PATH))
    cases = json.dumps(codes)
    script = f"""
import {{ readFileSync }} from "node:fs";
import ts from "typescript";
const source = readFileSync({source_path}, "utf8");
const output = ts.transpileModule(source, {{ compilerOptions: {{
  module: ts.ModuleKind.ESNext,
  target: ts.ScriptTarget.ES2022,
}} }}).outputText;
const module = await import(`data:text/javascript,${{encodeURIComponent(output)}}`);
console.log(JSON.stringify({cases}.map(module.normalizeCliAuthorizationCode)));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        cwd=WEB_ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_cli_authorization_code_is_derived_from_current_search() -> None:
    assert _read_user_codes(
        "?user_code=FIRST-CODE",
        "?user_code=SECOND-CODE",
        "?other=value",
        "?user_code=%20a%20b%09c%0A%20",
    ) == ["FIRST-CODE", "SECOND-CODE", "", "ABC"]


def test_cli_authorization_code_normalization_matches_backend() -> None:
    assert _normalize_user_codes(" a b\tc\n ", "second-code") == [
        "ABC",
        "SECOND-CODE",
    ]


def test_cli_authorization_request_guard_ignores_stale_results() -> None:
    assert _current_request_results() == [False, False, True, False]
