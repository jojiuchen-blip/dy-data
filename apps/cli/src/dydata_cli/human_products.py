"""Human-only product management: fresh login, item preview, explicit publication."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import warnings
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from .client import CliError
from .constants import ERROR_EXIT_CODES
from .environments import EnvironmentConfigError, resolve_environment
from .human_client import HumanProductSession
from .human_contracts import ACTION_FIELDS, HOUR_FIELDS, require_ids, validate_rule_patch
from .parser import CliArgumentError, CliArgumentParser


_ACTION_LABELS = {
    "publish_list": "发布适用门店名单", "publish_rule": "按字段发布独立规则",
    "enable": "正式开启商品流转", "disable": "关闭商品新入库流转", "grants": "替换商品管理授权",
}
_ERROR_MESSAGES = {
    "INVALID_ARGUMENT": "输入或文件格式无效。请检查命令帮助及输入文件。",
    "INTERACTIVE_REQUIRED": "请在安全的交互终端中由本人输入并确认。",
    "AUTH_FAILED": "登录失败，请核对本人账号及密码。",
    "AUTH_EXPIRED": "当前会话失效，请重新运行命令并登录。",
    "SCOPE_DENIED": "当前账号没有该操作权限。",
    "API_UNAVAILABLE": "服务连接失败；写请求没有自动重试，请先核对服务器实际结果。",
    "RATE_LIMITED": "请求频率受限，请稍后重新预览。",
    "SCHEMA_MISMATCH": "服务返回格式不兼容，请检查客户端与服务版本。",
    "INTERNAL_ERROR": "操作未能完成，请保留审计回执后核对实际状态。",
}


def _terminal_is_interactive() -> bool:
    try:
        return all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
    except (AttributeError, OSError):
        return False


def _parser() -> argparse.ArgumentParser:
    parser = CliArgumentParser(prog="dydata-products", allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("manage", "shared-rule", "shared-rule-grants"):
        command = subparsers.add_parser(name, allow_abbrev=False)
        command.add_argument("--input", type=Path, help="UTF-8 JSON change file; never credentials")
        command.add_argument("--audit", type=Path, help="create a new credential-free JSON audit file")
        if name == "manage":
            command.add_argument("--q", default="", help="product ID or name search")
            command.add_argument("--product-scope", choices=("all", "jingcheng", "byd"), default="all")
            command.add_argument("--page-size", type=int, default=50)
    return parser


def _load_input(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise CliError("INVALID_ARGUMENT")
        with path.open("r", encoding="utf-8-sig") as source:
            result = json.load(source)
    except (OSError, ValueError):
        raise CliError("INVALID_ARGUMENT") from None
    if not isinstance(result, dict):
        raise CliError("INVALID_ARGUMENT")
    return result


def _write_json(stream: TextIO, value: Any) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    stream.flush()


def _ids_from_prompt(value: str) -> list[str]:
    items = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    try:
        return require_ids(items, empty=False)
    except CliError:
        raise CliError("INVALID_ARGUMENT") from None


def _select_products(
    session: HumanProductSession, parsed: argparse.Namespace,
    ask: Callable[[str], str], stream: TextIO,
) -> tuple[dict[str, Any], bool]:
    page = 1
    selected: dict[str, None] = {}
    seen: set[str] = set()
    filters = {"q": parsed.q.strip(), "product_scope": parsed.product_scope}
    while True:
        data = session.list_products(**filters, page=page, page_size=parsed.page_size)
        stream.write(f"第 {page} 页；筛选命中 {data['total']}；已选 {len(selected)}\n")
        if data["can_manage_shared_rule"]:
            stream.write("已获精诚养车共享基座维护权：运行 dydata-products shared-rule。\n")
        if data["can_manage_grants"]:
            stream.write("维护精诚养车项目组授权：运行 dydata-products shared-rule-grants。\n")
        for row in data["rows"]:
            if row["can_manage"]:
                seen.add(row["product_id"])
            _write_json(stream, {key: row[key] for key in (
                "product_id", "product_name", "product_scope", "routing_enabled", "can_manage",
            )})
        if not data["total"]:
            return {"product_ids": [], "all_matching": False, "filters": filters}, data["can_manage_grants"]
        answer = ask("商品ID逗号分隔可跨页累计；n/p翻页；all选全部筛选；done确认；q退出: ").strip()
        if answer == "q":
            return {"product_ids": [], "all_matching": False, "filters": filters}, data["can_manage_grants"]
        if answer == "all":
            return {"product_ids": [], "all_matching": True, "filters": filters}, data["can_manage_grants"]
        if answer == "done" and selected:
            return {"product_ids": list(selected), "all_matching": False, "filters": filters}, data["can_manage_grants"]
        if answer in {"n", "p"}:
            if answer == "n" and page * parsed.page_size < data["total"]:
                page += 1
            elif answer == "p" and page > 1:
                page -= 1
            continue
        try:
            product_ids = _ids_from_prompt(answer)
        except CliError:
            stream.write("请输入已展示的可管理商品ID，或翻页/全选命令。\n")
            continue
        if not set(product_ids) <= seen:
            stream.write("选择包含未展示或不可管理商品，未增加选择。\n")
            continue
        selected.update(dict.fromkeys(product_ids))


def _rule_input(payload: dict[str, Any] | None, ask: Callable[[str], str]) -> dict[str, Any]:
    if payload is not None:
        if set(payload) != {"rules"}:
            raise CliError("INVALID_ARGUMENT")
        return validate_rule_patch(payload["rules"])
    patch: dict[str, Any] = {}
    for key, maximum in HOUR_FIELDS.items():
        value = ask(f"{key} (1..{maximum}小时；回车保留): ").strip()
        if value:
            try:
                patch[key] = int(value)
            except ValueError:
                raise CliError("INVALID_ARGUMENT") from None
    for key in sorted(ACTION_FIELDS):
        value = ask(f"{key} (next/close；回车保留): ").strip()
        if value:
            patch[key] = value
    return validate_rule_patch(patch)


def _change_input(
    action: str, payload: dict[str, Any] | None, ask: Callable[[str], str],
) -> dict[str, Any]:
    if action == "publish_rule":
        return {"rules": _rule_input(payload, ask)}
    if action == "publish_list":
        if payload is None:
            return {"store_ids": _ids_from_prompt(ask("共享门店编码（逗号分隔）: "))}
        try:
            if set(payload) == {"store_ids"}:
                return {"store_ids": require_ids(payload["store_ids"], empty=False)}
            if set(payload) != {"lists"} or not isinstance(payload["lists"], list) or not payload["lists"]:
                raise CliError("INVALID_ARGUMENT")
            lists = []
            for row in payload["lists"]:
                if not isinstance(row, dict) or set(row) != {"product_id", "store_ids"}:
                    raise CliError("INVALID_ARGUMENT")
                product_id = require_ids([row["product_id"]], empty=False)[0]
                lists.append({"product_id": product_id, "store_ids": require_ids(row["store_ids"], empty=False)})
            require_ids([row["product_id"] for row in lists])
            return {"lists": lists}
        except CliError:
            raise CliError("INVALID_ARGUMENT") from None
    if payload is not None:
        raise CliError("INVALID_ARGUMENT")
    return {}


def _narrow_body(body: dict[str, Any], product_ids: list[str]) -> dict[str, Any]:
    narrowed = {**body, "product_ids": product_ids, "all_matching": False}
    if "lists" in narrowed:
        narrowed["lists"] = [row for row in narrowed["lists"] if row["product_id"] in product_ids]
    return narrowed


def _cancel_pending(audit: dict[str, Any], pending: list[str]) -> int:
    if audit["attempts"]:
        audit["status"] = "partial"
        audit["failed_product_ids"] = pending
        return 1
    audit["status"] = "cancelled"
    return 0


def _publish_batches(
    session: HumanProductSession, body: dict[str, Any], ask: Callable[[str], str],
    stream: TextIO, audit: dict[str, Any],
) -> int:
    while True:
        preview = session.batch({**body, "preview": True}, idempotency_key=f"human_preview_{uuid4().hex}")
        stream.write("逐商品预览（尚未发布）：\n")
        for row in preview["results"]:
            _write_json(stream, row)
        ready = [row["product_id"] for row in preview["results"] if row["status"] == "preview"]
        failed = [row["product_id"] for row in preview["results"] if row["status"] == "failed"]
        audit["previews"].append({"action": body["action"], **preview})
        if not ready:
            audit["failed_product_ids"] = failed
            audit["status"] = "partial" if failed else "cancelled"
            if failed and ask("仅重新预览失败商品？[y/N]: ").strip().lower() == "y":
                body = _narrow_body(body, failed)
                continue
            return 1 if failed else 0
        confirmation = f"PUBLISH {len(ready)}"
        stream.write(f"操作：{_ACTION_LABELS[body['action']]}；仅提交上列 {len(ready)} 个预览成功商品。\n")
        if body["action"] == "enable":
            stream.write(f"业务授权说明：{body['authorization_note']}\n")
        if ask(f"本人确认执行请输入 {confirmation}，其他输入取消: ").strip() != confirmation:
            return _cancel_pending(audit, ready + failed)
        # Freeze all-matching into the exact previewed IDs before the mutation.
        committed = {**_narrow_body(body, ready), "preview": False}
        if body["action"] == "enable":
            committed["expected_list_versions"] = {
                row["product_id"]: row["before"]["list_version"]
                for row in preview["results"] if row["status"] == "preview"
            }
        key = f"human_publish_{uuid4().hex}"
        attempt = {"action": body["action"], "product_ids": ready, "idempotency_key": key, "status": "unknown"}
        if "expected_list_versions" in committed:
            attempt["expected_list_versions"] = committed["expected_list_versions"]
        audit["attempts"].append(attempt)
        audit["status"] = "unknown"
        try:
            result = session.batch(committed, idempotency_key=key)
        except CliError as exc:
            attempt.update({"request_id": exc.request_id, "error_code": exc.code})
            raise
        attempt.update({**result, "status": "returned"})
        stream.write("逐商品发布结果：\n")
        for row in result["results"]:
            _write_json(stream, row)
        failed.extend(row["product_id"] for row in result["results"] if row["status"] == "failed")
        audit["failed_product_ids"] = failed
        audit["status"] = "partial" if failed else "complete"
        if not failed:
            return 0
        if ask("仅重试失败商品（重新预览并确认）？[y/N]: ").strip().lower() != "y":
            return 1
        body = _narrow_body(body, failed)


def _all_product_ids(session: HumanProductSession, selection: dict[str, Any], page_size: int) -> list[str]:
    if not selection["all_matching"]:
        return selection["product_ids"]
    result: dict[str, None] = {}
    page = 1
    while True:
        data = session.list_products(**selection["filters"], page=page, page_size=page_size)
        result.update({row["product_id"]: None for row in data["rows"] if row["can_manage"]})
        if page * page_size >= data["total"]:
            return list(result)
        page += 1


def _manage_grants(
    session: HumanProductSession, selection: dict[str, Any], parsed: argparse.Namespace,
    payload: dict[str, Any] | None, ask: Callable[[str], str], stream: TextIO, audit: dict[str, Any],
) -> int:
    pending = _all_product_ids(session, selection, parsed.page_size)
    desired: list[str] | None = None
    if payload is not None:
        if set(payload) != {"user_ids"}:
            raise CliError("INVALID_ARGUMENT")
        try:
            desired = require_ids(payload["user_ids"])
        except CliError:
            raise CliError("INVALID_ARGUMENT") from None
    while pending:
        previews, failed = [], []
        for product_id in pending:
            try:
                current = session.get_grants(product_id)
                if desired is None:
                    stream.write("可授权用户：\n")
                    for user in current["users"]:
                        _write_json(stream, user)
                    answer = ask("替换为哪些user_id（逗号分隔；输入none清空）: ").strip()
                    desired = [] if answer == "none" else _ids_from_prompt(answer)
                if not set(desired) <= {user["user_id"] for user in current["users"]}:
                    raise CliError("INVALID_ARGUMENT")
                preview = {"product_id": product_id, "before": current["user_ids"], "after": desired}
                previews.append(preview)
                _write_json(stream, preview)
            except CliError as exc:
                failed.append(product_id)
                _write_json(stream, {"product_id": product_id, "status": "failed", "error_code": exc.code})
        audit["previews"].append({"action": "grants", "results": previews})
        audit["failed_product_ids"] = failed
        if previews:
            confirmation = f"AUTHORIZE {len(previews)}"
            if ask(f"替换以上授权请输入 {confirmation}，其他输入取消: ").strip() != confirmation:
                return _cancel_pending(audit, pending)
            for preview in previews:
                attempt = {**preview, "action": "grants", "status": "unknown"}
                audit["attempts"].append(attempt)
                audit["status"] = "unknown"
                try:
                    result = session.set_grants(preview["product_id"], desired or [])
                except CliError as exc:
                    attempt.update({"error_code": exc.code, "request_id": exc.request_id})
                    # Connection loss can mean the PUT committed: never retry it blindly.
                    if exc.code in {"API_UNAVAILABLE", "SCHEMA_MISMATCH", "INTERNAL_ERROR"}:
                        raise
                    failed.append(preview["product_id"])
                    attempt["status"] = "failed"
                else:
                    attempt.update({"status": "success", "after": result["user_ids"],
                                    "request_id": session.request_id, "server_request_id": session.server_request_id})
                _write_json(stream, attempt)
        audit["failed_product_ids"] = failed
        audit["status"] = "partial" if failed else "complete"
        if not failed:
            return 0
        if ask("仅重试失败商品授权（重新读取并确认）？[y/N]: ").strip().lower() != "y":
            return 1
        pending = failed
    audit["status"] = "cancelled"
    return 0


def _manage_shared_rule_grants(
    session: HumanProductSession, payload: dict[str, Any] | None,
    ask: Callable[[str], str], stream: TextIO, audit: dict[str, Any],
) -> int:
    stream.write("精诚养车项目组共享基座维护人授权（须全范围管理员权限）。\n")
    current = session.get_shared_rule_grants()
    stream.write("可授权用户：\n")
    for user in current["users"]:
        _write_json(stream, user)
    if payload is None:
        answer = ask("共享基座维护人user_id（逗号分隔；输入none清空）: ").strip()
        desired = [] if answer == "none" else _ids_from_prompt(answer)
    else:
        if set(payload) != {"user_ids"}:
            raise CliError("INVALID_ARGUMENT")
        try:
            desired = require_ids(payload["user_ids"])
        except CliError:
            raise CliError("INVALID_ARGUMENT") from None
    if not set(desired) <= {user["user_id"] for user in current["users"]}:
        raise CliError("INVALID_ARGUMENT")
    preview = {"action": "shared_rule_grants", "before": current["user_ids"], "after": desired}
    audit["previews"].append(preview)
    _write_json(stream, preview)
    if ask("替换精诚共享基座维护人请输入 AUTHORIZE SHARED，其他输入取消: ").strip() != "AUTHORIZE SHARED":
        audit["status"] = "cancelled"
        return 0
    attempt = {**preview, "status": "unknown"}
    audit["attempts"].append(attempt)
    audit["status"] = "unknown"
    result = session.set_shared_rule_grants(desired)
    attempt.update({"status": "success", "after": result["user_ids"],
                    "request_id": session.request_id, "server_request_id": session.server_request_id})
    audit["status"] = "complete"
    _write_json(stream, attempt)
    return 0


def _run(
    session: HumanProductSession, parsed: argparse.Namespace, payload: dict[str, Any] | None,
    ask: Callable[[str], str], password_input: Callable[[str], str], stream: TextIO,
    audit: dict[str, Any],
) -> int:
    stream.write(f"本人交互管理；环境 {session.environment.name}；服务 {session.environment.web_url}\n")
    username = ask("Username: ").strip()
    if not username or not username.isprintable():
        raise CliError("INVALID_ARGUMENT")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            password = password_input("Password: ")
        except getpass.GetPassWarning:
            raise CliError("INTERACTIVE_REQUIRED") from None
    if not isinstance(password, str) or not password:
        raise CliError("INVALID_ARGUMENT")
    try:
        identity = session.login(username, password)
    finally:
        password = ""
    audit["actor"] = identity
    stream.write(f"已登录：{identity['username']}；角色 {identity['role']}。关闭会话即清除临时Cookie。\n")
    if parsed.command == "shared-rule-grants":
        return _manage_shared_rule_grants(session, payload, ask, stream, audit)
    if parsed.command == "shared-rule":
        stream.write("精诚养车共享基座由获授权的项目组维护；维护权不授予其他商品或授权分发权限。\n")
        rules = _rule_input(payload, ask)
        preview = session.shared_rule(rules=rules, preview=True)
        _write_json(stream, preview)
        audit["previews"].append({"action": "shared_rule", **preview})
        if ask("发布精诚养车共享基座请输入 PUBLISH SHARED，其他输入取消: ").strip() != "PUBLISH SHARED":
            audit["status"] = "cancelled"
            return 0
        audit["status"] = "unknown"
        attempt = {"action": "shared_rule", "status": "unknown", "rules": rules}
        audit["attempts"].append(attempt)
        result = session.shared_rule(rules=rules, preview=False)
        attempt.update(result)
        audit["status"] = "complete"
        _write_json(stream, result)
        return 0
    selection, can_manage_grants = _select_products(session, parsed, ask, stream)
    if not selection["product_ids"] and not selection["all_matching"]:
        audit["status"] = "cancelled"
        return 0
    actions = ["publish_list", "publish_rule", "enable", "disable"]
    if can_manage_grants:
        actions.append("grants")
    stream.write("；".join(f"{index + 1} {_ACTION_LABELS[action]}" for index, action in enumerate(actions)) + "\n")
    answer = ask("操作编号（其他输入取消）: ").strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(actions):
        audit["status"] = "cancelled"
        return 0
    action = actions[int(answer) - 1]
    if action == "grants":
        return _manage_grants(session, selection, parsed, payload, ask, stream, audit)
    change = _change_input(action, payload, ask)
    authorization_note = ""
    if action == "enable":
        authorization_note = ask("业务负责人已确认有效名单并明确授权开启；请填写授权人/依据: ").strip()
        if not authorization_note or not authorization_note.isprintable() or len(authorization_note) > 2000:
            raise CliError("INVALID_ARGUMENT")
    if "lists" in change and not selection["all_matching"]:
        if set(row["product_id"] for row in change["lists"]) != set(selection["product_ids"]):
            raise CliError("INVALID_ARGUMENT")
    body = {**selection, **change, "action": action, "authorization_note": authorization_note}
    return _publish_batches(session, body, ask, stream, audit)


def main(
    argv: Sequence[str] | None = None, *,
    session_factory: Callable[[], HumanProductSession] | None = None,
    text_input: Callable[[str], str] | None = None,
    password_input: Callable[[str], str] | None = None,
    is_interactive_terminal: Callable[[], bool] | None = None,
    stream: TextIO | None = None,
) -> int:
    """Run the human console; no headless, token, password or URL arguments exist."""
    target = stream or sys.stdout
    audit: dict[str, Any] = {
        "channel": "human_cli", "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "cancelled", "previews": [], "attempts": [], "failed_product_ids": [],
    }
    audit_stream = None
    with ExitStack() as stack:
        try:
            parsed = _parser().parse_args(argv)
            if parsed.command == "manage" and (
                not 1 <= parsed.page_size <= 200 or len(parsed.q) > 200
                or (parsed.q.strip() and not parsed.q.strip().isprintable())
            ):
                raise CliError("INVALID_ARGUMENT")
            if not (is_interactive_terminal or _terminal_is_interactive)():
                raise CliError("INTERACTIVE_REQUIRED")
            payload = _load_input(parsed.input)
            if parsed.audit is not None:
                audit_stream = stack.enter_context(parsed.audit.open("x", encoding="utf-8"))
            environment = resolve_environment()
            audit["environment"] = environment.name
            with (session_factory() if session_factory else HumanProductSession(environment=environment)) as session:
                exit_code = _run(
                    session, parsed, payload, text_input or input, password_input or getpass.getpass, target, audit,
                )
        except (CliArgumentError, EnvironmentConfigError, OSError, UnicodeError):
            target.write(_ERROR_MESSAGES["INVALID_ARGUMENT"] + "\n")
            audit["error_code"] = "INVALID_ARGUMENT"
            exit_code = 2
        except CliError as exc:
            target.write(f"{_ERROR_MESSAGES.get(exc.code, _ERROR_MESSAGES['INTERNAL_ERROR'])} 请求编号：{exc.request_id}\n")
            audit["error_code"] = exc.code
            audit["request_id"] = exc.request_id
            exit_code = ERROR_EXIT_CODES[exc.code]
        except (EOFError, KeyboardInterrupt):
            target.write("交互已中止。\n")
            exit_code = 130
        except Exception:
            target.write(_ERROR_MESSAGES["INTERNAL_ERROR"] + "\n")
            audit["error_code"] = "INTERNAL_ERROR"
            exit_code = 6
        audit["finished_at"] = datetime.now(timezone.utc).isoformat()
        audit["exit_code"] = exit_code
        _write_json(target, {"audit": audit})
        if audit_stream is not None:
            try:
                _write_json(audit_stream, audit)
            except OSError:
                target.write("本地审计文件写入失败，请保存以上终端回执。\n")
                return exit_code or 5
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
