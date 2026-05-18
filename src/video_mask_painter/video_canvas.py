import asyncio
import time
from pathlib import Path

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc

import numpy as np
import cv2

from .util import *

_scroll_zoom_levels = [2 ** (x / 4) for x in range(-28, 21)]
_default_zoom_level = 28

class VideoCanvas(ttk.Canvas):
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
        self.frame_changing_event = Observable()
        self.drawing_started_event = Observable()
        self.drawing_finished_event = Observable()

    def _on_destroy(self, event:tk.Event):
        self._task.cancel()

    ###########################################################################
    ## Viewport rendering

    def update_view(self):
        zoom = _scroll_zoom_levels[self._zoom_level]
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

    def _on_resize(self, event:tk.Event):
        h = self.winfo_height()
        w = self.winfo_width()
        self._render_buffer = np.empty((h, w, 3), dtype=np.ubyte)
        self._mask_render_buffer = np.empty((h, w, 3), dtype=np.ubyte)
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

    def _on_pan_stop(self, event:tk.Event):
        self._panning_view = False

    def _on_pan_move(self, event:tk.Event):
        current_pos = event_vec(event)
        zoom = _scroll_zoom_levels[self._zoom_level]
        delta = (current_pos - self._last_mouse_pos) / zoom
        self._view_position += delta
        self.update_view()

    def _mouse_to_view(self, vec:np.ndarray) -> np.ndarray:
        zoom = _scroll_zoom_levels[self._zoom_level]
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
        self._drawing = True
        self._last_drawing_pos = self._mouse_to_view(event_vec(event))
        self.drawing_started_event()
        if self._mask_image_array is not None:
            self._mask_image_array = self._mask_image_array.copy()

    def _on_draw_stop(self, event:tk.Event):
        if not self._video:
            return
        self._drawing = False
        self.drawing_finished_event()

    def _on_draw_move(self, event:tk.Event):
        current_pos = event_vec(event)
        brush_pos = self._mouse_to_view(current_pos)
        color = 0x00 if self._drawing_mode else 0xff
        cv2.line(self._mask_image_array, self._last_drawing_pos.astype(np.int32), brush_pos.astype(np.int32), color, self._brush_size, cv2.LINE_AA)
        self._last_drawing_pos = brush_pos
        self.update_view()

    def _on_mouse_move(self, event:tk.Event):
        if not self._video:
            return
        if self._panning_view:
            self._on_pan_move(event)
        elif self._drawing and self._mask_image_array is not None:
            self._on_draw_move(event)
        self._last_mouse_pos = event_vec(event)

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
            data = np.full(size + (1,), fill_value=0xff, dtype=np.ubyte)
            data.flags.writeable = False
            return data

    def set_brush_size(self, size:int):
        self._brush_size = size

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
                    self._read_frame()
                    next_deadline = t + frame_time

    def _read_frame(self):
        if not self._video:
            return
        ret, self._video_image_array = self._video.read(self._video_image_array)
        if not ret:
            return
        cv2.cvtColor(self._video_image_array, cv2.COLOR_BGR2RGB, self._video_image_array)
        self.frame_changing_event(self.get_frame_pos())
        self.update_view()

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
        self._video_photo_image = None
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

    def previous_frame(self):
        if not self._video:
            return
        pos = self.get_frame_pos() - 1
        self.set_frame_pos(pos)

    def next_frame(self):
        if not self._video:
            return
        self._read_frame()