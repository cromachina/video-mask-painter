import asyncio

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc

from .util import *

_side_pad = 15

class MeterLine():
    def __init__(self, timeline:'Timeline', position:float, color:str):
        self._timeline = timeline
        self._position = position
        self.id = self._timeline.create_line(
            0, 0, 0, 0,
            fill=color,
            state=ttkc.DISABLED)
        self._timeline.reg_obj(self)

    def on_resize(self):
        h = self._timeline.winfo_height()
        w = self._timeline.winfo_width() - _side_pad * 2
        x = self._position * w + _side_pad
        self._timeline.coords(self.id, x, 0, x, h)

    def set_position(self, position:float):
        self._position = position
        self.on_resize()

class FramePositionMarker():
    def __init__(self, timeline:'Timeline'):
        h = 10
        self.w = 20
        self._timeline = timeline
        self._position = 0.0
        self.id = self._timeline.create_polygon(
            0, 0, self.w // 2, h, self.w, 0,
            fill='#ffffff',
            state=ttkc.DISABLED)
        self._timeline.reg_obj(self)

    def on_resize(self):
        w = self._timeline.winfo_width() - _side_pad * 2
        x = self._position * w + _side_pad - self.w / 2
        self._timeline.moveto(self.id, x, 0)

    def set_position(self, position):
        self._position = position
        self.on_resize()

keyframe_color = '#c3c3c3'
keyframe_color_selected = '#ff0000'

class KeyframeMarker():
    def __init__(self, timeline:'Timeline', index:int):
        self._timeline = timeline
        self.index = index
        radius = 7
        self._radius = radius
        self.id = self._timeline.create_polygon(
            -radius, 0, 0, radius, radius, 0, 0, -radius,
            fill=keyframe_color,
            activefill=keyframe_color_selected,
            outline='#000000',
        )
        self._timeline.reg_keyframe(self)
        self._timeline.tag_bind(self.id, '<Button-1>', self._on_click)
        self.on_resize()

    def on_resize(self):
        h = self._timeline.winfo_height()
        w = self._timeline.winfo_width() - _side_pad * 2
        x = self._timeline.index_to_position(self.index) * w + _side_pad - self._radius
        y = h / 2 - self._radius
        self._timeline.moveto(self.id, x, y)

    def _on_click(self, event):
        self._timeline.set_selected_keyframe(self)

    def set_selected(self, state):
        self._timeline.itemconfig(self.id, fill=keyframe_color_selected if state else keyframe_color)

class Timeline(ttk.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._objects = {}
        self._keyframes = {}
        self._selected_keyframe_index = None
        self._current_frame = 0
        self._frame_count = 0
        self._background_area = self.create_rectangle(0, 0, 0, 0, fill="#292929", outline='')
        line_count = 24
        light = '#717171'
        dark = '#353535'
        for i in range(line_count + 1):
            position = i / line_count
            MeterLine(self, position, light if i % 2 == 0 else dark)
        self._position_marker = FramePositionMarker(self)
        self._drag_update_delay = 0.1
        self._mouse_event = None
        self._drag_check = False
        self._task = asyncio.create_task(self._drag_update_task())
        self.bind('<Configure>', self._on_resize)
        self.tag_bind(self._background_area, '<Button-1>', self._on_drag_start)
        self.tag_bind(self._background_area, '<Motion>', self._on_motion)
        self.tag_bind(self._background_area, '<ButtonRelease-1>', self._on_drag_stop)
        self.bind('<Destroy>', self._on_destroy)
        self.position_updated_event = Observable()

    def set_frame_count(self, frame_count:int):
        self._frame_count = frame_count

    def index_to_position(self, index:int) -> float:
        if self._frame_count == 0:
            return 0
        return index / float(self._frame_count)

    def set_selected_keyframe(self, keyframe:KeyframeMarker):
        self.unset_selected_keyframe()
        keyframe.set_selected(True)
        self._selected_keyframe_index = keyframe.index
        self.set_position_marker(keyframe.index)
        self.position_updated_event(keyframe.index)

    def unset_selected_keyframe(self):
        keyframe = self._keyframes.get(self._selected_keyframe_index)
        if keyframe:
            keyframe.set_selected(False)
        self._selected_keyframe_index = None

    def _on_destroy(self, event:tk.Event):
        self._task.cancel()

    def reg_obj(self, obj:object):
        self._objects[obj.id] = obj

    def reg_keyframe(self, keyframe:KeyframeMarker):
        self._keyframes[keyframe.index] = keyframe

    def _on_resize(self, event:tk.Event):
        for object in self._objects.values():
            object.on_resize()
        self.coords(self._background_area, (0, 0, self.winfo_width() - 1, self.winfo_height() - 1))

    def set_position_marker(self, index:int):
        self._position_marker.set_position(self.index_to_position(index))

    def _on_drag_start(self, event:tk.Event):
        self._on_click(event)
        self._drag_check = True

    def _on_motion(self, event:tk.Event):
        self._mouse_event = event
        if self._drag_check:
            self._update_marker_position(self._mouse_event)

    def _on_drag_stop(self, event:tk.Event):
        self._on_click(event)
        self._drag_check = False

    async def _drag_update_task(self):
        while True:
            await asyncio.sleep(self._drag_update_delay)
            if self._drag_check:
                self._on_click(self._mouse_event)

    def _event_to_position(self, event:tk.Event):
        w = self.winfo_width() - _side_pad * 2
        return clamp(0.0, 1.0, (event.x - _side_pad) / w)

    def _update_marker_position(self, event:tk.Event):
        position = self._event_to_position(event)
        self._position_marker.set_position(position)
        return position

    def _on_click(self, event:tk.Event):
        self.unset_selected_keyframe()
        position = self._update_marker_position(event)
        self.position_updated_event(int(position * self._frame_count))

    def add_keyframe(self, index:int):
        return KeyframeMarker(self, index)

    def clear_keyframes(self):
        for keyframe in self._keyframes.values():
            self.delete(keyframe.id)
        self._keyframes.clear()