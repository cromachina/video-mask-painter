import asyncio
import logging
from pathlib import Path
import threading
import importlib.metadata
import time

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap.widgets import tooltip
from ttkbootstrap_icons_bs import BootstrapIcon
from tkinter import filedialog

import numpy as np
import cv2
from pyrsistent import *

from . import asynctk

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

class AsyncTk(tk.Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protocol('WM_DELETE_WINDOW', self.stop)
        self.running = False
        self.sleep_time = 1.0 / 60.0

    def cleanup(self):
        pass

    def stop(self):
        self.running = False
        self.cleanup()

    async def async_main_loop(self):
        self.running = True
        while self.running:
            self.update()
            await asyncio.sleep(self.sleep_time)

class AsyncTkCallback:
    tasks = set()

    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        task = asyncio.create_task(self.func(*args, **kwargs))
        AsyncTkCallback.tasks.add(task)
        task.add_done_callback(AsyncTkCallback.tasks.discard)

class Keyframe(PClass):
    index = field(type=int)
    mask = field(type=np.ndarray)

class ProjectData(PClass):
    video_file_path = field(Path, factory=Path)
    keyframes = pvector_field(Keyframe)
    selected_frame = field(type=int)

    def get_keyframe(frame_index):
        # Binary search keyframes
        pass

def make_button(master, name, icon_name, command):
    icon = BootstrapIcon(icon_name, size=20, color='#ffffff', style='outline')
    button = ttk.Button(master, image=icon, command=command, bootstyle='outline')
    button.pack(side=ttkc.LEFT)
    tooltip.ToolTip(button, text=name)
    return button

def make_checkbutton(master, name, icon_name):
    icon = BootstrapIcon(icon_name, size=22, color='#ffffff', style='outline')
    button = ttk.Checkbutton(master, image=icon, bootstyle='outline-toolbutton')
    button.pack(side=ttkc.LEFT)
    tooltip.ToolTip(button, text=name)
    return button

def make_radiobutton(master, name, icon_name, value, variable):
    icon = BootstrapIcon(icon_name, size=22, color='#ffffff', style='outline')
    button = ttk.Radiobutton(master, image=icon, value=value, variable=variable, bootstyle='outline-toolbutton')
    button.pack(side=ttkc.LEFT)
    tooltip.ToolTip(button, text=name)
    return button

def make_separator(master):
    sep = ttk.Separator(master, orient=ttkc.VERTICAL)
    sep.pack(side=ttkc.LEFT, padx=5)

side_pad = 15

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

        self.drag_update_delay = 0.1
        self.mouse_event = None
        self.drag_check = False
        self.timer = asyncio.create_task(self.update_task())

        self.bind('<Button-1>', self.on_drag_start)
        self.bind('<Motion>', self.on_motion)
        self.bind('<ButtonRelease-1>', self.on_drag_stop)
        self.bind('<Destroy>', self.on_destroy)

    def on_destroy(self, event):
        self.timer.cancel()

    def reg_obj(self, obj):
        self.objects[obj.id] = obj

    def on_resize(self, event):
        for object in self.objects.values():
            object.on_resize()

    def set_position(self, position):
        self.position_marker.set_position(position)

    def set_pos_updated_callback(self, cb):
        self.pos_updated_callback = cb

    def on_drag_start(self, event):
        self.on_click(event)
        self.drag_check = True

    def on_motion(self, event):
        self.mouse_event = event
        if self.drag_check:
            self.update_marker_position(self.mouse_event)

    def on_drag(self, event):
        self.update_marker_position(self.mouse_event)

    def on_drag_stop(self, event):
        self.on_click(event)
        self.drag_check = False

    async def update_task(self):
        while True:
            await asyncio.sleep(self.drag_update_delay)
            if self.drag_check:
                self.on_click(self.mouse_event)

    def event_to_position(self, event):
        w = self.winfo_width() - side_pad * 2
        return min(1.0, max(0.0, (event.x - side_pad) / w))

    def update_marker_position(self, event):
        position = self.event_to_position(event)
        self.set_position(position)
        return position

    def on_click(self, event):
        position = self.update_marker_position(event)
        if self.pos_updated_callback:
            self.pos_updated_callback(position)

    def add_keyframe(self, position):
        return KeyframeMarker(self, position)

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

class VideoPlayer(tk.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._video = None
        self._frame_count = 0
        self._fps = 60
        self._video_id = None
        self._photo_image = None
        self._pos_updated_callback = None
        self._playing = False
        self._timer = asyncio.create_task(self.update_task())
        self.bind('<Destroy>', self.on_destroy)

    def on_destroy(self, event):
        self._timer.cancel()

    async def update_task(self):
        while True:
            await asyncio.sleep(1.0 / self.get_fps())
            if self._playing:
                self.read_frame()

    def set_pos_updated_callback(self, cb):
        self._pos_updated_callback = cb

    def open_video(self, file_path:Path):
        self.close_video()
        if not file_path.exists():
            # TODO Show error
            return
        self._video = cv2.VideoCapture(str(file_path))
        self._frame_count = self._video.get(cv2.CAP_PROP_FRAME_COUNT)
        self._fps = self._video.get(cv2.CAP_PROP_FPS)
        self._video_id = self.create_image((0, 0), anchor=ttkc.NW)

    def close_video(self):
        if self._video is None:
            return
        self._video.release()
        self._video = None
        self._frame_count = 0
        self._fps = 60
        self.delete(self._video_id)
        self._video_id = None

    def get_frame_pos(self):
        if not self._video:
            return 0
        return self._video.get(cv2.CAP_PROP_POS_FRAMES)

    def get_frame_count(self):
        return self._frame_count

    def get_fps(self):
        return self._fps

    def get_time_string(self):
        curr_time = format_time(self.get_frame_pos(), self.get_fps())
        total_time = format_time(self.get_frame_count(), self.get_fps())
        return f'{curr_time} / {total_time}'

    def set_frame_pos(self, frame):
        if not self._video:
            return
        self._video.set(cv2.CAP_PROP_POS_FRAMES, frame - 1)
        self.read_frame()

    def read_frame(self):
        if not self._video:
            return
        ret, image = self._video.read()
        if not ret:
            return
        height, width = image.shape[:2]
        ppm_header = f'P6 {width} {height} 255 '.encode()
        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, image)
        data = ppm_header + image.tobytes()
        self._photo_image = tk.PhotoImage(width=width, height=height, data=data, format='PPM')
        self.itemconfig(self._video_id, image=self._photo_image)
        if self._pos_updated_callback:
            self._pos_updated_callback(self.get_frame_pos() / self.get_frame_count())

    def play(self):
        self._playing = True

    def pause(self):
        self._playing = False

    def previous_frame(self):
        if not self._video:
            return
        pos = self.get_frame_pos() - 1
        self.set_frame_pos(pos)

    def next_frame(self):
        if not self._video:
            return
        self.read_frame()

    def seek(self, position):
        if not self._video:
            return
        frame = int(self._frame_count * position)
        self.set_frame_pos(frame)

class App(asynctk.AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {__version__}')
        self.geometry('{}x{}'.format(1000, 600))
        ttk.Style('darkly')

        self.undo_stack = []
        self.project = None

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
        self.video_player = VideoPlayer(self, width=1, height=1)
        self.video_player.pack(fill=ttkc.BOTH, expand=True)

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
        label = ttk.Label(button_frame, text='Brush size')
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

        button_frame = ttk.Frame(self)
        button_frame.pack()

        self.time_label = ttk.Label(button_frame)
        self.time_label.pack(side=ttkc.LEFT)
        self.video_file_name_label = ttk.Label(button_frame)
        self.video_file_name_label.pack(side=ttkc.LEFT)

        # Timeline and info
        # TODO Zoom and pan timeline?

        self.timeline = Timeline(self, height=50)
        self.timeline.pack(fill=ttkc.X)
        self.timeline.set_pos_updated_callback(self.video_player.seek)
        self.video_player.set_pos_updated_callback(self.position_updated)
        self.position_updated(0)

        self.bind_all('<MouseWheel>', self.on_mousewheel)
        self.bind_all('<Button-4>', lambda _: self.previous_frame())
        self.bind_all('<Button-5>', lambda _: self.next_frame())

    def position_updated(self, position):
        self.time_label.config(text=self.video_player.get_time_string())
        self.timeline.set_position(position)

    def open_video(self):
        file_name = filedialog.askopenfilename(
            title='Open Video',
            filetypes=(('MP4', '*.mp4'), ('Any', '*.*')),
        )
        if file_name:
            self.project = ProjectData(video_file_path=file_name)
            self.video_player.open_video(self.project.video_file_path)
            self.video_player.next_frame()
            self.video_file_name_label.config(text=f'({self.project.video_file_path.name})')

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
        self.video_player.play()

    def pause_video(self):
        self.video_player.pause()

    def previous_frame(self):
        self.video_player.previous_frame()

    def next_frame(self):
        self.video_player.next_frame()

    def on_mousewheel(self, event):
        if event.delta > 0:
            self.next_frame()
        else:
            self.previous_frame()

async def async_main():
    await App().async_main_loop()

def main():
    asyncio.run(async_main())