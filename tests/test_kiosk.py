"""Regression checks that never contact the host, print, reboot, or edit /boot."""
from datetime import datetime
import logging
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cups
import requests
import serial
from PIL import Image
import kiosk_animated_label as animation
import kiosk_bcr
import kiosk_boot_config as boot
import kiosk_config
import kiosk_main
import kiosk_report as report
import kiosk_service as service
import kiosk_utils as utils

ROOT = Path(__file__).resolve().parents[1]


def response(status=200, content_type='application/pdf', content=b'%PDF-test'):
    result = Mock(status_code=status, headers={'Content-Type': content_type}, content=content)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class ConfigTests(unittest.TestCase):
    def test_installed_configuration(self):
        config = kiosk_config.read_config(ROOT / 'kiosk.ini')
        self.assertIsNotNone(config)
        self.assertEqual(config['assets_loader'], str(ROOT / 'assets'))
        self.assertIn('button_reset_to_default_time_ms', config)
        for key, value in config.items():
            if key.startswith('animated_icon_') and isinstance(value, str):
                self.assertTrue((Path(config['assets_loader']) / value).is_file())

    def test_defaults_and_whitespace(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'custom.ini'
            path.write_text('[INTERFACE]\nlanguages = LAT, ENG, RUS\n')
            config = kiosk_config.read_config(path)
            self.assertEqual(config['languages'], ['LAT', 'ENG', 'RUS'])
            self.assertEqual(config['working_hours'], ['7:30', '19:00'])
            self.assertEqual(config['assets_loader'], str(Path(folder) / 'assets'))

    def test_invalid_config_returns_none(self):
        for content in ('[INTERFACE]\ndefault_language_index=9',
                        '[INTERFACE]\nanimated_icon_delay=bad',
                        '[BARCODE]\nbc_regex=[',
                        '[REPORT]\nprinters=this is invalid',
                        '[INTERFACE]\nworking_hours=7,19',
                        '[REPORT]\nbutton_printer_reset=9'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'kiosk.ini'
                path.write_text(content)
                self.assertIsNone(kiosk_config.read_config(path))

    def test_literal_percent_in_url(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.ini'
            path.write_text('[REPORT]\nurl=http://host/?HASH=%23{}\n')
            self.assertEqual(kiosk_config.read_config(path)['url'], 'http://host/?HASH=%23{}')


class UtilityTests(unittest.TestCase):
    def test_failed_watchdog_is_inactive(self):
        with patch('builtins.open', side_effect=OSError('missing watchdog')):
            watchdog = utils.WatchDog('/dev/missing')
        self.assertFalse(watchdog.pat())
        self.assertFalse(watchdog.stop())

    def test_watchdog_stops_and_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'watchdog'
            watchdog = utils.WatchDog(path)
            self.assertTrue(watchdog.pat())
            self.assertTrue(watchdog.stop())
            self.assertEqual(path.read_text(), '1\nV\n')
            self.assertFalse(watchdog.pat())

    def test_weekdays_and_overnight_shifts(self):
        self.assertTrue(utils.is_working_time(datetime(2026, 10, 2, 10), '7:30', '19:00'))
        self.assertFalse(utils.is_working_time(datetime(2026, 10, 3, 10), '7:30', '19:00'))
        self.assertTrue(utils.is_working_time(datetime(2026, 10, 3, 1), '22:00', '06:00'))
        self.assertFalse(utils.is_working_time(datetime(2026, 10, 4, 1), '22:00', '06:00'))
        self.assertIsInstance(utils.is_working_time('10:00'), bool)

    def test_safe_pdf_filename_and_page_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report; touch INJECTED.pdf'
            with Image.new('RGB', (20, 20), 'white') as image:
                image.save(path, 'PDF')
            self.assertEqual(utils.get_numpages_from_pdf(path), 1)
            self.assertFalse((Path(folder) / 'INJECTED.pdf').exists())

    def test_brightness_base_device_and_file_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / 'panel'
            device.mkdir()
            (device / 'max_brightness').write_text('100')
            (device / 'brightness').write_text('0')
            for path in (folder, device, device / 'brightness'):
                self.assertTrue(utils.set_brightness(255, path))
                self.assertEqual((device / 'brightness').read_text(), '100')
            self.assertTrue(utils.set_brightness(-1, device))
            self.assertEqual((device / 'brightness').read_text(), '0')

    def test_missing_backlight_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(utils.set_brightness(100, folder))

    def test_dpms_arguments_and_failures(self):
        with patch.object(utils.subprocess, 'run') as run:
            self.assertTrue(utils.set_screen_dpms(15))
            self.assertEqual(run.call_args.args[0], ['xset', 'dpms', '15', '15', '15'])
            run.side_effect = FileNotFoundError()
            self.assertFalse(utils.set_screen_dpms(15))

    def test_host_timeout_and_status(self):
        with patch.object(utils.requests, 'get', side_effect=requests.Timeout()):
            self.assertFalse(utils.host_connection_ok('http://host'))
        result = response(status=500)
        result.text = 'OK'
        with patch.object(utils.requests, 'get', return_value=result):
            self.assertFalse(utils.host_connection_ok('http://host'))


class ReportTests(unittest.TestCase):
    def test_connection_runtime_error(self):
        with patch.object(report.cups, 'Connection', side_effect=RuntimeError('offline')):
            self.assertIsNone(report.connect_to_cups())

    def test_download_timeout_has_consistent_result(self):
        with patch.object(report.requests, 'get', side_effect=requests.ReadTimeout()):
            self.assertEqual(report.get_report_from_host('http://host'), [None, None])

    def test_pdf_content_type_parameters(self):
        with patch.object(report.requests, 'get', return_value=response(content_type='application/pdf; charset=binary')):
            status, path = report.get_report_from_host('http://host')
        try:
            self.assertEqual(status, 200)
            self.assertEqual(Path(path).read_bytes(), b'%PDF-test')
        finally:
            os.unlink(path)

    def test_non_pdf_and_unready_responses(self):
        for status, mime in ((200, 'text/html'), (409, 'application/pdf'), (500, 'text/html')):
            with patch.object(report.requests, 'get', return_value=response(status, mime)):
                self.assertEqual(report.get_report_from_host('http://host'), [status, None])

    def test_write_error_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.pdf'
            path.touch()
            stream = Mock(name=str(path))
            stream.name = str(path)
            stream.__enter__ = Mock(return_value=stream)
            stream.__exit__ = Mock(return_value=False)
            stream.write.side_effect = OSError('disk full')
            with patch.object(report.requests, 'get', return_value=response()), \
                    patch.object(report.tempfile, 'NamedTemporaryFile', return_value=stream):
                self.assertEqual(report.get_report_from_host('http://host'), [None, None])
            self.assertFalse(path.exists())

    def test_no_matching_printer_or_ppd(self):
        conn = Mock()
        available = {'usb://HP': {'device-make-and-model': 'HP LaserJet'}}
        self.assertFalse(report.add_printer(conn, {'Canon': 'model'}, available)[0])
        conn.getPPDs.return_value = {}
        self.assertFalse(report.add_printer(conn, {'HP': 'model'}, available)[0])
        conn.addPrinter.assert_not_called()

    def test_printer_install_returns_true_and_keeps_other_queues(self):
        conn = Mock()
        conn.getDevices.return_value = {'usb://HP': {'device-make-and-model': 'HP LaserJet'}}
        conn.getPrinters.return_value = {'other': {'device-uri': 'usb://Other'}}
        conn.getDefault.return_value = 'other'
        conn.getPPDs.return_value = {'hp.ppd': {}}
        config = {'include_schemes': ['usb'], 'printers': {'HP': 'HP model'}}
        self.assertTrue(report.init_printer(conn, config, Queue()))
        conn.deletePrinter.assert_not_called()
        conn.printTestPage.assert_not_called()
        conn.setDefault.assert_called_once_with('HP_model')

    def test_failed_install_returns_false(self):
        conn = Mock()
        conn.getDevices.return_value = {'usb://Other': {}}
        conn.getPrinters.return_value = {}
        conn.getDefault.return_value = None
        self.assertFalse(report.init_printer(conn, {'include_schemes': ['usb'], 'printers': {'HP': 'model'}}, Queue()))

    def test_printer_init_preserves_new_test_page_jobs(self):
        conn = Mock()
        conn.getDevices.return_value = {'usb://HP': {}}
        conn.getPrinters.return_value = {'HP': {'device-uri': 'usb://HP'}}
        conn.getDefault.return_value = 'HP'
        self.assertTrue(report.init_printer(conn, {'include_schemes': ['usb'], 'printers': {}}, Queue()))
        conn.cancelAllJobs.assert_not_called()

    def test_print_uses_default_and_preserves_file_for_caller(self):
        conn = Mock()
        conn.getPrinters.return_value = {'other': {}, 'default': {}}
        conn.getDefault.return_value = 'default'
        conn.printFile.return_value = 42
        with tempfile.NamedTemporaryFile() as stream:
            self.assertEqual(report.print_report(conn, stream.name), 42)
            self.assertTrue(Path(stream.name).exists())
        self.assertEqual(conn.printFile.call_args.args[0], 'default')

    def test_print_failure_and_missing_default(self):
        conn = Mock()
        conn.getPrinters.return_value = {'default': {}}
        conn.getDefault.return_value = 'default'
        conn.printFile.side_effect = cups.IPPError(1, 'offline')
        self.assertIsNone(report.print_report(conn, 'report.pdf'))
        conn.getDefault.return_value = None
        self.assertIsNone(report.print_report(conn, 'report.pdf'))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = kiosk_config.read_config(ROOT / 'kiosk.ini')
        self.config['report_delay'] = 0
        self.queue = Queue()
        self.sound = patch.object(utils, 'speak_status').start()
        self.sleep = patch.object(service.time, 'sleep').start()
        service.lang = (1, 'ENG')
        service.conn = Mock()

    def tearDown(self):
        patch.stopall()

    def test_empty_and_trailing_junk_barcodes_rejected(self):
        with patch.object(report, 'get_report_from_host') as download:
            for barcode in ('', '1234567#1234JUNK', '1234567#123456'):
                self.assertFalse(service.bc_callback(barcode, self.config, self.queue))
            download.assert_not_called()

    def test_network_failure_and_non_pdf_are_nonfatal(self):
        for result in ([None, None], [200, None]):
            with patch.object(report, 'get_report_from_host', return_value=result), \
                    patch.object(report, 'print_report') as printing:
                self.assertFalse(service.bc_callback('1234567#1234', self.config, self.queue))
                printing.assert_not_called()

    def test_unready_report_message(self):
        with patch.object(report, 'get_report_from_host', return_value=[409, None]):
            self.assertFalse(service.bc_callback('1234567#1234', self.config, self.queue))
        self.assertIn('\n', self.queue.get_nowait().ticket_value)

    def test_pdf_cleanup_on_success_failure_or_invalid_pdf(self):
        for job_id, pdf_error in ((42, None), (None, None), (42, ValueError('invalid PDF'))):
            with self.subTest(job_id=job_id, pdf_error=pdf_error), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'report.pdf'
                path.write_bytes(b'%PDF-test')
                with patch.object(report, 'get_report_from_host', return_value=[200, str(path)]) as download, \
                        patch.object(utils, 'get_numpages_from_pdf', return_value=2, side_effect=pdf_error), \
                        patch.object(report, 'print_report', return_value=job_id):
                    success = service.bc_callback(']1234567#1234', self.config, self.queue)
                self.assertEqual(success, job_id is not None and pdf_error is None)
                self.assertFalse(path.exists())
                self.assertIn('1234567%231234', download.call_args.args[0])

    def test_worker_already_stopped_does_not_touch_hardware(self):
        stop = threading.Event()
        stop.set()
        with patch.object(report, 'connect_to_cups') as connect:
            service.service_thread(stop, config=self.config, queue_from_gui=Queue(), queue_to_gui=Queue())
        connect.assert_not_called()

    def test_ethernet_read_failure_is_nonfatal(self):
        with patch.object(service.Path, 'read_text', side_effect=OSError()):
            self.assertEqual(service.ethernet_speed(), 'unknown')


class BarcodeTests(unittest.TestCase):
    def test_start_failure_and_disconnection(self):
        reader = kiosk_bcr.BarcodeReader()
        with patch.object(kiosk_bcr.serial, 'Serial', side_effect=serial.SerialException('offline')):
            reader.start()
        self.assertFalse(reader.running)
        reader.next()
        connection = Mock()
        type(connection).in_waiting = unittest.mock.PropertyMock(side_effect=serial.SerialException('unplugged'))
        reader.serial_connection = connection
        reader.running = True
        reader.next()
        self.assertFalse(reader.running)
        connection.close.assert_called_once()

    def test_bad_encoding_does_not_stop_reader(self):
        callback = Mock()
        reader = kiosk_bcr.BarcodeReader(callback=callback)
        reader.serial_connection = Mock(in_waiting=1)
        reader.serial_connection.readline.return_value = b'\xff\n'
        reader.running = True
        reader.next()
        self.assertTrue(reader.running)
        callback.assert_not_called()

    def test_bounce_uses_monotonic_clock(self):
        callback = Mock()
        reader = kiosk_bcr.BarcodeReader(callback=callback, bounce=2)
        reader.serial_connection = Mock(in_waiting=1)
        reader.serial_connection.readline.return_value = b'1234567#1234\n'
        reader.running = True
        with patch.object(kiosk_bcr.time, 'monotonic', side_effect=[10, 11, 13, 13]):
            reader.next()
            reader.next()
            reader.next()
        self.assertEqual(callback.call_count, 2)


class AnimationAndButtonTests(unittest.TestCase):
    def test_gui_honors_custom_config_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'custom.ini'
            path.write_text('[INTERFACE]\nscreen_width=640\n')
            app = Mock(worker_failed=False)
            with patch.object(sys, 'argv', ['kiosk_main.py', '-c', str(path)]), \
                    patch.object(kiosk_main, 'load_gif_frames', return_value={}), \
                    patch.object(kiosk_main, 'KioskApp', return_value=app) as factory, \
                    patch.object(service, 'service_thread'), \
                    patch.object(kiosk_main.signal, 'signal'), \
                    patch.object(kiosk_main.logging, 'basicConfig'):
                self.assertEqual(kiosk_main.main(), 0)
            self.assertEqual(factory.call_args.kwargs['config']['screen_width'], 640)
            self.assertEqual(factory.call_args.kwargs['config']['assets_loader'], str(Path(folder) / 'assets'))

    def test_worker_failure_exits_for_systemd_restart(self):
        app = Mock()
        app.slave_thread.is_alive.return_value = False
        app.stop_event.is_set.return_value = False
        kiosk_main.KioskApp.check_queue(app)
        self.assertTrue(app.worker_failed)
        app.quit_app.assert_called_once()
        app.after.assert_not_called()

    def test_legacy_pickle_is_not_loaded_and_source_changes_are_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / 'img_cache').mkdir()
            (source / 'img_cache' / 'icon.gif.pkl').write_bytes(b'invalid pickle')
            with Image.new('RGB', (10, 10), 'red') as image:
                image.save(source / 'icon.gif')
            cache = animation.load_gif_frames(source / 'img_cache', 20, 30)
            self.assertEqual(cache['icon.gif'][0].size, (20, 30))
            with Image.new('RGB', (10, 10), 'blue') as image:
                image.save(source / 'icon.gif')
            self.assertEqual(animation.load_gif_frames(source)['icon.gif'][0].getpixel((0, 0)), (0, 0, 255, 255))

    def test_restarting_animation_resets_cycle_count_and_cancels_timer(self):
        label = Mock()
        label.frames = ['frame']
        label.current_frame = 8
        label._curr_cycle = 9
        label._after_id = 'old'
        label._is_animating = True
        label.delay = 50
        label.stop_animation.side_effect = lambda: animation.AnimatedGifLabelAcc.stop_animation(label)
        label._animate.side_effect = lambda: animation.AnimatedGifLabelAcc._animate(label)
        animation.AnimatedGifLabelAcc.start_animation(label, 2)
        label.after_cancel.assert_called_once_with('old')
        self.assertEqual(label._curr_cycle, 1)
        self.assertTrue(label._is_animating)
        animation.AnimatedGifLabelAcc._animate(label)
        self.assertFalse(label._is_animating)

    def test_disable_buttons_uses_instance_queue_and_keeps_all_disabled(self):
        frame = Mock()
        frame.buttons = [Mock(), Mock(), Mock()]
        frame.config = {'languages': ['LAT', 'ENG', 'RUS']}
        frame.queue_from_gui = Queue()
        kiosk_main.MainFrame.disable_buttons(frame, 1)
        self.assertEqual(frame.queue_from_gui.get_nowait(), (1, 'ENG'))
        for button in frame.buttons:
            button.state_disable.assert_called_once()
        button = Mock()
        kiosk_main.KioskButton.idle(button)
        self.assertNotIn('state', button.configure.call_args.kwargs)

    def test_debounce_schedules_callback(self):
        frame = Mock(selected_button=1)
        kiosk_main.MainFrame.debounce_buttons(frame, 1000)
        frame.enable_buttons.assert_not_called()
        frame.after.assert_called_once_with(1000, frame.enable_buttons, 1)


class SetupTests(unittest.TestCase):
    def test_missing_ethernet_has_bounded_wait(self):
        env = dict(os.environ, INTERFACE='kiosk-review-nonexistent', TOTAL_TIMEOUT='0')
        result = subprocess.run(['bash', str(ROOT / 'wait-for-ethernet.sh')],
                                env=env, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'Ethernet unavailable', result.stdout)

    def test_cmdline_idempotent_and_replaces_conflicting_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cmdline.txt'
            path.write_text('console=tty1 consoleblank=60 fbcon=rotate:2 root=PARTUUID=test video=HDMI-A-1:1920x1080\n')
            path.chmod(0o640)
            boot.update_file(path, boot.cmdline_text(path))
            first = path.read_text()
            boot.update_file(path, boot.cmdline_text(path))
            self.assertEqual(first, path.read_text())
            self.assertEqual(first.count('consoleblank='), 1)
            self.assertIn('root=PARTUUID=test', first)
            self.assertIn('video=HDMI-A-1:1920x1080', first)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(len(list(Path(folder).glob('*.bak'))), 1)

    def test_overlay_idempotent_and_preserves_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.txt'
            path.write_text('[all]\ndtoverlay=vc4-kms-v3d\n[pi4]\nother=1\n')
            boot.update_file(path, boot.config_text(path))
            self.assertEqual(path.read_text().count('dtoverlay=vc4-kms-dsi-7inch'), 1)
            self.assertEqual(boot.config_text(path), path.read_text())
            self.assertIn('[pi4]\nother=1', path.read_text())

    def test_bad_legacy_config_does_not_modify_cmdline(self):
        with tempfile.TemporaryDirectory() as folder:
            config, cmdline = Path(folder) / 'config.txt', Path(folder) / 'cmdline.txt'
            config.write_text('[all]\n')
            cmdline.write_text('root=test\n')
            env = dict(os.environ, CMDLINE_FILE=str(cmdline))
            result = subprocess.run(['bash', str(ROOT / 'update_config.sh'), str(config)],
                                    env=env, capture_output=True, cwd='/tmp')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(cmdline.read_text(), 'root=test\n')
            self.assertEqual(config.read_text(), '[all]\n')

    def test_boot_wrappers_work_from_other_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config file.txt'
            path.write_text('dtoverlay=vc4-kms-v3d\n')
            for _ in range(2):
                subprocess.run(['bash', str(ROOT / 'update_config_txt.sh'), str(path)],
                               check=True, capture_output=True, cwd='/tmp')
            self.assertEqual(path.read_text().count('dtoverlay=vc4-kms-dsi-7inch'), 1)
            cmdline = Path(folder) / 'cmdline.txt'
            cmdline.write_text('root=test\n')
            for _ in range(2):
                subprocess.run(['bash', str(ROOT / 'update_cmdline.sh'), str(cmdline)],
                               check=True, capture_output=True, cwd='/tmp')
            self.assertEqual(cmdline.read_text().count('consoleblank='), 1)

    def test_cups_config_handles_commented_defaults_and_is_repeatable(self):
        for text in ('# BrowseRemoteProtocols dnssd\n', 'BrowseRemoteProtocols dnssd cups\n',
                     'BrowseRemoteProtocols none\n', 'BrowseRemoteProtocols dnssd\nBrowseRemoteProtocols cups\n'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'cups-browsed.conf'
                path.write_text(text)
                path.chmod(0o640)
                for _ in range(2):
                    subprocess.run(['bash', str(ROOT / 'change_cups-browsed.sh'), str(path)],
                                   check=True, capture_output=True)
                self.assertEqual(path.read_text().splitlines().count('BrowseRemoteProtocols none'), 1)
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_log_file_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'logs with spaces' / 'kiosk.log'
            subprocess.run(['bash', str(ROOT / 'make_logdirs.sh'), str(path)], check=True, capture_output=True)
            self.assertTrue(path.is_file())

    def test_every_shell_script_parses(self):
        for path in ROOT.glob('*.sh'):
            with self.subTest(path=path.name):
                subprocess.run(['bash', '-n', str(path)], check=True, capture_output=True)


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    unittest.main()
