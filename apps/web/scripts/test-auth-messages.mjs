import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/pages/authMessages.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { activationFailureMessage, accountSubmitFailureMessage, isAccountAlreadyActivated } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
for (const state of ["审核失败", "审核中", "已解绑", "未知"]) {
  const message = activationFailureMessage({ reason_code: "certification_not_successful", certification_status: state });
  assert.equal(message, `当前子机构账号认证状态为“${state}”。认证状态刷新可能有延迟，若抖音来客显示“已激活”，请半个小时后再尝试激活。`);
  assert.equal(accountSubmitFailureMessage({ status: 401, message: "", code: "activation_verification_failed", reasonCode: "certification_not_successful", certificationStatus: state }), message);
}
assert.match(activationFailureMessage({ reason_code: "identity_not_matched" }), /同一条记录/);
assert.match(activationFailureMessage({ reason_code: "store_disabled" }), /门店.*停用/);
assert.match(activationFailureMessage({ reason_code: "account_disabled" }), /账户.*停用/);
assert.match(activationFailureMessage({ reason_code: "account_type_unsupported" }), /子机构区域号/);
assert.match(activationFailureMessage({ reason_code: "future_reason" }), /联系管理员/);
assert.match(activationFailureMessage({}), /联系管理员/);
assert.match(activationFailureMessage({ reason_code: "certification_not_successful" }), /“未知”/);
assert.match(accountSubmitFailureMessage({ status: 409, message: "Username already exists" }), /更换/);
assert.match(accountSubmitFailureMessage({ status: 409, message: "Account already initialized" }), /前往登录/);
assert.equal(accountSubmitFailureMessage({ status: 503, message: "sensitive server detail" }), undefined);
assert.equal(isAccountAlreadyActivated({ status: 409, message: "Account already initialized" }), true);
assert.equal(isAccountAlreadyActivated({ status: 409, message: "Username already exists" }), false);
assert.equal(isAccountAlreadyActivated({ status: 503, message: "Account already initialized" }), false);
console.log("Auth message behavior checks passed");
