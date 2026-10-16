"""Independent, loopback PostgreSQL rehearsal for the authorized scope wrapper."""
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from apps.api.dy_api import models as M
from apps.api.dy_api.routes.fee_admin import create_settlement_scope_rules
from apps.api.dy_api.routes._data import DashboardDataStore
from apps.worker.settlement_rebuild import scoped_business_month
from test_api_fee_admin import _seed_sku
from test_month_close import _publish_month
from test_settlement_projection import _seed_base, _seed_fee_month

@pytest.fixture
def rehearsal(monkeypatch):
    raw=os.environ['DY_RELEASE_POSTGRES_URL']
    url=make_url(raw)
    assert url.host in {'127.0.0.1','localhost'} and url.database=='dydata_release'
    schema='scope_ops_gate_'+uuid4().hex
    admin=create_engine(url)
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(url,connect_args={'options':f'-c search_path={schema} -c lock_timeout=2000 -c statement_timeout=15000'})
    try:
        M.Base.metadata.create_all(engine)
        spec=importlib.util.spec_from_file_location('scope_ops_'+uuid4().hex,os.environ['DYDATA_OPS_SCOPE_SCRIPT'])
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module
        spec.loader.exec_module(module)
        monkeypatch.setattr(module,'get_engine',lambda:engine)
        with Session(engine) as s:
            _seed_base(s,prefix='scope-ops-gate')
            _seed_sku(s,'scope-ops-sku','QA SKU',owner_account_id='QA_PRIVATE_OWNER_98123')
            _seed_fee_month(s,prefix='scope-ops-finance',month='2026-08',index=1,amounts=(100,10))
            s.commit()
            _publish_month(s)
            create_settlement_scope_rules({'effectiveMonth':'2026-08','ownerAccountId':'QA_PRIVATE_OWNER_98123','allowedSaleChannels':['LIVE','SHORT_VIDEO'],'changeReason':'isolated fixture'},module._synthetic_request(),idempotency_key='august-isolated-fixture-0001',username='qa-fixture',store=DashboardDataStore(s))
            s.add(M.SettlementStatement(statement_id='qa-aug-statement',store_id='scope-ops-finance-store',statement_month='2026-08',statement_status=4,promotion_original_fee_cent=10,promotion_net_fee_cent=10,confirmed_by='qa-fixture',confirmed_at=datetime.now(timezone.utc),locked_by='qa-fixture',locked_at=datetime.now(timezone.utc),lock_version='qa-aug-lock'))
            s.add(M.InvoiceRecord(invoice_id='qa-aug-invoice',store_id='scope-ops-finance-store',statement_month='2026-08',statement_id='qa-aug-statement',fee_direction=1,invoice_number='12345678901234567890',invoice_date=date(2026,8,31),invoice_amount_cent=10,invoice_status=1,source_type=1,registered_by='qa-fixture'))
            s.commit()
        yield module,engine
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

def invoke(module,monkeypatch,*,apply=False,reason='authorized September fixture'):
    args=['scope-ops','--actor','ops-authorized-fixture','--idempotency-key','september-atomic-fixture-0001','--change-reason',reason]
    if apply:args.append('--apply')
    monkeypatch.setattr(sys,'argv',args)
    return module.main()

def target_state(engine):
    with Session(engine) as s:
        rules=s.scalar(select(func.count()).select_from(M.SettlementScopeRule).where(M.SettlementScopeRule.effective_month=='2026-09'))
        jobs=list(s.scalars(select(M.JobRun).where(M.JobRun.job_name=='settlement_rebuild',M.JobRun.metadata_json['requested_by'].as_string()=='ops-authorized-fixture')))
        return rules,[(j.job_id,j.status,scoped_business_month(j.metadata_json)) for j in jobs]

def observe_internal_route_commit(module,engine,monkeypatch,*,fail=False):
    original=module.create_settlement_scope_rules
    calls=[]
    def observed(*args,**kwargs):
        result=original(*args,**kwargs)
        # A separate PostgreSQL connection must not see the route's internal
        # commit until the outer wrapper has stamped and committed the job.
        assert target_state(engine)==(0,[])
        calls.append(True)
        if fail:raise RuntimeError('QA_PRIVATE_OWNER_98123 deliberately injected')
        return result
    monkeypatch.setattr(module,'create_settlement_scope_rules',observed)
    return calls

def test_pg_dry_run_apply_and_read_only_replay(rehearsal,monkeypatch,capsys):
    module,engine=rehearsal
    with Session(engine) as s:before=module._fingerprint(s)
    calls=observe_internal_route_commit(module,engine,monkeypatch)
    assert invoke(module,monkeypatch)==0
    assert target_state(engine)==(0,[])
    assert invoke(module,monkeypatch,apply=True)==0
    rules,jobs=target_state(engine)
    assert rules==2 and len(jobs)==1 and jobs[0][1:]==('queued','2026-09')
    assert len(calls)==2
    with Session(engine) as s:
        job=s.get(M.JobRun,jobs[0][0]);job.status='success'
        s.add(M.SettlementStatement(statement_id='qa-sep-statement',store_id='scope-ops-finance-store',statement_month='2026-09'))
        s.commit()
        expected_job=dict(s.execute(select(*M.JobRun.__table__.c).where(M.JobRun.job_id==job.job_id)).mappings().one())
    # Replaying after a target bill exists must be read-only, preserving status.
    assert invoke(module,monkeypatch,apply=True)==0
    assert len(calls)==2
    with Session(engine) as s:
        assert module._fingerprint(s)==before
        actual=dict(s.execute(select(*M.JobRun.__table__.c).where(M.JobRun.job_id==jobs[0][0])).mappings().one())
        assert actual==expected_job
        assert s.scalar(select(func.count()).select_from(M.JobEvent).where(M.JobEvent.job_id==jobs[0][0],M.JobEvent.event_type=='settlement_scope_restricted'))==1
    assert 'QA_PRIVATE_OWNER_98123' not in capsys.readouterr().out

def test_pg_route_commit_then_fault_rolls_back_everything(rehearsal,monkeypatch,capsys):
    module,engine=rehearsal
    with Session(engine) as s:before=module._fingerprint(s)
    calls=observe_internal_route_commit(module,engine,monkeypatch,fail=True)
    assert invoke(module,monkeypatch,apply=True)!=0
    assert calls==[True] and target_state(engine)==(0,[])
    with Session(engine) as s:assert module._fingerprint(s)==before
    output=capsys.readouterr().out
    assert 'QA_PRIVATE_OWNER_98123' not in output
    assert 'deliberately injected' not in output

def test_pg_reused_key_different_payload_refuses_without_rewrite(rehearsal,monkeypatch):
    module,engine=rehearsal
    assert invoke(module,monkeypatch,apply=True)==0
    with Session(engine) as s:
        before_rules=[dict(r) for r in s.execute(select(*M.SettlementScopeRule.__table__.c)).mappings()]
        before_jobs=[dict(r) for r in s.execute(select(*M.JobRun.__table__.c).where(M.JobRun.job_name=='settlement_rebuild')).mappings()]
    assert invoke(module,monkeypatch,apply=True,reason='different payload must refuse')!=0
    with Session(engine) as s:
        assert [dict(r) for r in s.execute(select(*M.SettlementScopeRule.__table__.c)).mappings()]==before_rules
        assert [dict(r) for r in s.execute(select(*M.JobRun.__table__.c).where(M.JobRun.job_name=='settlement_rebuild')).mappings()]==before_jobs


@pytest.mark.parametrize('tamper', ['unscoped','wrong_month','wrong_actor','wrong_trigger','missing_event','wrong_event_actor'])
def test_pg_incompatible_replay_is_read_only_refused(rehearsal,monkeypatch,tamper):
    from apps.worker.settlement_rebuild import settlement_month_scope_metadata
    module,engine=rehearsal
    assert invoke(module,monkeypatch,apply=True)==0
    _,jobs=target_state(engine)
    with Session(engine) as s:
        job=s.get(M.JobRun,jobs[0][0])
        metadata=dict(job.metadata_json)
        if tamper=='unscoped':
            for key in settlement_month_scope_metadata('2026-09'):metadata.pop(key,None)
        elif tamper=='wrong_month':metadata.update(settlement_month_scope_metadata('2026-10'))
        elif tamper=='wrong_actor':metadata['requested_by']='different-qa-actor'
        elif tamper=='wrong_trigger':metadata['trigger']='different-qa-trigger'
        job.metadata_json=metadata
        event=s.scalar(select(M.JobEvent).where(M.JobEvent.job_id==job.job_id,M.JobEvent.event_type=='settlement_scope_restricted'))
        if tamper=='missing_event':s.delete(event)
        elif tamper=='wrong_event_actor':event.actor_id='different-qa-actor'
        s.commit()
        expected_job=dict(s.execute(select(*M.JobRun.__table__.c).where(M.JobRun.job_id==job.job_id)).mappings().one())
        expected_events=[dict(r) for r in s.execute(select(*M.JobEvent.__table__.c).where(M.JobEvent.job_id==job.job_id)).mappings()]
    assert invoke(module,monkeypatch,apply=True)!=0
    with Session(engine) as s:
        assert dict(s.execute(select(*M.JobRun.__table__.c).where(M.JobRun.job_id==jobs[0][0])).mappings().one())==expected_job
        assert [dict(r) for r in s.execute(select(*M.JobEvent.__table__.c).where(M.JobEvent.job_id==jobs[0][0])).mappings()]==expected_events
