import time
import weakref
import importlib.resources
import importlib.metadata
import pickle
from pathlib import Path

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap.widgets import tooltip

from pyrsistent import *
import numpy as np
import cairosvg

from . import icons

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

def lerp(a, b, t):
    return (b - a) * t + a

def bilinear(a, b, c, t):
    ab = lerp(a, b, t)
    bc = lerp(b, c, t)
    return lerp(ab, bc, t)

def secant_method(f, x0=0, x1=1, iters=20):
    for _ in range(iters):
        f0 = f(x0)
        f1 = f(x1)
        if f0 == f1:
            return x1
        x2 = x1 - f1 * (x1 - x0) / (f1 - f0)
        x0, x1 = x1, x2
    return x2

def quadratic_bezier(a, b, c, t):
    return bilinear(a, b, c, t)[1]

def inverse_quadratic_bezier(a, b, c, value):
    return secant_method(lambda x: quadratic_bezier(a, b, c, x) - value)

def clamp(min_val, max_val, val):
    return max(min_val, min(max_val, val))

def pvector_insert(vector, item, index):
    return vector[:index] + pvector([item]) + vector[index:]

def frames_to_time(frames, fps):
    time = frames / fps
    min, sec = divmod(time, 60)
    hour, min = divmod(min, 60)
    frame = frames % fps
    return (int(hour), int(min), int(sec), int(frame))

def format_time(frames, fps):
    h, m, s, f = frames_to_time(frames, fps)
    fps_digits = int(np.ceil(np.log10(fps + 1)))
    return f'{h:02d}:{m:02d}:{s:02d}:{f:0{fps_digits}d}'

def event_vec(event:tk.Event):
    return np.array((event.x, event.y))

def swap(vec):
    return np.array((vec[1], vec[0]))

def numpy_to_photoimage(array:np.ndarray):
    h, w = array.shape[:2]
    ppm_header = f'P6 {w} {h} 255 '.encode()
    data = ppm_header + array.tobytes()
    return tk.PhotoImage(width=w, height=h, data=data, format='PPM')

def get_icon_image(name, size, color):
    path = importlib.resources.files(icons).joinpath(f'{name}.svg')
    data = cairosvg.svg2png(file_obj=open(path, 'rb'), output_width=size, output_height=size)
    return tk.PhotoImage(width=size, height=size, data=data, format='png')

def add_tag(widget:tk.Widget, tag):
    widget.bindtags((tag,) + widget.bindtags())

def _setup_button(button, name, icon_name, size):
    icon = get_icon_image(icon_name, size=size, color='#ffffff')
    button.config(image=icon)
    button.__icon = icon
    if name is not None:
        tooltip.ToolTip(button, text=name)
    return button

def make_button(master, name, icon_name, command, size=20):
    return _setup_button(ttk.Button(master, command=command, bootstyle='outline'), name, icon_name, size)

def make_checkbutton(master, name, icon_name, variable, size=22):
    return _setup_button(ttk.Checkbutton(master, variable=variable, bootstyle='outline-toolbutton'), name, icon_name, size)

def make_radiobutton(master, name, icon_name, value, variable, size=22):
    return _setup_button(ttk.Radiobutton(master, value=value, variable=variable, bootstyle='outline-toolbutton'), name, icon_name, size)

class FlowLayout(ttk.Frame):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.master.bind('<Configure>', self._on_resize, True)

    def _on_resize(self, event):
        max_width = event.width
        row_width = 0
        row_height = 0
        row_y = 0
        row = []
        def center():
            x = 0
            for child in row:
                child.place(
                    x=(max_width - row_width) / 2 + x,
                    y=(row_height - child.winfo_reqheight()) / 2 + row_y,
                )
                x += child.winfo_reqwidth()
            row.clear()
        for child in self.winfo_children():
            next_width = child.winfo_reqwidth()
            if row_width != 0 and next_width + row_width >= max_width:
                center()
                row_y += row_height
                row_width = 0
                row_height = 0
            row.append(child)
            row_width += next_width
            row_height = max(row_height, child.winfo_reqheight())
        center()
        self.configure(height=row_y + row_height)

class timeit():
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = time.time()

    def __exit__(self, exc_type, exc, tb):
        t = (time.time() - self.start) * 1000
        print(f'{self.name} {t:.2f}')

class Observable():
    def __init__(self):
        self.callbacks = set()

    def add(self, callback):
        try:
            self.callbacks.add(weakref.WeakMethod(callback, self.remove))
        except:
            self.callbacks.add(callback)

    def remove(self, callback):
        self.callbacks.discard(callback)

    def call(self, *args, **kwargs):
        for callback in self.callbacks:
            if isinstance(callback, weakref.WeakMethod):
                cb = callback()
            else:
                cb = callback
            if cb:
                cb(*args, **kwargs)

    def call_catch(self, *args, **kwargs):
        for callback in self.callbacks:
            if isinstance(callback, weakref.WeakMethod):
                cb = callback()
            else:
                cb = callback
            if cb:
                try:
                    cb(*args, **kwargs)
                except Exception as ex:
                    print(ex)

    def __iadd__(self, callback):
        self.add(callback)
        return self

    def __isub__(self, callback):
        self.remove(callback)
        return self

    def __call__(self, *args, **kwargs):
        self.call(*args, **kwargs)

class Box():
    def __init__(self, value=None):
        self._value = value
        self.value_changed = Observable()

    def set(self, value):
        self._value = value
        self.value_changed(self._value)

    def get(self):
        return self._value

class Settings:
    def __init__(self, file_name):
        self._file_path = Path.home() / file_name
        self._data = {}
        self._vars = {}
        try:
            if self._file_path.exists():
                with self._file_path.open('rb') as fp:
                    self._data = pickle.load(fp)
                    for item in self._data.items():
                        self.get(*item)
        except Exception as ex:
            print(ex)

    def get(self, key, default) -> Box:
        if key in self._vars:
            return self._vars.get(key)
        var = Box(default)
        def save(value):
            self._data[key] = var.get()
        var.value_changed += save
        self._vars[key] = var
        return var

    def save(self):
        with self._file_path.open('wb') as fp:
            pickle.dump(self._data, fp)

settings = Settings(f'.{__package__}')