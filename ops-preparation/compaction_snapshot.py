"""Read-only, aggregate-only financial guard for the authorized compaction."""
import hashlib
import json
from sqlalchemy import select, text
from apps.api.dy_api import models as M
from dy_api.pdca_readonly_access import _open_pdca_readonly_session


def snapshot():
    scope = _open_pdca_readonly_session()
    session = next(scope)
    try:
        assert session.scalar(text('SHOW transaction_read_only')) == 'on'
        models = (
            M.SettlementFeeResult, M.SettlementFeeResultCurrent,
            M.SettlementFeeAdjustment, M.SettlementStatement,
            M.SettlementStatementEntry, M.SettlementStatementConfirmation,
            M.InvoiceRecord, M.PromotionInvoice, M.PromotionInvoiceAllocation,
            M.SettlementScopeRule, M.SkuFeeRule,
        )
        facts = {}
        for model in models:
            rows = session.execute(select(*model.__table__.c)).mappings()
            values = sorted(json.dumps(dict(row), sort_keys=True, default=str,
                                       separators=(',', ':')) for row in rows)
            facts[model.__tablename__] = {
                'rows': len(values),
                'sha256': hashlib.sha256('\n'.join(values).encode()).hexdigest(),
            }
        active = session.get(M.SettlementProjectionActive, 'settlement')
        assert active is not None and active.generation_id
        head = session.get(M.SettlementProjectionGeneration, active.generation_id)
        assert head is not None and head.state == 'published'
        return {'financial_facts': facts, 'head': {
            'generation_id': head.generation_id, 'state': head.state,
            'kind': head.generation_kind, 'depth': head.lineage_depth,
        }}
    finally:
        scope.close()


if __name__ == '__main__':
    try:
        print(json.dumps(snapshot(), sort_keys=True), flush=True)
    except Exception as exc:
        print(json.dumps({'snapshot_error_type': type(exc).__name__}), flush=True)
        raise SystemExit(2)
