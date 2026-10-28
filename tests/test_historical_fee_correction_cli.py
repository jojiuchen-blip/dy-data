"""Synthetic CLI preview, explicit apply and durable idempotent readback."""
import json
import sys

import pytest
from sqlalchemy.orm import sessionmaker

from scripts import historical_fee_correction as cli
from test_historical_fee_correction import fingerprint,seed


def test_cli_preview_apply_and_retry(db_session,tmp_path,monkeypatch,capsys):
    manifest,sources = seed(db_session)
    manifest_path = tmp_path/"private-manifest.json"
    source_path = tmp_path/"private-source.json"
    manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
    source_path.write_bytes(next(iter(sources.values())))
    argv = ["historical_fee_correction","--manifest",str(manifest_path),"--source",str(source_path)]
    factory = sessionmaker(bind=db_session.get_bind(),autoflush=False)
    monkeypatch.setattr(cli,"get_session_factory",lambda:factory)
    monkeypatch.setattr(sys,"argv",argv)
    before = fingerprint(db_session)
    cli.main()
    preview = json.loads(capsys.readouterr().out)
    assert fingerprint(db_session) == before
    monkeypatch.setattr(sys,"argv",[*argv,"--apply","--expected-preview-sha256",preview["preview_sha256"]])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["durable_readback_verified"] and not result["already_applied"]
    db_session.expire_all()
    before = fingerprint(db_session)
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["durable_readback_verified"] and result["already_applied"]
    assert fingerprint(db_session) == before


def test_cli_missing_reviewed_hash_rejected_before_opening_database(monkeypatch):
    monkeypatch.setattr(sys,"argv",["cli","--manifest","fake","--source","fake","--apply"])
    monkeypatch.setattr(cli,"get_session_factory",lambda:pytest.fail("must not open database"))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
