#!/usr/bin/env python3
"""Stage a trusted release; retain exactly one previous source tree.

Run under the deployment lock as root. This touches source trees only, never
business data, environment files, Docker volumes or backup retention.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile


def plain_path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink in deployment path')
    return path


def stage_source(app, archive, expected_hash):
    app, archive = plain_path(app), plain_path(archive)
    parent = app.parent
    plain_path(parent / 'logs')
    if not parent.is_dir() or archive.parent != parent or not archive.is_file():
        raise ValueError('Archive must be a regular direct child of source parent')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
        raise ValueError('Invalid source checksum')
    with archive.open('rb') as stream:
        checksum = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
        if checksum.hexdigest() != expected_hash:
            raise ValueError('Source checksum mismatch')
    if app.exists() and not app.is_dir():
        raise ValueError('Source must be a directory')
    stage = plain_path(parent / (app.name + '-stage'))
    previous = plain_path(parent / (app.name + '-previous'))
    retired = plain_path(parent / (app.name + '-retired'))
    record = plain_path(parent / (app.name + '-previous.identity.json'))
    if stage.exists() or retired.exists():
        raise ValueError('Unfinished staging requires operator inspection')
    if previous.exists() and not app.exists():
        raise ValueError('Previous source without current tree requires inspection')
    if previous.exists():
        if not previous.is_dir() or not record.is_file():
            raise ValueError('Previous source identity missing')
        identity = previous.stat()
        if json.loads(record.read_text()) != [identity.st_dev, identity.st_ino]:
            raise ValueError('Previous source identity mismatch')
    elif record.exists():
        raise ValueError('Previous source record has no tree')
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        declared = {}
        for member in members:
            name = PurePosixPath(member.name)
            canonical = member.name.rstrip('/') if member.isdir() else member.name
            if not canonical or canonical == '.' or canonical != str(name) or ':' in canonical:
                raise ValueError('Noncanonical archive path')
            if canonical in declared:
                raise ValueError('Duplicate archive path')
            declared[canonical] = member.isdir()
            if name.is_absolute() or '..' in name.parts or '\\' in member.name:
                raise ValueError('Unsafe archive path')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Unsupported archive member')
        for name in declared:
            if any(str(part) in declared and not declared[str(part)] for part in PurePosixPath(name).parents):
                raise ValueError('Archive file used as parent directory')
        if not any(m.name == 'deploy/tencent/deploy.sh' and m.isfile() for m in members):
            raise ValueError('Deployment script absent from source')
        capacity = shutil.disk_usage(parent)
        # Reserve enough for the next ordinary database backup as well as source.
        backups = parent / 'logs' / 'backups'
        reserve = 0
        if backups.exists():
            plain_path(backups)
            candidates = [p for p in backups.iterdir() if re.fullmatch(r'pre-migrate-\d{8}T\d{6}Z\.dump', p.name) and not p.is_symlink() and p.is_file()]
            if candidates:
                reserve = max(candidates, key=lambda p: p.stat().st_mtime).stat().st_size * 1.5
        if capacity.free - sum(m.size for m in members) - reserve < max(10 * 1024**3, capacity.total * .15):
            raise ValueError('Source staging capacity gate failed')
        stage.mkdir(mode=0o700)
        try:
            # Explicit regular-file extraction is compatible with Python 3.10;
            # never apply archive ownership, links, devices or special modes.
            for member in members:
                destination = stage.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as reader, destination.open('xb') as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    destination.chmod(member.mode & 0o777)
        except BaseException:
            shutil.rmtree(stage)
            raise
    had_app, had_previous = app.exists(), previous.exists()
    try:
        if had_previous:
            previous.rename(retired)
        if had_app:
            app.rename(previous)
        stage.rename(app)
    except BaseException:
        if had_app and previous.exists() and not app.exists():
            previous.rename(app)
        if had_previous and retired.exists():
            retired.rename(previous)
        if stage.exists():
            shutil.rmtree(stage)
        raise
    if had_app:
        identity = previous.stat()
        record.write_text(json.dumps([identity.st_dev, identity.st_ino]))
        record.chmod(0o600)
    if retired.exists():
        # Exact, identity-checked old source only. rmtree does not follow tree
        # symlinks; no recursive chmod/chown and no business paths are visited.
        shutil.rmtree(retired)
    archive.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', required=True)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    stage_source(args.app_dir, args.archive, args.sha256)
    print('Source staged; previous source retained for rollback')


if __name__ == '__main__':
    main()
