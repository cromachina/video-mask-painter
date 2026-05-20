import colorsys

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc

import numpy as np

from .util import *

_checker_params = (0.1, 0.3, 5)
_color_picker_tag = "colorpicker"

def _make_sat_value_gradient(width, height, tint):
    sat = np.tile(np.linspace((1, 1, 1), tint, width), (height, 1)).reshape(height, width, 3)
    val = np.linspace((1, 1, 1), (0, 0, 0), height).repeat(width, axis=0).reshape(height, width, 3)
    res = sat * val
    return (res * 255).astype(np.ubyte)

def _make_checkers(col_a, col_b, checksize, width, height):
    a = np.full((checksize, checksize, 1), col_a)
    b = np.full((checksize, checksize, 1), col_b)
    c2 = checksize * 2
    block = np.vstack((np.hstack((a, b)), np.hstack((b, a)))).reshape(c2, c2)
    return np.tile(block, (int(np.ceil(height / c2)), int(np.ceil(width / c2))))[:height,:width].reshape(height, width, 1)

def _make_alpha_gradient(width, height, tint):
    color = np.full((height, width, 3), fill_value=tint)
    alpha = np.linspace(1.0, 0.0, height).repeat(width, axis=0).reshape(height, width, 1)
    check = _make_checkers(*_checker_params, width, height)
    res = color * alpha + check * (1 - alpha)
    return (res * 255).astype(np.ubyte)

def _make_hue_gradient(width, height):
    hue = np.linspace(0, 1, height)
    res = np.empty((height, 3))
    for i in range(len(hue)):
        res[i] = colorsys.hsv_to_rgb(hue[i], 1, 1)
    res = res.repeat(width, axis=0).reshape(height, width, 3)
    return (res * 255).astype(np.ubyte)

def _make_color_preview(width, height, color, alpha):
    color = np.full((height, width, 3), fill_value=color)
    check = _make_checkers(*_checker_params, width, height)
    res = color * alpha + check * (1 - alpha)
    return (res * 255).astype(np.ubyte)

def _color_to_position(color):
    h, s, v = colorsys.rgb_to_hsv(*map(lambda x: x / 255.0, color))
    return h, s, (1 - v)

class ColorBox(ttk.Canvas):
    def __init__(self, master=None, initial_color=(0, 0, 0), *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        add_tag(self, _color_picker_tag)
        self._gradient_id = self.create_image(0, 0, anchor=ttkc.NW)
        self._selector_size = 6
        self._selector_id = self.create_oval(0, 0, self._selector_size, self._selector_size, fill='', outline='#ffffff')
        self._photoimage = None
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
        gradient = _make_sat_value_gradient(w, h, tint)
        self._photoimage = numpy_to_photoimage(gradient)
        self.itemconfig(self._gradient_id, image=self._photoimage)

    def _update_selector(self):
        xy = self._from_rel(self._selector_pos)
        offset = self._selector_size / 2
        self.moveto(self._selector_id, *(xy - offset))

    def _on_resize(self, event:tk.Event):
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

    def set_hue(self, hue):
        self._hue = hue / 255
        self._remake_gradient()
        self.color_selected_event(self.get_color())

class ColorBar(ttk.Canvas):
    def __init__(self, master=None, initial_color=(0, 0, 0), initial_alpha=255, hue_mode=False, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        add_tag(self, _color_picker_tag)
        self._background_id = self.create_image(0, 0, anchor=ttkc.NW)
        self._selector_id = self.create_rectangle(
            0, 0, 0, 0,
            fill='',
            outline='#ffffff')
        self._hue_mode = hue_mode
        self._selector_size = 3
        if self._hue_mode:
            self._selector_pos = colorsys.rgb_to_hsv(*(np.array(initial_color) / 255))[0]
        else:
            self._selector_pos = 1 - (initial_alpha / 255)
        self._photoimage = None
        self._color = initial_color
        self.bind('<Configure>', self._on_resize)
        self.bind('<Button-1>', self._on_click)
        self.bind('<B1-Motion>', self._on_click)
        self.color_selected_event = Observable()

    def _remake_gradient(self):
        h = self.winfo_height()
        w = self.winfo_width()
        if self._hue_mode:
            gradient = _make_hue_gradient(w, h)
        else:
            gradient = _make_alpha_gradient(w, h, np.array(self._color) / 255.0)
        self._photoimage = numpy_to_photoimage(gradient)
        self.itemconfig(self._background_id, image=self._photoimage)

    def _update_selector(self):
        h = self.winfo_height()
        self.moveto(self._selector_id, -1, self._selector_pos * (h - self._selector_size - 1) - 1)

    def _on_resize(self, event:tk.Event):
        w = self.winfo_width()
        self.coords(self._selector_id, 0, 0, w - 1, self._selector_size)
        self._update_selector()
        self._remake_gradient()

    def _on_click(self, event:tk.Event):
        h = self.winfo_height()
        self._selector_pos = clamp(0, 1, event.y / h)
        self._update_selector()
        value = int((self._selector_pos if self._hue_mode else 1 - self._selector_pos) * 255)
        self.color_selected_event(value)

    def set_color(self, color):
        self._color = color
        self._remake_gradient()

class ColorPicker(ttk.Frame):
    def __init__(self, master=None, initial_color=(0, 0, 0), initial_alpha=255, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        add_tag(self, _color_picker_tag)
        self._color_box = ColorBox(self, initial_color, height=0, width=0)
        self._color_box.pack(side=ttkc.LEFT, expand=True, fill=ttkc.BOTH)
        self._alpha_bar = ColorBar(self, initial_color, initial_alpha, height=1, width=20)
        self._alpha_bar.pack(side=ttkc.LEFT, padx=7, fill=ttkc.Y)
        self._hue_bar = ColorBar(self, initial_color, hue_mode=True, width=20)
        self._hue_bar.pack(side=ttkc.LEFT, fill=ttkc.Y)
        self._color_box.color_selected_event += self._alpha_bar.set_color
        self._hue_bar.color_selected_event += self._color_box.set_hue
        self.color_selected_event = self._color_box.color_selected_event
        self.alpha_selected_event = self._alpha_bar.color_selected_event

class ColorPickerHover(ttk.Canvas):
    def __init__(self, master=None, initial_color=(0, 0, 0), initial_alpha=255, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._id = self.create_image(0, 0, anchor=ttkc.NW)
        self._border_id = self.create_rectangle(
            0, 0, 0, 0,
            fill='',
            outline='#000000')
        self._photoimage = None
        self._color = initial_color
        self._alpha = initial_alpha
        self._popup = tk.Toplevel()
        self._popup.overrideredirect(True)
        self._popup.geometry('250x150')
        self._popup.withdraw()
        self._color_picker = ColorPicker(self._popup, initial_color, initial_alpha)
        self._color_picker.pack(fill=ttkc.BOTH, expand=True, padx=7, pady=7)
        self._timeout = None
        self._stay_open = False
        self.bind('<Configure>', self._on_resize)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self._popup.bind('<Enter>', self._on_popup_enter)
        self._color_picker.bind_class(_color_picker_tag, '<Button-1>', self._on_popup_click, '+')
        self._popup.bind('<Leave>', self._on_leave)
        self.winfo_toplevel().bind('<Button-1>', self._close_popup, '+')
        self.winfo_toplevel().bind('<FocusOut>', self._close_popup, '+')
        self._color_picker.color_selected_event += self._on_color_selected
        self._color_picker.alpha_selected_event += self._on_alpha_selected
        self.color_selected_event = self._color_picker.color_selected_event
        self.alpha_selected_event = self._color_picker.alpha_selected_event

    def _update_color(self):
        h = self.winfo_height()
        w = self.winfo_width()
        color = _make_color_preview(w, h, np.array(self._color) / 255.0, self._alpha / 255)
        self._photoimage = numpy_to_photoimage(color)
        self.itemconfig(self._id, image=self._photoimage)

    def _on_resize(self, event:tk.Event):
        h = self.winfo_height()
        w = self.winfo_width()
        self.coords(self._border_id, 0, 0, w - 1, h - 1)
        self._update_color()

    def _on_enter(self, event:tk.Event):
        self._popup.deiconify()
        y = self.winfo_rooty() - self._popup.winfo_height()
        x = self.winfo_rootx() - self._popup.winfo_width() + self.winfo_width()
        self._popup.geometry('+{}+{}'.format(x, y))

    def _on_leave(self, event):
        if not self._stay_open:
            self._timeout = self.after(250, self._close_popup)

    def _close_popup(self, *args):
        self._popup.withdraw()
        self._stay_open = False

    def _on_popup_enter(self, event):
        if self._timeout:
            self.after_cancel(self._timeout)
            self._timeout = None

    def _on_popup_click(self, event):
        print('clicked')
        self._stay_open = True

    def _on_color_selected(self, color):
        self._color = color
        self._update_color()

    def _on_alpha_selected(self, alpha):
        self._alpha = alpha
        self._update_color()