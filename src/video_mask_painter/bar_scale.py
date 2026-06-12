import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc

import numpy as np

from . import util

_power_points = [
    np.array((0, 0)),
    np.array((1, 0)),
    np.array((1, 1.01)),
]

class BarScale(ttk.Canvas):
    LINEAR = 0
    CURVE = 1
    def __init__(self, master=None, label='', value=0, minval=0, maxval=100, scale_type=LINEAR, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._background_id = self.create_rectangle(
            0, 0, 0, 0,
            fill="#292929"
        )
        self._bar_id = self.create_rectangle(
            0, 0, 0, 0,
            fill="#57516C",
            outline=''
        )
        self._border_id = self.create_rectangle(
            0, 0, 0, 0,
            fill='',
            outline='#000000'
        )
        self._label_id = self.create_text(
            0, 0,
            anchor=ttkc.W,
            fill='#ffffff',
            text=label
        )
        self._value_id = self.create_text(
            0, 0,
            anchor=ttkc.E,
            fill='#ffffff'
        )
        self._bar_value = 0
        self._value = value
        self._minval = minval
        self._maxval = maxval
        self._last_x = 0
        self._dragging = False
        self._precise_dragging = False
        self._scale_type = scale_type
        self.value_updated_event = util.Observable()
        self.update_stopped_event = util.Observable()
        self.bind('<Configure>', self._on_resize)
        self.bind('<Button-1>', self._on_drag_start)
        self.bind('<ButtonRelease-1>', self._on_drag_stop)
        self.bind('<Button-3>', self._on_precise_drag_start)
        self.bind('<ButtonRelease-3>', self._on_precise_drag_stop)
        self.bind('<Motion>', self._on_motion)
        self.bind('<Button-4>', self._on_incr_value)
        self.bind('<Button-5>', self._on_decr_value)
        self.bind('<MouseWheel>', self._on_mousewheel)
        self.set_value(value)

    def get_value(self):
        return self._value

    def set_value(self, value):
        self._value = util.clamp(self._minval, self._maxval, value)
        self._bar_value = self._value_to_bar_position(self._value)
        self._update_value_view()

    def _value_to_bar_position(self, value):
        if self._scale_type == self.CURVE:
            y = value / (self._maxval - self._minval)
            bar_value = util.inverse_quadratic_bezier(*_power_points, util.clamp(0, 1, y))
        else:
            bar_value = value / (self._maxval - self._minval)
        return util.clamp(0, 1, bar_value)

    def _bar_position_to_value(self, bar_value):
        if self._scale_type == self.CURVE:
            value = (self._maxval - self._minval) * util.quadratic_bezier(*_power_points, util.clamp(0, 1, bar_value))
        else:
            value = (self._maxval - self._minval) * bar_value
        return util.clamp(self._minval, self._maxval, value)

    def _update_value_view(self):
        h = self.winfo_height()
        w = self.winfo_width()
        self.coords(self._bar_id, 0, 0, self._bar_value * w, h)
        self.coords(self._value_id, w - 5, h / 2)
        self.itemconfig(self._value_id, text=str(int(self._value)))
        self.value_updated_event(self._value)

    def _on_resize(self, event:tk.Event):
        h = self.winfo_height()
        w = self.winfo_width()
        self.coords(self._background_id, 0, 0, w, h)
        self.coords(self._border_id, 0, 0, w - 1, h - 1)
        self.coords(self._label_id, 5, h / 2)
        self._update_value_view()

    def _on_drag_start(self, event:tk.Event):
        self._last_x = event.x
        self._dragging = True
        self._on_motion(event)
        return "break"

    def _on_drag_stop(self, event:tk.Event):
        self._dragging = False
        self.update_stopped_event()
        return "break"

    def _on_precise_drag_start(self, event:tk.Event):
        self._last_x = event.x
        self._precise_dragging = True
        return "break"

    def _on_precise_drag_stop(self, event:tk.Event):
        self._precise_dragging = False
        self.update_stopped_event()
        return "break"

    def _on_motion(self, event:tk.Entry):
        w = self.winfo_width()
        if self._dragging:
            self._bar_value = event.x / w
        elif self._precise_dragging:
            delta = (event.x - self._last_x) / (w * 10)
            self._bar_value += delta
        if self._dragging or self._precise_dragging:
            self._value = self._bar_position_to_value(self._bar_value)
            self._update_value_view()
        self._last_x = event.x

    def _on_incr_value(self, event:tk.Entry):
        self.set_value(self._value + 1)
        return "break"

    def _on_decr_value(self, event:tk.Entry):
        self.set_value(self._value - 1)
        return "break"

    def _on_mousewheel(self, event:tk.Entry):
        if event.delta > 0:
            self._on_incr_value()
        else:
            self._on_decr_value()
        return "break"