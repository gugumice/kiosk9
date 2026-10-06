"""Offline fixtures for clearing every printer's old jobs before CUPS starts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kiosk_clear_print_jobs as cleanup
import kiosk_report as report

ROOT = Path(__file__).resolve().parents[1]


class PrintStartupTests(unittest.TestCase):
    def test_all_job_files_and_recovery_files_cleared_preserving_printer_files(self):
        with tempfile.TemporaryDirectory() as folder:
            spool, cache = Path(folder) / 'spool', Path(folder) / 'cache'
            spool.mkdir()
            cache.mkdir()
            jobs = ('c00001', 'd00001-001', 'c00002.N', 'd00002-002', 'c100001.O', 'd100001-1000')
            for name in jobs:
                (spool / name).write_text('old job')
            for name in ('printers.conf', 'printer.ppd', 'README', 'control', 'd00001-invalid'):
                (spool / name).write_text('keep')
            (spool / 'tmp').mkdir()
            (spool / 'tmp' / 'keep').write_text('unrelated')
            (cache / 'HP.data').write_text('printer cache')
            for name in cleanup.CACHE_FILES:
                (cache / name).write_text('NextJobId 10\n<Job 1>\nName Test Page\n</Job>\n')
                (cache / name).chmod(0o640)
            self.assertEqual(cleanup.clear_spool(spool, cache), len(jobs))
            for name in jobs:
                self.assertFalse((spool / name).exists())
            self.assertEqual((spool / 'printers.conf').read_text(), 'keep')
            self.assertEqual((spool / 'tmp' / 'keep').read_text(), 'unrelated')
            self.assertEqual((cache / 'HP.data').read_text(), 'printer cache')
            for name in cleanup.CACHE_FILES:
                self.assertIn('NextJobId 100002', (cache / name).read_text())
                self.assertNotIn('<Job', (cache / name).read_text())
                self.assertEqual((cache / name).stat().st_mode & 0o777, 0o640)

    def test_next_job_id_preserved_across_caches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'job.cache').write_text('NextJobId 100\n')
            (root / 'job.cache.O').write_text('NextJobId 200\n')
            cleanup.clear_spool(root / 'missing-spool', root)
            self.assertIn('NextJobId 200', (root / 'job.cache').read_text())

    def test_dry_run_never_modifies_spool(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'c00001').write_text('job')
            (root / 'job.cache').write_text('NextJobId 2\n<Job 1>\n')
            self.assertEqual(cleanup.clear_spool(root, root, dry_run=True), 1)
            self.assertEqual((root / 'c00001').read_text(), 'job')
            self.assertIn('<Job', (root / 'job.cache').read_text())

    def test_symlink_rejected_before_any_job_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'c00001').write_text('keep until validation completes')
            (root / 'outside').write_text('keep')
            (root / 'd00001-001').symlink_to(root / 'outside')
            with self.assertRaises(ValueError):
                cleanup.clear_spool(root, root)
            self.assertTrue((root / 'c00001').exists())
            self.assertEqual((root / 'outside').read_text(), 'keep')

    def test_configured_spool_and_cache_paths_are_used(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cups-files.conf'
            path.write_text('#RequestRoot /ignored\nRequestRoot "/custom/spool with spaces"\nCacheDir /custom/cache # note\n')
            self.assertEqual(cleanup.cups_directories(path),
                             (Path('/custom/spool with spaces'), Path('/custom/cache')))
            path.write_text('RequestRoot relative/path\n')
            with self.assertRaises(ValueError):
                cleanup.cups_directories(path)

    def test_live_scheduler_refused_before_spool_modification(self):
        with patch.object(sys, 'argv', ['kiosk_clear_print_jobs.py']), \
                patch.object(cleanup.os, 'geteuid', return_value=0), \
                patch.object(cleanup, 'scheduler_running', return_value=True), \
                patch.object(cleanup, 'clear_spool') as clear:
            with self.assertRaises(SystemExit) as exited:
                cleanup.main()
        self.assertEqual(exited.exception.code, 1)
        clear.assert_not_called()

    def test_test_page_submitted_after_cleanup_survives_printer_init(self):
        conn = Mock()
        conn.getDevices.return_value = {'usb://HP': {}}
        conn.getPrinters.return_value = {'HP': {'device-uri': 'usb://HP'}}
        conn.getDefault.return_value = 'HP'
        conn.printTestPage.return_value = 7
        self.assertEqual(report.print_report(conn), 7)
        self.assertTrue(report.init_printer(conn, {'include_schemes': ['usb'], 'printers': {}}))
        conn.cancelAllJobs.assert_not_called()
        conn.deletePrinter.assert_not_called()

    def test_systemd_covers_all_cups_activation_paths_and_runs_once(self):
        unit = (ROOT / 'kiosk-clear-print-jobs.service').read_text()
        self.assertIn('RemainAfterExit=yes', unit)
        self.assertIn('DefaultDependencies=no', unit)
        self.assertIn('Before=cups.service cups.socket cups.path', unit)
        for name in ('cups.service', 'cups.socket', 'cups.path'):
            dropin = (ROOT / 'systemd' / (name + '.d') / 'kiosk-clear-print-jobs.conf').read_text()
            self.assertIn('Requires=kiosk-clear-print-jobs.service', dropin)
            self.assertIn('After=kiosk-clear-print-jobs.service', dropin)


if __name__ == '__main__':
    unittest.main()
