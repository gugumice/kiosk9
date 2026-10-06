"""Read-only Raspberry Pi detection shared by provisioning and first boot."""
import argparse
from pathlib import Path
import re


def board_number(model_file='/proc/device-tree/model'):
    model = Path(model_file).read_text().rstrip('\x00\n')
    match = re.match(r'^Raspberry Pi ([45]) Model B\b', model)
    if not match:
        raise ValueError(f'Expected Raspberry Pi 4 or 5 Model B; found {model!r}')
    return match.group(1)


def boot_directory(candidates=('/boot/firmware', '/boot')):
    for candidate in candidates:
        directory = Path(candidate)
        if all((directory / name).is_file() for name in ('config.txt', 'cmdline.txt')):
            return directory
    raise ValueError('Cannot find config.txt and cmdline.txt together in /boot/firmware or /boot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('board', 'boot-dir'))
    args = parser.parse_args()
    try:
        print(board_number() if args.kind == 'board' else boot_directory())
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
