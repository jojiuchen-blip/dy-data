"""Safe source staging for the Tencent deployment bootstrap."""
import hashlib
import io
import importlib.util
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'stage_deploy_source.py'


def load_script():
    spec = importlib.util.spec_from_file_location('stage_deploy_source', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_at(root, entries):
    archive = root / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        for name, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == 'symlink':
                info.type = tarfile.SYMTYPE
                info.linkname = '/outside'
                output.addfile(info)
            else:
                info.size = 3
                output.addfile(info, io.BytesIO(b'new'))
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def setup_source(tmp_path, monkeypatch):
    module = load_script()
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(total=100 * 1024**3, free=80 * 1024**3))
    app = tmp_path / 'repo'
    app.mkdir()
    (app / 'old.txt').write_text('old')
    return module, app


def test_two_releases_keep_exactly_one_previous_source(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    for _ in range(3):
        archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
        module.stage_source(app, archive, digest)
        assert not archive.exists()
        assert (app / 'deploy/tencent/deploy.sh').read_bytes() == b'new'
        assert (tmp_path / 'repo-previous').is_dir()
        assert not (tmp_path / 'repo-retired').exists()
        assert not (tmp_path / 'repo-stage').exists()


@pytest.mark.parametrize('name,kind', [('../escape', 'file'), ('/escape', 'file'), ('linked', 'symlink')])
def test_unsafe_archive_never_replaces_source(tmp_path, monkeypatch, name, kind):
    module, app = setup_source(tmp_path, monkeypatch)
    archive, digest = archive_at(tmp_path, [(name, kind)])
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert (app / 'old.txt').read_text() == 'old'


def test_hash_and_capacity_fail_before_source_change(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
    with pytest.raises(ValueError):
        module.stage_source(app, archive, '0' * 64)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(total=100 * 1024**3, free=10 * 1024**3))
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert (app / 'old.txt').read_text() == 'old'


def test_existing_retention_directory_requires_identity_record(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    (tmp_path / 'repo-previous').mkdir()
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert (app / 'old.txt').exists()


def test_archive_must_be_direct_child_of_app_parent(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    nested = tmp_path / 'nested'
    nested.mkdir()
    archive, digest = archive_at(nested, [('deploy/tencent/deploy.sh', 'file')])
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert (app / 'old.txt').exists()


def test_failed_switch_restores_both_source_generations(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
    module.stage_source(app, archive, digest)
    (app / 'current.txt').write_text('current')
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
    original = Path.rename

    def fail_switch(path, target):
        if path.name == 'repo-stage':
            raise OSError('simulated switch failure')
        return original(path, target)

    monkeypatch.setattr(Path, 'rename', fail_switch)
    with pytest.raises(OSError):
        module.stage_source(app, archive, digest)
    assert (app / 'current.txt').read_text() == 'current'
    assert (tmp_path / 'repo-previous' / 'old.txt').read_text() == 'old'
    assert not (tmp_path / 'repo-retired').exists()


def test_symlink_source_and_retention_are_rejected(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (tmp_path / 'repo-previous').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Host cannot create filesystem symlinks')
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert outside.is_dir()
    assert (app / 'old.txt').exists()


def test_workflow_uses_stager_and_keeps_core_deployment_gates():
    workflow = (SCRIPT.parents[1] / '.github/workflows/tencent-lighthouse-deploy.yml').read_text(encoding='utf-8')
    assert 'scripts/stage_deploy_source.py' in workflow
    assert '--sha256 "$expected_hash"' in workflow
    assert 'sudo -n bash -s --' in workflow
    assert 'flock -n 9' in workflow
    assert 'SKIP_GIT_SYNC=true' in workflow
    assert 'bash deploy/tencent/deploy.sh "$target_sha"' in workflow
    assert 'find "$app_dir"' not in workflow
    assert '${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}' in workflow


def test_python310_hashing_and_tar_extraction(tmp_path, monkeypatch):
    module, app = setup_source(tmp_path, monkeypatch)
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')])
    monkeypatch.delattr(module.hashlib, 'file_digest', raising=False)
    extractall = module.tarfile.TarFile.extractall

    def python310_extractall(self, path='.', members=None, *, numeric_owner=False):
        return extractall(self, path, members=members, numeric_owner=numeric_owner)

    monkeypatch.setattr(module.tarfile.TarFile, 'extractall', python310_extractall)
    module.stage_source(app, archive, digest)
    assert (app / 'deploy/tencent/deploy.sh').read_bytes() == b'new'


@pytest.mark.parametrize('entry', ['.', './', './deploy/tencent/deploy.sh', 'deploy/../overwrite', 'C:/escape', '//server/share'])
def test_noncanonical_member_names_are_rejected(tmp_path, monkeypatch, entry):
    module, app = setup_source(tmp_path, monkeypatch)
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file'), (entry, 'file')])
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert (app / 'old.txt').exists()


@pytest.mark.parametrize('entries', [
    [('node', 'file'), ('node/child', 'file')],
    [('node/child', 'file'), ('node', 'file')],
    [('deploy/tencent/deploy.sh', 'file')],
])
def test_file_directory_conflicts_and_duplicates_rejected(tmp_path, monkeypatch, entries):
    module, app = setup_source(tmp_path, monkeypatch)
    archive, digest = archive_at(tmp_path, [('deploy/tencent/deploy.sh', 'file')] + entries)
    with pytest.raises(ValueError):
        module.stage_source(app, archive, digest)
    assert (app / 'old.txt').exists()
