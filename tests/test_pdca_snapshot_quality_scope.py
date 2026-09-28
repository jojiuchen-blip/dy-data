from datetime import datetime
import pytest
from apps.api.dy_api.models import DataQualityIssue,JobRun
from test_pdca_snapshot import client,snapshot,page


def add_issue(session,identity,**links):
    session.add(DataQualityIssue(issue_id=identity,issue_type='synthetic',message='synthetic only',**links))


def test_quality_scope_preserves_union_and_explicit_cohort(client,db_session):
    db_session.add(JobRun(job_id='J',job_name='synthetic',status='success',window_start=datetime(2026,8,1),window_end=datetime(2026,8,3)))
    add_issue(db_session,'ORDER',order_id='A')
    add_issue(db_session,'COUPON',coupon_id='C')
    add_issue(db_session,'BATCH',order_id='OUTSIDE',source_run_id='J')
    add_issue(db_session,'OVERLAP',order_id='A',coupon_id='C',source_run_id='J')
    add_issue(db_session,'OTHER',order_id='OUTSIDE')
    db_session.commit()
    broad=snapshot(client)
    assert broad['meta']['quality_issue_scope']=='related_batches'
    assert [r['issue_id'] for r in page(client,broad,'quality_issues').json()['data']['rows']]==['BATCH','COUPON','ORDER','OVERLAP']
    cohort=snapshot(client,qualityIssueScope='cohort')
    assert cohort['meta']['quality_issue_scope']=='cohort'
    assert 'batch_only_quality_issues_excluded' in cohort['meta']['blocking_reasons']
    assert cohort['meta']['publishable'] is False
    result=page(client,cohort,'quality_issues').json()
    assert result['meta']['quality_issue_scope']=='cohort'
    assert [r['issue_id'] for r in result['data']['rows']]==['COUPON','ORDER','OVERLAP']
    assert client.get('/api/v1/admin/pdca-source-snapshots',params={'periodStart':'2026-08-01','periodEnd':'2026-08-02','observedThrough':'2026-09-01T00:00:00Z','qualityIssueScope':'truncate'}).status_code==422


def test_quality_ids_empty_cohort_keeps_batch_evidence(db_session):
    from dy_api.pdca_snapshot_projection import _quality_rows
    add_issue(db_session,'BATCH',source_run_id='J');db_session.commit()
    assert [r['issue_id'] for r in _quality_rows(db_session,[],[],{'J'},'related_batches')]==['BATCH']
    assert _quality_rows(db_session,[],[],{'J'},'cohort')==[]


def test_quality_limits_apply_to_deduplicated_union(db_session,monkeypatch):
    from dy_api import pdca_snapshot_projection as p
    monkeypatch.setattr(p,'MAX_DATASET_ROWS',2)
    add_issue(db_session,'A',order_id='O',coupon_id='C',source_run_id='J')
    add_issue(db_session,'B',order_id='O',coupon_id='C',source_run_id='J');db_session.commit()
    assert len(p._quality_rows(db_session,['O'],['C'],{'J'},'related_batches'))==2
    add_issue(db_session,'C',source_run_id='J');db_session.commit()
    with pytest.raises(p.SnapshotLimitError):p._quality_rows(db_session,['O'],['C'],{'J'},'related_batches')
    assert len(p._quality_rows(db_session,['O'],['C'],{'J'},'cohort'))==2


def test_quality_union_overflow_even_when_individual_branches_fit(db_session,monkeypatch):
    from dy_api import pdca_snapshot_projection as p
    monkeypatch.setattr(p,'MAX_DATASET_ROWS',2)
    add_issue(db_session,'A',order_id='O');add_issue(db_session,'B',coupon_id='C');add_issue(db_session,'C',source_run_id='J');db_session.commit()
    with pytest.raises(p.SnapshotLimitError):p._quality_rows(db_session,['O'],['C'],{'J'},'related_batches')


def test_quality_identifier_and_projected_cells_still_bounded(db_session,monkeypatch):
    from dy_api import pdca_snapshot_projection as p
    monkeypatch.setattr(p,'MAX_CELL_CHARACTERS',8)
    add_issue(db_session,'X'*9,order_id='O');db_session.commit()
    with pytest.raises(p.SnapshotLimitError):p._quality_rows(db_session,['O'],[],set(),'cohort')


def test_quality_id_select_bounds_transfer_even_if_guard_sees_other_subset(db_session,monkeypatch):
    from dy_api import pdca_snapshot_projection as p
    monkeypatch.setattr(p,'MAX_CELL_CHARACTERS',8)
    add_issue(db_session,'Y'*9,order_id='O');db_session.commit()
    # The independent preflight may inspect another unordered LIMIT subset.
    monkeypatch.setattr(db_session,'scalar',lambda *args,**kwargs: None)
    original=p._rows
    transferred=[]
    def observe(session,statement):
        rows=original(session,statement);transferred.extend(rows);return rows
    monkeypatch.setattr(p,'_rows',observe)
    with pytest.raises(p.SnapshotLimitError):p._quality_rows(db_session,['O'],[],set(),'cohort')
    assert transferred==[{'issue_id':None}]
