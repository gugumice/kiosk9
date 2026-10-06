"""Pi 4/5 provisioning fixtures: no packages, services or live boot files changed."""
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kiosk_boot_config as boot
import kiosk_install
import kiosk_platform


class PlatformTests(unittest.TestCase):
    def test_pi4_and_pi5_models(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / 'model'
            for board in ('4', '5'):
                model.write_bytes(f'Raspberry Pi {board} Model B Rev 1.1\x00'.encode())
                self.assertEqual(kiosk_platform.board_number(model), board)

    def test_other_boards_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / 'model'
            for value in ('Raspberry Pi 3 Model B', 'Raspberry Pi 400 Rev 1.0', 'PC'):
                model.write_text(value)
                with self.assertRaises(ValueError):
                    kiosk_platform.board_number(model)

    def test_modern_and_legacy_boot_layouts(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder) / 'boot'
            modern = legacy / 'firmware'
            modern.mkdir(parents=True)
            candidates = (modern, legacy)
            with self.assertRaises(ValueError):
                kiosk_platform.boot_directory(candidates)
            (legacy / 'config.txt').write_text('dtoverlay=vc4-kms-v3d\n')
            (legacy / 'cmdline.txt').write_text('root=test\n')
            self.assertEqual(kiosk_platform.boot_directory(candidates), legacy)
            (modern / 'config.txt').write_text('dtoverlay=vc4-kms-v3d\n')
            # Never mix config.txt from one layout with cmdline.txt from another.
            self.assertEqual(kiosk_platform.boot_directory(candidates), legacy)
            (modern / 'cmdline.txt').write_text('root=test\n')
            self.assertEqual(kiosk_platform.boot_directory(candidates), modern)


class DisplayTests(unittest.TestCase):
    def test_other_board_sections_do_not_hide_missing_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.txt'
            for board, other in (('4', '5'), ('5', '4')):
                original = (f'[pi{other}]\ndtoverlay=vc4-kms-v3d\n'
                            'dtoverlay=vc4-kms-dsi-7inch\n[cm4]\notg_mode=1\n')
                path.write_text(original)
                updated = boot.config_text(path, board=board)
                self.assertTrue(updated.startswith(original))
                self.assertTrue(updated.endswith('[all]\ndtoverlay=vc4-kms-v3d\n'
                                                 'dtoverlay=vc4-kms-dsi-7inch\n'))
                path.write_text(updated)
                self.assertEqual(boot.config_text(path, board=board), updated)

    def test_existing_overlay_parameters_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.txt'
            original = ('[pi4]\ndtoverlay=vc4-kms-v3d,cma-256 # GPU\n'
                        'dtoverlay=vc4-kms-dsi-7inch,invx # touch\n[all]\n')
            path.write_text(original)
            self.assertEqual(boot.config_text(path, board='4'), original)

    def test_missing_kms_is_added_for_pi4(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.txt'
            path.write_text('[all]\ndtoverlay=vc4-kms-dsi-7inch\n')
            updated = boot.config_text(path, board='4')
            self.assertIn('dtoverlay=vc4-kms-v3d\n', updated)
            self.assertEqual(updated.count('dtoverlay=vc4-kms-dsi-7inch'), 1)

    def test_preflight_does_not_write_or_back_up(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.txt'
            original = '[pi5]\ndtoverlay=vc4-kms-v3d\n'
            path.write_text(original)
            subprocess.run([sys.executable, str(ROOT / 'kiosk_boot_config.py'),
                            'config', str(path), '--board', '4', '--check'],
                           check=True, capture_output=True)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_legacy_wrapper_uses_cmdline_beside_config(self):
        with tempfile.TemporaryDirectory() as folder:
            config, cmdline = Path(folder) / 'config.txt', Path(folder) / 'cmdline.txt'
            config.write_text('dtoverlay=vc4-kms-v3d\n')
            cmdline.write_text('root=test video=HDMI-A-1:1920x1080\n')
            env = dict(os.environ)
            env.pop('CMDLINE_FILE', None)
            subprocess.run(['bash', str(ROOT / 'update_config.sh'), str(config)],
                           env=env, check=True, capture_output=True, cwd='/tmp')
            self.assertIn('consoleblank=0', cmdline.read_text())
            self.assertIn('video=HDMI-A-1:1920x1080', cmdline.read_text())


class CopyTests(unittest.TestCase):
    def test_install_preserves_local_state_and_excludes_foreign_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'target'
            source.mkdir()
            target.mkdir()
            for name in ('kiosk.ini', 'kiosk.log', 'kiosk_main.py'):
                (source / name).write_text('source')
                (target / name).write_text('local')
            for name in ('.venv', '.review-backups', '__pycache__', 'assets/img_cache'):
                (source / name).mkdir(parents=True)
                (source / name / 'foreign').write_text('do not copy')
            (source / 'assets' / 'icon.gif').write_bytes(b'asset')
            kiosk_install.copy_package(source, target)
            kiosk_install.copy_package(source, target)
            self.assertEqual((target / 'kiosk.ini').read_text(), 'local')
            self.assertEqual((target / 'kiosk.log').read_text(), 'local')
            self.assertEqual((target / 'kiosk_main.py').read_text(), 'source')
            self.assertEqual((target / 'assets' / 'icon.gif').read_bytes(), b'asset')
            for name in ('.venv', '.review-backups', '__pycache__', 'assets/img_cache'):
                self.assertFalse((target / name).exists())

    def test_fresh_install_gets_config_and_retains_existing_native_venv(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'target'
            source.mkdir()
            (source / 'kiosk.ini').write_text('configuration')
            (target / '.venv').mkdir(parents=True)
            (target / '.venv' / 'native').write_text('local dependency')
            kiosk_install.copy_package(source, target)
            self.assertEqual((target / 'kiosk.ini').read_text(), 'configuration')
            self.assertEqual((target / '.venv' / 'native').read_text(), 'local dependency')

    def test_in_place_install_is_unchanged_and_nested_destination_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / 'kiosk.ini').write_text('local')
            kiosk_install.copy_package(source, source)
            self.assertEqual((source / 'kiosk.ini').read_text(), 'local')
            with self.assertRaises(ValueError):
                kiosk_install.copy_package(source, source / 'nested')
            self.assertFalse((source / 'nested').exists())


class PreflightTests(unittest.TestCase):
    def test_pi4_preflight_on_both_layouts_never_changes_boot_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / 'bin'
            tools.mkdir()
            python = tools / 'python3'
            python.write_text('#!/bin/bash\n'
                              'if [[ $1 == */kiosk_platform.py ]]; then\n'
                              '  case $2 in\n'
                              '    board) echo 4;;\n'
                              '    boot-dir) echo "$FIXTURE_BOOT_DIR";;\n'
                              '  esac\n'
                              'else\n'
                              f'  exec {shlex.quote(sys.executable)} "$@"\n'
                              'fi\n')
            python.chmod(0o755)
            raspi = tools / 'raspi-config'
            raspi.write_text('#!/bin/sh\nexit 0\n')
            raspi.chmod(0o755)
            for layout in ('boot', 'boot/firmware'):
                boot_dir = root / layout
                boot_dir.mkdir(parents=True, exist_ok=True)
                config, cmdline = boot_dir / 'config.txt', boot_dir / 'cmdline.txt'
                original = '[pi5]\ndtoverlay=vc4-kms-v3d\n'
                config.write_text(original)
                cmdline.write_text('root=PARTUUID=fixture\n')
                env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                           KIOSK_USER=pwd.getpwuid(os.getuid()).pw_name,
                           FIXTURE_BOOT_DIR=str(boot_dir))
                result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--check'],
                                        env=env, cwd='/tmp', capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Raspberry Pi 4', result.stdout)
                self.assertIn(str(boot_dir), result.stdout)
                self.assertEqual(config.read_text(), original)
                self.assertEqual(cmdline.read_text(), 'root=PARTUUID=fixture\n')
                self.assertFalse(list(boot_dir.glob('*.bak')))


if __name__ == '__main__':
    unittest.main()
