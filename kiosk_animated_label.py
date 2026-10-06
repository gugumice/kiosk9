#!/usr/bin/env python3
"""Load GIF frames from source images and animate them on the Tk main thread."""
import logging
import os
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageSequence, ImageTk

import kiosk_config


def read_frames(path, width=None, height=None):
    with Image.open(path) as image:
        frames = []
        for frame in ImageSequence.Iterator(image):
            frame = frame.convert('RGBA').copy()
            if width and height:
                frame = frame.resize((width, height), Image.Resampling.LANCZOS)
            frames.append(frame)
    if not frames:
        raise ValueError(f'No frames in {path}')
    return frames


def gif_frames_to_dict(config=None, gifs_keys=None):
    if config is None or gifs_keys is None:
        raise ValueError('Configuration and GIF keys are required')
    result = {}
    for key in gifs_keys:
        filename = config[key]
        try:
            result[filename] = read_frames(Path(config['assets_loader']) / filename,
                                           config['animated_icon_width'], config['animated_icon_height'])
        except (OSError, ValueError) as exc:
            logging.warning('Cannot load GIF %s: %s', filename, exc)
    return result


def save_gif_frames(source, cache_path=None):
    """Export image sequences as GIFs; never write executable pickle data."""
    if cache_path is None:
        raise ValueError('Destination path not specified')
    destination = Path(cache_path)
    destination.mkdir(parents=True, exist_ok=True)
    for filename, frames in source.items():
        if frames:
            frames[0].save(destination / Path(filename).name, format='GIF',
                           save_all=True, append_images=frames[1:], duration=50, loop=0)


def load_gif_frames(source_dir=None, width=None, height=None):
    """Build an in-memory cache from GIFs. Ignore legacy .pkl caches.

    Accept the former assets/img_cache path for compatibility. Source GIFs are
    authoritative, so changes to images or dimensions are reflected at startup.
    """
    if source_dir is None:
        raise ValueError('Source directory not specified')
    source = Path(source_dir)
    if source.name == 'img_cache':
        source = source.parent
    result = {}
    for path in source.glob('*.gif'):
        try:
            result[path.name] = read_frames(path, width, height)
        except (OSError, ValueError) as exc:
            logging.warning('Cannot load GIF %s: %s', path, exc)
    return result


class AnimatedGifLabelAcc(tk.Label):
    def __init__(self, master, gif_path, delay=50, width=None, height=None, img_cache=None):
        super().__init__(master, padx=0, pady=0)
        self.gif_path = gif_path
        self.delay = delay
        self.img_cache = img_cache if img_cache is not None else {}
        filename = os.path.basename(gif_path)
        if filename not in self.img_cache:
            try:
                self.img_cache[filename] = read_frames(gif_path, width, height)
            except (OSError, ValueError) as exc:
                logging.warning('Cannot load animation %s: %s', gif_path, exc)
                self.img_cache[filename] = []
        self.frames = [ImageTk.PhotoImage(frame.resize((width, height)) if width and height
                                         and frame.size != (width, height) else frame, master=self)
                       for frame in self.img_cache[filename]]
        self.current_frame = 0
        self._is_animating = False
        self._anim_cycles = 0
        self._curr_cycle = 0
        self._after_id = None

    def start_animation(self, cycles=0):
        self.stop_animation()
        self.current_frame = 0
        self._curr_cycle = 0
        self._anim_cycles = cycles
        self._is_animating = bool(self.frames)
        self._animate()

    def stop_animation(self):
        self._is_animating = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def stopped(self):
        return not self._is_animating

    def _animate(self):
        self._after_id = None
        if not self._is_animating:
            return
        self.config(image=self.frames[self.current_frame])
        self.current_frame += 1
        if self.current_frame == len(self.frames):
            self.current_frame = 0
            self._curr_cycle += 1
        if self._anim_cycles and self._curr_cycle >= self._anim_cycles:
            self._is_animating = False
        else:
            self._after_id = self.after(self.delay, self._animate)

    def destroy(self):
        self.stop_animation()
        super().destroy()


def main():
    config = kiosk_config.read_config(Path(__file__).with_name('kiosk.ini'))
    if config is None:
        return
    root = tk.Tk()
    root.geometry('300x300')
    label = AnimatedGifLabelAcc(root, os.path.join(config['assets_loader'], 'loading.gif'),
                               delay=40, width=200, height=200)
    label.pack(expand=True)
    label.start_animation(1)
    root.mainloop()


if __name__ == '__main__':
    main()
