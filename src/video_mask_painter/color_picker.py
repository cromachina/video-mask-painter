import colorsys

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc

import numpy as np

from .util import *

def _make_sat_value_gradient(width, height, tint):
    sat = np.tile(np.linspace((1, 1, 1), tint, width), (height, 1)).reshape(height, width, 3)
    val = np.linspace((1, 1, 1), (0, 0, 0), height).repeat(width, axis=0).reshape(height, width, 3)
    return (sat * val * 255).astype(np.ubyte)

def _color_to_position(color):
    h, s, v = colorsys.rgb_to_hsv(*map(lambda x: x / 255.0, color))
    return h, s, (1 - v)

class ColorBox(ttk.Canvas):
    def __init__(self, master=None, initial_color=(0, 0, 0), *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._gradient_id = self.create_image(0, 0, anchor=ttkc.NW)
        self._selector_size = 6
        self._selector_id = self.create_oval(0, 0, self._selector_size, self._selector_size, fill='', outline='#ffffff')
        self._photoimage = None
        self._gradient_array = None
        hsv = _color_to_position(initial_color)
        self._selector_pos = hsv[1:]
        self._hue = hsv[0]
        self.bind('<Configure>', self._on_resize)
        self.bind('<Button-1>', self._on_click)
        self.bind('<B1-Motion>', self._on_click)
        self.color_selected_event = Observable()

    def _to_rel(self, xy):
        relx = xy[0] / (self.winfo_width() - 1)
        rely = xy[1] / (self.winfo_height() - 1)
        return np.array((relx, rely))

    def _from_rel(self, relxy):
        x = int(relxy[0] * (self.winfo_width() - 1))
        y = int(relxy[1] * (self.winfo_height() - 1))
        return np.array((x, y))

    def _remake_gradient(self):
        h = self.winfo_height()
        w = self.winfo_width()
        tint = colorsys.hsv_to_rgb(self._hue, 1, 1)
        self._gradient_array = _make_sat_value_gradient(w, h, tint)
        ppm_header = f'P6 {w} {h} 255 '.encode()
        data = ppm_header + self._gradient_array.tobytes()
        self._photoimage = tk.PhotoImage(width=w, height=h, data=data, format='PPM')
        self.itemconfig(self._gradient_id, image=self._photoimage)

    def _update_selector(self):
        xy = self._from_rel(self._selector_pos)
        offset = self._selector_size / 2
        self.moveto(self._selector_id, *(xy - offset))

    def _on_resize(self, event:tk.Event=None):
        self._remake_gradient()
        self._update_selector()

    def _set_color_position(self, x, y):
        self._selector_pos = self._to_rel((x, y))
        self._update_selector()
        self.color_selected_event(self.get_color())

    def _set_color_rel(self, relx, rely):
        self._selector_pos = (relx, rely)
        self._update_selector()
        self.color_selected_event(self.get_color())

    def _on_click(self, event:tk.Event):
        y = clamp(0, self.winfo_height() - 1, event.y)
        x = clamp(0, self.winfo_width() - 1, event.x)
        self._set_color_position(x, y)

    def get_color(self) -> None:
        s, v = self._selector_pos
        v = 1 - v
        return (np.array(colorsys.hsv_to_rgb(self._hue, s, v)) * 255.0).astype(np.ubyte)

    def set_color(self, color):
        h, s, v = _color_to_position(color)
        self._hue = h
        self._remake_gradient()
        self._set_color_rel(s, v)

class ColorBar(ttk.Canvas):
    def __init__(self, master=None, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._id = self.create_image(0, 0, anchor=ttkc.NW)
        self._

class ColorPicker(ttk.Canvas):
    def __init__(self, master=None):
        pass