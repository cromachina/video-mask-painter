import asyncio
from pathlib import Path

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap_icons_bs import BootstrapIcon
from tkinter import filedialog
from ttkbootstrap import dialogs

import cv2
import numpy as np

from . import util, project, asynctk

class VideoExport(tk.Toplevel):
    def __init__(self, master, proj:project.Project, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._project = proj
        frame = ttk.Frame(self)
        label = ttk.Label(frame, text='Output file:')
        label.pack(side=ttkc.LEFT)
        self._output_file_var = ttk.StringVar()
        file_entry = ttk.Entry(frame, textvariable=self._output_file_var)
        file_entry.pack(side=ttkc.LEFT, fill=ttkc.X, expand=True)
        file_select_button = ttk.Button(frame, text="Select", command=self._on_file_selected)
        file_select_button.pack(side=ttkc.LEFT)
        frame = ttk.Frame(self)
        label = ttk.Label(frame, text="Mosaic size (percent):")
        label.pack(side=ttkc.LEFT)
        self._mosaic_percent_var = ttk.DoubleVar(value=1)
        mosaic_size_spinbox = ttk.Spinbox(frame, from_=0, to=100, textvariable=self._mosaic_percent_var)
        mosaic_size_spinbox.pack(side=ttkc.LEFT, fill=ttkc.X, expand=True)
        ttk.Button(self, text='Export Mosaic', command=asynctk.AsyncTkCallback(self._on_export_mosaic))
        ttk.Button(self, text='Export Mask', command=asynctk.AsyncTkCallback(self._on_export_mask))
        self._progress_label = ttk.Label(self)
        self._progress_bar = ttk.Progressbar(self)
        ttk.Button(self, text='Cancel Running Export', command=self._on_cancel_export)
        self._loop = asyncio.get_event_loop()
        self._thread_running = False
        self._thread = None

        for child in self.winfo_children():
            child.pack(fill=ttkc.X, pady=2, padx=2)

        self.bind('<Destroy>', self._on_cancel_export, '+')

    def _on_file_selected(self):
        filename = filedialog.asksaveasfilename(
            title="Output file",
        )
        if filename:
            self._output_file_var.set(filename)

    def _update_progress(self, value):
        self._progress_label.config(text=str(int(value)))
        self._progress_bar.config(value=value)

    def _update_progress_threadsafe(self, value):
        self._loop.call_soon_threadsafe(self._update_progress, value)

    def _export_mosaic(self, output_path:Path, mosaic_percent:float, progress_callback) -> None:
        input_file = self._project.video_file_path
        state = self._project.get_current()
        input = cv2.VideoCapture(str(input_file))
        fps = int(input.get(cv2.CAP_PROP_FPS))
        frame_count = input.get(cv2.CAP_PROP_FRAME_COUNT)
        size = int(input.get(cv2.CAP_PROP_FRAME_WIDTH)), int(input.get(cv2.CAP_PROP_FRAME_HEIGHT))
        output = cv2.VideoWriter(str(output_path.with_suffix('.mp4')), cv2.VideoWriter.fourcc(*'avc1'), fps, size)
        data = None
        buffer = None
        while self._thread_running:
            res, data = input.read(data)
            if not res:
                break
            frame_index = input.get(cv2.CAP_PROP_POS_FRAMES)
            keyframe = state.get_keyframe(frame_index)
            mask = keyframe.data
            buffer = util.mosaic(data, mask, mosaic_percent, buffer)
            output.write(buffer)
            progress_callback(100 * (frame_index / frame_count))
        input.release()
        output.release()

    def _export_mask(self, output_path:Path, progress_callback):
        input_file = self._project.video_file_path
        state = self._project.get_current()
        input = cv2.VideoCapture(str(input_file))
        fps = int(input.get(cv2.CAP_PROP_FPS))
        frame_count = input.get(cv2.CAP_PROP_FRAME_COUNT)
        size = int(input.get(cv2.CAP_PROP_FRAME_WIDTH)), int(input.get(cv2.CAP_PROP_FRAME_HEIGHT))
        input.release()
        output = cv2.VideoWriter(str(output_path.with_suffix('.mp4')), cv2.VideoWriter.fourcc(*'avc1'), fps, size)
        frame_index = 0
        last_keyframe = None
        while self._thread_running and frame_index < frame_count:
            frame_index += 1
            keyframe = state.get_keyframe(frame_index)
            if keyframe is not last_keyframe:
                data = keyframe.data.repeat(3, axis=2)
            last_keyframe = keyframe
            output.write(data)
            progress_callback(100 * (frame_index / frame_count))
        output.release()

    async def _on_export_mosaic(self):
        if self._thread_running:
            return
        self._thread_running = True
        await asyncio.to_thread(
            self._export_mosaic,
            Path(self._output_file_var.get()),
            self._mosaic_percent_var.get(),
            self._update_progress_threadsafe)
        self._thread_running = False

    async def _on_export_mask(self):
        if self._thread_running:
            return
        self._thread_running = True
        await asyncio.to_thread(
            self._export_mask,
            Path(self._output_file_var.get()),
            self._update_progress_threadsafe)
        self._thread_running = False

    def _on_cancel_export(self, *args):
        self._thread_running = False