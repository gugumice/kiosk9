#!/usr/bin/env python3
"""Background kiosk startup, barcode processing, and printer submission."""
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty
from urllib.parse import quote, urlsplit

import kiosk_report
import kiosk_utils
from kiosk_bcr import BarcodeReader

lang = None
conn = None


def drain_queue(queue):
    while True:
        try:
            queue.get_nowait()
        except Empty:
            return


def proc_queue(msg, config):
    kiosk_utils.speak_status(os.path.join(config['assets_loader'], f'lang_{msg[1]}.wav'))


def ethernet_speed():
    try:
        speed = int(Path('/sys/class/net/eth0/speed').read_text().strip())
        return speed if speed > 0 else 'unknown'
    except (OSError, ValueError):
        return 'unknown'


def service_thread(th_ev: threading.Event, polling_int=0.5, config=None,
                   queue_from_gui=None, queue_to_gui=None):
    global lang, conn
    reader = None

    def notify(message=None, purpose=kiosk_utils.TicketPurpose.SYS, cycles=1):
        kiosk_utils.send_ticket(ticket_value=message, ticket_type=purpose,
                                ticket_animate_cycles=cycles, queue_tx=queue_to_gui)

    try:
        if th_ev.wait(1):
            return
        lang = (config['default_language_index'], config['languages'][config['default_language_index']])
        last_msg_time = time.monotonic()
        drain_queue(queue_from_gui)
        conn = None
        while not th_ev.is_set():
            conn = kiosk_report.connect_to_cups()
            if conn is not None:
                break
            notify('Error connecting to CUPS', kiosk_utils.TicketPurpose.ERR)
            if th_ev.wait(5):
                return
        if th_ev.is_set():
            return

        reset_buttons = config['button_printer_reset']
        if reset_buttons:
            names = ', '.join(config['languages'][i] for i in reset_buttons)
            kiosk_utils.speak_status(os.path.join(config['assets_loader'], 'attn.wav'))
            notify(f'<{names}> to reset printers', kiosk_utils.TicketPurpose.PRN)
            if th_ev.wait(5):
                return
            try:
                msg = queue_from_gui.get_nowait()
            except Empty:
                msg = None
            if msg is not None and msg[0] in reset_buttons:
                kiosk_report.delete_printers(conn=conn)
                notify('Resetting printers on CUPS', kiosk_utils.TicketPurpose.PRN)

        while not th_ev.is_set():
            if kiosk_report.init_printer(conn=conn, config=config, queue_to_gui=queue_to_gui):
                break
            if th_ev.wait(3):
                return
        if th_ev.is_set():
            return

        host = kiosk_utils.host_info() or ['unknown', 'unknown']
        notify(f'Service thread started\nIP: {host[0]}\nHost: {host[1]}\nWatchdog: {config["watchdog_device"]}', cycles=3)
        count = 0
        server = urlsplit(config['url_test']).netloc
        while not th_ev.is_set() and not kiosk_utils.host_connection_ok(config['url_test']):
            count += 1
            notify(f'Connection to\n{server}\nfailed, eth spd: {ethernet_speed()}\nRetrying ({count})...',
                   kiosk_utils.TicketPurpose.NET)
            if th_ev.wait(1):
                return
        if th_ev.is_set():
            return
        notify(f'Host connection OK\n{server[:18]} eth spd: {ethernet_speed()}', kiosk_utils.TicketPurpose.NET)

        reader = BarcodeReader(port=config['bc_reader_port'], baudrate=config['bc_reader_boudrate'],
                               bounce=config['bc_reader_bounce'], callback=bc_callback,
                               timeout=config['bc_timeout'], config=config, queueTX=queue_to_gui)
        reader.start()
        if reader.running:
            notify(f'Barcode reader OK\n{reader.port}', kiosk_utils.TicketPurpose.BCR)
        drain_queue(queue_from_gui)
        notify(purpose=kiosk_utils.TicketPurpose.EOT, cycles=0)
        while not th_ev.is_set():
            if not reader.running:
                notify(f'Barcode reader unavailable:\n{reader.port}\nRetrying...', kiosk_utils.TicketPurpose.BCR)
                reader.start()
                if not reader.running:
                    if th_ev.wait(5):
                        return
                    continue
                notify(f'Barcode reader OK\n{reader.port}', kiosk_utils.TicketPurpose.BCR)

            try:
                msg = queue_from_gui.get_nowait()
            except Empty:
                msg = None
            if msg is not None:
                proc_queue(msg, config)
                lang = msg
                last_msg_time = time.monotonic()
                notify(purpose=kiosk_utils.TicketPurpose.BCR)
            if (time.monotonic() > last_msg_time + config['screen_brightness_to_min'] * 60
                    and not kiosk_utils.is_working_time(start=config['working_hours'][0],
                                                       end=config['working_hours'][1], workdays=config['working_days'])):
                kiosk_utils.set_brightness(config['screen_brightness_inactive'], config['screen_brightness_path'])
                last_msg_time = time.monotonic()
            reader.next()
            th_ev.wait(polling_int)
    except Exception:
        logging.exception('Kiosk service thread stopped unexpectedly')
        notify('Service stopped\nRestart required', kiosk_utils.TicketPurpose.ERR, cycles=3)
    finally:
        if reader is not None:
            reader.stop()


def bc_callback(barcode, config, queue_to_gui):
    """Validate the complete barcode, download the PDF and submit it to CUPS."""
    selected = lang or (config['default_language_index'], config['languages'][config['default_language_index']])
    language_index, language = selected

    def sound(filename, background=False):
        kiosk_utils.speak_status(os.path.join(config['assets_loader'], filename), background=background)

    def notify(message=None, purpose=kiosk_utils.TicketPurpose.ERR, cycles=2):
        kiosk_utils.send_ticket(ticket_value=message, ticket_type=purpose,
                                ticket_animate_cycles=cycles, queue_tx=queue_to_gui)

    if barcode and not barcode[0].isnumeric():
        barcode = barcode[1:]
    if not barcode or re.fullmatch(config['bc_regex'], barcode) is None:
        sound(f'barcode_invalid{language}.wav', background=True)
        notify()
        return False

    path = None
    try:
        sound('attn.wav', background=True)
        url = config['url'].format(config['host'], quote(barcode, safe=''), quote(language, safe=''))
        status, path = kiosk_report.get_report_from_host(url, timeout=config['httpreq_timeout'])
        if status == 409:
            notify(config['report_not_ready_msg'][language_index].replace('\\', '\n'))
            sound(f'not_ready{language}.wav')
            return False
        if status != 200 or path is None:
            notify('Report download failed')
            sound('error-attn.wav')
            return False
        pages = kiosk_utils.get_numpages_from_pdf(path)
        sound(f'start_print{language}.wav')
        sound(f'NumPages_{pages}_{language}.wav' if pages < 11 else f'NumPages_10more_{language}.wav')
        notify(f'{config["report_num_pages"][language_index]}:\n{pages}', kiosk_utils.TicketPurpose.PRN)
        time.sleep(config['report_delay'])
        job_id = kiosk_report.print_report(conn=conn, tmp_file=path)
        if job_id is None:
            notify('Print submission failed')
            sound('error-attn.wav')
            return False
        notify(purpose=kiosk_utils.TicketPurpose.AOK, cycles=1)
        sound(f'end_print{language}.wav')
        return True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logging.error('Report processing failed (%s)', type(exc).__name__)
        notify('Report processing failed')
        sound('error-attn.wav')
        return False
    finally:
        if path is not None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                logging.warning('Cannot remove temporary report')
