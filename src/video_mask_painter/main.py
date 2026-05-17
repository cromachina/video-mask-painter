import asyncio
import logging
from pathlib import Path
import threading
import importlib.metadata

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap.widgets import tooltip
from ttkbootstrap_icons_bs import BootstrapIcon
from tkinter import filedialog

import numpy as np
from pyrsistent import *

from . import asynctk

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

class Keyframe(PClass):
    index = field(type=int)
    mask = field(type=np.ndarray)

class VideoMaskData(PClass):
    keyframes = pvector_field(Keyframe)
    selected_frame = field(type=int)

    def get_keyframe(frame_index):
        # Binary search keyframes
        pass

def make_button(master, name, icon_name, command):
    icon = BootstrapIcon(icon_name, size=20, color="#ffffff", style='outline')
    button = ttk.Button(master, image=icon, command=command, bootstyle='outline')
    button.pack(side=ttkc.LEFT)
    tooltip.ToolTip(button, text=name)
    return button

def make_checkbutton(master, name, icon_name):
    icon = BootstrapIcon(icon_name, size=22, color="#ffffff", style='outline')
    button = ttk.Checkbutton(master, image=icon, bootstyle='outline-toolbutton')
    button.pack(side=ttkc.LEFT)
    tooltip.ToolTip(button, text=name)
    return button

def make_radiobutton(master, name, icon_name, value, variable):
    icon = BootstrapIcon(icon_name, size=22, color="#ffffff", style='outline')
    button = ttk.Radiobutton(master, image=icon, value=value, variable=variable, bootstyle='outline-toolbutton')
    button.pack(side=ttkc.LEFT)
    tooltip.ToolTip(button, text=name)
    return button

def make_separator(master):
    sep = ttk.Separator(master, orient=ttkc.VERTICAL)
    sep.pack(side=ttkc.LEFT, padx=5)

side_pad = 5

class MeterLine():
    def __init__(self, canvas:ttk.Canvas, position, color):
        self.canvas = canvas
        self.position = position
        self.id = self.canvas.create_line(0, 0, 0, 0, fill=color)
        self.canvas.reg_obj(self)

    def on_resize(self):
        h = self.canvas.winfo_height()
        w = self.canvas.winfo_width() - side_pad * 2
        x = self.position * w + side_pad
        self.canvas.coords(self.id, x, 0, x, h)

    def set_position(self, position):
        self.position = position
        self.on_resize()

class FramePositionMarker():
    def __init__(self, canvas:ttk.Canvas):
        h = 10
        self.w = 20
        self.canvas = canvas
        self.position = 0.0
        self.id = self.canvas.create_polygon(
            0, 0, self.w // 2, h, self.w, 0,
            fill='#ffffff')
        self.canvas.reg_obj(self)

    def on_resize(self):
        w = self.canvas.winfo_width() - side_pad * 2
        x = self.position * w + side_pad - self.w / 2
        self.canvas.moveto(self.id, x, 0)

    def set_position(self, position):
        self.position = position
        self.on_resize()

class KeyframeMarker():
    def __init__(self, canvas:ttk.Canvas, position):
        self.canvas = canvas
        self.position = position
        radius = 7
        self.radius = radius
        self.id = self.canvas.create_polygon(
            -radius, 0, 0, radius, radius, 0, 0, -radius,
            fill='#c3c3c3',
            outline='#000000',
            activefill='#ff0000',
        )
        self.canvas.reg_obj(self)

    def on_resize(self):
        h = self.canvas.winfo_height()
        w = self.canvas.winfo_width() - side_pad * 2
        x = self.position * w - side_pad + 1
        y = h / 2 - self.radius
        self.canvas.moveto(self.id, x, y)

class Timeline(tk.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bind('<Configure>', self.on_resize)
        self.objects = {}

        line_count = 24
        light = '#717171'
        dark = '#353535'
        for i in range(line_count + 1):
            position = i / line_count
            MeterLine(self, position, light if i % 2 == 0 else dark)

        self.position_marker = FramePositionMarker(self)
        self.position_marker.set_position(0.33)

    def reg_obj(self, obj):
        self.objects[obj.id] = obj

    def on_resize(self, event):
        for object in self.objects.values():
            object.on_resize()

    def add_keyframe(self, position):
        return KeyframeMarker(self, position)

class App(asynctk.AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {__version__}')
        self.geometry('{}x{}'.format(1000, 600))
        ttk.Style('darkly')

        self.undo_stack = []

        # Menu bar
        # Open Video, Open Project, Save Project, Render Video, Exit
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        file_menu = tk.Menu(menubar)
        menubar.add_cascade(label='File', menu=file_menu)
        file_menu.add_command(label='Open Video', command=self.open_video)
        file_menu.add_command(label='Open Project', command=self.open_project)
        file_menu.add_command(label='Save Project', command=self.save_project)
        file_menu.add_command(label='Save As Project', command=self.save_as_project)
        file_menu.add_command(label='Render Video', command=self.render_video)
        file_menu.add_command(label='Exit', command=self.exit)

        # Video and drawing area
        # Click to draw
        # space + click to pan
        # scroll to zoom
        self.viewport = tk.Canvas(self, width=1, height=1)
        self.viewport.pack(fill=ttkc.BOTH, expand=True)

        # Project Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack()
        make_button(button_frame, 'Undo', 'arrow-90deg-left', self.undo)
        make_button(button_frame, 'Redo', 'arrow-90deg-right', self.redo)

        # Keyframe Buttons
        make_button(button_frame, 'Previous keyframe', 'arrow-left-square', self.previous_keyframe)
        make_button(button_frame, 'Next keyframe', 'arrow-right-square', self.next_keyframe)
        make_button(button_frame, 'Add blank keyframe', 'plus-square', self.add_blank_keyframe)
        make_button(button_frame, 'Clone keyframe', 'copy', self.clone_keyframe)
        make_button(button_frame, 'Delete keyframe', 'x-square', self.delete_keyframe)

        # Video playback buttons
        make_button(button_frame, 'Play video', 'play', self.play_video)
        make_button(button_frame, 'Pause video', 'pause', self.pause_video)
        make_button(button_frame, 'Previous frame', 'arrow-left-short', self.previous_frame)
        make_button(button_frame, 'Next frame', 'arrow-right-short', self.next_frame)
        self.loop_button = make_checkbutton(button_frame, 'Toggle loop video', 'repeat')

        # TODO FPS field

        make_separator(button_frame)

        # Auto-keyframe radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.auto_keyframe_off = 'off'
        self.auto_keyframe_blank = 'blank'
        self.auto_keyframe_clone = 'clone'
        self.auto_keyframe_var = ttk.StringVar(value=self.auto_keyframe_off)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe off', 'window-x', self.auto_keyframe_off, self.auto_keyframe_var)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe blank', 'window-plus', self.auto_keyframe_blank, self.auto_keyframe_var)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe clone', 'window-stack', self.auto_keyframe_clone, self.auto_keyframe_var)

        make_separator(button_frame)

        # Drawing mode radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.drawing_mode_draw = 'draw'
        self.drawing_mode_erase = 'erase'
        self.drawing_mode_var = ttk.StringVar(value=self.drawing_mode_draw)
        make_radiobutton(radio_frame, 'Toggle draw', 'pencil', self.drawing_mode_draw, self.drawing_mode_var)
        make_radiobutton(radio_frame, 'Toggle erase', 'eraser', self.drawing_mode_erase, self.drawing_mode_var)

        make_separator(button_frame)

        # Brush size selector
        label = ttk.Label(button_frame, text="Brush size")
        label.pack(side=ttkc.LEFT)
        self.brush_scale_var = ttk.IntVar(value=1)
        brush_scale = ttk.Scale(button_frame, variable=self.brush_scale_var, from_=1, to=1000)
        brush_scale.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.brush_size_var = ttk.IntVar()
        def scale_brush_val(*_):
            x = self.brush_scale_var.get()
            v = int(2 ** (x / 100))
            self.brush_size_var.set(v)
        self.brush_scale_var.trace_add('write', scale_brush_val)
        scale_brush_val()
        label = ttk.Label(button_frame, textvariable=self.brush_size_var, width=5)
        label.pack(side=ttkc.LEFT)

        # Timeline and info

        self.timeline = Timeline(self, height=50)
        self.timeline.pack(fill=ttkc.X)
        self.timeline.add_keyframe(0.0)
        self.timeline.add_keyframe(0.25)
        self.timeline.add_keyframe(0.5)
        self.timeline.add_keyframe(0.75)
        self.timeline.add_keyframe(1.0)

        # Video file name label
        # Project file name label
        # Time/total time label
        # Seek bar with keyframe indicator shapes
        # Zoom and scroll?

    def open_video(self):
        pass

    def open_project(self):
        pass

    def save_project(self):
        pass

    def save_as_project(self):
        pass

    def render_video(self):
        pass

    def exit(self):
        # TODO Unsaved work check
        self.stop()

    def cleanup(self):
        self.destroy()

    def undo(self):
        pass

    def redo(self):
        pass

    def previous_keyframe(self):
        pass

    def next_keyframe(self):
        pass

    def add_blank_keyframe(self):
        pass

    def clone_keyframe(self):
        pass

    def delete_keyframe(self):
        pass

    def play_video(self):
        pass

    def pause_video(self):
        pass

    def previous_frame(self):
        pass

    def next_frame(self):
        pass

async def async_main():
    await App().async_main_loop()

def main():
    asyncio.run(async_main())