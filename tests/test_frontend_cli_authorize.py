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


def test_cli_authorization_code_is_derived_from_current_search() -> None:
    assert _read_user_codes(
        "?user_code=FIRST-CODE",
        "?user_code=SECOND-CODE",
        "?other=value",
    ) == ["FIRST-CODE", "SECOND-CODE", ""]
