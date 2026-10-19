from sqlalchemy import create_engine,event,select,func
from sqlalchemy.orm import Session
from apps.api.dy_api.models import Base,RawDouyinOrder
from apps.api.dy_api.ranking_schema_v1 import metadata,runs,samples,lead_bindings,snapshots
from apps.api.dy_api.ranking_snapshots import calculate_snapshot
from apps.worker.ranking_preview_fixture import seed_preview,START,END,CUTOFF,ELIGIBILITY_VERSION
import pytest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine);metadata.create_all(engine)
    with Session(engine) as session:
        seed_preview(session)
        original=session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id=='O1'))
        for i in range(1200):
            session.add(RawDouyinOrder(order_id=f'MEM-{i}',sku_id=original.sku_id,sale_time=original.sale_time,owner_account_id=original.owner_account_id))
        session.commit()
        yield session
    engine.dispose()

def calculate(db,key):
    return calculate_snapshot(db,run_id=key,period_start=START,period_end=END,observed_through=CUTOFF,roster_at=START,eligibility_version=ELIGIBILITY_VERSION,data_mode='business',max_period_rows=50000)

def test_snapshot_write_batches_are_bounded_and_complete(db):
    sizes=[]
    def inspect(conn,clause,multiparams,params,options):
        if getattr(clause,'is_insert',False) and clause.table.name in {samples.name,snapshots.name,lead_bindings.name}:
            sizes.append(len(multiparams))
    event.listen(db.bind,'before_execute',inspect)
    calculate(db,'bounded');db.commit()
    assert max(sizes)<=500, f'unbounded driver parameter batch: {max(sizes)}'
    assert db.scalar(select(func.count()).select_from(samples).where(samples.c.run_id=='bounded',samples.c.metric_key=='order_count',samples.c.sample_key.like('MEM-%')))==1200
    assert db.scalar(select(runs.c.status).where(runs.c.run_id=='bounded'))=='success'

def test_later_batch_failure_rolls_back_entire_snapshot(db):
    writes=0
    before=db.scalar(select(func.count()).select_from(lead_bindings))
    def fail(conn,clause,multiparams,params,options):
        nonlocal writes
        if getattr(clause,'is_insert',False) and clause.table.name==samples.name:
            writes+=1
            if writes==2: raise RuntimeError('synthetic second-batch failure')
    event.listen(db.bind,'before_execute',fail)
    with pytest.raises(RuntimeError,match='second-batch'):
        calculate(db,'rollback')
    assert db.scalar(select(func.count()).select_from(runs).where(runs.c.run_id=='rollback'))==0
    assert db.scalar(select(func.count()).select_from(samples).where(samples.c.run_id=='rollback'))==0
    assert db.scalar(select(func.count()).select_from(snapshots).where(snapshots.c.run_id=='rollback'))==0
    assert db.scalar(select(func.count()).select_from(lead_bindings))==before

def test_refresh_terminal_payloads_are_loaded_in_bounded_batches(monkeypatch):
    from apps.api.dy_api import clue_followup_metrics
    from apps.api.dy_api.ranking_lifecycle import _future_terminal_payload_min
    cutoff=datetime(2026,10,19,tzinfo=timezone.utc)
    ids={f'ORDER-{i:04d}' for i in range(1201)};calls=[];seen=[]
    def load(session,order_ids,**options):
        batch=list(order_ids);calls.append(len(batch));seen.extend(batch)
        assert options=={'observed_through':cutoff,'include_raw_clues':True}
        return {key:SimpleNamespace(terminal_at=cutoff+timedelta(minutes=int(key.split('-')[1])+1)) for key in batch}
    monkeypatch.setattr(clue_followup_metrics,'load_terminal_evidence',load)
    result=_future_terminal_payload_min(object(),ids,cutoff=cutoff)
    assert max(calls)<=500, f'raw JSON evidence for {max(calls)} orders retained at once'
    assert len(seen)==len(ids) and set(seen)==ids
    assert len(result)==len(ids) and min(result)==cutoff+timedelta(minutes=1)


def test_real_terminal_parser_preserves_evidence_across_batch_boundary(db):
    from apps.api.dy_api.models import RawDouyinOrderCoupon,RawDouyinVerifyRecord,SettlementOrderDetail
    from apps.api.dy_api.clue_followup_metrics import load_terminal_evidence
    from apps.api.dy_api.ranking_lifecycle import _future_terminal_payload_min
    cutoff=datetime(2026,10,19,tzinfo=timezone.utc)
    before=cutoff-timedelta(hours=4)
    ids={f'BOUNDARY-{i:04d}' for i in range(503)}
    for key in sorted(ids):
        db.add(RawDouyinOrder(order_id=key,source_observed_at=before,raw_payload={}))
    db.flush()
    # Both sides of the 500-ID boundary contain canceled and replacement facts.
    for index in (499,500):
        key=f'BOUNDARY-{index:04d}';coupon=f'COUPON-{index}';verify=f'VERIFY-{index}'
        db.add_all([
            RawDouyinOrderCoupon(coupon_id=coupon,order_id=key,coupon_status='unused',coupon_status_normalized='available',source_observed_at=before),
            RawDouyinVerifyRecord(verify_id=verify,coupon_id=coupon,verify_status='success',verify_time=before,cancel_time=before+timedelta(hours=1),source_observed_at=before+timedelta(hours=1)),
            SettlementOrderDetail(coupon_id=coupon,order_id=key,product_type='maintenance',verify_id=verify if index==499 else 'VERIFY-REPLACEMENT',is_verified=True,verify_time=before if index==499 else before+timedelta(hours=2),updated_at=before+timedelta(hours=2)),
        ])
    for index in (498,501,502):
        row=db.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id==f'BOUNDARY-{index:04d}'))
        row.order_status='1'
        row.raw_payload={'certificate':[{'item_status':301,'refund_time':int((cutoff+timedelta(hours=index-497)).timestamp())}]}
    db.commit()
    whole=load_terminal_evidence(db,ids,observed_through=cutoff,include_raw_clues=True)
    parts={}
    ordered=sorted(ids)
    for offset in range(0,len(ordered),500):
        parts.update(load_terminal_evidence(db,ordered[offset:offset+500],observed_through=cutoff,include_raw_clues=True))
    assert parts==whole
    assert whole['BOUNDARY-0499'].kind is None
    assert whole['BOUNDARY-0500'].kind=='verified'
    expected=sorted(e.terminal_at for e in whole.values() if e.terminal_at and e.terminal_at>cutoff)
    assert len(expected)==3
    assert sorted(_future_terminal_payload_min(db,ids,cutoff=cutoff))==expected
