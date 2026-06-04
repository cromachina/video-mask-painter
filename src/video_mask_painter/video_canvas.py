import asyncio
import time
from pathlib import Path
import sys
import os

import tkinter as tk

import numpy as np
import cv2

# BUG pysdl3 import takes a long time on nix (over 3 seconds), and also throws a nix store write error
# https://github.com/NixOS/nixpkgs/issues/527580
import sdl3
import ctypes

from . import util

sdl3.SDL_Init(sdl3.SDL_INIT_VIDEO)

_scroll_zoom_levels = [2 ** (x / 4) for x in range(-28, 21)]
_default_zoom_level = 28

class SDL_Error(Exception):
    pass

def raise_sdl_error(text):
    raise SDL_Error(f'{text}: {sdl3.SDL_GetError().decode()}')

def to_frect_ref(rect):
    return None if rect is None else ctypes.byref(sdl3.SDL_FRect(*rect))

class StreamingTexture():
    def __init__(self, renderer, size):
        self._size = size
        self._texture = sdl3.SDL_CreateTexture(renderer, sdl3.SDL_PIXELFORMAT_BGRA32, sdl3.SDL_TEXTUREACCESS_STREAMING, int(size[0]), int(size[1]))
        if not self._texture:
            raise_sdl_error("Creating texture")
        sdl3.SDL_SetTextureScaleMode(self.get(), sdl3.SDL_SCALEMODE_LINEAR)

    def __del__(self):
        self.destroy()

    def destroy(self):
        if self._texture is not None:
            sdl3.SDL_DestroyTexture(self._texture)
            self._texture = None

    def get(self):
        return self._texture

    def write_with(self, func):
        pixels = ctypes.c_void_p(0)
        pitch = ctypes.c_int(0)
        sdl3.SDL_LockTexture(self._texture, None, ctypes.pointer(pixels), ctypes.pointer(pitch))
        dst = np.ctypeslib.as_array(ctypes.cast(pixels, ctypes.POINTER(ctypes.c_uint8)), tuple(util.swap(self._size)) + (4,))
        func(dst)
        sdl3.SDL_UnlockTexture(self._texture)

    def copy_from(self, array:np.ndarray):
        def f(dst):
            if array.shape[2] == 1:
                dst[:,:,:3] = 255
                np.copyto(dst[:,:,3], array.reshape(array.shape[:2]))
            else:
                dst[:,:,3] = 255
                np.copyto(dst[:,:,:3], array)
        self.write_with(f)

    def get_size(self):
        return self._size

class EmbeddedWindow():
    def __init__(self, widget:tk.Widget):
        self.window = None
        self.renderer = None
        self._widget = widget
        self._ctrl_down = False
        self.mouse_motion_event = util.Observable()
        self.mouse_button_event = util.Observable()
        self.mouse_wheel_event = util.Observable()

    def create(self):
        if self.window:
            return
        props = sdl3.SDL_CreateProperties()
        win_id = self._widget.winfo_id()
        win_id_ptr = ctypes.cast(win_id, ctypes.c_void_p)
        if sys.platform == 'linux':
            session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()
            if session_type == 'wayland':
                sdl3.SDL_SetBooleanProperty(props, sdl3.SDL_PROP_WINDOW_CREATE_WAYLAND_SURFACE_ROLE_CUSTOM_BOOLEAN, True)
                sdl3.SDL_SetPointerProperty(props, sdl3.SDL_PROP_WINDOW_CREATE_WAYLAND_WL_SURFACE_POINTER, win_id_ptr)
            else:
                sdl3.SDL_SetNumberProperty(props, sdl3.SDL_PROP_WINDOW_CREATE_X11_WINDOW_NUMBER, win_id)
        elif sys.platform == 'darwin':
            sdl3.SDL_SetPointerProperty(props, sdl3.SDL_PROP_WINDOW_CREATE_COCOA_VIEW_POINTER, win_id_ptr)
        elif sys.platform == 'win32':
            sdl3.SDL_SetPointerProperty(props, sdl3.SDL_PROP_WINDOW_CREATE_WIN32_HWND_POINTER, win_id_ptr)
        self.window = sdl3.SDL_CreateWindowWithProperties(props)
        if not self.window:
            raise_sdl_error("Creating window")
        self.renderer = sdl3.SDL_CreateRenderer(self.window, None)
        if not self.renderer:
            raise_sdl_error("Creating renderer")

    def destroy(self):
        if self.renderer:
            sdl3.SDL_DestroyRenderer(self.renderer)
            self.renderer = None
        if self.window:
            sdl3.SDL_DestroyWindow(self.window)
            self.window = None

    # BUG These events seem to slightly get messed up when embedded in a Tk window.
    # Mouse wheel barely works unless another mouse button is held down while scrolling.
    # I don't know why this happens with SDL3 and not SDL2.
    def process_events(self):
        event = sdl3.SDL_Event()
        while sdl3.SDL_PollEvent(ctypes.byref(event)):
            match event.type:
                case sdl3.SDL_EVENT_MOUSE_MOTION:
                    #print('motion', event.motion.state, event.motion.x, event.motion.y, event.motion.xrel, event.motion.yrel)
                    self.mouse_motion_event(event.motion)
                case sdl3.SDL_EVENT_MOUSE_BUTTON_DOWN | sdl3.SDL_EVENT_MOUSE_BUTTON_UP:
                    #print('button', event.button.button, event.motion.x, event.motion.y)
                    self.mouse_button_event(event.button)
                case sdl3.SDL_EVENT_MOUSE_WHEEL:
                    #print('wheel', event.wheel.x, event.wheel.y)
                    self.mouse_wheel_event(event.wheel)

    def set_size(self, w, h):
        sdl3.SDL_SetWindowPosition(self.window, 0, 0)
        sdl3.SDL_SetWindowSize(self.window, w, h)
        sdl3.SDL_SetRenderLogicalPresentation(self.renderer, w, h, sdl3.SDL_LOGICAL_PRESENTATION_DISABLED)

    def clear(self, r=255, g=255, b=255, a=255):
        sdl3.SDL_SetRenderDrawColor(self.renderer, r, g, b, a)
        sdl3.SDL_RenderClear(self.renderer)

    def create_texture(self, size):
        return StreamingTexture(self.renderer, size)

    def render_texture(self, texture:sdl3.LP_SDL_Texture, srcrect=None, dstrect=None):
        if not sdl3.SDL_RenderTexture(self.renderer, texture, to_frect_ref(srcrect), to_frect_ref(dstrect)):
            raise_sdl_error("Rendering texture")

class VideoCanvas(tk.Frame):
    def __init__(self, master=None, initial_color=(0, 0, 0), initial_alpha=255, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._sdl_window = EmbeddedWindow(self)
        self._video_texture = None
        self._mask_texture = None
        self._brush_texture = None
        self._view_needs_update = False
        self._video = None
        self._video_image_array = None
        self._mask_image_array = None
        self._brush_size = 1
        self._cursor_visible = False
        self._mask_color = initial_color
        self._mask_alpha = initial_alpha
        self._drawing = False
        self._drawing_mode = True # False = erasing
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
        self.bind('<Enter>', self._on_mouse_enter)
        self.bind('<Leave>', self._on_mouse_leave)
        for e in ['<Motion>', '<Button>', '<ButtonRelease>', '<Key>']:
            self.bind(e, print)
        self.winfo_toplevel().update_hook += self._update_view
        self.frame_changing_event = util.Observable()
        self.drawing_started_event = util.Observable()
        self.drawing_finished_event = util.Observable()
        # BUG Tk events don't seem to fire inside of the SDL window and cursor setting doesn't work.
        self.config(cursor='none')
        self._sdl_window.mouse_button_event += self._on_mouse_button
        self._sdl_window.mouse_motion_event += self._on_mouse_motion
        self._sdl_window.mouse_wheel_event += self._on_mouse_wheel
        self._sdl_poll_task = asyncio.create_task(self._run_poll_task())

    async def _run_poll_task(self):
        while True:
            if self._sdl_window:
                try:
                    self._sdl_window.process_events()
                except Exception as ex:
                    import traceback
                    traceback.print_exception(ex)
            await asyncio.sleep(0)

    def _on_destroy(self, event:tk.Event):
        self._task.cancel()
        self._sdl_poll_task.cancel()
        for resource in [self._brush_texture, self._mask_texture, self._video_texture, self._sdl_window]:
            if resource:
                resource.destroy()

    def _get_zoom_factor(self):
        return _scroll_zoom_levels[self._zoom_level]

    def _on_mouse_button(self, event):
        if event.button == sdl3.SDL_BUTTON_LEFT:
            if event.down:
                self._on_draw_start(event)
            else:
                self._on_draw_stop()
        elif event.button == sdl3.SDL_BUTTON_RIGHT:
            if event.down:
                self._on_pan_start()
            else:
                self._on_pan_stop()

    def _on_mouse_motion(self, event):
        self._mouse_pos = util.event_vec(event)
        if self._panning_view:
            self._on_pan_move(event)
        elif self._drawing and self._mask_image_array is not None:
            self._on_draw_move(event)
            self.update_view()
            self._update_view()
        self.update_view()
        self._last_mouse_pos = util.event_vec(event)

    def _on_mouse_wheel(self, event):
        if sdl3.SDL_GetModState() & sdl3.SDL_KMOD_CTRL:
            if event.y > 0:
                self._on_zoom_in()
            else:
                self._on_zoom_out()
        else:
            if event.y > 0:
                self.previous_frame()
            else:
                self.next_frame()

    ###########################################################################
    ## Viewport rendering

    def _update_view(self):
        if not self._sdl_window.window:
            return
        if not self._view_needs_update:
            return
        self._view_needs_update = False
        zoom = self._get_zoom_factor()
        clear_color = (0x33, 0x33, 0x33)
        self._sdl_window.clear(*clear_color)
        if self._video:
            canvas_size = np.array((self.winfo_width(), self.winfo_height()))
            image_size = util.swap(np.array(self._video_texture.get_size()))
            offset = (-image_size * 0.5 + self._view_position) * zoom + canvas_size * 0.5
            size = image_size * zoom
            rect = (*offset, *size)
            self._sdl_window.render_texture(self._video_texture.get(), dstrect=rect)
            if self._mask_image_array is not None:
                sdl3.SDL_SetTextureBlendMode(self._mask_texture.get(), sdl3.SDL_BLENDMODE_BLEND)
                sdl3.SDL_SetTextureColorMod(self._mask_texture.get(), *self._mask_color)
                sdl3.SDL_SetTextureAlphaMod(self._mask_texture.get(), self._mask_alpha)
                self._sdl_window.render_texture(self._mask_texture.get(), dstrect=rect)
        if self._cursor_visible:
            size = np.array(self._brush_texture._size)
            offset = size / 2
            cursor_rect = (*(self._mouse_pos - (size / 2)), *size)
            self._sdl_window.render_texture(self._brush_texture.get(), dstrect=cursor_rect)
        sdl3.SDL_RenderPresent(self._sdl_window.renderer)

    def update_view(self, *args):
        self._view_needs_update = True

    def _on_resize(self, event:tk.Event):
        h = self.winfo_height()
        w = self.winfo_width()
        if not self._sdl_window.window:
            self._sdl_window.create()
            self._regenerate_brush_texture()
        self._sdl_window.set_size(w, h)
        self.update_view()

    ###########################################################################
    ## Viewport navigation

    def _on_zoom_in(self):
        self._zoom(1)

    def _on_zoom_out(self):
        self._zoom(-1)

    def _zoom(self, level_delta:int):
        self._zoom_level += level_delta
        self._zoom_level = util.clamp(0, len(_scroll_zoom_levels) - 1, self._zoom_level)
        self._regenerate_brush_texture()
        self.update_view()

    def _on_pan_start(self):
        self._panning_view = True
        # BUG: Changing cursor causes the SDL window to flicker or momentarily stop drawing.
        # It cannot be changed with SDL_SetCursor.
        # It seems that SDL and Tk interfere with each other during this moment.
        # self.config(cursor='cross')
        self.hide_cursor()

    def _on_pan_stop(self):
        self._panning_view = False
        # self.config(cursor='none')
        if self._mouse_inside:
            self.show_cursor()

    def _on_pan_move(self, event):
        current_pos = util.event_vec(event)
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

    def _on_draw_start(self, event):
        if not self._video or self._mask_image_array is None:
            return
        self.pause()
        self.show_cursor()
        self._drawing = True
        self._last_drawing_pos = self._mouse_to_view(util.event_vec(event))
        self.drawing_started_event()
        self._mask_image_array = self._mask_image_array.copy()
        self._on_draw_move(event)

    def _on_draw_stop(self):
        if not self._video or self._mask_image_array is None:
            return
        self._drawing = False
        if not self._mouse_inside:
            self.hide_cursor()
        self.drawing_finished_event()

    def _on_draw_move(self, event):
        if not self._video or self._mask_image_array is None:
            return
        current_pos = util.event_vec(event)
        brush_pos = self._mouse_to_view(current_pos)
        color = 0xff if self._drawing_mode else 0x00
        cv2.line(
            self._mask_image_array, self._last_drawing_pos.astype(np.int32),
            brush_pos.astype(np.int32), color, self._brush_size, cv2.LINE_AA)
        self._mask_texture.copy_from(self._mask_image_array)
        self._last_drawing_pos = brush_pos

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
        if self._mask_image_array is not None:
            self._mask_texture.copy_from(self._mask_image_array)
        self.update_view()

    def get_mask_image_array(self) -> np.ndarray | None:
        return self._mask_image_array

    def get_blank_image_array(self) -> np.ndarray | None:
        if self._video:
            size = self.get_video_size()
            data = np.full(size + (1,), fill_value=0x00, dtype=np.ubyte)
            return data

    def _regenerate_brush_texture(self):
        size = max(2, int(self._brush_size * self._get_zoom_factor()))
        tex_size = size + 4
        radius = size // 2
        tex_center = tex_size // 2
        tex_center = (tex_center, tex_center)
        self._brush_texture = self._sdl_window.create_texture((tex_size, tex_size))
        sdl3.SDL_SetTextureBlendMode(self._brush_texture.get(), sdl3.SDL_BLENDMODE_BLEND)
        sdl3.SDL_SetTextureColorMod(self._brush_texture.get(), 0, 0, 0)
        array = np.zeros((tex_size, tex_size, 1), dtype=np.ubyte)
        cv2.circle(
            array, center=tex_center, radius=radius,
            color=0xff, thickness=1, lineType=cv2.LINE_AA)
        cv2.circle(
            array, center=tex_center, radius=1,
            color=0xff, thickness=1, lineType=cv2.LINE_AA)
        self._brush_texture.copy_from(array)

    def set_brush_size(self, size:int):
        self._brush_size = int(size)
        self._mouse_pos = self.winfo_width() / 2, self.winfo_height() / 2
        self._regenerate_brush_texture()
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
                    if not self._read_frame() and self._repeat:
                        self.set_frame_pos(1)
                    next_deadline = t + frame_time

    def _read_frame(self):
        if not self._video:
            return False
        ret, self._video_image_array = self._video.read(self._video_image_array)
        if not ret:
            return False
        self._video_texture.copy_from(self._video_image_array)
        self.frame_changing_event(self.get_frame_pos())
        self.update_view()
        return True

    def open_video(self, file_path:Path):
        self.close_video()
        if not file_path.exists():
            # TODO Show error
            return
        self._video = cv2.VideoCapture(str(file_path))
        self._frame_count = int(self._video.get(cv2.CAP_PROP_FRAME_COUNT))
        self._fps = int(self._video.get(cv2.CAP_PROP_FPS))
        self._video_texture = self._sdl_window.create_texture(util.swap(self.get_video_size()))
        self._mask_texture = self._sdl_window.create_texture(util.swap(self.get_video_size()))
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
        return int(self._video.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(self._video.get(cv2.CAP_PROP_FRAME_WIDTH))

    def get_time_string(self) -> str:
        curr_time = util.format_time(self.get_frame_pos(), self.get_fps())
        total_time = util.format_time(self.get_frame_count(), self.get_fps())
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

    def set_repeat(self, value:bool):
        self._repeat = value