"""Real PostgreSQL write-proof counterexamples; dedicated loopback schema only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.dy_api import models as m
from apps.api.dy_api.dashboard_publications.schema import metadata as publication_metadata
from apps.worker import missing_fee_repair as repair
from apps.worker import settlement as settlement
from test_missing_fee_repair import preview, setup_batch
from test_missing_fee_repair_postgres import _install_fixture_tracking, apply, counts


@pytest.fixture(scope="module")
def proof_engine():
    url = os.getenv("DYDATA_MISSING_FEE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit disposable loopback test database required")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    schema = "fee_proof_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=1000"})
    m.Base.metadata.create_all(engine)
    publication_metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture(autouse=True)
def reset_proof_schema(proof_engine):
    """Reset only this generated schema, avoiding repeated 150-table creation."""
    known = set(m.Base.metadata.tables) | set(publication_metadata.tables)
    with proof_engine.begin() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        triggers = connection.execute(text("SELECT c.relname,t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND NOT t.tgisinternal")).all()
        for table, trigger in triggers:
            connection.execute(text(f'DROP TRIGGER "{trigger}" ON {repair._quoted_relation(schema, table)}'))
        relations = connection.execute(text("SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND c.relkind IN ('r','p','v','m','f')")).all()
        for name, kind in relations:
            if name not in known:
                object_type = {"v": "VIEW", "m": "MATERIALIZED VIEW", "f": "FOREIGN TABLE"}.get(kind, "TABLE")
                connection.execute(text(f'DROP {object_type} IF EXISTS {repair._quoted_relation(schema, name)} CASCADE'))
        connection.execute(text("TRUNCATE " + ",".join(repair._quoted_relation(schema, name) for name in sorted(known)) + " RESTART IDENTITY CASCADE"))
    _install_fixture_tracking(proof_engine)


def seed(proof_engine, *, count=1, sidecar=True):
    with proof_engine.begin() as connection:
        if sidecar:
            connection.execute(text("CREATE TABLE dashboard_unknown_proof (id integer PRIMARY KEY,payload text)"))
            connection.execute(text("INSERT INTO dashboard_unknown_proof VALUES(1,'original')"))
    with Session(proof_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session, count=count)
        report = preview(session, manifest, exclusions)
    return manifest, exclusions, report


def assert_zero(proof_engine):
    with Session(proof_engine) as session:
        assert counts(session) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize("operation", [
    "INSERT INTO dashboard_unknown_proof VALUES(2,'unexpected')",
    "UPDATE dashboard_unknown_proof SET payload='unexpected'",
    "DELETE FROM dashboard_unknown_proof",
    "UPDATE dashboard_unknown_proof SET payload='unexpected';UPDATE dashboard_unknown_proof SET payload='original'",
    "INSERT INTO dashboard_unknown_proof VALUES(2,'temporary');DELETE FROM dashboard_unknown_proof WHERE id=2",
    "TRUNCATE dashboard_unknown_proof",
    "ALTER TABLE dashboard_unknown_proof ADD COLUMN unexpected integer",
    "DROP TABLE dashboard_unknown_proof;CREATE TABLE dashboard_unknown_proof(id integer PRIMARY KEY,payload text)",
])
def test_unknown_sidecar_direct_writes_or_ddl_rollback(proof_engine, monkeypatch, operation):
    manifest, exclusions, report = seed(proof_engine)
    real = settlement.rebuild_dual_fee_results
    def altered(session, **kwargs):
        result = real(session, **kwargs)
        for statement in operation.split(';'):
            session.execute(text(statement))
        return result
    monkeypatch.setattr(settlement, "rebuild_dual_fee_results", altered)
    with Session(proof_engine, autoflush=False) as session:
        with pytest.raises(repair.MissingFeeRepairError):
            apply(session, manifest, exclusions, report["preview_hash"])
        assert session.execute(text("SELECT * FROM dashboard_unknown_proof")).all() == [(1,"original")]
    assert_zero(proof_engine)


@pytest.mark.parametrize("effect", ["audit_fee", "audit_row", "audit_counter", "audit_sidecar",
                                   "deferred_fee", "deferred_sidecar", "nested_truncate", "nested_structure",
                                   "nested_index", "nested_trigger_function"])
def test_database_internal_and_final_deferred_effects_reject(proof_engine, effect):
    manifest, exclusions, report = seed(proof_engine)
    bodies = {
        "audit_fee": "UPDATE settlement_fee_result SET fee_amount_cent=fee_amount_cent+1;RETURN NEW;",
        "audit_row": "NEW.operator_id:='unexpected';RETURN NEW;",
        "audit_counter": "UPDATE dashboard_publication_source_counters SET generation=generation+1,changed_at=clock_timestamp() WHERE source_name='finance_operation_audit';RETURN NEW;",
        "audit_sidecar": "UPDATE dashboard_unknown_proof SET payload='unexpected';RETURN NEW;",
        "deferred_fee": "UPDATE settlement_fee_result SET fee_amount_cent=fee_amount_cent+1;RETURN NEW;",
        "deferred_sidecar": "UPDATE dashboard_unknown_proof SET payload='unexpected';RETURN NEW;",
        "nested_truncate": "TRUNCATE dashboard_unknown_proof;RETURN NEW;",
        "nested_structure": "ALTER TABLE dashboard_unknown_proof ADD COLUMN IF NOT EXISTS unexpected integer;RETURN NEW;",
        "nested_index": "CREATE INDEX IF NOT EXISTS proof_nested_index ON dashboard_unknown_proof(payload);RETURN NEW;",
        "nested_trigger_function": "CREATE OR REPLACE FUNCTION proof_guard_dummy() RETURNS trigger LANGUAGE plpgsql AS $inner$ BEGIN NEW.payload:='unexpected';RETURN NEW;END $inner$;RETURN NEW;",
    }
    with proof_engine.begin() as connection:
        if effect == "nested_trigger_function":
            connection.execute(text("CREATE OR REPLACE FUNCTION proof_guard_dummy() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW;END $$"))
            connection.execute(text("CREATE TRIGGER proof_guard_dummy BEFORE UPDATE ON dashboard_unknown_proof FOR EACH ROW EXECUTE FUNCTION proof_guard_dummy()"))
        connection.execute(text("CREATE OR REPLACE FUNCTION proof_effect() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN " + bodies[effect] + " END $$"))
        if effect.startswith("deferred"):
            trigger = "CREATE CONSTRAINT TRIGGER proof_effect AFTER INSERT ON settlement_fee_result DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION proof_effect()"
        elif effect == "audit_row":
            trigger = "CREATE TRIGGER proof_effect BEFORE INSERT ON finance_operation_audit FOR EACH ROW EXECUTE FUNCTION proof_effect()"
        else:
            table = "finance_operation_audit" if effect.startswith("audit") else "settlement_fee_result"
            trigger = f"CREATE TRIGGER proof_effect AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION proof_effect()"
        connection.execute(text(trigger))
    with Session(proof_engine, autoflush=False) as session:
        with pytest.raises(repair.MissingFeeRepairError, match="final outputs|exact audit|source counter|physical/structural|transaction writes"):
            apply(session, manifest, exclusions, report["preview_hash"])
    assert_zero(proof_engine)


@pytest.mark.parametrize("kind", ["partition", "inheritance", "materialized", "view", "foreign"])
def test_unsupported_relation_kind_rejects_before_writer(proof_engine, monkeypatch, kind):
    manifest, exclusions, report = seed(proof_engine)
    server = "proof_server_" + uuid4().hex
    wrapper = "proof_wrapper_" + uuid4().hex
    with proof_engine.begin() as connection:
        if kind == "partition":
            connection.execute(text("CREATE TABLE dashboard_unsupported(id integer) PARTITION BY RANGE(id)"))
        elif kind == "inheritance":
            connection.execute(text("CREATE TABLE dashboard_unsupported() INHERITS(dashboard_unknown_proof)"))
        elif kind == "materialized":
            connection.execute(text("CREATE MATERIALIZED VIEW dashboard_unsupported AS SELECT 1 AS id"))
        elif kind == "view":
            connection.execute(text("CREATE VIEW dashboard_unsupported AS SELECT 1 AS id"))
        else:
            connection.execute(text(f'CREATE FOREIGN DATA WRAPPER "{wrapper}" NO HANDLER'))
            connection.execute(text(f'CREATE SERVER "{server}" FOREIGN DATA WRAPPER "{wrapper}"'))
            connection.execute(text(f'CREATE FOREIGN TABLE dashboard_unsupported(id integer) SERVER "{server}"'))
    monkeypatch.setattr(settlement,"rebuild_dual_fee_results",lambda *_args,**_kwargs:pytest.fail("writer must not start"))
    try:
        with Session(proof_engine,autoflush=False) as session:
            with pytest.raises(repair.MissingFeeRepairError,match="ordinary"):
                apply(session,manifest,exclusions,report["preview_hash"])
        assert_zero(proof_engine)
    finally:
        if kind == "foreign":
            with proof_engine.begin() as connection:
                connection.execute(text(f'DROP SERVER "{server}" CASCADE'))
                connection.execute(text(f'DROP FOREIGN DATA WRAPPER "{wrapper}"'))


def test_track_counts_off_fails_before_writer(proof_engine, monkeypatch):
    manifest, exclusions, report = seed(proof_engine)
    real = repair._fence
    def disabled(session, started):
        session.execute(text("SET LOCAL track_counts=off"))
        return real(session,started)
    monkeypatch.setattr(repair,"_fence",disabled)
    # Even an attempted configuration bypass in this transaction is rejected.
    with Session(proof_engine,autoflush=False) as session:
        with pytest.raises(repair.MissingFeeRepairError,match="configuration|track_counts"):
            apply(session,manifest,exclusions,report["preview_hash"])
    assert_zero(proof_engine)


def test_actual_disabled_track_counts_connection_rejects(proof_engine,monkeypatch):
    manifest,exclusions,report=seed(proof_engine)
    with proof_engine.connect() as connection:schema=connection.scalar(text('SELECT current_schema()'))
    disabled=create_engine(proof_engine.url,connect_args={'options':f'-c search_path={schema} -c track_counts=off'})
    try:
        with Session(disabled,autoflush=False) as session:
            assert session.scalar(text("SELECT current_setting('track_counts')"))=='off';session.rollback()
            with pytest.raises(repair.MissingFeeRepairError,match='track_counts'):
                apply(session,manifest,exclusions,report['preview_hash'])
    finally:disabled.dispose()
    assert_zero(proof_engine)


def test_missing_transaction_stat_result_fails_closed(proof_engine,monkeypatch):
    seed(proof_engine)
    with Session(proof_engine,autoflush=False) as session:
        schema=session.scalar(text('SELECT current_schema()'));names=repair._protected_names(session)
        real=session.execute
        def incomplete(statement,*args,**kwargs):
            result=real(statement,*args,**kwargs)
            if 'LEFT JOIN pg_catalog.pg_stat_xact_all_tables' in str(statement):
                rows=[dict(row) for row in result.mappings()];rows[0]['n_tup_ins']=None
                return SimpleNamespace(mappings=lambda:rows)
            return result
        monkeypatch.setattr(session,'execute',incomplete)
        with pytest.raises(repair.MissingFeeRepairError,match='statistics missing'):
            repair._relation_state(session,schema,names)


def test_xact_counters_are_live_and_stable_across_idle_reads(proof_engine):
    seed(proof_engine)
    with Session(proof_engine,autoflush=False) as session:
        schema,names,baseline=repair._fence(session,time.monotonic())
        original=baseline['dashboard_unknown_proof']['counts']
        session.execute(text('SELECT pg_sleep(1.1)'))
        assert repair._relation_state(session,schema,names)['dashboard_unknown_proof']['counts']==original
        session.execute(text("INSERT INTO dashboard_unknown_proof VALUES(2,'observed immediately')"))
        after=repair._relation_state(session,schema,names)['dashboard_unknown_proof']['counts']
        assert tuple(end-start for start,end in zip(original,after))==(1,0,0)
        session.execute(text('SELECT pg_sleep(1.1)'))
        assert repair._relation_state(session,schema,names)['dashboard_unknown_proof']['counts']==after
        session.rollback()


@pytest.mark.parametrize("source", ["settlement_fee_result", "settlement_fee_result_current", "finance_operation_audit"])
def test_required_source_counter_missing_rejects(proof_engine, source):
    manifest, exclusions, report = seed(proof_engine)
    with proof_engine.begin() as connection:
        connection.execute(text("DELETE FROM dashboard_publication_source_counters WHERE source_name=:name"),{"name":source})
    with Session(proof_engine,autoflush=False) as session:
        with pytest.raises(repair.MissingFeeRepairError,match="counter row missing"):
            apply(session,manifest,exclusions,report["preview_hash"])
    assert_zero(proof_engine)


@pytest.mark.parametrize("wrong", ["dq-delete", "dq-update", "counter-other", "counter-extra", "counter-time"])
def test_write_exceptions_do_not_open_whole_tables(proof_engine, monkeypatch, wrong):
    manifest, exclusions, report = seed(proof_engine)
    with Session(proof_engine) as session:
        session.add(m.DataQualityIssue(issue_id="outside-issue",issue_type="outside",coupon_id="outside",message="synthetic"))
        session.commit()
        session.execute(text("INSERT INTO dashboard_publication_source_counters VALUES('outside',0,clock_timestamp())"));session.commit()
    statements = {
        "dq-delete":"DELETE FROM data_quality_issues WHERE issue_id='outside-issue'",
        "dq-update":"UPDATE data_quality_issues SET message='unexpected' WHERE issue_id='outside-issue'",
        "counter-other":"UPDATE dashboard_publication_source_counters SET generation=generation+1 WHERE source_name='outside'",
        "counter-extra":"UPDATE dashboard_publication_source_counters SET generation=generation+1 WHERE source_name='settlement_fee_result'",
        "counter-time":"UPDATE dashboard_publication_source_counters SET changed_at='2000-01-01' WHERE source_name='settlement_fee_result'",
    }
    real = settlement.rebuild_dual_fee_results
    def altered(session,**kwargs):
        result=real(session,**kwargs);session.execute(text(statements[wrong]));return result
    monkeypatch.setattr(settlement,"rebuild_dual_fee_results",altered)
    with Session(proof_engine,autoflush=False) as session:
        with pytest.raises(repair.MissingFeeRepairError):apply(session,manifest,exclusions,report["preview_hash"])
    assert_zero(proof_engine)


def test_target_dq_delete_is_exact_and_allowed(proof_engine, monkeypatch):
    manifest,exclusions,report=seed(proof_engine)
    with Session(proof_engine) as session:
        session.add(m.DataQualityIssue(issue_id="target-issue",issue_type="target",coupon_id=manifest['coupons'][0]['coupon_id'],message="synthetic"));session.commit()
    real=settlement.rebuild_dual_fee_results
    def clear(session,**kwargs):
        result=real(session,**kwargs);session.execute(text("DELETE FROM data_quality_issues WHERE issue_id='target-issue'"));return result
    monkeypatch.setattr(settlement,"rebuild_dual_fee_results",clear)
    with Session(proof_engine,autoflush=False) as session:
        assert apply(session,manifest,exclusions,report["preview_hash"])["applied"]
        assert session.get(m.DataQualityIssue,"target-issue") is None


def test_preview_protection_contract_changes_hash_without_breaking_legacy_request_digest(proof_engine, monkeypatch):
    manifest,exclusions,report=seed(proof_engine)
    original_request=repair.digest(repair.validate_request(manifest,exclusions))
    changed=deepcopy(repair.WRITE_PROOF_CONTRACT);changed['version']='another-reviewed-contract'
    monkeypatch.setattr(repair,"WRITE_PROOF_CONTRACT",changed)
    with Session(proof_engine,autoflush=False) as session:
        assert preview(session,manifest,exclusions)['preview_hash']!=report['preview_hash']
        assert repair.digest(repair.validate_request(manifest,exclusions))==original_request


def test_legacy_successful_audit_replays_without_rewriting_it(proof_engine):
    manifest,exclusions,report=seed(proof_engine)
    request=repair.validate_request(manifest,exclusions)
    legacy_hash=repair.digest({'request':request,'dependencies':report['dependency_hash'],'quotes':report['quotes']})
    audit_id='missing-fee-'+repair.digest(manifest['request_id'])
    legacy={key:value for key,value in report.items() if key not in {'write_proof_version','write_proof_contract'}}
    legacy.update(preview_hash=legacy_hash,applied=True,calculation_run_id=audit_id,financial_before='legacy',financial_after='legacy')
    with Session(proof_engine,autoflush=False) as session:
        settlement.rebuild_dual_fee_results(session,calculation_run_id=audit_id,coupon_ids=[row['coupon_id'] for row in manifest['coupons']])
        session.add(m.FinanceOperationAudit(audit_id=audit_id,operation_type=repair.OPERATION,target_type='EXACT_COUPON_BATCH',
            target_id=repair.digest([row['coupon_id'] for row in manifest['coupons']]),operator_id=manifest['actor'],operator_role=1,
            after_snapshot=legacy,result_status=1,request_id=manifest['request_id'],request_payload_sha256=repair.digest(request)))
        session.commit()
        before=repair._rows(session,m.FinanceOperationAudit.__table__);session.rollback()
        replay=apply(session,manifest,exclusions,legacy_hash)
        assert replay['replayed'] and 'write_proof_version' not in replay
        assert repair._rows(session,m.FinanceOperationAudit.__table__)==before


@pytest.mark.parametrize("tamper",["fee","audit"])
def test_replay_readback_ignores_stale_unexpired_identity_map(proof_engine,tamper):
    manifest,exclusions,report=seed(proof_engine)
    with Session(proof_engine,autoflush=False,expire_on_commit=False) as session:
        apply(session,manifest,exclusions,report['preview_hash'])
        cached=session.scalar(select(m.SettlementFeeResult).limit(1));original=cached.input_fingerprint
        audit=session.scalar(select(m.FinanceOperationAudit).where(
            m.FinanceOperationAudit.audit_id=='missing-fee-'+repair.digest(manifest['request_id'])))
        original_request=audit.request_payload_sha256
        session.commit()
        with proof_engine.begin() as connection:
            if tamper=='fee':
                connection.execute(text("UPDATE settlement_fee_result SET input_fingerprint=:fingerprint WHERE fee_result_id=:identity"),
                    {'fingerprint':'b'*64,'identity':cached.fee_result_id})
            else:
                connection.execute(text("UPDATE finance_operation_audit SET request_payload_sha256=:fingerprint WHERE audit_id=:identity"),
                    {'fingerprint':'b'*64,'identity':audit.audit_id})
        assert cached.input_fingerprint==original
        assert audit.request_payload_sha256==original_request
        with pytest.raises(repair.MissingFeeRepairError,match='outputs changed' if tamper=='fee' else 'idempotency'):
            apply(session,manifest,exclusions,report['preview_hash'])


def test_postcheck_seal_rejects_commit_hook_sql(proof_engine):
    manifest,exclusions,report=seed(proof_engine)
    with Session(proof_engine,autoflush=False) as session:
        def late_sql(active):active.execute(text("UPDATE dashboard_unknown_proof SET payload='late'"))
        event.listen(session,"before_commit",late_sql)
        try:
            with pytest.raises(repair.MissingFeeRepairError,match="after final"):
                apply(session,manifest,exclusions,report['preview_hash'])
        finally:event.remove(session,"before_commit",late_sql)
    assert_zero(proof_engine)


@pytest.mark.parametrize("statement", ["INSERT INTO dashboard_unknown_proof VALUES(2,'concurrent')", "TRUNCATE dashboard_unknown_proof"])
def test_unknown_sidecar_concurrent_writes_stay_fenced(proof_engine,monkeypatch,statement):
    manifest,exclusions,report=seed(proof_engine)
    real=repair._preview
    def other_writer():
        with proof_engine.connect() as connection:
            connection.execute(text("SET LOCAL lock_timeout='100ms'"))
            with pytest.raises(DBAPIError) as error:connection.execute(text(statement))
            assert error.value.orig.sqlstate=='55P03'
            connection.rollback()
    def inspect(session,*args):
        with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(other_writer).result(timeout=5)
        return real(session,*args)
    monkeypatch.setattr(repair,"_preview",inspect)
    with Session(proof_engine,autoflush=False) as session:assert apply(session,manifest,exclusions,report['preview_hash'])['applied']


def test_representative_50_coupon_large_derived_tables_receipt(proof_engine,monkeypatch,tmp_path):
    manifest,exclusions,_=seed(proof_engine,count=50,sidecar=False)
    large_names=('dashboard_large_proof_perf','settlement_projection_large_proof_perf',
                 'settlement_ranking_large_proof_perf','settlement_monthly_large_proof_perf',
                 'settlement_details_large_proof_perf')
    with proof_engine.begin() as connection:
        for name in large_names:
            connection.execute(text(f'CREATE TABLE "{name}" AS SELECT item AS id,repeat(md5(item::text),32) AS payload FROM generate_series(1,100000) item'))
        physical=sum(connection.scalar(text('SELECT pg_total_relation_size(:name)'),{'name':name}) for name in large_names)
    statements=[];metrics=[]
    def observe(_connection,_cursor,statement,*_):statements.append(statement)
    event.listen(proof_engine,'before_cursor_execute',observe)
    def measured(label,function):
        def call(*args,**kwargs):
            started=time.monotonic();before=len(statements)
            try:return function(*args,**kwargs)
            finally:metrics.append({'phase':label,'seconds':round(time.monotonic()-started,3),'sql_statements':len(statements)-before})
        return call
    monkeypatch.setattr(repair,'_outside_financial_fingerprint',measured('ledger_hash',repair._outside_financial_fingerprint))
    monkeypatch.setattr(repair,'_assert_write_proof',measured('final_relation_write_proof',repair._assert_write_proof))
    monkeypatch.setattr(settlement,'rebuild_dual_fee_results',measured('ordinary_exact_writer',settlement.rebuild_dual_fee_results))
    try:
        with Session(proof_engine,autoflush=False) as session:
            started=time.monotonic();report=preview(session,manifest,exclusions);preview_seconds=time.monotonic()-started
            started=time.monotonic()
            try:
                applied=apply(session,manifest,exclusions,report['preview_hash'])
                assert applied['applied'];outcome='success'
            except (repair.MissingFeeBudgetError,DBAPIError) as error:
                if isinstance(error,DBAPIError):assert error.orig.sqlstate=='57014'
                outcome='budget-refused'
            apply_seconds=time.monotonic()-started
        if outcome=='success':
            with Session(proof_engine) as session:assert counts(session)==(100,100,0,1,0)
        else:assert_zero(proof_engine)
        # No business SELECT may scan any large sidecar; catalog/LOCK statements
        # contain their identities but never read their payload rows.
        assert not any('to_jsonb(t)' in sql and any('"'+name+'" t' in sql for name in large_names) for sql in statements)
        receipt={'outcome':outcome,'coupon_count':50,'direction_count':100,'large_derived_tables':5,
                 'derived_rows':500000,'derived_total_relation_bytes':physical,'budget':repair.BUDGET,
                 'preview_seconds':round(preview_seconds,3),'apply_seconds':round(apply_seconds,3),
                 'sql_statements':len(statements),'phases':metrics,'production':False,'database':'dedicated_loopback_postgresql'}
        (tmp_path/'write-proof-50-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print('write-proof 50 receipt: '+json.dumps(receipt))
    finally:event.remove(proof_engine,'before_cursor_execute',observe)
