import asyncio
from pathlib import Path
import importlib.metadata

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap.widgets import tooltip
from tkinter import filedialog
from ttkbootstrap import dialogs

from . import asynctk, util, video_canvas, project, timeline, bar_scale, color_picker, video_export

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

def make_button(master, name, icon_name, command):
    icon = util.get_icon_image(icon_name, size=20, color='#ffffff')
    button = ttk.Button(master, image=icon, command=command, bootstyle='outline')
    button.pack(side=ttkc.LEFT)
    button.__icon = icon
    tooltip.ToolTip(button, text=name)
    return button

def make_checkbutton(master, name, icon_name, variable):
    icon = util.get_icon_image(icon_name, size=22, color='#ffffff')
    button = ttk.Checkbutton(master, image=icon, variable=variable, bootstyle='outline-toolbutton')
    button.pack(side=ttkc.LEFT)
    button.__icon = icon
    tooltip.ToolTip(button, text=name)
    return button

def make_radiobutton(master, name, icon_name, value, variable):
    icon = util.get_icon_image(icon_name, size=22, color='#ffffff')
    button = ttk.Radiobutton(master, image=icon, value=value, variable=variable, bootstyle='outline-toolbutton')
    button.pack(side=ttkc.LEFT)
    button.__icon = icon
    tooltip.ToolTip(button, text=name)
    return button

def make_separator(master):
    sep = ttk.Separator(master, orient=ttkc.VERTICAL)
    sep.pack(side=ttkc.LEFT, padx=5)

class App(asynctk.AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {__version__}')
        self.geometry('{}x{}'.format(1200, 800))
        ttk.Style('darkly')
        initial_color = (0, 0, 255)
        initial_alpha = 127
        initial_brush_size = 10

        self.undo_limit = 100
        self.project = None

        # Menu bar
        menubar = ttk.Menu(self)
        self.config(menu=menubar)
        file_menu = ttk.Menu(menubar)
        menubar.add_cascade(label='File', menu=file_menu)
        file_menu.add_command(label='Open Video as New Project', command=self.open_video)
        file_menu.add_command(label='Open Project', command=self.open_project)
        file_menu.add_command(label='Save Project', command=self.save_project)
        file_menu.add_command(label='Save As Project', command=self.save_as_project)
        file_menu.add_command(label='Set Project Video', command=self.set_project_video)
        file_menu.add_command(label='Exit', command=self.close_requested)
        menubar.add_command(label='Render Video', command=self.render_video)

        # Video and drawing area
        self.video_canvas = video_canvas.VideoCanvas(self, initial_color, initial_alpha, width=1, height=1)
        self.video_canvas.pack(fill=ttkc.BOTH, expand=True)

        # Project Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack()
        make_button(button_frame, 'Undo', 'undo', self.undo)
        make_button(button_frame, 'Redo', 'redo', self.redo)

        make_separator(button_frame)

        # Video playback buttons
        make_button(button_frame, 'Play/Pause video', 'play-pause', self.play_pause_video)
        make_button(button_frame, 'Previous frame', 'left', self.previous_frame)
        make_button(button_frame, 'Next frame', 'right', self.next_frame)
        self.repeat_var = ttk.BooleanVar(value=False)
        self.repeat_var.trace_add('write', self.toggle_repeat)
        make_checkbutton(button_frame, 'Toggle loop video', 'repeat', self.repeat_var)
        make_button(button_frame, 'Reset view', 'fullscreen', self.reset_view)

        make_separator(button_frame)

        # Keyframe Buttons
        make_button(button_frame, 'Previous keyframe', 'keyframe-left', self.previous_keyframe)
        make_button(button_frame, 'Next keyframe', 'keyframe-right', self.next_keyframe)
        make_button(button_frame, 'Add blank keyframe', 'keyframe-blank', self.add_blank_keyframe)
        make_button(button_frame, 'Clone keyframe', 'keyframe-clone', self.clone_keyframe)
        make_button(button_frame, 'Delete keyframe', 'keyframe-delete', self.delete_keyframe)

        make_separator(button_frame)

        # Auto-keyframe radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.auto_keyframe_off = 'off'
        self.auto_keyframe_blank = 'blank'
        self.auto_keyframe_clone = 'clone'
        self.auto_keyframe_var = ttk.StringVar(value=self.auto_keyframe_off)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe off', 'auto-keyframe-off', self.auto_keyframe_off, self.auto_keyframe_var)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe blank', 'auto-keyframe-blank', self.auto_keyframe_blank, self.auto_keyframe_var)
        make_radiobutton(radio_frame, 'Toggle auto-keyframe clone', 'auto-keyframe-clone', self.auto_keyframe_clone, self.auto_keyframe_var)

        make_separator(button_frame)

        # Drawing mode radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.drawing_mode_draw = 'draw'
        self.drawing_mode_erase = 'erase'
        self.drawing_mode_var = ttk.StringVar(value=self.drawing_mode_draw)
        make_radiobutton(radio_frame, 'Toggle draw', 'draw', self.drawing_mode_draw, self.drawing_mode_var)
        make_radiobutton(radio_frame, 'Toggle erase', 'erase', self.drawing_mode_erase, self.drawing_mode_var)
        self.drawing_mode_var.trace_add('write', self.on_drawing_mode_changed)

        # Brush size selector
        brush_scale = bar_scale.BarScale(
            button_frame, label='Brush size', value=initial_brush_size, minval=1, maxval=1000,
            scale_type=bar_scale.BarScale.CURVE, height=30, width=150)
        brush_scale.pack(side=ttkc.LEFT, padx=5)
        brush_scale.value_updated_event += self.on_brush_size_changed
        brush_scale.update_stopped_event += self.video_canvas.hide_cursor

        # Mask tint selector
        self.color_picker = color_picker.ColorPickerHover(button_frame, initial_color, initial_alpha, height=30, width=40)
        self.color_picker.pack(side=ttkc.LEFT)
        self.color_picker.color_selected_event += self.video_canvas.set_mask_color
        self.color_picker.alpha_selected_event += self.video_canvas.set_mask_alpha

        button_frame = ttk.Frame(self)
        button_frame.pack()

        self.time_label = ttk.Label(button_frame)
        self.time_label.pack(side=ttkc.LEFT)
        self.video_file_name_label = ttk.Label(button_frame)
        self.video_file_name_label.pack(side=ttkc.LEFT)

        # Timeline and info
        self.timeline = timeline.Timeline(self, height=50)
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
        self.bind('<Control-z>', self.undo)
        self.bind('<z>', self.redo)

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
            self.project = project.Project(project.ProjectState(), video_file_path=Path(file_path))
            self.load_video(self.project.video_file_path)
            self.add_blank_keyframe()

    @saved_check('exiting')
    def close_requested(self):
        super().close_requested()

    @saved_check('opening')
    def open_project(self):
        file_path = filedialog.askopenfilename(
            title='Open Project',
            filetypes=project.project_file_types,
        )
        if file_path:
            self.project = project.load_project(file_path)
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
                project.save_project(self.project, self.project.project_file_path)
                self.project.set_saved()
                return True
            else:
                return self.save_as_project()
        return False

    def save_as_project(self, *args):
        if self.project:
            file_path = filedialog.asksaveasfilename(
                title='Save As',
                filetypes=project.project_file_types,
            )
            if file_path:
                file_path = Path(file_path)
                project.save_project(self.project, file_path)
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
        if self.project:
            util.push_state_all(self, ttkc.DISABLED)
            export_window = video_export.VideoExport(self, self.project)
            export_window.transient(self)
            export_window.grab_set()
            def done(e):
                util.pop_state_all(self)
                export_window.grab_release()
            export_window.bind('<Destroy>', done, '+')

    def update_to_selected(self):
        if self.project:
            state = self.project.get_current()
            if state.selected_index:
                self.video_canvas.set_frame_pos(state.selected_index)

    def undo(self, *args):
        if self.project:
            self.project.undo()
            self.update_to_selected()
            self.update_view()

    def redo(self, *args):
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
            keyframe = project.Keyframe(index=index, data=data)
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

    def play_pause_video(self):
        if self.video_canvas.is_playing():
            self.video_canvas.pause()
        else:
            self.video_canvas.play()

    def previous_frame(self, *args):
        self.video_canvas.previous_frame()

    def next_frame(self, *args):
        self.video_canvas.next_frame()

    def toggle_repeat(self, *args):
        self.repeat_var.get()

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