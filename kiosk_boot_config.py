#!/usr/bin/env python3
"""Idempotent, backed-up edits used by the Raspberry Pi setup wrappers."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import stat
import tempfile

PARAMETERS = ('video=DSI-1:panel_orientation=right_side_up', 'fbcon=rotate:1', 'consoleblank=0')


def update_file(path, text):
    path = Path(path).resolve()
    original = path.read_text(encoding='utf-8')
    if original == text:
        print(f'Already configured: {path}')
        return
    backup = path.with_name(path.name + datetime.now().strftime('.%Y%m%d-%H%M%S-%f.bak'))
    shutil.copy2(path, backup)
    metadata = path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name + '.', delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        if os.geteuid() == 0:
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Updated: {path}; backup: {backup}')


def cmdline_text(path):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise ValueError('Kernel command line must contain one nonempty line')
    # Other monitors may have their own video= options; preserve those.
    tokens = [token for token in lines[0].split()
              if not token.startswith(('video=DSI-1:', 'fbcon=', 'consoleblank='))]
    return ' '.join(tokens + list(PARAMETERS)) + '\n'


def config_text(path, replace_kms=False):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    overlay = 'dtoverlay=vc4-kms-dsi-7inch'
    has_overlay = any(line.strip() == overlay for line in lines)
    output = []
    found = False
    for line in lines:
        if line.strip() == 'dtoverlay=vc4-kms-v3d':
            found = True
            if not replace_kms:
                output.append(line)
            if not has_overlay:
                output.append(overlay)
                has_overlay = True
        else:
            output.append(line)
    if not found and not has_overlay:
        raise ValueError('Target dtoverlay line not found in config file')
    return '\n'.join(output) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('cmdline', 'config', 'legacy'))
    parser.add_argument('path')
    parser.add_argument('--cmdline', default='/boot/firmware/cmdline.txt')
    args = parser.parse_args()
    try:
        if args.kind == 'cmdline':
            update_file(args.path, cmdline_text(args.path))
        else:
            # Compute both edits before changing either file.
            text = config_text(args.path, replace_kms=args.kind == 'legacy')
            cmdline = cmdline_text(args.cmdline) if args.kind == 'legacy' else None
            update_file(args.path, text)
            if cmdline is not None:
                update_file(args.cmdline, cmdline)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
