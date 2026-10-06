"""Copy kiosk sources while retaining the destination's local runtime state."""
import argparse
from pathlib import Path
import shutil


def copy_package(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        return
    if source in destination.parents:
        raise ValueError('Install destination must be outside the source directory')

    def excluded(directory, names):
        ignored = {name for name in names if name in {'.venv', '.review-backups', '.git',
                                                     '__pycache__', 'review.patch', 'kiosk.log'}}
        if Path(directory) == source:
            if (destination / 'kiosk.ini').exists():
                ignored.add('kiosk.ini')
        if Path(directory) == source / 'assets':
            ignored.add('img_cache')
        return ignored

    shutil.copytree(source, destination, ignore=excluded, dirs_exist_ok=True)
    # An unpacked source folder may have private permissions; the service user
    # needs to traverse its installation directory.
    destination.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    try:
        copy_package(args.source, args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
