import asyncio
from pathlib import Path
import importlib.metadata
import time
import weakref
import bisect

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap.widgets import tooltip
from ttkbootstrap_icons_bs import BootstrapIcon
from tkinter import filedialog

import numpy as np
import cv2
from pyrsistent import *

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

def pvector_insert(vector, item, index):
    return vector[:index] + pvector([item]) + vector[index:]

def pvector_popleft(vector):
    return vector[1:]

class timeit():
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = time.time()

    def __exit__(self, exc_type, exc, tb):
        t = int((time.time() - self.start) * 1000)
        print(f'{self.name} {t}')

class Observable():
    def __init__(self):
        self.callbacks = set()

    def add(self, callback):
        self.callbacks.add(weakref.WeakMethod(callback, self.remove))

    def remove(self, callback):
        self.callbacks.discard(callback)

    def call(self, *args, **kwargs):
        for callback in self.callbacks:
            cb = callback()
            if cb:
                cb(*args, **kwargs)

    def __iadd__(self, callback):
        self.add(callback)
        return self

    def __isub__(self, callback):
        self.remove(callback)
        return self

    def __call__(self, *args, **kwargs):
        self.call(*args, **kwargs)

def clamp(min_val, max_val, val):
    return max(min_val, min(max_val, val))

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
    data = field(type=np.ndarray)

class ProjectState(PClass):
    keyframes = pvector_field(Keyframe)
    selected_index = field(initial=None)

    def print_keyframes(self):
        print('----------')
        for keyframe in self.keyframes:
            print(keyframe.index, id(keyframe.data))

    def get_keyframe(self, index):
        if not self.keyframes:
            return None
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return None
        return self.keyframes[ix]

    def get_previous_keyframe(self, index):
        if not self.keyframes:
            return None
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return None
        keyframe = self.keyframes[ix]
        if keyframe.index == index:
            ix -= 1
        if ix < 0:
            return None
        return self.keyframes[ix]

    def get_next_keyframe(self, index):
        if not self.keyframes:
            return None
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index)
        if ix >= len(self.keyframes):
            return None
        keyframe = self.keyframes[ix]
        if keyframe.index == index:
            ix += 1
        if ix >= len(self.keyframes):
            return None
        return self.keyframes[ix]

    def insert_keyframe(self, keyframe:Keyframe):
        ix = bisect.bisect(self.keyframes, keyframe.index, key=lambda x: x.index)
        return self.set(keyframes=pvector_insert(self.keyframes, keyframe, ix))

    def remove_keyframe(self, index:int):
        if not self.keyframes:
            return self
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return self
        return self.set(keyframes=self.keyframes.delete(ix))

    def update_keyframe(self, index, data):
        data.flags.writeable = False
        keyframe = self.get_keyframe(index).set(data=data)
        return self.remove_keyframe(keyframe.index).insert_keyframe(keyframe)

class Project():
    def __init__(self, initial_state:ProjectState, video_file_path:Path, project_file_path:Path|None=None):
        self.video_file_path = video_file_path
        self.project_file_path = project_file_path
        self._states = pvector()
        self._current_index = 0
        self._next_id = 0
        self._saved_id = 0
        self.append(initial_state)

    def get_current(self) -> ProjectState:
        return self._states[self._current_index][1]

    def update_current(self, state:ProjectState):
        self._states = self._states.set(self._current_index, (self.self._get_current_id(), state))

    def _get_current_id(self):
        return self._states[self._current_index][0]

    def append(self, state:ProjectState, state_limit:int|None=None):
        state = (self._next_id, state)
        self._next_id += 1
        self._states = self._states[:self._current_index + 1]
        self._states = self._states.append(state)
        if state_limit is not None and len(self._states) > state_limit:
            delta = len(self._states) - state_limit
            self._states = self._states[delta:]
        self._current_index = len(self._states) - 1

    def undo(self):
        self._current_index = max(0, self._current_index - 1)
        return self.get_current()

    def redo(self):
        self._current_index = min(self._current_index + 1, len(self._states) - 1)
        return self.get_current()

    def can_undo(self):
        return self._current_index != 0

    def can_redo(self):
        return self._current_index != (len(self._states) - 1)

    def is_saved(self):
        return self._saved_id == self._get_current_id()

    def set_saved(self):
        self._saved_id = self._get_current_id()

    def set_dirty(self):
        self._saved_id = None

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

keyframe_color = '#c3c3c3'
keyframe_color_selected = '#ff0000'

class KeyframeMarker():
    def __init__(self, timeline, index):
        self.timeline = timeline
        self.index = index
        radius = 7
        self.radius = radius
        self.id = self.timeline.create_polygon(
            -radius, 0, 0, radius, radius, 0, 0, -radius,
            fill=keyframe_color,
            activefill=keyframe_color_selected,
            outline='#000000',
        )
        self.timeline.reg_keyframe(self)
        self.timeline.tag_bind(self.id, '<Button-1>', self.on_click)
        self.on_resize()

    def on_resize(self):
        h = self.timeline.winfo_height()
        w = self.timeline.winfo_width() - side_pad * 2
        x = self.timeline.index_to_position(self.index) * w + side_pad - self.radius
        y = h / 2 - self.radius
        self.timeline.moveto(self.id, x, y)

    def on_click(self, event):
        self.timeline.set_selected_keyframe(self)

    def set_selected(self, state):
        self.timeline.itemconfig(self.id, fill=keyframe_color_selected if state else keyframe_color)

class Timeline(tk.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.objects = {}
        self.keyframes = {}
        self.selected_keyframe_index = None
        self.current_frame = 0
        self.frame_count = 0

        self.background_area = self.create_rectangle(0, 0, 0, 0, fill="#292929", outline='')

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

        self.bind('<Configure>', self.on_resize)
        self.tag_bind(self.background_area, '<Button-1>', self.on_drag_start)
        self.tag_bind(self.background_area, '<Motion>', self.on_motion)
        self.tag_bind(self.background_area, '<ButtonRelease-1>', self.on_drag_stop)
        self.bind('<Destroy>', self.on_destroy)
        self.position_updated_event = Observable()

    def set_frame_count(self, frame_count:int):
        self.frame_count = frame_count

    def index_to_position(self, index:int) -> float:
        if self.frame_count == 0:
            return 0
        return index / float(self.frame_count)

    def set_selected_keyframe(self, keyframe:KeyframeMarker):
        self.unset_selected_keyframe()
        keyframe.set_selected(True)
        self.selected_keyframe_index = keyframe.index
        self.set_position_marker(keyframe.index)
        self.position_updated_event(keyframe.index)

    def unset_selected_keyframe(self):
        keyframe = self.keyframes.get(self.selected_keyframe_index)
        if keyframe:
            keyframe.set_selected(False)
        self.selected_keyframe_index = None

    def on_destroy(self, event):
        self.timer.cancel()

    def reg_obj(self, obj):
        self.objects[obj.id] = obj

    def reg_keyframe(self, keyframe:KeyframeMarker):
        self.keyframes[keyframe.index] = keyframe

    def on_resize(self, event):
        for object in self.objects.values():
            object.on_resize()
        self.coords(self.background_area, (0, 0, self.winfo_width() - 1, self.winfo_height() - 1))

    def set_position_marker(self, index):
        self.position_marker.set_position(self.index_to_position(index))

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
        return clamp(0.0, 1.0, (event.x - side_pad) / w)

    def update_marker_position(self, event):
        position = self.event_to_position(event)
        self.position_marker.set_position(position)
        return position

    def on_click(self, event):
        self.unset_selected_keyframe()
        position = self.update_marker_position(event)
        self.position_updated_event(int(position * self.frame_count))

    def add_keyframe(self, index):
        return KeyframeMarker(self, index)

    def clear_keyframes(self):
        for keyframe in self.keyframes.values():
            self.delete(keyframe.id)
        self.keyframes.clear()

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

def scale(scale):
    return np.array([
        [scale, 0, 0],
        [0, scale, 0],
        [0, 0, 1],
    ], np.float64)

def translate(dx, dy):
    return np.array([
        [1, 0, dx],
        [0, 1, dy],
        [0, 0, 1],
    ], np.float64)

def multiply(*matrices):
    result = np.identity(3, np.float64)
    for m in reversed(matrices):
        np.matmul(result, m, result)
    return result

scroll_zoom_levels = [2 ** (x / 4) for x in range(-28, 21)]
default_zoom_level = 28

def event_vec(event:tk.Event):
    return np.array((event.x, event.y))

def swap(vec):
    return np.array((vec[1], vec[0]))

class VideoCanvas(tk.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._video = None
        self._video_photo_image = None
        self._video_image_array = None
        self._mask_image_array = None
        self._brush_size = 1
        self._drawing = False
        self._drawing_mode = True # False = erasing
        self._render_buffer = np.empty((1,1,3), dtype=np.ubyte)
        self._frame_count = 0
        self._fps = 60
        self._video_id = self.create_image((0, 0), anchor=ttkc.NW)
        self._playing = False
        self._last_mouse_pos = np.array((0.0, 0.0))
        self._panning_view = False
        self._view_position = np.array((0.0, 0.0))
        self._zoom_level = default_zoom_level
        self._timer = asyncio.create_task(self.update_task())
        self.bind('<Configure>', self.on_resize)
        self.bind('<Destroy>', self.on_destroy)
        self.bind('<Button-1>', self.on_draw_start)
        self.bind('<ButtonRelease-1>', self.on_draw_stop)
        self.bind('<Button-3>', self.on_pan_start)
        self.bind('<ButtonRelease-3>', self.on_pan_stop)
        self.bind('<Motion>', self.on_mouse_move)
        self.bind('<MouseWheel>', self.on_mousewheel)
        self.bind('<Button-4>', lambda *_: self.previous_frame())
        self.bind('<Button-5>', lambda *_: self.next_frame())
        self.bind('<Control-Button-4>', self.on_zoom_in)
        self.bind('<Control-Button-5>', self.on_zoom_out)
        self.frame_changing_event = Observable()
        self.drawing_started_event = Observable()
        self.drawing_finished_event = Observable()

    def update_view(self):
        zoom = scroll_zoom_levels[self._zoom_level]
        clear_color = (0x33, 0x33, 0x33)
        if self._video:
            if self._mask_image_array is not None:
                video_image = self._video_image_array / 255.0
                mask_image = self._mask_image_array / 255.0
                composite = ((video_image * mask_image) * 255.0).astype(np.ubyte)
            else:
                composite = self._video_image_array
            canvas_h = self.winfo_height()
            canvas_w = self.winfo_width()
            image_size = np.array(self._video_image_array.shape[:2])
            matrix = multiply(
                translate(-image_size[1] * 0.5, -image_size[0] * 0.5),
                translate(self._view_position[0], self._view_position[1]),
                scale(zoom),
                translate(canvas_w * 0.5, canvas_h * 0.5),
            )
            height, width = self._render_buffer.shape[:2]
            cv2.warpAffine(composite, matrix[:2], dsize=(width, height), dst=self._render_buffer,
                borderMode=cv2.BORDER_CONSTANT, borderValue=clear_color, flags=cv2.INTER_AREA)
        else:
            self._render_buffer[:,:] = clear_color
        height, width = self._render_buffer.shape[:2]
        ppm_header = f'P6 {width} {height} 255 '.encode()
        data = ppm_header + self._render_buffer.tobytes()
        self._video_photo_image = tk.PhotoImage(width=width, height=height, data=data, format='PPM')
        self.itemconfig(self._video_id, image=self._video_photo_image)

    def set_drawing_mode(self):
        self._drawing_mode = True

    def set_erasing_mode(self):
        self._drawing_mode = False

    def set_mask_image_array(self, array):
        self._mask_image_array = array

    def get_mask_image_array(self):
        return self._mask_image_array

    def get_blank_image_array(self):
        size = self.get_video_size()
        data = np.full(size + (1,), fill_value=0xff, dtype=np.ubyte)
        data.flags.writeable = False
        return data

    def set_brush_size(self, size:int):
        self._brush_size = size

    def on_zoom_in(self, event):
        self.zoom(1, event)

    def on_zoom_out(self, event):
        self.zoom(-1, event)

    def zoom(self, level_delta, event):
        self._zoom_level += level_delta
        self._zoom_level = clamp(0, len(scroll_zoom_levels) - 1, self._zoom_level)
        self.update_view()

    def on_pan_start(self, event):
        self._panning_view = True

    def on_pan_stop(self, event):
        self._panning_view = False

    def mouse_to_view(self, vec):
        zoom = scroll_zoom_levels[self._zoom_level]
        canvas_h = self.winfo_height()
        canvas_w = self.winfo_width()
        canvas_size = np.array((canvas_w, canvas_h))
        image_size = np.array(self._video_image_array.shape[:2])
        return (vec - (canvas_size / 2)) / zoom + (image_size / 2) - self._view_position

    def on_draw_start(self, event):
        if not self._video:
            return
        self._drawing = True
        self._last_drawing_pos = self.mouse_to_view(event_vec(event))
        self.drawing_started_event()
        if self._mask_image_array is not None:
            self._mask_image_array = self._mask_image_array.copy()

    def on_draw_stop(self, event):
        if not self._video:
            return
        self._drawing = False
        self.drawing_finished_event()

    def on_mouse_move(self, event:tk.Event):
        if not self._video:
            return
        current_pos = event_vec(event)
        if self._panning_view:
            zoom = scroll_zoom_levels[self._zoom_level]
            delta = (current_pos - self._last_mouse_pos) / zoom
            self._view_position += delta
            self.update_view()
        elif self._drawing and self._mask_image_array is not None:
            brush_pos = self.mouse_to_view(current_pos)
            color = 0x00 if self._drawing_mode else 0xff
            cv2.line(self._mask_image_array, self._last_drawing_pos.astype(np.int32), brush_pos.astype(np.int32), color, self._brush_size, cv2.LINE_AA)
            self._last_drawing_pos = brush_pos
            self.update_view()
        self._last_mouse_pos = current_pos

    def on_mousewheel(self, event):
        if event.delta > 0:
            self.next_frame()
        else:
            self.previous_frame()

    def on_resize(self, event):
        h = self.winfo_height()
        w = self.winfo_width()
        self._render_buffer = np.empty((h, w, 3), dtype=np.ubyte)
        self._mask_render_buffer = np.empty((h, w, 3), dtype=np.ubyte)
        self.update_view()

    def reset_view(self):
        self._zoom_level = default_zoom_level
        self._view_position = np.array((0.0, 0.0))
        self.update_view()

    def on_destroy(self, event):
        self._timer.cancel()

    async def update_task(self):
        next_deadline = 0
        while True:
            frame_time = 1.0 / self.get_fps()
            await asyncio.sleep(frame_time / 2)
            if self._playing:
                t = time.time()
                if t >= next_deadline:
                    self.read_frame()
                    next_deadline = t + frame_time

    def open_video(self, file_path:Path):
        self.close_video()
        if not file_path.exists():
            # TODO Show error
            return
        self._video = cv2.VideoCapture(str(file_path))
        self._frame_count = int(self._video.get(cv2.CAP_PROP_FRAME_COUNT))
        self._fps = int(self._video.get(cv2.CAP_PROP_FPS))
        self.next_frame()
        self.reset_view()

    def close_video(self):
        if self._video is None:
            return
        self._video.release()
        self._video = None
        self._video_image_array = None
        self._video_photo_image = None
        self._mask_image_array = None
        self._frame_count = 0
        self._fps = 60
        self.update_view()

    def get_frame_pos(self):
        if not self._video:
            return 0
        return int(self._video.get(cv2.CAP_PROP_POS_FRAMES))

    def get_frame_count(self):
        return self._frame_count

    def get_fps(self):
        return self._fps

    def get_video_size(self):
        if not self._video:
            return (0, 0)
        return self._video_image_array.shape[:2]

    def get_time_string(self):
        curr_time = format_time(self.get_frame_pos(), self.get_fps())
        total_time = format_time(self.get_frame_count(), self.get_fps())
        return f'{curr_time} / {total_time}'

    def set_frame_pos(self, index):
        if not self._video:
            return
        self._video.set(cv2.CAP_PROP_POS_FRAMES, index - 1)
        self.read_frame()

    def read_frame(self):
        if not self._video:
            return
        ret, self._video_image_array = self._video.read(self._video_image_array)
        if not ret:
            return
        cv2.cvtColor(self._video_image_array, cv2.COLOR_BGR2RGB, self._video_image_array)
        self.frame_changing_event(self.get_frame_pos())
        self.update_view()

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

class App(AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {__version__}')
        self.geometry('{}x{}'.format(1000, 600))
        ttk.Style('darkly')

        self.undo_limit = 100
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
        self.video_canvas = VideoCanvas(self, width=1, height=1)
        self.video_canvas.pack(fill=ttkc.BOTH, expand=True)

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
        make_button(button_frame, 'Reset view', 'arrows-fullscreen', self.reset_view)

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
        self.drawing_mode_var.trace_add('write', self.on_drawing_mode_changed)

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
        self.brush_scale_var.trace_add('write', self.on_brush_size_changed)

        button_frame = ttk.Frame(self)
        button_frame.pack()

        self.time_label = ttk.Label(button_frame)
        self.time_label.pack(side=ttkc.LEFT)
        self.video_file_name_label = ttk.Label(button_frame)
        self.video_file_name_label.pack(side=ttkc.LEFT)

        # Timeline and info
        self.timeline = Timeline(self, height=50)
        self.timeline.pack(fill=ttkc.X)
        self.timeline.position_updated_event += self.video_canvas.set_frame_pos
        self.video_canvas.frame_changing_event += self.on_frame_changing
        self.video_canvas.drawing_started_event += self.on_drawing_started
        self.video_canvas.drawing_finished_event += self.on_drawing_finished

        self.timeline.bind('<MouseWheel>', self.on_mousewheel)
        self.timeline.bind('<Button-4>', lambda event: self.previous_frame())
        self.timeline.bind('<Button-5>', lambda event: self.next_frame())

    def update_view(self):
        if self.project:
            self.timeline.clear_keyframes()
            state = self.project.get_current()
            for keyframe in state.keyframes:
                self.timeline.add_keyframe(keyframe.index)
            index = self.video_canvas.get_frame_pos()
            keyframe = state.get_keyframe(index)
            data = keyframe.data if keyframe else None
            self.video_canvas.set_mask_image_array(data)
            self.video_canvas.update_view()

    def on_frame_changing(self, index):
        if self.project:
            state = self.project.get_current()
            keyframe = state.get_keyframe(index)
            data = keyframe.data if keyframe else None
            self.video_canvas.set_mask_image_array(data)
            self.time_label.config(text=self.video_canvas.get_time_string())
            self.timeline.set_position_marker(index)

    def on_drawing_mode_changed(self, *args):
        mode = self.drawing_mode_var.get()
        if mode == self.drawing_mode_draw:
            self.video_canvas.set_drawing_mode()
        elif mode == self.drawing_mode_erase:
            self.video_canvas.set_erasing_mode()

    def on_brush_size_changed(self, *args):
        self.video_canvas.set_brush_size(self.brush_size_var.get())

    def on_drawing_started(self):
        if self.project:
            state = self.project.get_current()
            index = self.video_canvas.get_frame_pos()
            keyframe = state.get_keyframe(index)
            mode = self.auto_keyframe_var.get()
            if keyframe:
                if keyframe.index == index:
                    return
                if mode == self.auto_keyframe_blank:
                    self.add_blank_keyframe()
                elif mode == self.auto_keyframe_clone:
                    self.clone_keyframe()
            else:
                if mode != self.auto_keyframe_off:
                    self.add_blank_keyframe()

    def on_drawing_finished(self):
        if self.project:
            data = self.video_canvas.get_mask_image_array()
            if data is None:
                return
            index = self.video_canvas.get_frame_pos()
            state = self.project.get_current().update_keyframe(index, data).set(selected_index=index)
            self.project.append(state, self.undo_limit)

    def open_video(self):
        file_name = filedialog.askopenfilename(
            title='Open Video',
            filetypes=(('MP4', '*.mp4'), ('Any', '*.*')),
        )
        if file_name:
            self.project = Project(ProjectState(), video_file_path=Path(file_name))
            self.video_canvas.open_video(self.project.video_file_path)
            self.video_file_name_label.config(text=f'({self.project.video_file_path.name})')
            self.timeline.set_frame_count(self.video_canvas.get_frame_count())

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

    def update_to_selected(self):
        if self.project:
            state = self.project.get_current()
            if state.selected_index:
                self.video_canvas.set_frame_pos(state.selected_index)

    def undo(self):
        if self.project:
            self.project.undo()
            self.update_to_selected()
            self.update_view()

    def redo(self):
        if self.project:
            self.project.redo()
            self.update_to_selected()
            self.update_view()

    def previous_keyframe(self):
        if self.project:
            state = self.project.get_current()
            index = self.video_canvas.get_frame_pos()
            keyframe = state.get_previous_keyframe(index)
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def next_keyframe(self):
        if self.project:
            state = self.project.get_current()
            index = self.video_canvas.get_frame_pos()
            keyframe = state.get_next_keyframe(index)
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def add_blank_keyframe(self):
        if self.project:
            index = self.video_canvas.get_frame_pos()
            state = self.project.get_current()
            keyframe = state.get_keyframe(index)
            if keyframe and keyframe.index == index:
                return
            data = self.video_canvas.get_blank_image_array()
            keyframe = Keyframe(index=index, data=data)
            state = state.insert_keyframe(keyframe).set(selected_index=index)
            self.project.append(state, self.undo_limit)
            self.update_view()

    def clone_keyframe(self):
        if self.project:
            index = self.video_canvas.get_frame_pos()
            state = self.project.get_current()
            keyframe = state.get_keyframe(index)
            if keyframe and keyframe.index == index:
                return
            if not keyframe:
                self.add_blank_keyframe()
                return
            keyframe = keyframe.set(index=index)
            state = state.insert_keyframe(keyframe).set(selected_index=index)
            self.project.append(state, self.undo_limit)
            self.update_view()

    def delete_keyframe(self):
        if self.project:
            index = self.video_canvas.get_frame_pos()
            state = self.project.get_current()
            keyframe = state.get_keyframe(index)
            if keyframe:
                state = state.remove_keyframe(index)
                self.project.append(state, self.undo_limit)
            self.update_view()

    def play_video(self):
        self.video_canvas.play()

    def pause_video(self):
        self.video_canvas.pause()

    def previous_frame(self):
        self.video_canvas.previous_frame()

    def next_frame(self):
        self.video_canvas.next_frame()

    def reset_view(self):
        self.video_canvas.reset_view()

    def on_mousewheel(self, event):
        if event.delta > 0:
            self.next_frame()
        else:
            self.previous_frame()

async def async_main():
    await App().async_main_loop()

def main():
    asyncio.run(async_main())