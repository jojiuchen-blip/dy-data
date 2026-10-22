"""Bounded, read-only production verification; outputs aggregate counts only."""
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from dy_api.db import make_engine
from dy_api.routes._data import DashboardDataStore
from dy_api.schemas import ClueAssignmentRoundData

class VerificationDataStore(DashboardDataStore):
    def _clue_order_phones(self, order_ids):
        return {order_id: ('', '') for order_id in order_ids}


def verify():
    engine = make_engine()
    with Session(engine) as session:
        session.execute(text('SET TRANSACTION READ ONLY'))
        session.execute(text("SET LOCAL statement_timeout = '8s'"))
        session.execute(text("SET LOCAL lock_timeout = '1s'"))
        store_id = session.execute(text("""
            SELECT assigned_store_id FROM clue_assignment_rounds
            WHERE execution_mode = 'formal' AND assigned_at >= '2026-09-01'
              AND verified_at IS NOT NULL AND is_self_store_verified = true
              AND assigned_store_id IS NOT NULL
            ORDER BY assigned_at DESC LIMIT 1
        """)).scalar_one()
        data_store = VerificationDataStore(session)
        base = dict(scope_store_ids=(store_id,), assigned_store_id=store_id,
                    assigned_date_start='2026-09-01', product_type='all', page=1, page_size=5)
        actor = dict(role='store', store_ids=(store_id,), store_scope_mode='specified',
                     is_highest_admin=False, auth_type='user')
        own = data_store.clue_assignment_rounds(dict(base, verification_status='self_store_verified'), actor)
        other = data_store.clue_assignment_rounds(dict(base, verification_status='other_store_verified'), actor)
        hidden = data_store.clue_assignment_rounds(dict(base, scope_store_ids=()), actor)
        ClueAssignmentRoundData(**own)
        assert own['rows'] and own['pagination']['total'] > 0
        assert all(r['is_self_store_verified'] and r['verified_at'] for r in own['rows'])
        assert all(not r['is_self_store_verified'] and r['verified_at'] for r in other['rows'])
        assert hidden['rows'] == [] and hidden['pagination']['total'] == 0
        assert all('verified_store_name' in r and 'verified_store_id' in r for r in own['rows'])
        print('PRODUCTION_CLUE_READ_ONLY_OK', json.dumps(dict(
            self_verified_total=own['pagination']['total'],
            other_verified_total=other['pagination']['total'],
            sample_count=len(own['rows']),
            named_store_count=sum(bool(r['verified_store_name']) for r in own['rows']),
            empty_scope_total=hidden['pagination']['total'])))
        session.rollback()
    engine.dispose()

if __name__ == '__main__':
    try:
        verify()
    except Exception as exc:
        print('PRODUCTION_CLUE_READ_ONLY_FAILED', type(exc).__name__)
        raise SystemExit(1) from None
