"""Optional real-widget smoke check: DISPLAY=:99 .venv/bin/python tests/gui_smoke.py.

Run against a virtual X server. Hardware actions are mocked and no worker starts.
"""
from pathlib import Path
from queue import Queue
import sys
import threading
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kiosk_config
import kiosk_main as gui
from kiosk_utils import Ticket, TicketPurpose


def main():
    root = Path(__file__).resolve().parents[1]
    config = kiosk_config.read_config(root / 'kiosk.ini')
    config.update(button_debounce_time_ms=50, button_reset_to_default_time_ms=100000,
                  animated_icon_delay=10, animated_icon_width=30, animated_icon_height=30)
    gui.config = config
    gui.img_cache = {value: [Image.new('RGBA', (30, 30), 'white'), Image.new('RGBA', (30, 30), 'blue')]
                     for key, value in config.items()
                     if key.startswith('animated_icon_') and isinstance(value, str)}
    queue, stop, errors = Queue(), threading.Event(), []
    worker = Mock()
    worker.is_alive.return_value = True
    with patch('kiosk_utils.set_brightness'), patch('kiosk_utils.set_screen_dpms'):
        app = gui.KioskApp(config=config, queue_to_gui=queue, slave_thread=worker, stop_event=stop)
        app.report_callback_exception = lambda *exc: errors.append(exc)
        app.update()
        app._display_dpms = 15
        app.frame.on_click((1, 'ENG'))
        assert gui.queue_from_gui.get_nowait() == (1, 'ENG')
        assert all(button.cget('state') == 'disabled' for button in app.frame.buttons)
        app.after(80, app.quit)
        app.mainloop()
        assert all(button.cget('state') == 'normal' for button in app.frame.buttons)
        queue.put(Ticket(TicketPurpose.BCR, 'Barcode', ticket_animate_cycles=1))
        app.check_queue()
        app.update()
        first = app.popup_window.frame.icon
        first.stop_animation()
        queue.put(Ticket(TicketPurpose.BCR, 'Again', ticket_animate_cycles=2))
        app.check_queue()
        assert first is app.popup_window.frame.icon
        assert first._is_animating
        first.stop_animation()
        queue.put(Ticket(TicketPurpose.ERR, 'Error', ticket_animate_cycles=1))
        app.check_queue()
        app.update()
        assert first is not app.popup_window.frame.icon
        app.popup_window.frame.icon.stop_animation()
        queue.put(Ticket(TicketPurpose.EOT))
        app.check_queue()
        app.update()
        # An explicit ticket duration holds the popup even if its animation ends.
        queue.put(Ticket(TicketPurpose.AOK, 'Timed', ticket_display_time=1000, ticket_animate_cycles=1))
        app.check_queue()
        app.popup_window.frame.icon.stop_animation()
        queue.put(Ticket(TicketPurpose.ERR, 'Next', ticket_animate_cycles=1))
        app.check_queue()
        assert queue.qsize() == 1
        app.popup_window.minimum_display_until = 0
        app.check_queue()
        assert queue.empty()
        app.quit_app()
        assert stop.is_set()
    assert not errors, errors
    print('GUI smoke passed: startup, language selection, debounce, popup reuse, icon changes, ticket duration, shutdown')


if __name__ == '__main__':
    main()
