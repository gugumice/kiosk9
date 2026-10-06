#!/usr/bin/env python3
"""Run the kiosk worker with console output instead of the touchscreen GUI."""
import argparse
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import threading

import kiosk_config
import kiosk_service
from kiosk_utils import Ticket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-c', '--config', default=str(Path(__file__).with_name('kiosk.ini')))
    args = parser.parse_args()
    config = kiosk_config.read_config(args.config)
    if config is None:
        parser.exit(1, 'Invalid configuration\n')
    logging.basicConfig(format='%(asctime)s - %(message)s',
                        level=os.environ.get('LOGLEVEL', config['log_level']).upper(),
                        filename=config['log_file'], force=True)
    outgoing, incoming = Queue(), Queue()
    stop = threading.Event()
    worker = threading.Thread(target=kiosk_service.service_thread, kwargs={
        'th_ev': stop, 'config': config, 'queue_from_gui': outgoing, 'queue_to_gui': incoming,
    }, daemon=True)
    worker.start()
    interrupted = False
    try:
        while worker.is_alive():
            try:
                message = incoming.get(timeout=0.5)
            except Empty:
                continue
            if isinstance(message, Ticket):
                print(f'{message.ticket_type.name}: {message.ticket_value or ""}', flush=True)
            else:
                logging.warning('Unknown message type: %s', type(message))
    except KeyboardInterrupt:
        interrupted = True
    finally:
        stop.set()
        worker.join(timeout=2)
    return 0 if interrupted else 1


if __name__ == '__main__':
    raise SystemExit(main())
