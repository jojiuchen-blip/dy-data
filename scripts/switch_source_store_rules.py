"""Versioned source-store rollout / restore. Dry-run unless --apply is explicit."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from apps.api.dy_api.db import make_engine, make_session_factory
from apps.api.dy_api.models import ClueAllocationRule, ClueAllocationRuleVersion
from apps.worker.clue_rule_versions import create_rule_version, publish_rule_version, rule_version_snapshot


def replacement_payload(snapshot, *, source_mode):
    payload = copy.deepcopy(snapshot)
    payload.pop("rule_version_id", None)
    payload.pop("version_no", None)
    if source_mode:
        for config in payload["strategy_configs"]:
            kind = config["strategy_type"]
            config["execution_order"] = {"sales_store_priority": 1, "nearby_city_optimization": 2, "city_fallback": 3}[kind]
            config["enabled"] = kind != "city_fallback"
            if kind == "nearby_city_optimization":
                config["params"]["selection_mode"] = "douyin_source_store"
    return payload


def save_exclusive(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())


def switch(session, *, restore=None):
    rules = session.scalars(select(ClueAllocationRule).order_by(ClueAllocationRule.rule_id).with_for_update()).all()
    versions = session.scalars(select(ClueAllocationRuleVersion).where(ClueAllocationRuleVersion.status == "published")).all()
    by_rule = {version.rule_id: version for version in versions}
    before = []
    for rule in rules:
        if rule.rule_id not in by_rule:
            continue
        version = by_rule[rule.rule_id]
        before.append({"rule_id": rule.rule_id, "scope_type": rule.scope_type,
                       "scope_key": rule.scope_key, "snapshot": rule_version_snapshot(session, version)})
    if not before or not any(row["scope_type"] == "global" for row in before):
        raise ValueError("no published global rule")
    if restore is not None and {row["rule_id"] for row in restore} != set(by_rule):
        raise ValueError("published rule scopes changed; review before restore")
    return before


def publish_replacements(session, source, *, source_mode):
    output = []
    for row in sorted(source, key=lambda row: (row["scope_type"] != "global", row["rule_id"])):
        version = create_rule_version(session, row["rule_id"], created_by="source-store-rule-maintenance",
                                      **replacement_payload(row["snapshot"], source_mode=source_mode))
        publish_rule_version(session, version.rule_version_id, published_by="source-store-rule-maintenance")
        output.append({"rule_id": row["rule_id"], "rule_version_id": version.rule_version_id,
                       "snapshot": rule_version_snapshot(session, version)})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True, help="New backup path; never overwrites an existing file")
    parser.add_argument("--restore", type=Path, help="Restore configuration from an earlier backup as new versions")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    restore = json.loads(args.restore.read_text(encoding="utf-8"))["rules"] if args.restore else None
    with make_session_factory(make_engine())() as session:
        before = switch(session, restore=restore)
        if args.apply:
            save_exclusive(args.backup, {"rules": before, "operation": "restore" if restore else "source_mode"})
        after = publish_replacements(session, restore if restore is not None else before, source_mode=restore is None)
        if args.apply:
            session.commit()
        else:
            session.rollback()
        print(json.dumps({"applied": args.apply, "rules": after}, ensure_ascii=False))


if __name__ == "__main__":
    main()
