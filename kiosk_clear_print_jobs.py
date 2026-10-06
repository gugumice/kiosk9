#!/usr/bin/env python3
"""Remove old CUPS spool jobs before the scheduler starts, once per boot.

Do not run against a live scheduler. Printer definitions, PPDs, and printer
caches are retained. Test pages submitted after this service finishes survive
later kiosk/CUPS service restarts because the systemd unit remains active.
"""
import argparse
import logging
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile

JOB_FILE = re.compile(r'(?:c[0-9]{5,}|d[0-9]{5,}-[0-9]{3,})(?:\.[NO])?')
CACHE_FILES = ('job.cache', 'job.cache.O', 'job.cache.N')


def cups_directories(config_path):
    directories = {'requestroot': Path('/var/spool/cups'), 'cachedir': Path('/var/cache/cups')}
    for line in Path(config_path).read_text(encoding='utf-8').splitlines():
        fields = shlex.split(line, comments=True)
        if fields and fields[0].lower() in directories:
            if len(fields) != 2 or not Path(fields[1]).is_absolute():
                raise ValueError(f'Invalid {fields[0]} in {config_path}')
            directories[fields[0].lower()] = Path(fields[1])
    return directories['requestroot'], directories['cachedir']


def scheduler_running(proc_root=Path('/proc')):
    for path in proc_root.glob('[0-9]*/comm'):
        try:
            if path.read_text().strip() == 'cupsd':
                return True
        except FileNotFoundError:
            continue  # The process exited during enumeration.
    return False


def regular_file(path):
    # Refuse links and directories rather than following a spool entry elsewhere.
    return stat.S_ISREG(path.lstat().st_mode)


def empty_job_cache(path, next_job_id):
    """Keep monotonically increasing job IDs without retaining queued jobs."""
    metadata = path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.kiosk-job-cache-', delete=False) as stream:
            temporary = stream.name
            stream.write(f'# Jobs cleared at boot by kiosk\nNextJobId {next_job_id}\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        if os.geteuid() == 0:
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def clear_spool(spool_dir, cache_dir, dry_run=False):
    spool_dir, cache_dir = Path(spool_dir), Path(cache_dir)
    # Validate all targets before removing any files. CUPS must be stopped.
    jobs = []
    if spool_dir.exists():
        for path in spool_dir.iterdir():
            if JOB_FILE.fullmatch(path.name):
                if not regular_file(path):
                    raise ValueError(f'Refusing nonregular job file: {path}')
                jobs.append(path)
    caches = []
    next_job_id = 1
    for filename in CACHE_FILES:
        path = cache_dir / filename
        if path.exists() or path.is_symlink():
            if not regular_file(path):
                raise ValueError(f'Refusing nonregular job cache: {path}')
            caches.append(path)
            for line in path.read_text(encoding='utf-8').splitlines():
                match = re.fullmatch(r'\s*NextJobId\s+([0-9]+)\s*', line)
                if match:
                    next_job_id = max(next_job_id, int(match[1]))
    for path in jobs:
        job_id = int(re.match(r'[cd]([0-9]+)', path.name)[1])
        next_job_id = max(next_job_id, job_id + 1)
    if dry_run:
        logging.info('Dry run: %d job files and %d job caches would be cleared', len(jobs), len(caches))
        return len(jobs)
    for path in jobs:
        path.unlink()
    # Empty both normal and recovery caches so old jobs cannot be restored.
    for path in caches:
        empty_job_cache(path, next_job_id)
    logging.info('Cleared %d previous print-job files; next job ID %d', len(jobs), next_job_id)
    return len(jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cups-files', default='/etc/cups/cups-files.conf')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        if not args.dry_run:
            if os.geteuid() != 0:
                raise PermissionError('Boot cleanup must run as root')
            if scheduler_running():
                raise RuntimeError('CUPS is running; refusing to modify its spool')
        spool, cache = cups_directories(args.cups_files)
        clear_spool(spool, cache, dry_run=args.dry_run)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'Print-job cleanup failed: {exc}\n')


if __name__ == '__main__':
    main()
