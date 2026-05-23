import time
import weakref
import tkinter as tk
import importlib.resources

from pyrsistent import *
import numpy as np
import cv2
import numba
import cairosvg

from . import icons

@numba.vectorize
def lerp(a, b, t):
    return (b - a) * t + a

@numba.vectorize
def bilinear(a, b, c, t):
    ab = lerp(a, b, t)
    bc = lerp(b, c, t)
    return lerp(ab, bc, t)

def secant_method(f, x0=0, x1=1, iters=20):
    for _ in range(iters):
        f0 = f(x0)
        f1 = f(x1)
        if f0 == f1:
            return x1
        x2 = x1 - f1 * (x1 - x0) / (f1 - f0)
        x0, x1 = x1, x2
    return x2

def quadratic_bezier(a, b, c, t):
    return bilinear(a, b, c, t)[1]

def inverse_quadratic_bezier(a, b, c, value):
    return secant_method(lambda x: quadratic_bezier(a, b, c, x) - value)

def clamp(min_val, max_val, val):
    return max(min_val, min(max_val, val))

def pvector_insert(vector, item, index):
    return vector[:index] + pvector([item]) + vector[index:]

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

def event_vec(event:tk.Event):
    return np.array((event.x, event.y))

def swap(vec):
    return np.array((vec[1], vec[0]))

_rangemax = np.int16(0x3fff)

@numba.njit
def to_short_array(value):
    value = value.astype(np.short)
    return (value << 6) | (value >> 2)

@numba.njit
def to_byte_array(value):
    return (value >> 6).astype(np.ubyte)

@numba.njit
def to_short(value):
    value = np.short(value)
    return (value << 6) | (value >> 2)

@numba.njit
def to_byte(value):
    return np.ubyte(value >> 6)

@numba.njit
def mul(a, b):
    return (a * b) >> 14

@numba.vectorize
def lerp_ubyte(a, b, t):
    a = to_short(a)
    b = to_short(b)
    t = to_short(t)
    return to_byte(mul(b - a, t) + a)

def mosaic(image, mask, mosaic_percent, out=None):
    original_size = swap(image.shape[:2])
    min_dim = int(min(original_size) * (mosaic_percent / 100))
    min_dim = max(4, min_dim)
    scale_dimension = (original_size[0] // min_dim, original_size[1] // min_dim)
    mosaic_image = cv2.resize(image, scale_dimension, interpolation=cv2.INTER_AREA)
    if out is None:
        out = np.empty_like(image)
    mosaic_image = cv2.resize(mosaic_image, original_size, out, interpolation=cv2.INTER_NEAREST).reshape(image.shape)
    return lerp_ubyte(image, mosaic_image, mask)

def numpy_to_photoimage(array:np.ndarray):
    h, w = array.shape[:2]
    ppm_header = f'P6 {w} {h} 255 '.encode()
    data = ppm_header + array.tobytes()
    return tk.PhotoImage(width=w, height=h, data=data, format='PPM')

def get_icon_image(name, size, color):
    path = importlib.resources.files(icons).joinpath(f'{name}.svg')
    data = cairosvg.svg2png(file_obj=open(path, 'rb'), output_width=size, output_height=size)
    return tk.PhotoImage(width=size, height=size, data=data, format='png')

def add_tag(widget:tk.Widget, tag):
    widget.bindtags((tag,) + widget.bindtags())

def push_state_all(widget, state):
    try:
        widget.__state = widget.config('state')
        widget.config(state=state)
    except:
        pass
    for child in widget.winfo_children():
        push_state_all(child, state)

def pop_state_all(widget):
    try:
        widget.config(state=widget.__state)
    except:
        pass
    for child in widget.winfo_children():
        pop_state_all(child)

class timeit():
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = time.time()

    def __exit__(self, exc_type, exc, tb):
        t = (time.time() - self.start) * 1000
        print(f'{self.name} {t:.2f}')

class Observable():
    def __init__(self):
        self.callbacks = set()

    def add(self, callback):
        try:
            self.callbacks.add(weakref.WeakMethod(callback, self.remove))
        except:
            self.callbacks.add(callback)

    def remove(self, callback):
        self.callbacks.discard(callback)

    def call(self, *args, **kwargs):
        for callback in self.callbacks:
            if isinstance(callback, weakref.WeakMethod):
                cb = callback()
            else:
                cb = callback
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