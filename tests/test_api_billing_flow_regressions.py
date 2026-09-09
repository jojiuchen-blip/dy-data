"""Exercise financial write locks through the established real API fixture."""
from sqlalchemy import event
from test_api_store_billing import client
import test_api_store_billing as flows


def test_invoice_registration_refreshes_and_orders_statement_locks(client, db_session, monkeypatch):
    locks = []
    def capture(state):
        query = state.statement
        if getattr(query, "_for_update_arg", None) is not None and "FROM settlement_statement \n" in str(query):
            # Registration locks a batch; confirmation locks one ID.
            if " IN (" in str(query):
                locks.append((state.execution_options.get("populate_existing"), str(query)))
    event.listen(db_session, "do_orm_execute", capture)
    try:
        flows.test_promotion_invoice_registers_multiple_complete_period_allocations(client, db_session, monkeypatch)
        assert locks and all(fresh and "ORDER BY" in sql for fresh, sql in locks)
    finally:
        event.remove(db_session, "do_orm_execute", capture)
