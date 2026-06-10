import asyncio
from pathlib import Path
import importlib.metadata
import tempfile
import threading

import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from tkinter import filedialog
from ttkbootstrap import dialogs

from . import asynctk, util, video_canvas, project, timeline, bar_scale, color_picker, video_export

__package__ = 'video-mask-painter'
__version__ = importlib.metadata.version(__package__)

def make_separator(master):
    sep = ttk.Separator(master, orient=ttkc.VERTICAL)
    sep.pack(side=ttkc.LEFT, padx=5)

def load_settings(file_name:str):
    file_path = Path.home() / file_name
    if not file_path.exists():
        return {}

class App(asynctk.AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {__version__}')
        ttk.Style('darkly')

        self.settings = util.Settings(f'.{__package__}')
        self.win_geometry_var = self.settings.get('win_geometry', "1200x800")
        self.mask_color_var = self.settings.get('mask_color', (0, 0, 255))
        self.mask_alpha_var = self.settings.get('mask_alpha', 127)
        self.brush_size_var = self.settings.get('brush_size', 10)
        self.last_open_dir_var = self.settings.get('last_open_dir', '')
        self.last_export_file_var = self.settings.get('last_export_file', '')

        self.geometry(self.win_geometry_var.get())

        self.undo_limit = 100
        self.project = None

        # Menu bar
        menubar = ttk.Menu(self)
        self.config(menu=menubar)
        file_menu = ttk.Menu(menubar)
        menubar.add_cascade(label='File', menu=file_menu)
        file_menu.add_command(label='Open Video as New Project', command=self.open_video)
        file_menu.add_command(label='Open Project', command=self.open_project)
        file_menu.add_command(label='Open Project from Backup Directory', command=self.open_project_from_backup_dir)
        file_menu.add_command(label='Save Project', command=self.save_project)
        file_menu.add_command(label='Save As Project', command=self.save_as_project)
        file_menu.add_command(label='Set Project Video', command=self.set_project_video)
        file_menu.add_command(label='Exit', command=self.close_requested)
        menubar.add_command(label='Render Video', command=self.render_video)

        self.base_frame = ttk.Frame(self)
        self.base_frame.place(relwidth=1, relheight=1)

        # Video and drawing area
        self.video_canvas = video_canvas.VideoCanvas(self.base_frame, self.mask_color_var.get(), self.mask_alpha_var.get(), width=1, height=1)
        self.video_canvas.pack(fill=ttkc.BOTH, expand=True)

        # Project Buttons
        button_frame = ttk.Frame(self.base_frame)
        button_frame.pack()
        util.make_button(button_frame, 'Undo', 'undo', self.undo)
        util.make_button(button_frame, 'Redo', 'redo', self.redo)

        make_separator(button_frame)

        # Video playback buttons
        util.make_button(button_frame, 'Play/Pause video', 'play-pause', self.play_pause_video)
        util.make_button(button_frame, 'Previous frame', 'left', self.previous_frame)
        util.make_button(button_frame, 'Next frame', 'right', self.next_frame)
        self.repeat_var = ttk.BooleanVar(value=False)
        self.repeat_var.trace_add('write', self.toggle_repeat)
        util.make_checkbutton(button_frame, 'Toggle loop video', 'repeat', self.repeat_var)
        util.make_button(button_frame, 'Reset view', 'fullscreen', self.reset_view)

        make_separator(button_frame)

        # Keyframe Buttons
        util.make_button(button_frame, 'Previous keyframe', 'keyframe-left', self.previous_keyframe)
        util.make_button(button_frame, 'Next keyframe', 'keyframe-right', self.next_keyframe)
        util.make_button(button_frame, 'Add blank keyframe', 'keyframe-blank', self.add_blank_keyframe)
        util.make_button(button_frame, 'Clone keyframe', 'keyframe-clone', self.clone_keyframe)
        util.make_button(button_frame, 'Delete keyframe', 'keyframe-delete', self.delete_keyframe)
        util.make_button(button_frame, 'Cut keyframe', 'keyframe-cut', self.cut_keyframe)
        util.make_button(button_frame, 'Copy keyframe', 'keyframe-copy', self.copy_keyframe)
        util.make_button(button_frame, 'Paste keyframe', 'keyframe-paste', self.paste_keyframe)

        make_separator(button_frame)

        # Auto-keyframe radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.auto_keyframe_off = 'off'
        self.auto_keyframe_blank = 'blank'
        self.auto_keyframe_clone = 'clone'
        self.auto_keyframe_var = ttk.StringVar(value=self.auto_keyframe_off)
        util.make_radiobutton(radio_frame, 'Toggle auto-keyframe off', 'auto-keyframe-off', self.auto_keyframe_off, self.auto_keyframe_var)
        util.make_radiobutton(radio_frame, 'Toggle auto-keyframe blank', 'auto-keyframe-blank', self.auto_keyframe_blank, self.auto_keyframe_var)
        util.make_radiobutton(radio_frame, 'Toggle auto-keyframe clone', 'auto-keyframe-clone', self.auto_keyframe_clone, self.auto_keyframe_var)

        make_separator(button_frame)

        # Drawing mode radio
        radio_frame = ttk.Frame(button_frame)
        radio_frame.pack(fill=ttkc.X, side=ttkc.LEFT)
        self.drawing_mode_draw = 'draw'
        self.drawing_mode_erase = 'erase'
        self.drawing_mode_var = ttk.StringVar(value=self.drawing_mode_draw)
        util.make_radiobutton(radio_frame, 'Toggle draw', 'draw', self.drawing_mode_draw, self.drawing_mode_var)
        util.make_radiobutton(radio_frame, 'Toggle erase', 'erase', self.drawing_mode_erase, self.drawing_mode_var)
        self.drawing_mode_var.trace_add('write', self.on_drawing_mode_changed)

        # Brush size selector
        brush_scale = bar_scale.BarScale(
            button_frame, label='Brush size', value=self.brush_size_var.get(), minval=1, maxval=1000,
            scale_type=bar_scale.BarScale.CURVE, height=30, width=150)
        brush_scale.pack(side=ttkc.LEFT, padx=5)
        brush_scale.value_updated_event += self.video_canvas.set_brush_size
        brush_scale.value_updated_event += lambda v: self.brush_size_var.set(int(v))
        brush_scale.update_stopped_event += self.video_canvas.hide_cursor

        # Mask tint selector
        self.color_picker = color_picker.ColorPickerHover(button_frame, self.mask_color_var.get(), self.mask_alpha_var.get(), height=30, width=40)
        self.color_picker.pack(side=ttkc.LEFT)
        self.color_picker.color_selected_event += self.video_canvas.set_mask_color
        self.color_picker.alpha_selected_event += self.video_canvas.set_mask_alpha
        self.color_picker.color_selected_event += lambda v: self.mask_color_var.set(tuple(v))
        self.color_picker.alpha_selected_event += self.mask_alpha_var.set

        button_frame = ttk.Frame(self.base_frame)
        button_frame.pack()

        self.time_label = ttk.Label(button_frame)
        self.time_label.pack(side=ttkc.LEFT)
        self.video_file_name_label = ttk.Label(button_frame)
        self.video_file_name_label.pack(side=ttkc.LEFT)
        self.saved_label = ttk.Label(button_frame, width=2)
        self.saved_label.pack(side=ttkc.LEFT)

        # Timeline and info
        self.timeline = timeline.Timeline(self.base_frame, height=50)
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
        self.bind('<Control-Z>', self.redo)
        self.bind('<Control-y>', self.redo)
        self.bind('<Destroy>', self.on_destroy)
        self.bind('<x>', self.cut_keyframe)
        self.bind('<c>', self.copy_keyframe)
        self.bind('<v>', self.paste_keyframe)

        self.stopped_event = threading.Event()
        self.last_auto_saved_id = None
        self.auto_backup_task = asyncio.create_task(asyncio.to_thread(self.auto_backup))

    def auto_backup(self):
        while not self.stopped_event.wait(60):
            proj = self.project
            if proj and not proj.is_saved() and self.last_auto_saved_id != proj.get_current_id():
                temp = Path(tempfile.gettempdir())
                if proj.project_file_path is not None:
                    file = proj.project_file_path.name
                else:
                    file = proj.video_file_path.with_suffix(project.project_extension + '~').name
                file = temp / file
                project.save_project(proj, file)
                self.last_auto_saved_id = proj.get_current_id()

    def on_destroy(self, event):
        self.win_geometry_var.set(self.winfo_geometry())
        self.settings.save()
        self.stopped_event.set()
        for task in [self.auto_backup_task]:
            if task is not None and not task.done():
                task.cancel()
                try:
                    ex = task.exception()
                    print(ex)
                except:
                    pass

    def get_current(self):
        index = self.video_canvas.get_frame_pos()
        state = self.project.get_current()
        keyframe = state.get_keyframe(index)
        return index, state, keyframe

    def update_view(self):
        if self.project:
            self.timeline.clear_keyframes()
            index, state, keyframe = self.get_current()
            for kf in state.keyframes:
                self.timeline.add_keyframe(kf.index)
            data = keyframe.data if keyframe else None
            self.video_canvas.set_mask_image_array(data)
            self.video_canvas.update_view()
            self.update_saved_label()

    def update_saved_label(self):
        if self.project is not None:
            self.saved_label.config(text='' if self.project.is_saved() else '*')

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

    def on_drawing_started(self):
        if self.project:
            index, state, keyframe = self.get_current()
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
            self.project = self.project.append(state, self.undo_limit)
            self.update_saved_label()

    def load_video(self, file_path:Path):
        self.video_canvas.open_video(file_path)
        self.video_file_name_label.config(text=f'({file_path.name})')
        self.timeline.set_frame_count(self.video_canvas.get_frame_count())
        self.update_view()

    @staticmethod
    def saved_check(string):
        def wrapped(func):
            def wrapped(self, *args, **kwargs):
                if self.project and not self.project.is_saved():
                    result = dialogs.Messagebox.yesnocancel(f'Save current project before {string}?', 'Save')
                    if result == 'No':
                        pass
                    elif result == 'Yes':
                        if not self.save_project():
                            return
                    else:
                        return
                func(self, *args, **kwargs)
            return wrapped
        return wrapped

    @saved_check('opening')
    def open_video(self):
        file_path = filedialog.askopenfilename(
            title='Open Video',
            filetypes=(('MP4', '*.mp4'), ('Any', '*.*')),
            initialdir=self.last_open_dir_var.get(),
        )
        if file_path:
            file_path = Path(file_path)
            self.last_open_dir_var.set(str(file_path.parent))
            self.project = project.Project(video_file_path=file_path).set_saved()
            self.last_auto_saved_id = None
            self.update_saved_label()
            self.load_video(self.project.video_file_path)
            self.add_blank_keyframe()

    @saved_check('exiting')
    def close_requested(self):
        super().close_requested()

    @saved_check('opening')
    def open_project_from_dir(self, dir:Path):
        file_path = filedialog.askopenfilename(
            title='Open Project',
            filetypes=project.project_file_types,
            initialdir=dir,
        )
        if file_path:
            file_path = Path(file_path)
            self.last_open_dir_var.set(str(file_path.parent))
            self.project = project.load_project(file_path)
            self.last_auto_saved_id = None
            self.update_saved_label()
            try:
                self.load_video(self.project.video_file_path)
            except:
                result = dialogs.Messagebox.yesno(
                    'Could not find or open project video file.\nPick another video to load for this project?',
                    'Video Load Error')
                if result == 'Yes':
                    self.set_project_video()

    def open_project(self):
        self.open_project_from_dir(self.last_open_dir_var.get())

    def open_project_from_backup_dir(self):
        self.open_project_from_dir(tempfile.gettempdir())

    def save_project(self, *args):
        if self.project:
            if self.project.project_file_path:
                project.save_project(self.project, self.project.project_file_path)
                self.project = self.project.set_saved()
                self.update_saved_label()
                return True
            else:
                return self.save_as_project()
        return False

    def save_as_project(self, *args):
        if self.project:
            file_path = filedialog.asksaveasfilename(
                title='Save As',
                filetypes=project.project_file_types,
                initialdir=self.last_open_dir_var.get(),
            )
            if file_path:
                file_path = Path(file_path)
                self.last_open_dir_var.set(str(file_path.parent))
                project.save_project(self.project, file_path)
                self.project = self.project.set(project_file_path=file_path).set_saved()
                self.update_saved_label()
                return True
        return False

    def set_project_video(self):
        if self.project:
            file_path = filedialog.askopenfilename(
                title='Set Project Video',
                filetypes=(('MP4', '*.mp4'), ('Any', '*.*')),
                initialdir=self.last_open_dir_var.get(),
            )
            if file_path:
                file_path = Path(file_path)
                self.last_open_dir_var.set(str(file_path.parent))
                self.project = self.project.set(video_file_path=file_path).set_dirty()
                self.update_saved_label()
                self.load_video(self.project.video_file_path)
        else:
            self.open_video()

    def render_video(self):
        if self.project:
            util.push_state_all(self, ttkc.DISABLED)
            export_window = video_export.VideoExport(self, self.project, self.last_export_file_var)
            export_window.place(anchor=ttkc.CENTER, relx=0.5, rely=0.5, width=500)
            export_window.grab_set()
            self.video_canvas.config(cursor='')
            self.video_canvas.update_view()
            def done(e):
                if self.video_canvas.winfo_exists():
                    self.video_canvas.config(cursor='none')
                util.pop_state_all(self)
                export_window.grab_release()
            export_window.bind('<Destroy>', done, '+')

    def update_to_selected(self):
        if self.project:
            state = self.project.get_current()
            if state.selected_index is not None:
                self.video_canvas.set_frame_pos(state.selected_index)

    def undo(self, *args):
        if self.project:
            self.project = self.project.undo()
            self.update_to_selected()
            self.update_view()

    def redo(self, *args):
        if self.project:
            self.project = self.project.redo()
            self.update_to_selected()
            self.update_view()

    def previous_keyframe(self, *args):
        if self.project:
            index, state, keyframe = self.get_current()
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def next_keyframe(self, *args):
        if self.project:
            index, state, keyframe = self.get_current()
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def add_blank_keyframe(self, *args):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe and keyframe.index == index:
                return
            data = self.video_canvas.get_blank_image_array()
            keyframe = project.Keyframe(index=index, data=data)
            state = state.insert_keyframe(keyframe).set(selected_index=index)
            self.project = self.project.append(state, self.undo_limit)
            self.update_view()

    def clone_keyframe(self):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe and keyframe.index == index:
                return
            if not keyframe:
                self.add_blank_keyframe()
                return
            keyframe = keyframe.set(index=index)
            state = state.insert_keyframe(keyframe).set(selected_index=index)
            self.project = self.project.append(state, self.undo_limit)
            self.update_view()

    def delete_keyframe(self):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe:
                state = state.remove_keyframe(index).set(selected_index=None)
                self.project = self.project.append(state, self.undo_limit)
            self.update_view()

    def cut_keyframe(self, *args):
        self.copy_keyframe()
        self.delete_keyframe()

    def copy_keyframe(self, *args):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe:
                self.project = self.project.set(copy_buffer=keyframe)

    def paste_keyframe(self, *args):
        if self.project and self.project.copy_buffer:
            index, state, keyframe = self.get_current()
            buffer = self.project.copy_buffer
            if keyframe and keyframe.index == index:
                state = state.update_keyframe(index, buffer.data)
            else:
                state = state.insert_keyframe(buffer.set(index=index))
            self.project = self.project.append(state, self.undo_limit)
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
        self.video_canvas.set_repeat(self.repeat_var.get())

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