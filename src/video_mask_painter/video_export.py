import asyncio
import threading
import multiprocessing as mp
from multiprocessing import connection
import queue
from pathlib import Path

import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from tkinter import filedialog

import cv2
import moderngl
import numpy as np

from . import util, project, asynctk

_vert_shader = '''
#version 460
in vec2 position;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
}
'''

_mosaic_shader = '''
#version 460
uniform sampler2D target;
uniform sampler2D mask;
uniform vec2 texture_size;
uniform float mosaic_size;
out vec4 frag_color;
void main() {
    vec2 uv = gl_FragCoord.xy / texture_size;
    vec2 size = vec2(mosaic_size, mosaic_size);
    vec2 offset = floor(gl_FragCoord.xy / size) * size;
    vec3 base_color = texture(target, uv).rgb;
    vec3 mosaic_color = vec3(0);
    // Average pixel color.
    for (float x = 0; x < mosaic_size; x++) {
        for (float y = 0; y < mosaic_size; y++) {
            mosaic_color += texture(target, (offset + vec2(x, y)) / texture_size).rgb;
        }
    }
    mosaic_color = mosaic_color / pow(mosaic_size, 2.0);
    float mask_value = texture(mask, uv).r;
    frag_color = vec4(mix(base_color, mosaic_color, mask_value), 1.0);
}
'''

def _export_mosaic(proj:project.Project, output_path:Path, mosaic_percent:float, running_callback, progress_callback) -> None:
    state = proj.get_current()
    input = cv2.VideoCapture(str(proj.video_file_path))
    fps = int(input.get(cv2.CAP_PROP_FPS))
    frame_count = input.get(cv2.CAP_PROP_FRAME_COUNT)
    size = int(input.get(cv2.CAP_PROP_FRAME_WIDTH)), int(input.get(cv2.CAP_PROP_FRAME_HEIGHT))
    output = cv2.VideoWriter(str(output_path.with_suffix('.mp4')), cv2.VideoWriter.fourcc(*'avc1'), fps, size)

    ctx = moderngl.create_context(require=460, standalone=True)
    prog = ctx.program(vertex_shader=_vert_shader, fragment_shader=_mosaic_shader)
    vertices = np.array([-1, -1, 3, -1, -1, 3], dtype=np.float32)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, vbo, 'position')
    frame_tex = ctx.texture(size, 3, dtype='nu1')
    mask_tex = ctx.texture(size, 1, dtype='nu1')
    output_tex = ctx.texture(size, 3, dtype='nu1')
    fbo = ctx.framebuffer(color_attachments=[output_tex])
    fbo.use()
    prog['target'] = 0
    prog['mask'] = 1
    prog['texture_size'] = size
    min_dim = max(4, int(min(size) * (mosaic_percent / 100)))
    prog['mosaic_size'] = min_dim
    frame_tex.use(0)
    mask_tex.use(1)

    mask_shape  = tuple(util.swap(size)) + (1,)
    color_shape = tuple(util.swap(size)) + (3,)
    blank = np.full(mask_shape, 0, dtype=np.ubyte)
    frame_data = None
    mask_data = blank
    frame_index = 0

    send_queue = queue.SimpleQueue()
    return_queue = queue.SimpleQueue()
    # Balance between speed and memory usage.
    buffer_queue_count = 10
    for i in range(buffer_queue_count):
        return_queue.put(np.empty(color_shape, dtype=np.ubyte))

    def run_writer_thread():
        while True:
            data = send_queue.get()
            if data is None:
                return
            output.write(data)
            return_queue.put(data)
            if frame_index % 10 or frame_index == frame_count:
                progress_callback((frame_index, frame_count))

    writer_thread = threading.Thread(target=run_writer_thread)
    writer_thread.start()
    buffer = np.empty(color_shape, dtype=np.ubyte)

    while running_callback():
        res, frame_data = input.read(frame_data)
        if not res:
            break
        frame_tex.write(frame_data)
        frame_index = int(input.get(cv2.CAP_PROP_POS_FRAMES))
        keyframe = state.get_keyframe(frame_index)
        if keyframe is None:
            next_mask = blank
        else:
            next_mask = keyframe.data
        if next_mask is not mask_data:
            mask_data = next_mask
            mask_tex.write(mask_data)
        vao.render()
        buffer = return_queue.get()
        fbo.read_into(buffer)
        send_queue.put(buffer)
    send_queue.put(None)
    writer_thread.join()

    input.release()
    output.release()
    ctx.release()

def _export_mosaic_proc(proj:project.Project, output_path:Path, mosaic_percent:float, conn:connection.Connection):
    try:
        _export_mosaic(
            proj,
            output_path,
            mosaic_percent,
            lambda: not conn.poll(0),
            lambda x: conn.send(x))
    except Exception as ex:
        print(ex)
    finally:
        conn.close()

class VideoExport(ttk.Frame):
    def __init__(self, master, app, *args, **kwargs):
        super().__init__(master=master, padding=3, *args, **kwargs)
        self._app = app
        frame = ttk.Frame(self)
        label = ttk.Label(frame, text='Output file:')
        label.pack(side=ttkc.LEFT)
        self._export_file_box = util.settings.get('last_export_file', '')
        self._export_file_var = ttk.StringVar(self, self._export_file_box.get())
        self._export_file_var.trace_add('write', lambda *_: self._export_file_box.set(self._export_file_var.get()))
        file_entry = ttk.Entry(frame, textvariable=self._export_file_var)
        file_entry.pack(side=ttkc.LEFT, fill=ttkc.X, expand=True)
        file_select_button = ttk.Button(frame, text='Select', command=self._on_file_selected)
        file_select_button.pack(side=ttkc.LEFT)

        frame = ttk.Frame(self)
        label = ttk.Label(frame, text='Mosaic size (%):')
        label.pack(side=ttkc.LEFT)
        self._mosaic_percent_var = ttk.DoubleVar(value=1)
        mosaic_size_spinbox = ttk.Spinbox(frame, from_=0, to=100, textvariable=self._mosaic_percent_var)
        mosaic_size_spinbox.pack(side=ttkc.LEFT, fill=ttkc.X, expand=True)

        ttk.Button(self, text='Export Mosaic', command=asynctk.AsyncTkCallback(self._on_export_mosaic))
        ttk.Button(self, text='Export Mask', command=asynctk.AsyncTkCallback(self._on_export_mask))
        ttk.Button(self, text='Cancel Running Export', command=self._on_cancel_export)

        frame = ttk.Frame(self)
        label = ttk.Label(frame, text='Progress:')
        label.pack(side=ttkc.LEFT)
        self._progress_bar = ttk.Progressbar(frame)
        self._progress_bar.pack(side=ttkc.LEFT, fill=ttkc.X, expand=True)

        frame = ttk.Frame(self)
        label = ttk.Label(frame, text='Frames:')
        label.pack(side=ttkc.LEFT)
        self._progress_label = ttk.Label(frame, text='0/0')
        self._progress_label.pack(side=ttkc.LEFT, expand=True)

        self._loop = asyncio.get_event_loop()
        self._thread_running = False
        self._thread = None

        for child in self.winfo_children():
            child.pack(fill=ttkc.X, pady=2, padx=2, expand=True)

        self.bind('<Destroy>', self._on_cancel_export, '+')

    def _on_file_selected(self):
        init_dir = Path(self._export_file_var.get()).parent
        filename = filedialog.asksaveasfilename(
            title='Output file',
            initialdir=init_dir
        )
        if filename:
            self._export_file_var.set(filename)

    def _update_progress(self, value, total):
        try:
            self._progress_bar.config(value=100 * (value / total))
            self._progress_label.config(text=f'{int(value)}/{int(total)}')
        except:
            pass

    def _update_progress_threadsafe(self, *args):
        self._loop.call_soon_threadsafe(self._update_progress, *args)

    def _export_mosaic(self, output_path:Path, mosaic_percent:float, progress_callback) -> None:
        proj = self.app.project
        if not proj:
            return
        parent_conn, child_conn = mp.Pipe()
        mp.set_start_method('spawn')
        proc = mp.Process(target=_export_mosaic_proc, args=(
            proj,
            output_path,
            mosaic_percent,
            child_conn,
        ))
        try:
            proc.start()
            child_conn.close()
            while True:
                data = parent_conn.recv()
                progress_callback(*data)
                if self._thread_running == False:
                    parent_conn.send(None)
                    break
                if not proc.is_alive():
                    break
        except EOFError:
            pass
        except Exception as ex:
            print(ex)
            proc.kill()
        finally:
            proc.join()
            proc.close()
            parent_conn.close()
            child_conn.close()

    def _export_mask(self, output_path:Path, progress_callback):
        proj = self.app.project
        if not proj:
            return
        input_file = proj.video_file_path
        state = proj.get_current()
        input = cv2.VideoCapture(str(input_file))
        fps = int(input.get(cv2.CAP_PROP_FPS))
        frame_count = input.get(cv2.CAP_PROP_FRAME_COUNT)
        size = int(input.get(cv2.CAP_PROP_FRAME_WIDTH)), int(input.get(cv2.CAP_PROP_FRAME_HEIGHT))
        input.release()
        output = cv2.VideoWriter(str(output_path.with_suffix('.mp4')), cv2.VideoWriter.fourcc(*'avc1'), fps, size)
        frame_index = 0
        blank = np.full(tuple(util.swap(size)) + (3,), 0, dtype=np.ubyte)
        mask_data = blank
        last_keyframe = None
        while self._thread_running and frame_index < frame_count:
            frame_index += 1
            keyframe = state.get_keyframe(frame_index)
            if keyframe is None:
                next_mask = blank
            elif keyframe is not last_keyframe:
                next_mask = keyframe.data.repeat(3, axis=2)
            mask_data = next_mask
            last_keyframe = keyframe
            output.write(mask_data)
            progress_callback(frame_index, frame_count)
        output.release()

    async def _thread_run(self, *args):
        if self._thread_running:
            return
        self._thread_running = True
        await asyncio.to_thread(*args)
        self._thread_running = False

    async def _on_export_mosaic(self):
        await self._thread_run(
            self._export_mosaic,
            Path(self._export_file_var.get()),
            self._mosaic_percent_var.get(),
            self._update_progress_threadsafe)

    async def _on_export_mask(self):
        await self._thread_run(
            self._export_mask,
            Path(self._export_file_var.get()),
            self._update_progress_threadsafe)

    def _on_cancel_export(self, *args):
        self._thread_running = False