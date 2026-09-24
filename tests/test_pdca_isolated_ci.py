"""The PDCA verification workflow must not gain production access."""
from pathlib import Path

import yaml


def test_pdca_ci_is_test_only_and_uses_disposable_loopback_postgres():
    path = Path(__file__).resolve().parents[1] / '.github/workflows/pdca-readonly-verify.yml'
    assert path.is_file(), 'Missing isolated PDCA verification workflow'
    source = path.read_text(encoding='utf-8')
    workflow = yaml.safe_load(source)
    assert workflow['permissions'] == {'contents': 'read'}
    assert set(workflow['jobs']) == {'verify-pdca'}
    job = workflow['jobs']['verify-pdca']
    assert job['runs-on'] == 'ubuntu-latest'
    assert 'environment' not in job
    assert job['env']['PDCA_READONLY_TEST_PORT'] == '55439'
    postgres = job['services']['postgres']
    assert postgres['env']['POSTGRES_DB'] == 'pdca_readonly_test'
    assert postgres['ports'] == ['127.0.0.1:55439:5432']
    assert 'secrets.' not in source
    assert 'pull_request_target' not in source
    assert 'ssh' not in source.lower()
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'tests/test_pdca_readonly_postgres.py' in commands
    assert 'tests/test_pdca_source_evidence.py' in commands
    assert 'deploy' not in commands.lower()
