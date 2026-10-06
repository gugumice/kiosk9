#!/usr/bin/env python3
"""Download reports and manage the kiosk's CUPS printer."""
import logging
import os
import tempfile

import cups
import requests

import kiosk_config
import kiosk_utils

CUPS_ERRORS = (cups.IPPError, RuntimeError, OSError)


def connect_to_cups():
    try:
        return cups.Connection()
    except CUPS_ERRORS as exc:
        logging.error('Failed to connect to CUPS: %s', exc)
        return None


def check_default(available, installed, default):
    return installed.get(default, {}).get('device-uri') in available


def add_printer(conn=None, allowed_printers=None, avilable_printers=None):
    """Return (success, queue name or error), including when no model matches."""
    for make, model in (allowed_printers or {}).items():
        for uri, device in (avilable_printers or {}).items():
            if not device.get('device-make-and-model', '').startswith(make):
                continue
            try:
                ppds = conn.getPPDs(ppd_make_and_model=model)
                if not ppds:
                    logging.warning('No PPD available for %s', model)
                    continue
                name = model.replace(' ', '_')
                conn.addPrinter(name=name, ppdname=next(iter(ppds)),
                                info=model, location='EGL', device=uri)
                conn.acceptJobs(name)
                conn.setPrinterShared(name, False)
                conn.setDefault(name)
                conn.enablePrinter(name)
                return True, name
            except CUPS_ERRORS as exc:
                logging.error('Failed to install printer: %s', exc)
                return False, str(exc)
    return False, 'No supported printer and matching PPD found'


def delete_printers(conn=None, printers=None):
    """Delete explicitly supplied queues, or all queues for a manual reset."""
    try:
        if printers is None:
            printers = conn.getPrinters()
        for printer in printers:
            conn.deletePrinter(printer)
            logging.info('Deleted printer: %s', printer)
        return True
    except CUPS_ERRORS as exc:
        logging.error('Failed to delete printers: %s', exc)
        return False


def init_printer(conn=None, config=None, queue_to_gui=None):
    def notify(message, purpose=kiosk_utils.TicketPurpose.PRN):
        kiosk_utils.send_ticket(ticket_value=message, ticket_type=purpose,
                                ticket_animate_cycles=1, queue_tx=queue_to_gui)
    if conn is None:
        return False
    try:
        available = conn.getDevices(include_schemes=config['include_schemes'])
        if not available:
            notify('No printers found\n' + ', '.join(config['include_schemes']))
            return False
        installed = conn.getPrinters()
        default = conn.getDefault()
        if default and check_default(available, installed, default):
            conn.acceptJobs(default)
            conn.enablePrinter(default)
            notify(f'{default}\nOK')
            return True
        # Preserve other queues. Select an installed supported printer if possible.
        for name, attrs in installed.items():
            uri = attrs.get('device-uri')
            model = available.get(uri, {}).get('device-make-and-model', '')
            if uri in available and any(model.startswith(make) for make in config['printers']):
                conn.setDefault(name)
                conn.acceptJobs(name)
                conn.enablePrinter(name)
                notify(f'{name}\nOK')
                return True
        success, result = add_printer(conn, config['printers'], available)
        if success:
            notify(f'{result}\nprinter installed')
            logging.info('Printer installed: %s', result)
            return True
        notify('Error installing printer\n' + result, kiosk_utils.TicketPurpose.ERR)
    except CUPS_ERRORS as exc:
        logging.error('Printer initialization failed: %s', exc)
        notify('Printer initialization failed', kiosk_utils.TicketPurpose.ERR)
    return False


def print_report(conn=None, tmp_file=None):
    """Return a job ID after CUPS accepts the job; return None on failure.

    The caller owns the report file and removes it after submission.
    """
    if conn is None:
        conn = connect_to_cups()
    if conn is None:
        return None
    try:
        printers = conn.getPrinters()
        printer = conn.getDefault()
        if not printer or printer not in printers:
            logging.error('No default printer available in CUPS')
            return None
        options = {'print-color-mode': 'monochrome'}
        if tmp_file:
            job_id = conn.printFile(printer, tmp_file, 'Kiosk report', options=options)
        else:
            job_id = conn.printTestPage(printer, options=options)
        return job_id if job_id and job_id > 0 else None
    except CUPS_ERRORS as exc:
        logging.error('Report submission failed: %s', exc)
        return None


def get_report_from_host(url, timeout=10):
    """Return [HTTP status, PDF path], or [None, None] for a failed request."""
    path = None
    try:
        with requests.get(url, timeout=timeout) as response:
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if response.status_code != 200 or content_type != 'application/pdf':
                return [response.status_code, None]
            with tempfile.NamedTemporaryFile(prefix='kio_', suffix='.pdf', delete=False) as stream:
                path = stream.name
                stream.write(response.content)
            return [response.status_code, path]
    except (requests.RequestException, OSError) as exc:
        # Request exception strings can include the report access token in the URL.
        logging.error('Report download failed (%s)', type(exc).__name__)
        if path:
            try:
                os.unlink(path)
            except OSError:
                logging.warning('Cannot remove temporary report')
        return [None, None]


def main():
    logging.basicConfig(format='%(levelname)s:%(asctime)s - %(message)s', level=logging.DEBUG)
    config = kiosk_config.read_config(os.path.join(os.path.dirname(__file__), 'kiosk.ini'))
    if config is not None:
        init_printer(conn=connect_to_cups(), config=config)


if __name__ == '__main__':
    main()
