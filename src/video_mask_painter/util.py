import time
import weakref
import tkinter as tk

from pyrsistent import *
import numpy as np

def lerp(a, b, t):
    return (b - a) * t + a

def bilinear(a, b, c, t):
    ab = lerp(a, b, t)
    bc = lerp(b, c, t)
    return lerp(ab, bc, t)

epsilon = 0.00001

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

def event_vec(event:tk.Event):
    return np.array((event.x, event.y))

def swap(vec):
    return np.array((vec[1], vec[0]))

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