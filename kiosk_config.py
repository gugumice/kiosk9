#!/usr/bin/env python3
import configparser
import logging
import os
import ast
import re
from datetime import datetime
from pathlib import Path

def read_config(filename):
    '''
    Sets default config values values
    Reads values from config file
    '''
    kiosk_config = {
        'log_file': None, # Set to valid path if dedicated log file is needed
        'log_level': 'INFO', # Set to logging.DEBUG for debug level logging
        # User interface settings
        'languages': ['LAT','ENG','RUS'],
        'default_language_index': 0,  # Default language index
        'bg_image': 'white_background.png',
        'assets_loader': 'assets', # Path to assets directory, relative to the script
        'font': ('DejaVu Sans Mono',50), # Font used in the interface
        'button_debounce_time_ms': 1000, # Time in milliseconds to debounce button presses
        'button_reset_to_default_time_ms': 10*1000, # Time in milliseconds to activate default button after last press
        #Settings for display brighetness 0 - 255
        'screen_brightness_active': 255,
        'screen_brightness_normal': 100,
        'screen_brightness_inactive': 50,
        'working_hours': ['7:30', '19:00'],
        'working_days': [0,1,2,3,4],
        'screen_brightness_to_min': 30,
        'screen_brightness_path': "/sys/class/backlight",
        'screen_dpms_timeout_secs': 300,
        #Settings for button frame size
        'button_frame_height': 500,
        'button_frame_width': 300,
        'button_frame_posXY': [100,200],
        #Settings for screen size
        'screen_width': 480,
        'screen_height': 800,
        #Settings for popup messages
        'popup_display_time': 5000,

        #Settings for animated icon
        'animated_icon_height': 100,
        'animated_icon_width': 100,
        'animated_icon_delay': 100,
        'animated_icon_sys': 'loading.gif',
        'animated_icon_prn': 'printer.gif',
        'animated_icon_bc': 'barcode.gif',
        'animated_icon_ok': 'verified.gif',
        'animated_icon_not_ok': 'alarm.gif',
        'animated_icon_no_data': 'report_not_ready.gif',
        'animated_icon_in_progress': 'work-in-progress.gif',
        'animated_icon_net': 'wifi.gif',

        'text_label_font_size': 20,
        'text_label_font': 'DejaVu Sans Mono',
        'report_not_ready_msg': ['NR','NR','NR'],
        'report_num_pages': ['NR','NR','NR'],

        # Barcode reader settings
        'bc_reader_bounce' : 3, # Bounce time in seconds for barcode reader
        'bc_reader_boudrate' : 9600,
        'bc_reader_port' : '/dev/ttyACM0',
        'bc_timeout' : .5,
        'bc_regex' : r'^\d{7,9}#\d{4,5}',

        #Host settings
        'host' : '10.100.50.104',
        'httpreq_timeout': 15, 
        'report_delay' : 5,
        'url' : 'http://{}/csp/sarmite/ea.kiosk.pdf.cls?HASH={}&LANG={}',
        'url_test' : 'http://10.100.50.102/sarmite/m5menu.csp',


        #printers':  {"HP": "HP LaserJet Series PCL 6 CUPS"},
        'include_schemes' : ['usb','driverless'],
        'printers' : {"HP": "HP LaserJet Series PCL 6 CUPS"},
        'button_printer_reset': [1],
        'watchdog_device' : None
    }
    if not os.path.isfile(filename):
        logging.critical("Config file {} does not exist!".format(filename))
        return(None)
    
    def sequence(value):
        if not value.strip():
            return []
        return [int(item) if item.isdigit() else item
                for item in (part.strip() for part in value.split(','))]

    cf = configparser.ConfigParser(interpolation=None, converters={
        'list': sequence,
        'tuple': lambda value: tuple(sequence(value)),
        'none': lambda value: None if value.strip().lower() in ('none', '') else value,
        'dict': lambda value: ast.literal_eval('{' + value + '}'),
    })
    settings = (
        ('log_file', 'getnone', 'INTERFACE', 'log_file'),
        ('log_level', 'get', 'INTERFACE', 'log_level'),
        ('languages', 'getlist', 'INTERFACE', 'languages'),
        ('assets_loader', 'get', 'INTERFACE', 'assets_loader'),
        ('bg_image', 'get', 'INTERFACE', 'bg_image'),
        ('font', 'gettuple', 'INTERFACE', 'font'),
        ('button_debounce_time_ms', 'getint', 'INTERFACE', 'button_debounce_time_ms'),
        ('button_reset_to_default_time_ms', 'getint', 'INTERFACE', 'button_reset_to_default_time_ms'),
        ('default_language_index', 'getint', 'INTERFACE', 'default_language_index'),
        ('screen_brightness_active', 'getint', 'INTERFACE', 'screen_brightness_active'),
        ('screen_brightness_normal', 'getint', 'INTERFACE', 'screen_brightness_normal'),
        ('screen_brightness_inactive', 'getint', 'INTERFACE', 'screen_brightness_inactive'),
        ('working_hours', 'getlist', 'INTERFACE', 'working_hours'),
        ('working_days', 'gettuple', 'INTERFACE', 'working_days'),
        ('screen_brightness_to_min', 'getint', 'INTERFACE', 'screen_brightness_to_min'),
        ('screen_brightness_path', 'get', 'INTERFACE', 'screen_brightness_path'),
        ('screen_dpms_timeout_secs', 'getint', 'INTERFACE', 'screen_dpms_timeout_secs'),
        ('screen_width', 'getint', 'INTERFACE', 'screen_width'),
        ('screen_height', 'getint', 'INTERFACE', 'screen_height'),
        ('animated_icon_height', 'getint', 'INTERFACE', 'animated_icon_height'),
        ('animated_icon_width', 'getint', 'INTERFACE', 'animated_icon_width'),
        ('animated_icon_delay', 'getint', 'INTERFACE', 'animated_icon_delay'),
        ('animated_icon_sys', 'get', 'INTERFACE', 'animated_icon_sys'),
        ('animated_icon_prn', 'get', 'INTERFACE', 'animated_icon_prn'),
        ('animated_icon_bc', 'get', 'INTERFACE', 'animated_icon_bc'),
        ('animated_icon_ok', 'get', 'INTERFACE', 'animated_icon_ok'),
        ('animated_icon_not_ok', 'get', 'INTERFACE', 'animated_icon_not_ok'),
        ('animated_icon_no_data', 'get', 'INTERFACE', 'animated_icon_no_data'),
        ('animated_icon_in_progress', 'get', 'INTERFACE', 'animated_icon_in_progress'),
        ('animated_icon_net', 'get', 'INTERFACE', 'animated_icon_net'),
        ('text_label_font_size', 'getint', 'INTERFACE', 'text_label_font_size'),
        ('text_label_font', 'get', 'INTERFACE', 'text_label_font'),
        ('button_frame_height', 'getint', 'INTERFACE', 'button_frame_height'),
        ('button_frame_width', 'getint', 'INTERFACE', 'button_frame_width'),
        ('button_frame_posXY', 'getlist', 'INTERFACE', 'button_frame_posXY'),
        ('popup_display_time', 'getint', 'INTERFACE', 'popup_display_time'),
        ('bc_reader_bounce', 'getint', 'BARCODE', 'bc_reader_bounce'),
        ('bc_reader_boudrate', 'getint', 'BARCODE', 'bc_reader_boudrate'),
        ('bc_reader_port', 'get', 'BARCODE', 'bc_reader_port'),
        ('bc_timeout', 'getfloat', 'BARCODE', 'bc_timeout'),
        ('host', 'get', 'REPORT', 'host'),
        ('httpreq_timeout', 'getint', 'REPORT', 'httpreq_timeout'),
        ('report_delay', 'getint', 'REPORT', 'report_delay'),
        ('url', 'get', 'REPORT', 'url'),
        ('url_test', 'get', 'REPORT', 'url_test'),
        ('printers', 'getdict', 'REPORT', 'printers'),
        ('button_printer_reset', 'getlist', 'REPORT', 'button_printer_reset'),
        ('include_schemes', 'getlist', 'REPORT', 'include_schemes'),
        ('report_not_ready_msg', 'getlist', 'REPORT', 'report_not_ready_msg'),
        ('report_num_pages', 'getlist', 'REPORT', 'report_num_pages'),
        ('watchdog_device', 'getnone', 'WATCHDOG', 'watchdog_device'),
        ('bc_regex', 'get', 'BARCODE', 'bc_regex'),
    )
    try:
        with open(filename, encoding='utf-8') as stream:
            cf.read_file(stream)
        for key, getter, section, option in settings:
            if cf.has_option(section, option):
                kiosk_config[key] = getattr(cf, getter)(section, option)
        validate_config(kiosk_config)
    except (OSError, configparser.Error, ValueError, TypeError, SyntaxError, re.error) as exc:
        logging.error("Invalid configuration %s: %s", filename, exc)
        return None

    base = Path(filename).resolve().parent
    for key in ('assets_loader', 'log_file'):
        if kiosk_config[key] is not None:
            kiosk_config[key] = str(base / kiosk_config[key])
    return kiosk_config


def validate_config(config):
    languages = config['languages']
    if not languages or any(not isinstance(value, str) or not value for value in languages):
        raise ValueError('languages must be a nonempty list of names')
    if not 0 <= config['default_language_index'] < len(languages):
        raise ValueError('default_language_index is out of range')
    for key in ('report_not_ready_msg', 'report_num_pages'):
        if len(config[key]) != len(languages) or any(not isinstance(v, str) for v in config[key]):
            raise ValueError(f'{key} must contain one string per language')
    if len(config['working_hours']) != 2:
        raise ValueError('working_hours must contain start and end times')
    for value in config['working_hours']:
        datetime.strptime(value, '%H:%M')
    if any(day not in range(7) for day in config['working_days']):
        raise ValueError('working_days must contain numbers from 0 to 6')
    if len(config['button_frame_posXY']) != 2 or any(not isinstance(v, int) for v in config['button_frame_posXY']):
        raise ValueError('button_frame_posXY must contain two integers')
    for key in ('screen_width', 'screen_height', 'button_frame_width', 'button_frame_height',
                'animated_icon_width', 'animated_icon_height', 'animated_icon_delay',
                'button_reset_to_default_time_ms', 'httpreq_timeout', 'bc_timeout', 'bc_reader_boudrate',
                'popup_display_time', 'text_label_font_size'):
        if config[key] <= 0:
            raise ValueError(f'{key} must be positive')
    for key in ('button_debounce_time_ms', 'report_delay', 'bc_reader_bounce',
                'screen_dpms_timeout_secs', 'screen_brightness_to_min'):
        if config[key] < 0:
            raise ValueError(f'{key} cannot be negative')
    for key in ('screen_brightness_active', 'screen_brightness_normal', 'screen_brightness_inactive'):
        if not 0 <= config[key] <= 255:
            raise ValueError(f'{key} must be between 0 and 255')
    if not isinstance(config['printers'], dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or not k or not v
        for k, v in config['printers'].items()
    ):
        raise ValueError('printers must map manufacturer names to PPD models')
    if config['log_level'].upper() not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
        raise ValueError('invalid log_level')
    if any(not isinstance(i, int) or not 0 <= i < len(languages) for i in config['button_printer_reset']):
        raise ValueError('button_printer_reset contains an invalid language index')
    re.compile(config['bc_regex'])

def main():
    f = str(Path(__file__).with_name('kiosk.ini'))
    logging.basicConfig(format='%(levelname)s:%(asctime)s - %(message)s', level=logging.DEBUG)
    cfg = read_config(f)
    print(cfg)


if __name__ == '__main__':
    main()
