#!/usr/bin/env python3
''' A module for utility classes and functions. '''

import os
from datetime import datetime, timedelta
from enum import Enum, auto
from queue import Queue
import subprocess
import threading
import logging
import requests
import kiosk_config
from pathlib import Path
queue_to_gui = Queue()
config = dict()

class TicketPurpose(Enum):
    '''Enum class to represent the purpose of the ticket.'''
    BCR = auto()  # Barcode reader ticket
    NET = auto()  # Request ticket
    PRN = auto()  # Printer ticket
    SYS = auto()  # System ticket
    ERR = auto()  # Error ticket
    AOK = auto()  # OK ticket
    PRG = auto()  # In progress ticket
    INC = auto()  # Incomplete rep ticket
    EOT = auto()  # End of ticket

class Ticket(object):
    """Class to represent a ticket with a type and value."""
    def __init__(self, ticket_type = TicketPurpose.SYS, ticket_value:str= None, ticket_display_time:int = 0, ticket_animate_cycles:int = 0):
        self.ticket_type:TicketPurpose = ticket_type
        self.ticket_value:str = ticket_value
        self.ticket_display_time:int = ticket_display_time
        self.ticket_animate_cycles:int = ticket_animate_cycles

def send_ticket(ticket_value:str = None, 
                ticket_type:TicketPurpose=TicketPurpose.SYS, 
                ticket_display_time:int = 0,
                ticket_animate_cycles:int = 0,
                queue_tx:Queue = None):
    """
    Function to send a ticket to the service thread.
    :param value: Value of the ticket
    :param : Type of the ticket (TicketPurpose)
    :param ticket_display_time: Time in milliseconds to display the ticket
    :param ticket_animate_cycles: For how many GIF cycles to display ticket
    """
    ticket = Ticket(ticket_type=ticket_type,
                    ticket_value=ticket_value,
                    ticket_display_time=ticket_display_time,
                    ticket_animate_cycles=ticket_animate_cycles)
    
    if queue_tx is None:
        queue_tx = queue_to_gui
    queue_tx.put(ticket)
    logging.info(f"Ticket sent: <{ticket.ticket_value}> of type <{ticket.ticket_type}>")

def host_info() -> list:
    """ 
    Function to get the IP address and hostname.
    Returns a list of IP address and hostname or None if it fails.
    """
    try:
        return([subprocess.check_output(['hostname', '-I']).decode('utf-8').strip(),
                subprocess.check_output(['hostname', '-f']).decode('utf-8').strip()]) 
    except (OSError, subprocess.SubprocessError):
        return(None)
    
def get_numpages_from_pdf(f:str) -> int:
    result = subprocess.run(
    ['pdfinfo', str(f)],
    capture_output=True, text=True, check=True, timeout=15
    )
    # Store the result in a variable
    for line in result.stdout.splitlines():
        if line.startswith('Pages:'):
            pages = int(line.split(':', 1)[1].strip())
            if pages > 0:
                return pages
    raise ValueError('PDF contains no readable pages')
    
def speak_status(f, background = True)-> None:
    '''
    Speak status messages
    '''
    try:
        args = ['aplay', '-q', str(f)]
        if background:
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Thread(target=process.wait, daemon=True).start()
        else:
            subprocess.run(args, check=True, timeout=60, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        logging.warning('Error playing sound %s: %s', f, exc)

def set_brightness(level: int, path:str = "/sys/class/backlight") -> bool:
    backlight_base = Path(path)
    if backlight_base.name == 'brightness':
        devices = [backlight_base.parent]
    elif (backlight_base / 'brightness').exists():
        devices = [backlight_base]
    else:
        devices = list(backlight_base.glob("*"))
    if not devices:
        logging.warning('No backlight device found on %s', backlight_base)
        return False

    errors = []
    successes = 0

    for device in devices:
        try:
            max_brightness = int((device / "max_brightness").read_text().strip())
            safe_level = max(0, min(level, max_brightness))
            with open(device / "brightness", "w") as f:
                f.write(str(safe_level))
            successes += 1
            logging.debug(f"Set brightness to {safe_level} on {device}")

        except Exception as e:
            errors.append((str(device), str(e)))

    if successes == 0:
        logging.error("Failed to set brightness on all devices: %s", errors)
        return False

    if errors:
        logging.debug("Some backlight devices failed, but brightness was set: %s", errors)
    return True

def set_screen_dpms(timeout_seconds: int) -> bool:
    """
    Set X11 screen blanking timeout.

    timeout_seconds=0 disables the screen saver.
    """
    env = os.environ.copy()
    env.setdefault('DISPLAY', ':0')
    commands = [['xset', '-dpms']] if timeout_seconds <= 0 else [
        ['xset', '+dpms'],
        ['xset', 'dpms', *([str(timeout_seconds)] * 3)],
    ]
    try:
        for args in commands:
            subprocess.run(args, env=env, check=True, timeout=5, capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        logging.warning('Cannot configure display power saving: %s', exc)
        return False
    return True
        
def host_connection_ok(url) -> bool:
    '''
    Test connection to host
    '''
    try:
        #requests.head(url,timeout=10)
        with requests.get(url, timeout=10) as response:
            return response.status_code == 200 and response.text.strip() == 'OK'
    except requests.RequestException:
        return(False)
    
def is_working_time(now:str = None, start:str='7:30', end:str='19:00', workdays:tuple=(0, 1, 2, 3, 4)):
    if now is None:
        now = datetime.now()
    elif isinstance(now, str):
        now = datetime.combine(datetime.now().date(), datetime.strptime(now, '%H:%M').time())
    # Convert strings to time objects
    start_time = datetime.strptime(start, "%H:%M").time()
    end_time = datetime.strptime(end, "%H:%M").time()    
    if start_time <= end_time:
        return now.weekday() in workdays and start_time <= now.time() <= end_time
    # The early-morning portion of an overnight shift belongs to the previous day.
    return ((now.weekday() in workdays and now.time() >= start_time) or
            ((now - timedelta(days=1)).weekday() in workdays and now.time() <= end_time))

class WatchDog(object):
    def __init__(self, wd_device:str = '/dev/watchdog'):
        self._wd = None
        try:
            self._wd = open(wd_device, "w")
        except Exception as e:
            logging.error('Error opening {}: {}'.format(wd_device, e))
            return(None)
        
    def pat(self):
        if self._wd is None:
            return False
        try:
            print('1',file = self._wd, flush = True)
            # print('.', end='', flush=True) 
            return(True)
        except:
            return(False)

    def stop(self):
        if self._wd is None:
            return False
        try:
            print('V',file = self._wd, flush = True)
            self._wd.close()
            self._wd = None
            return(True)
        except:
            return(False)
def main():
    config = kiosk_config.read_config(str(Path(__file__).with_name('kiosk.ini')))
    print(config)
    print(is_working_time(start=config['working_hours'][0], end=config['working_hours'][1], workdays=tuple(config['working_days'])))
    set_screen_dpms(0)

    #speak_status('assets/lang_LAT.wav', background=True)
    #speak_status(os.path.join(config['assets_loader'], 'start_print{}.wav'.format('LAT')), background=False)
    # set_brightness(255, config)
    # sleep(5)
    # set_brightness(100, config)
    # sleep(5)
    # set_brightness(0, config)


    # w = config['watchdog_device']
    # print(w)
    # wdObj = WatchDog(w)
    # for i in range(0,20):
    #     if wdObj:
    #         print(wdObj.pat())
    #     sleep(1)
    # wdObj.stop()
    # print('stopped')
if __name__ == '__main__':
    main()
