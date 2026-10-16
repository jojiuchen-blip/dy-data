"""Require completion evidence outside the remote streamed shell's stdin."""
import json
import sys
from pathlib import Path


def verify(operation: str, report: str) -> None:
    if operation == 'production_compact':
        proofs = []
        for line in report.splitlines():
            try:
                value = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and 'compaction_result' in value:
                proofs.append(value)
        if len(proofs) != 1:
            raise ValueError('missing_or_duplicate_compaction_receipt')
        proof = proofs[0]
        result, head = proof['compaction_result'], proof['after_head']
        if not (proof.get('financial_facts_unchanged') is True
                and result.get('status') == 'success' and result.get('generation_id')
                and head.get('generation_id') == result['generation_id']
                and head.get('kind') == 'compact' and head.get('depth') == 0):
            raise ValueError('invalid_compaction_receipt')
        return
    modes = {
        'production_recover_dry_run': 'recovery_driver_exit_code=0 mode=dry-run',
        'production_recover_apply': 'recovery_driver_exit_code=0 mode=apply',
        'production_scope_dry_run': 'september_scope_exit_code=0 mode=dry-run',
        'production_scope_apply': 'september_scope_exit_code=0 mode=apply',
    }
    expected = modes.get(operation)
    if expected is None or report.splitlines().count(expected) != 1:
        raise ValueError('missing_or_duplicate_operation_receipt')


if __name__ == '__main__':
    verify(sys.argv[1], Path(sys.argv[2]).read_text(encoding='utf-8'))
    print('controller_operation_receipt=verified')
