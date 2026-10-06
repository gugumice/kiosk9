#!/usr/bin/env python3

import tkinter as tk
import customtkinter as ctk
#from PIL import Image
import os, sys
import logging
import argparse
import signal

import threading
from queue import Queue, Empty
import time

import kiosk_config
import kiosk_utils
from kiosk_animated_label import AnimatedGifLabelAcc, load_gif_frames
import kiosk_service

# Global vars
config = dict()
queue_from_gui = Queue()
queue_to_gui = Queue()
img_cache = {}
# Polling interval for checking messages on service thread
# and BC reader timeout
polling_int = 0.5
logging.basicConfig(format='%(levelname)s:%(asctime)s - %(message)s')
logger = logging.getLogger()

class KioskButton(ctk.CTkButton):
    def __init__(self, master=None,  
                 lang:list = None,
                 active: bool = False,
                 button_debounce_time_ms:int = 5000):
        super().__init__(master,
                        border_width =20,
                        border_spacing=10,
                        corner_radius = 50,
                        hover = False,
                        font=("Noto Sans Mono",80, "bold"))
          
        self.lang = lang
        self.active = active
        self._button_debounce_time_ms = button_debounce_time_ms
        self.configure(
            command=lambda: self.master.on_click(self.lang),
            text = self.lang[1],
                        )     
        self.idle()
        
    def idle(self):
        self.active = False
        self.configure(border_color="#008ca4",
                       fg_color=("white","#008ca4"),
                       text_color= ("#008ca4","white"),
                       bg_color="transparent")
    
    def pressed(self):
        self.active = True
        self.configure(
                text_color="white",
                fg_color=("#008ca4")
                )
    def state_disable(self):
        self.configure(state = "disabled")
    
    def state_normal(self):
        self.configure(state = "normal")

class MainFrame(ctk.CTkFrame):
    """A custom frame class that inherits from CTkFrame.
    It contains a list of buttons and manages their state.
    """
    def __init__(self, master=None,
                width:int = 300, height:int = 500, posXY:list = [100,200],
                config:dict = None, queue_from_gui:Queue = None):
        super().__init__(master,
            width=width,
            height=height,
            border_width=0,
            border_color = "grey",
            fg_color="white",
            bg_color="white",)
        self.config = config
        # Set the size of the frame
        self.width = width
        self.height = height
        self.posXY = posXY
        self.buttons = list()
        self._debounce_after = None
        self.selected_button = config['default_language_index']
        self.queue_from_gui = queue_from_gui
        self._default_bttn_after = None
        self.init_buttons()
        self.enable_buttons(self.selected_button)
        self._default_bttn_after = self.after(self.config['button_reset_to_default_time_ms'], self.set_to_default_bttn)
          
    def init_buttons(self):
        for lang in enumerate(self.config['languages']):
            button = KioskButton(self, lang=lang,
                                 active=False,
                                 button_debounce_time_ms = 500)
            self.buttons.append(button)
            self.buttons[-1].pack(padx=25, pady=25, fill=ctk.BOTH, expand=True)
            logger.debug('bttns_init: {}'.format(lang))
    
    def debounce_buttons(self, debounce_time:int):
        self.disable_buttons()
        self.after(debounce_time, self.enable_buttons, self.selected_button)
        logger.debug('bttns_debounce')

    def disable_buttons(self, active_button_index:int = None):
        logger.debug('bttns_disabled')
        for idx, button in enumerate(self.buttons):
            button.state_disable()
            if idx == active_button_index:
                button.pressed()
                msg = (active_button_index, self.config["languages"][active_button_index])
                self.queue_from_gui.put(msg)
            else:
                button.idle()

    def deactivate_buttons(self):
        logger.debug('bttns_deactivated')
        for button in self.buttons:
            button.active = False

    def enable_buttons(self,active_button_index:int):
        self._debounce_after = None
        logger.debug('bttns_enabled, act: {}'.format(active_button_index))
        for idx, button in enumerate(self.buttons):
            button.state_normal()
            if idx == active_button_index:
                button.pressed()
            else:
                button.idle()

    def set_to_default_bttn(self):
        logger.info('setting to default button: {}'.format(self.config['default_language_index']))
        if self._debounce_after is not None:
            self.after_cancel(self._debounce_after)
            self._debounce_after = None
        if self.selected_button != self.config['default_language_index']:
            self.selected_button = self.config['default_language_index']
            self.disable_buttons(self.config['default_language_index'])
        self.enable_buttons(self.selected_button)
        # Set screen backlight to normal or low, depending on working hours, enable/disable screen powersave
        logger.debug('Checking working time for setting brightness and powersave')
        if kiosk_utils.is_working_time(start=self.config['working_hours'][0], end=self.config['working_hours'][1], workdays=self.config['working_days'],):
            logger.debug('Powersave disabled)')
            kiosk_utils.set_brightness(self.config['screen_brightness_normal'], self.config['screen_brightness_path'])
            if self.winfo_toplevel()._display_dpms != 0:
                self.winfo_toplevel()._display_dpms = 0
                kiosk_utils.set_screen_dpms(0)
                logger.debug('Set display dpms to {}'.format(self.winfo_toplevel()._display_dpms))
        else:
            logger.debug('Powersave enabled, timeout: {}'.format(self.config['screen_dpms_timeout_secs']))
            kiosk_utils.set_brightness(self.config['screen_brightness_inactive'], self.config['screen_brightness_path'])
            if self.winfo_toplevel()._display_dpms == 0:
                self.winfo_toplevel()._display_dpms = self.config['screen_dpms_timeout_secs']
                kiosk_utils.set_screen_dpms(self.config['screen_dpms_timeout_secs'])
                logger.debug('Set display dpms to {}'.format(self.winfo_toplevel()._display_dpms))

        # Delete existing timer if present
        if self._default_bttn_after:
            self.after_cancel(self._default_bttn_after)
        # Set new
        self._default_bttn_after = self.after(self.config['button_reset_to_default_time_ms'], self.set_to_default_bttn)
        
    def on_click(self, lang):
        logger.debug('bttns_sel: {}'.format(lang))
        self.selected_button = lang[0]
        # Set screen backlight to active
        kiosk_utils.set_brightness(self.config["screen_brightness_active"], self.config['screen_brightness_path'])
        if self.winfo_toplevel()._display_dpms != 0:
            kiosk_utils.set_screen_dpms(0)
            self.winfo_toplevel()._display_dpms = 0
            logger.debug('Set display dpms to {}'.format(self.winfo_toplevel()._display_dpms))
        #Debounce
        if self._debounce_after is not None:
            self.after_cancel(self._debounce_after)
        self.disable_buttons(self.selected_button)
        self._debounce_after = self.after(self.config['button_debounce_time_ms'], self.enable_buttons, self.selected_button)
        if self._default_bttn_after:
            self.after_cancel(self._default_bttn_after)

        self._default_bttn_after = self.after(self.config['button_reset_to_default_time_ms'], self.set_to_default_bttn)

class PopupFrame(ctk.CTkFrame):
    def __init__(self, master=None, config: dict = config):
        super().__init__(master,
                        fg_color="#fff",
                        bg_color="#fff",
                        border_width = 0,
                        width=config["button_frame_width"],
                        height=config["button_frame_height"],
                         )
        self._config = config
        self.pack_propagate(False)
        self._message_value = tk.StringVar(self)
        self.icon = None
        self.label = ctk.CTkLabel(
            self,
            textvariable=self._message_value,
            font=(config["text_label_font"], config["text_label_font_size"]),
            justify=tk.LEFT,
            padx=0,
            pady=0,)
        self.label.pack(side=tk.BOTTOM, expand=True, fill=tk.BOTH)
        self._prev_ticket_type = None

    def update(self, ticket: kiosk_utils.Ticket = None):
        self._message_value.set(ticket.ticket_value or "")
        # Icon already loaded?
        if ticket.ticket_type != self._prev_ticket_type:
            if self.icon is not None:
                self.icon.stop_animation()
                self.icon.destroy()
                self.icon = None
            # Choose GIF path by ticket type
            gif_map = {
                kiosk_utils.TicketPurpose.SYS: self._config["animated_icon_sys"],
                kiosk_utils.TicketPurpose.PRN: self._config["animated_icon_prn"],
                kiosk_utils.TicketPurpose.BCR: self._config["animated_icon_bc"],
                kiosk_utils.TicketPurpose.NET: self._config["animated_icon_net"],
                kiosk_utils.TicketPurpose.ERR: self._config["animated_icon_not_ok"],
                kiosk_utils.TicketPurpose.AOK: self._config["animated_icon_ok"],
                kiosk_utils.TicketPurpose.PRG: self._config["animated_icon_in_progress"],
                kiosk_utils.TicketPurpose.INC: self._config["animated_icon_no_data"],
            }
            gif_path = os.path.join(self._config["assets_loader"], gif_map.get(ticket.ticket_type, self._config["animated_icon_not_ok"]))
            self.icon = AnimatedGifLabelAcc(
                self,
                gif_path=gif_path,
                delay=self._config["animated_icon_delay"],
                width=self._config["animated_icon_width"],
                height=self._config["animated_icon_height"],
                img_cache=img_cache,
            )
        self._prev_ticket_type = ticket.ticket_type
        # show icon
        self.icon.pack(side=tk.BOTTOM, padx=0, pady=40)
        self.icon.start_animation(ticket.ticket_animate_cycles)

class KioskPopup(ctk.CTkToplevel):
    """A custom popup class that inherits from CTkToplevel."""
    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)
        self.overrideredirect(True)
        self.geometry(
            "{}x{}+{}+{}".format(
                config["button_frame_width"],
                config["button_frame_height"],
                config['button_frame_posXY'][0], config['button_frame_posXY'][1]))
        self.title("KioskPopup")
        self.attributes("-topmost", True)
        self.time_created = time.time()
        self.frame = PopupFrame(master=self, config=config)
        self.frame.pack(fill=tk.BOTH, expand=True)

    def close_popup(self):
        """Callback function for closing the popup."""
        logger.debug("Closing popup")
        self.destroy()
        
class KioskApp(ctk.CTk):
    """Main application class that inherits from CTk."""
    def __init__(self, config=None, queue_to_gui: Queue = None, slave_thread:threading.Thread = None, stop_event=None):
        super().__init__()
        self.queue_to_gui = queue_to_gui
        self.config = config
        self.slave_thread = slave_thread
        self.stop_event = stop_event
        self.worker_failed = False
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.bind('<Escape>', self.quit_app)     
        self.bg_image = (
            tk.PhotoImage(
                file=os.path.join(self.config["assets_loader"], self.config["bg_image"])
            )
            if self.config["bg_image"] else None
        )

        self.height = self.config["screen_height"]
        self.width = self.config["screen_width"]
        self._display_dpms=0

        # Canvas for popup widgets
        self.canvas = tk.Canvas(
            self, height=self.height, width=self.width, background="lightblue"
        )
        self.canvas.pack()
        if self.bg_image:
            self.canvas.create_image(0, 0, image=self.bg_image, anchor=ctk.NW)
        # Main frame

        self.frame = MainFrame(self, width=self.config['button_frame_width'],
                                height=self.config['button_frame_height'],
                                posXY = self.config['button_frame_posXY'],
                                config = self.config,
                                queue_from_gui = queue_from_gui,
                                )
        # Popup window for animated messages
        self.popup_window = None
        self._wd = None
        if config['watchdog_device'] is not None:
            try:
                self._wd = open(config['watchdog_device'], "w")
                logging.info('Watchdog enabled on:\n{}'.format(config['watchdog_device']))
            except Exception as e:
                logging.error(e)
                
        self.canvas.create_window(
            self.frame.posXY,
            width=self.frame.width,
            height=self.frame.height,
            window=self.frame,
            anchor=tk.NW,
        )
        self.check_queue()
    
    def quit_app(self,evt=None):
        logger.info('Kiosk exit requested')
        if self.stop_event is not None:
            self.stop_event.set()
        if self._wd is not None:
            try:
                print('V', file=self._wd, flush=True)
            except OSError as exc:
                logger.error('Watchdog stop failed: %s', exc)
            finally:
                self._wd.close()
                self._wd = None
        self.destroy()
    
    def check_queue(self):
        # print("^", end="", flush=True)  # heartbeat
        if (self.slave_thread is not None and not self.slave_thread.is_alive()
                and self.stop_event is not None and not self.stop_event.is_set()):
            logger.error('Service worker stopped; exiting for systemd to restart the kiosk')
            self.worker_failed = True
            self.quit_app()
            return
        self.after(500, self.check_queue)
        if self._wd is not None and self.slave_thread is not None and self.slave_thread.is_alive():
            try:
                print('1',file=self._wd, flush=True)
            except OSError as exc:
                logger.error('Watchdog write failed: %s', exc)

        if self.popup_window and self.popup_window.winfo_exists():
            icon = self.popup_window.frame.icon
            if time.monotonic() < self.popup_window.minimum_display_until:
                return
            if icon is not None and not icon.stopped():
                if time.monotonic() < self.popup_window.display_until:
                    return
                icon.stop_animation()
        if not self.queue_to_gui.empty():
            logger.debug('Exiting powersave or low brightness mode due to message in queue')
            if self.winfo_toplevel()._display_dpms != 0:
                kiosk_utils.set_screen_dpms(0)
                self.winfo_toplevel()._display_dpms = 0
                logger.debug('Set display dpms off')
            kiosk_utils.set_screen_dpms(0)
            kiosk_utils.set_brightness(self.config['screen_brightness_normal'], self.config['screen_brightness_path'])
            try:
                ticket = self.queue_to_gui.get_nowait()
            except Empty:
                return
            if not isinstance(ticket, kiosk_utils.Ticket):
                logger.error(f"Invalid message: {ticket}")
                return

            if ticket.ticket_type == kiosk_utils.TicketPurpose.EOT:
                if self.popup_window and self.popup_window.winfo_exists():
                    self._close_popup()
            else:
                if not self.popup_window or not self.popup_window.winfo_exists():
                    self.popup_window = KioskPopup(config=self.config, master=self)
                else:
                    self.popup_window.deiconify()
                self.popup_window.minimum_display_until = time.monotonic() + ticket.ticket_display_time / 1000
                self.popup_window.display_until = time.monotonic() + (
                    ticket.ticket_display_time or self.config['popup_display_time']) / 1000
                self.popup_window.frame.update(ticket=ticket)
        else:
            self._close_popup()

    def _close_popup(self):
        if self.popup_window and self.popup_window.winfo_exists():
            self.popup_window.withdraw()

def main():
    global config, queue_to_gui, queue_from_gui, img_cache, polling_int
    parser = argparse.ArgumentParser(
        description="EGL testing report kiosk application."
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        metavar="file",
        help="Name config file. Default: kiosk.ini",
        default=os.path.join(os.path.dirname(__file__), "kiosk.ini"),
    )
    args = parser.parse_args()
    if not os.path.isfile(args.config):
        print("Config file not found.")
        sys.exit(1)
    config = kiosk_config.read_config(args.config)
    if config is None:
        sys.exit(1)

    logging.basicConfig(format='%(levelname)s:%(asctime)s - %(message)s',
                        level=os.environ.get('LOGLEVEL', config['log_level']).upper(),
                        filename=config['log_file'], force=True)

    img_cache = load_gif_frames(config["assets_loader"], config["animated_icon_width"], config["animated_icon_height"])
    logger.debug("Finished loading image cache {}".format(len(img_cache)))

    # Start service thread
    th_ev = threading.Event()
    t1 = threading.Thread(
        target=kiosk_service.service_thread,
        kwargs=dict(
            th_ev=th_ev,
            polling_int=polling_int,
            config=config,
            queue_from_gui=queue_from_gui,
            queue_to_gui=queue_to_gui,
        ),
        daemon=True)
    t1.start()
    logger.info("Service_thread: {}".format(t1.is_alive()))

    try:
        kiosk_app = KioskApp(config=config, queue_to_gui=queue_to_gui, slave_thread=t1, stop_event=th_ev)
        signal.signal(signal.SIGTERM, lambda *_: kiosk_app.quit_app())
        kiosk_app.mainloop()
        return 1 if kiosk_app.worker_failed else 0
    finally:
        th_ev.set()
        t1.join(timeout=2)

if __name__ == '__main__':
    raise SystemExit(main())
