import asyncio
import time
from pathlib import Path

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc

import numpy as np
import cv2
import sdl2, sdl2.ext
from sdl2.ext.window import _check_video_init
from sdl2.ext.err import raise_sdl_err

from .util import *

sdl2.ext.init()

_scroll_zoom_levels = [2 ** (x / 4) for x in range(-28, 21)]
_default_zoom_level = 28

class EmbeddedWindow(sdl2.ext.Window):
    def __init__(self, widget:tk.Widget):
        _check_video_init(__class__)
        self.window = None
        self._widget = widget

    def create(self):
        if self.window:
            return
        window = sdl2.SDL_CreateWindowFrom(self._widget.winfo_id())
        if not window:
            raise_sdl_err(__name__)
        self.window = window.contents

class VideoCanvas(tk.Frame):
    def __init__(self, master=None, initial_color=(0, 0, 0), initial_alpha=255, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._sdl_window = EmbeddedWindow(self)
        self._sdl_surface = None
        self.winfo_toplevel().update_hook += self._update_view
        self._view_needs_update = False
        self._update_composite = False
        self._video = None
        self._video_image_array = None
        self._mask_image_array = None
        self._brush_size = 1
        self._cursor_visible = False
        self._mask_color = initial_color
        self._mask_alpha = initial_alpha
        self._drawing = False
        self._drawing_mode = True # False = erasing
        self._render_buffer = np.empty((1,1,3), dtype=np.ubyte)
        self._frame_count = 0
        self._fps = 60
        self._mouse_inside = False
        self._playing = False
        self._repeat = False
        self._mouse_pos = (0, 0)
        self._last_mouse_pos = np.array((0.0, 0.0))
        self._panning_view = False
        self._view_position = np.array((0.0, 0.0))
        self._zoom_level = _default_zoom_level
        self._task = asyncio.create_task(self._video_play_task())
        self.bind('<Configure>', self._on_resize)
        self.bind('<Destroy>', self._on_destroy)
        self.bind('<Button-1>', self._on_draw_start)
        self.bind('<ButtonRelease-1>', self._on_draw_stop)
        self.bind('<Button-3>', self._on_pan_start)
        self.bind('<ButtonRelease-3>', self._on_pan_stop)
        self.bind('<Motion>', self._on_mouse_move)
        self.bind('<MouseWheel>', self._on_mousewheel)
        self.bind('<Button-4>', lambda *_: self.previous_frame())
        self.bind('<Button-5>', lambda *_: self.next_frame())
        self.bind('<Control-Button-4>', self._on_zoom_in)
        self.bind('<Control-Button-5>', self._on_zoom_out)
        self.bind('<Enter>', self._on_mouse_enter)
        self.bind('<Leave>', self._on_mouse_leave)
        self.frame_changing_event = Observable()
        self.drawing_started_event = Observable()
        self.drawing_finished_event = Observable()
        self.config(cursor='none')

    def _update_hook(self, *args):
        if self._sdl_window.window:
            self._sdl_window.refresh()

    def _on_destroy(self, event:tk.Event):
        self._task.cancel()

    def _get_zoom_factor(self):
        return _scroll_zoom_levels[self._zoom_level]

    ###########################################################################
    ## Viewport rendering

    def _update_view(self):
        if not self._sdl_window.window:
            return
        if not self._view_needs_update:
            return
        zoom = self._get_zoom_factor()
        clear_color = (0x33, 0x33, 0x33)
        self._view_needs_update = False
        if self._video:
            # TODO: Do this rendering on the GPU instead as this operation
            # already maxes out a 12 core CPU
            if self._mask_image_array is not None:
                mask = np.array(self._mask_color, dtype=np.uint8)
                mask[0], mask[2] = mask[2], mask[0]
                composite = normal_blend(
                    self._video_image_array,
                    self._mask_image_array,
                    mask,
                    np.uint8(self._mask_alpha))
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
        if self._cursor_visible:
            cv2.circle(
                self._render_buffer, center=tuple(np.int64(self._mouse_pos)), radius=int(self._brush_size * zoom / 2),
                color=0, thickness=1, lineType=cv2.LINE_AA)
        sdl_array = sdl2.ext.pixels3d(self._sdl_surface, False)
        sdl_array[:,:,:] = cv2.cvtColor(self._render_buffer, cv2.COLOR_RGB2RGBA)
        self._sdl_window.refresh()

    def update_view(self, *args):
        self._view_needs_update = True

    def _on_resize(self, event:tk.Event):
        h = self.winfo_height()
        w = self.winfo_width()
        self._render_buffer = np.empty((h, w, 3), dtype=np.ubyte)
        self._mask_render_buffer = np.empty((h, w, 3), dtype=np.ubyte)
        self._sdl_window.create()
        self._sdl_window.size = (w, h)
        self._sdl_surface = self._sdl_window.get_surface()
        self.update_view()

    ###########################################################################
    ## Viewport navigation

    def _on_zoom_in(self, event:tk.Event):
        self._zoom(1, event)

    def _on_zoom_out(self, event:tk.Event):
        self._zoom(-1, event)

    def _zoom(self, level_delta:int, event:tk.Event):
        self._zoom_level += level_delta
        self._zoom_level = clamp(0, len(_scroll_zoom_levels) - 1, self._zoom_level)
        self.update_view()

    def _on_pan_start(self, event:tk.Event):
        self._panning_view = True
        # BUG: Changing cursor causes the SDL window to flicker or momentarily stop drawing.
        # It cannot be changed with SDL_SetCursor.
        # It seems that SDL and Tk interfere with each other during this moment.
        # self.config(cursor='cross')
        self.hide_cursor()

    def _on_pan_stop(self, event:tk.Event):
        self._panning_view = False
        # self.config(cursor='none')
        if self._mouse_inside:
            self.show_cursor()

    def _on_pan_move(self, event:tk.Event):
        current_pos = event_vec(event)
        zoom = self._get_zoom_factor()
        delta = (current_pos - self._last_mouse_pos) / zoom
        self._view_position += delta

    def _mouse_to_view(self, vec:np.ndarray) -> np.ndarray:
        zoom = self._get_zoom_factor()
        canvas_h = self.winfo_height()
        canvas_w = self.winfo_width()
        canvas_size = np.array((canvas_w, canvas_h))
        image_size = np.array(self._video_image_array.shape[:2])
        return (vec - (canvas_size / 2)) / zoom + (image_size / 2) - self._view_position

    def reset_view(self):
        self._zoom_level = _default_zoom_level
        self._view_position = np.array((0.0, 0.0))
        self.update_view()

    ###########################################################################
    ## Mask drawing

    def _on_draw_start(self, event:tk.Event):
        if not self._video:
            return
        self.pause()
        self.show_cursor()
        self._drawing = True
        self._last_drawing_pos = self._mouse_to_view(event_vec(event))
        self.drawing_started_event()
        if self._mask_image_array is not None:
            self._mask_image_array = self._mask_image_array.copy()

    def _on_draw_stop(self, event:tk.Event):
        if not self._video:
            return
        self._drawing = False
        if not self._mouse_inside:
            self.hide_cursor()
        self.drawing_finished_event()

    def _on_draw_move(self, event:tk.Event):
        if not self._video:
            return
        current_pos = event_vec(event)
        brush_pos = self._mouse_to_view(current_pos)
        color = 0xff if self._drawing_mode else 0x00
        cv2.line(
            self._mask_image_array, self._last_drawing_pos.astype(np.int32),
            brush_pos.astype(np.int32), color, self._brush_size, cv2.LINE_AA)
        self._last_drawing_pos = brush_pos

    def _on_mouse_move(self, event:tk.Event):
        self._mouse_pos = event_vec(event)
        if self._panning_view:
            self._on_pan_move(event)
        elif self._drawing and self._mask_image_array is not None:
            self._on_draw_move(event)
        self.update_view()
        self._last_mouse_pos = event_vec(event)

    def hide_cursor(self):
        self._cursor_visible = False
        self.update_view()

    def show_cursor(self):
        self._cursor_visible = True
        self.update_view()

    def _on_mouse_enter(self, event:tk.Event):
        self._mouse_inside = True
        self.show_cursor()
        self.update_view()

    def _on_mouse_leave(self, event:tk.Event):
        self._mouse_inside = False
        if not self._drawing:
            self.hide_cursor()
        self.update_view()

    def set_drawing_mode(self):
        self._drawing_mode = True

    def set_erasing_mode(self):
        self._drawing_mode = False

    def set_mask_image_array(self, array):
        self._mask_image_array = array

    def get_mask_image_array(self) -> np.ndarray | None:
        return self._mask_image_array

    def get_blank_image_array(self) -> np.ndarray | None:
        if self._video:
            size = self.get_video_size()
            data = np.full(size + (1,), fill_value=0x00, dtype=np.ubyte)
            data.flags.writeable = False
            return data

    def set_brush_size(self, size:int):
        self._brush_size = size
        self._mouse_pos = self.winfo_width() / 2, self.winfo_height() / 2
        self.show_cursor()

    def set_mask_color(self, color):
        self._mask_color = color
        self.update_view()

    def set_mask_alpha(self, alpha):
        self._mask_alpha = alpha
        self.update_view()

    ###########################################################################
    ## Video navigation

    async def _video_play_task(self):
        next_deadline = 0
        while True:
            frame_time = 1.0 / self.get_fps()
            await asyncio.sleep(frame_time / 2)
            if self._playing:
                t = time.time()
                if t >= next_deadline:
                    if not self._read_frame():
                        self.set_frame_pos(1)
                    next_deadline = t + frame_time

    def _read_frame(self):
        if not self._video:
            return False
        ret, self._video_image_array = self._video.read(self._video_image_array)
        if not ret:
            return False
        self.frame_changing_event(self.get_frame_pos())
        self.update_view()
        return True

    def _on_mousewheel(self, event:tk.Event):
        if event.delta > 0:
            self.next_frame()
        else:
            self.previous_frame()

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
        self._mask_image_array = None
        self._frame_count = 0
        self._fps = 60
        self.update_view()

    def get_frame_pos(self) -> int:
        if not self._video:
            return 0
        return int(self._video.get(cv2.CAP_PROP_POS_FRAMES))

    def set_frame_pos(self, index):
        if not self._video:
            return
        self._video.set(cv2.CAP_PROP_POS_FRAMES, index - 1)
        self._read_frame()

    def get_frame_count(self) -> int:
        return self._frame_count

    def get_fps(self) -> int:
        return self._fps

    def get_video_size(self) -> tuple[int, int]:
        if not self._video:
            return (0, 0)
        return self._video_image_array.shape[:2]

    def get_time_string(self) -> str:
        curr_time = format_time(self.get_frame_pos(), self.get_fps())
        total_time = format_time(self.get_frame_count(), self.get_fps())
        return f'{curr_time} / {total_time}'

    def play(self):
        self._playing = True

    def pause(self):
        self._playing = False

    def is_playing(self):
        return self._playing

    def previous_frame(self):
        if not self._video:
            return
        pos = self.get_frame_pos() - 1
        self.set_frame_pos(pos)

    def next_frame(self):
        if not self._video:
            return
        self._read_frame()