import asyncio
from pathlib import Path
import importlib.metadata

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap.widgets import tooltip
from ttkbootstrap_icons_bs import BootstrapIcon
from tkinter import filedialog
from ttkbootstrap import dialogs

from .util import *
from .video_canvas import VideoCanvas
from .project import *
from .timeline import *
from .bar_scale import *

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

class AsyncTk(tk.Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

class App(AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {__version__}')
        self.geometry('{}x{}'.format(1200, 800))
        ttk.Style('darkly')
        self.protocol('WM_DELETE_WINDOW', self.on_exit)

        self.undo_limit = 100
        self.project = None

        # Menu bar
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        file_menu = tk.Menu(menubar)
        menubar.add_cascade(label='File', menu=file_menu)
        file_menu.add_command(label='Open Video as New Project', command=self.open_video)
        file_menu.add_command(label='Open Project', command=self.open_project)
        file_menu.add_command(label='Save Project', command=self.save_project)
        file_menu.add_command(label='Save As Project', command=self.save_as_project)
        file_menu.add_command(label='Set Project Video', command=self.set_project_video)
        file_menu.add_command(label='Render Video', command=self.render_video)
        file_menu.add_command(label='Exit', command=self.on_exit)

        # Video and drawing area
        self.video_canvas = VideoCanvas(self, width=1, height=1)
        self.video_canvas.pack(fill=ttkc.BOTH, expand=True)

        # Project Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack()
        make_button(button_frame, 'Undo', 'arrow-90deg-left', self.undo)
        make_button(button_frame, 'Redo', 'arrow-90deg-right', self.redo)

        make_separator(button_frame)

        # Video playback buttons
        make_button(button_frame, 'Play video', 'play', self.play_video)
        make_button(button_frame, 'Pause video', 'pause', self.pause_video)
        make_button(button_frame, 'Previous frame', 'arrow-left-short', self.previous_frame)
        make_button(button_frame, 'Next frame', 'arrow-right-short', self.next_frame)
        self.loop_button = make_checkbutton(button_frame, 'Toggle loop video', 'repeat')
        make_button(button_frame, 'Reset view', 'arrows-fullscreen', self.reset_view)

        make_separator(button_frame)

        # Keyframe Buttons
        make_button(button_frame, 'Previous keyframe', 'arrow-left-square', self.previous_keyframe)
        make_button(button_frame, 'Next keyframe', 'arrow-right-square', self.next_keyframe)
        make_button(button_frame, 'Add blank keyframe', 'square', self.add_blank_keyframe)
        make_button(button_frame, 'Clone keyframe', 'copy', self.clone_keyframe)
        make_button(button_frame, 'Delete keyframe', 'x-square', self.delete_keyframe)

        make_separator(button_frame)

        # Auto-keyframe radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.auto_keyframe_off = 'off'
        self.auto_keyframe_blank = 'blank'
        self.auto_keyframe_clone = 'clone'
        self.auto_keyframe_var = ttk.StringVar(value=self.auto_keyframe_off)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe off', 'window-x', self.auto_keyframe_off, self.auto_keyframe_var)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe blank', 'window', self.auto_keyframe_blank, self.auto_keyframe_var)
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
        brush_scale = BarScale(
            button_frame, label='Brush size', value=1, minval=1, maxval=1000,
            scale_type=BarScale.CURVE, height=30, width=150)
        brush_scale.pack(side=ttkc.LEFT, padx=5)
        brush_scale.value_updated_event += self.on_brush_size_changed

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
        self.timeline.bind('<Button-4>', self.previous_frame)
        self.timeline.bind('<Button-5>', self.next_frame)

        self.bind('<Left>', self.previous_frame)
        self.bind('<Right>', self.next_frame)
        self.bind('<Shift-Left>', self.previous_keyframe)
        self.bind('<Shift-Right>', self.next_keyframe)
        self.bind('<Control-s>', self.save_project)
        self.bind('<Control-S>', self.save_as_project)

        #self.bind('<KeyPress>', print)

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

    def on_brush_size_changed(self, value):
        self.video_canvas.set_brush_size(int(value))

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

    def load_video(self, file_path:Path):
        self.video_canvas.open_video(file_path)
        self.video_file_name_label.config(text=f'({file_path.name})')
        self.timeline.set_frame_count(self.video_canvas.get_frame_count())
        self.update_view()

    @staticmethod
    def saved_check(string):
        def wrapped(func):
            def wrapped(self):
                if self.project and not self.project.is_saved():
                    result = dialogs.Messagebox.yesnocancel(f'Save current project before {string}?', 'Save')
                    if result == 'No':
                        pass
                    elif result == 'Yes':
                        if not self.save_project():
                            return
                    else:
                        return
                func(self)
            return wrapped
        return wrapped

    @saved_check('opening')
    def open_video(self):
        file_path = filedialog.askopenfilename(
            title='Open Video',
            filetypes=(('MP4', '*.mp4'), ('Any', '*.*')),
        )
        if file_path:
            self.project = Project(ProjectState(), video_file_path=Path(file_path))
            self.load_video(self.project.video_file_path)
            self.add_blank_keyframe()

    @saved_check('exiting')
    def on_exit(self):
        self.stop()

    @saved_check('opening')
    def open_project(self):
        file_path = filedialog.askopenfilename(
            title='Open Project',
            filetypes=project_file_types,
        )
        if file_path:
            self.project = load_project(file_path)
            try:
                self.load_video(self.project.video_file_path)
            except:
                result = dialogs.Messagebox.yesno(
                    'Could not find or open project video file.\nPick another video to load for this project?',
                    'Video Load Error')
                if result == 'Yes':
                    self.set_project_video()

    def save_project(self, *args):
        if self.project:
            if self.project.project_file_path:
                save_project(self.project, self.project.project_file_path)
                self.project.set_saved()
                return True
            else:
                return self.save_as_project()
        return False

    def save_as_project(self, *args):
        if self.project:
            file_path = filedialog.asksaveasfilename(
                title='Save As',
                filetypes=project_file_types,
            )
            if file_path:
                file_path = Path(file_path)
                save_project(self.project, file_path)
                self.project.set_saved()
                self.project.project_file_path = file_path
                return True
        return False

    def set_project_video(self):
        if self.project:
            file_path = filedialog.askopenfilename(
                title='Set Project Video',
                filetypes=(('MP4', '*.mp4'), ('Any', '*.*')),
            )
            if file_path:
                self.project.video_file_path = Path(file_path)
                self.project.set_dirty()
                self.load_video(self.project.video_file_path)
        else:
            self.open_video()

    def render_video(self):
        pass

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

    def previous_keyframe(self, *args):
        if self.project:
            state = self.project.get_current()
            index = self.video_canvas.get_frame_pos()
            keyframe = state.get_previous_keyframe(index)
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def next_keyframe(self, *args):
        if self.project:
            state = self.project.get_current()
            index = self.video_canvas.get_frame_pos()
            keyframe = state.get_next_keyframe(index)
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def add_blank_keyframe(self, *args):
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
                state = state.remove_keyframe(index).set(selected_index=None)
                self.project.append(state, self.undo_limit)
            self.update_view()

    def play_video(self):
        self.video_canvas.play()

    def pause_video(self):
        self.video_canvas.pause()

    def previous_frame(self, *args):
        self.video_canvas.previous_frame()

    def next_frame(self, *args):
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