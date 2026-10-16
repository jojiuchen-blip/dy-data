import json
import os
import shutil
import subprocess

import pytest
from verify_operation_receipt import verify


def test_preflight_only_report_is_not_a_completed_compaction():
    with pytest.raises(ValueError, match='missing_or_duplicate'):
        verify('production_compact', 'api_and_worker_source_verification=passed\nreal_resource_guard_enabled=true\n')


def test_compaction_requires_matching_published_head_and_unchanged_facts():
    proof = {'compaction_result': {'status': 'success', 'generation_id': 'compact-qa'},
             'after_head': {'generation_id': 'compact-qa', 'kind': 'compact', 'depth': 0},
             'financial_facts_unchanged': True}
    verify('production_compact', json.dumps(proof))
    proof['after_head']['generation_id'] = 'old-head'
    with pytest.raises(ValueError, match='invalid_compaction'):
        verify('production_compact', json.dumps(proof))


@pytest.mark.parametrize('operation', ['production_recover_apply', 'production_scope_apply'])
def test_dry_run_receipt_cannot_prove_an_apply(operation):
    with pytest.raises(ValueError):
        verify(operation, 'recovery_driver_exit_code=0 mode=dry-run\nseptember_scope_exit_code=0 mode=dry-run\n')


def test_streamed_shell_stdin_must_not_be_consumed_by_child_command():
    bash = os.environ.get('DYDATA_OPS_BASH') or shutil.which('bash')
    assert bash, 'bash_required_for_stdin_regression'
    prefix = 'compose() { cat > /dev/null; }\n'
    broken = subprocess.run([bash, '-s'], input=prefix+'compose exec\nprintf "completed\\n"\n', text=True, capture_output=True, check=True)
    assert 'completed' not in broken.stdout
    fixed = subprocess.run([bash, '-s'], input=prefix+'compose exec < /dev/null\nprintf "completed\\n"\n', text=True, capture_output=True, check=True)
    assert fixed.stdout.strip() == 'completed'
