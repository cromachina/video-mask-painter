import asyncio
from pathlib import Path
import tempfile
import threading

import tkinter as tk
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from tkinter import filedialog
from ttkbootstrap import dialogs

from . import asynctk, util, video_canvas, project, timeline, bar_scale, color_picker, video_export, action

def make_separator(master):
    sep_frame = ttk.Frame(master)
    sep = ttk.Separator(sep_frame, orient=ttkc.VERTICAL)
    sep.pack(padx=5)
    return sep_frame

class App(asynctk.AsyncTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(f'{__package__} {util.__version__}')
        ttk.Style('darkly')

        self.win_geometry_var = util.settings.get('win_geometry', "1200x800")
        self.mask_color_var = util.settings.get('mask_color', (0, 0, 255))
        self.mask_alpha_var = util.settings.get('mask_alpha', 127)
        self.brush_size_var = util.settings.get('brush_size', 10)
        self.last_open_dir_var = util.settings.get('last_open_dir', '')
        self.last_export_file_var = util.settings.get('last_export_file', '')

        def add_menu_action(menu, action, command):
            action.trigger += command
            menu.add_command(label=action.name, command=action.trigger)

        def make_action_button(master, action, command):
            action.trigger += command
            util.make_button(master, action.name, action.icon, action.trigger)

        def make_action_radio(master, action, value, var):
            action.trigger = lambda *_: var.set(value)
            util.make_radiobutton(button_frame, action.name, action.icon, value, var)

        self.action_runner = action.ActionRunner(self)

        open_video_as_new_project_action = self.action_runner.add_action(action.Action('Open Video as New Project'))
        open_project_action = self.action_runner.add_action(action.Action('Open Project'))
        open_project_from_backup_dir_action = self.action_runner.add_action(action.Action('Open Project from Backup Directory'))
        save_project_action = self.action_runner.add_action(action.Action('Save Project', [{'s'}]))
        save_as_project_action = self.action_runner.add_action(action.Action('Save As Project', [{'shift', 's'}]))
        set_project_video_action = self.action_runner.add_action(action.Action('Set Project Video'))
        exit_action = self.action_runner.add_action(action.Action('Exit'))
        render_video_action = self.action_runner.add_action(action.Action('Render Video'))
        shortcut_keys_action = self.action_runner.add_action(action.Action('Shortcut Keys'))
        undo_action = self.action_runner.add_action(action.Action('Undo', [{'z'}], 'undo'))
        redo_action = self.action_runner.add_action(action.Action('Redo', [{'a'}], 'redo'))
        play_pause_video_action = self.action_runner.add_action(action.Action('Play/Pause video', [{'space'}], 'play-pause'))
        previous_frame_action = self.action_runner.add_action(action.Action('Previous frame', [{'left'}, {'mouse4'}], 'left'))
        next_frame_action = self.action_runner.add_action(action.Action('Next frame', [{'right'}, {'mouse5'}], 'right'))
        toggle_loop_video_action = self.action_runner.add_action(action.Action('Toggle loop video', icon='repeat'))
        reset_view_action = self.action_runner.add_action(action.Action('Reset view', icon='fullscreen'))
        previous_keyframe_action = self.action_runner.add_action(action.Action('Previous keyframe', [{'shift', 'left'}, {'shift', 'mouse4'}], 'keyframe-left'))
        next_keyframe_action = self.action_runner.add_action(action.Action('Next keyframe', [{'shift', 'right'}, {'shift', 'mouse5'}], 'keyframe-right'))
        add_blank_keyframe_action = self.action_runner.add_action(action.Action('Add blank keyframe', [{'d'}], 'keyframe-blank'))
        clone_keyframe_action = self.action_runner.add_action(action.Action('Clone keyframe', [{'f'}],'keyframe-clone'))
        delete_keyframe_action = self.action_runner.add_action(action.Action('Delete keyframe', [{'g'}], 'keyframe-delete'))
        cut_keyframe_action = self.action_runner.add_action(action.Action('Cut keyframe', [{'x'}], 'keyframe-cut'))
        copy_keyframe_action = self.action_runner.add_action(action.Action('Copy keyframe', [{'c'}],'keyframe-copy'))
        paste_keyframe_action = self.action_runner.add_action(action.Action('Paste keyframe', [{'v'}], 'keyframe-cut'))
        paste_keyframe_into_action = self.action_runner.add_action(action.Action('Paste keyframe', [{'b'}], 'keyframe-cut'))
        toggle_auto_keyframe_off_action = self.action_runner.add_action(action.Action('Toggle auto-keyframe off', [{'e'}],'auto-keyframe-off'))
        toggle_auto_keyframe_blank_action = self.action_runner.add_action(action.Action('Toggle auto-keyframe blank', [{'r'}],'auto-keyframe-blank'))
        toggle_auto_keyframe_clone_action = self.action_runner.add_action(action.Action('Toggle auto-keyframe clone', [{'t'}],'auto-keyframe-clone'))
        toggle_draw_action = self.action_runner.add_action(action.Action('Toggle draw', [{'1'}], 'draw'))
        toggle_erase_action = self.action_runner.add_action(action.Action('Toggle erase', [{'2'}], 'erase'))
        incr_brush_size_fast_action =  self.action_runner.add_action(action.Action('Increment brush size (fast)'))
        decr_brush_size_fast_action =  self.action_runner.add_action(action.Action('Decrement brush size (fast)'))
        incr_brush_size_slow_action =  self.action_runner.add_action(action.Action('Increment brush size (slow)'))
        decr_brush_size_slow_action =  self.action_runner.add_action(action.Action('Decrement brush size (slow)'))

        self.geometry(self.win_geometry_var.get())

        self.undo_limit = 100
        self.project = None

        # Menu bar
        menubar = ttk.Menu(self)
        self.config(menu=menubar)
        file_menu = ttk.Menu(menubar)

        menubar.add_cascade(label='File', menu=file_menu)
        add_menu_action(file_menu, open_video_as_new_project_action, self.open_video)
        add_menu_action(file_menu, open_project_action, self.open_project)
        add_menu_action(file_menu, open_project_from_backup_dir_action, self.open_project_from_backup_dir)
        add_menu_action(file_menu, save_project_action, self.save_project)
        add_menu_action(file_menu, save_as_project_action, self.save_as_project)
        add_menu_action(file_menu, set_project_video_action, self.set_project_video)
        add_menu_action(file_menu, exit_action, self.close_requested)
        add_menu_action(menubar, render_video_action, self.render_video)
        add_menu_action(menubar, shortcut_keys_action, self.shortcut_keys)

        self.base_frame = ttk.Frame(self)
        self.base_frame.place(relwidth=1, relheight=1)

        # Video and drawing area
        self.video_canvas = video_canvas.VideoCanvas(self.base_frame, self.mask_color_var.get(), self.mask_alpha_var.get(), width=1, height=1)
        self.video_canvas.pack(fill=ttkc.BOTH, expand=True)

        # Project Buttons
        button_frame = util.FlowLayout(self.base_frame)
        button_frame.pack(fill=ttkc.X)
        make_action_button(button_frame, undo_action, self.undo)
        make_action_button(button_frame, redo_action, self.redo)

        make_separator(button_frame)

        # Video playback buttons
        make_action_button(button_frame, play_pause_video_action, self.play_pause_video)
        make_action_button(button_frame, previous_frame_action, self.previous_frame)
        make_action_button(button_frame, next_frame_action, self.next_frame)
        toggle_loop_video_action.trigger += self.toggle_repeat
        self.repeat_var = ttk.BooleanVar(value=False)
        self.repeat_var.trace_add('write', toggle_loop_video_action.trigger)
        util.make_checkbutton(button_frame, toggle_loop_video_action.name, toggle_loop_video_action.icon, self.repeat_var)
        make_action_button(button_frame, reset_view_action, self.reset_view)

        make_separator(button_frame)

        # Keyframe Buttons
        make_action_button(button_frame, previous_keyframe_action, self.previous_keyframe)
        make_action_button(button_frame, next_keyframe_action, self.next_keyframe)
        make_action_button(button_frame, add_blank_keyframe_action, self.add_blank_keyframe)
        make_action_button(button_frame, clone_keyframe_action, self.clone_keyframe)
        make_action_button(button_frame, delete_keyframe_action, self.delete_keyframe)
        make_action_button(button_frame, cut_keyframe_action, self.cut_keyframe)
        make_action_button(button_frame, copy_keyframe_action, self.copy_keyframe)
        make_action_button(button_frame, paste_keyframe_action, self.paste_keyframe)

        make_separator(button_frame)

        # Auto-keyframe radio
        self.auto_keyframe_off = 'off'
        self.auto_keyframe_blank = 'blank'
        self.auto_keyframe_clone = 'clone'
        self.auto_keyframe_var = ttk.StringVar(value=self.auto_keyframe_off)
        make_action_radio(button_frame, toggle_auto_keyframe_off_action, self.auto_keyframe_off, self.auto_keyframe_var)
        make_action_radio(button_frame, toggle_auto_keyframe_blank_action, self.auto_keyframe_blank, self.auto_keyframe_var)
        make_action_radio(button_frame, toggle_auto_keyframe_clone_action, self.auto_keyframe_clone, self.auto_keyframe_var)

        make_separator(button_frame)

        # Drawing mode radio
        self.drawing_mode_draw = 'draw'
        self.drawing_mode_erase = 'erase'
        self.drawing_mode_var = ttk.StringVar(value=self.drawing_mode_draw)
        make_action_radio(button_frame, toggle_draw_action, self.drawing_mode_draw, self.drawing_mode_var)
        make_action_radio(button_frame, toggle_erase_action, self.drawing_mode_erase, self.drawing_mode_var)
        self.drawing_mode_var.trace_add('write', self.on_drawing_mode_changed)

        # Brush size selector
        brush_scale_frame = ttk.Frame(button_frame)
        brush_scale = bar_scale.BarScale(
            brush_scale_frame, label='Brush size', value=self.brush_size_var.get(), minval=1, maxval=1000,
            scale_type=bar_scale.BarScale.CURVE, height=30, width=150)
        brush_scale.pack(padx=5)
        brush_scale.value_updated_event += self.video_canvas.set_brush_size
        brush_scale.value_updated_event += lambda v: self.brush_size_var.set(int(v))
        brush_scale.update_stopped_event += self.video_canvas.hide_cursor
        incr_brush_size_fast_action.trigger += brush_scale.incr_value_fast
        decr_brush_size_fast_action.trigger += brush_scale.decr_value_fast
        incr_brush_size_slow_action.trigger += brush_scale.incr_value_slow
        decr_brush_size_slow_action.trigger += brush_scale.decr_value_slow

        # Mask tint selector
        self.color_picker = color_picker.ColorPickerHover(button_frame, self.mask_color_var.get(), self.mask_alpha_var.get(), height=30, width=40)
        self.color_picker.color_selected_event += self.video_canvas.set_mask_color
        self.color_picker.alpha_selected_event += self.video_canvas.set_mask_alpha
        self.color_picker.color_selected_event += lambda v: self.mask_color_var.set(tuple(v))
        self.color_picker.alpha_selected_event += self.mask_alpha_var.set

        # Information labels
        label_frame = ttk.Frame(self.base_frame)
        label_frame.pack()

        self.time_label = ttk.Label(label_frame)
        self.time_label.pack(side=ttkc.LEFT)
        self.video_file_name_label = ttk.Label(label_frame)
        self.video_file_name_label.pack(side=ttkc.LEFT)
        self.saved_label = ttk.Label(label_frame, width=2)
        self.saved_label.pack(side=ttkc.LEFT)

        # Timeline
        self.timeline = timeline.Timeline(self.base_frame, height=50)
        self.timeline.pack(fill=ttkc.X)
        self.timeline.position_updated_event += self.video_canvas.set_frame_pos
        self.video_canvas.frame_changing_event += self.on_frame_changing
        self.video_canvas.drawing_started_event += self.on_drawing_started
        self.video_canvas.drawing_finished_event += self.on_drawing_finished

        self.stopped_event = threading.Event()
        self.last_auto_saved_id = None
        self.auto_backup_task = asyncio.create_task(asyncio.to_thread(self.auto_backup))

        self.export_window = None
        self.shortcut_window = None

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

    def on_drawing_mode_changed(self, *_):
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
    def open_video(self, *_):
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
    def close_requested(self, *_):
        self.win_geometry_var.set(self.winfo_geometry())
        util.settings.save()
        self.stopped_event.set()
        for task in [self.auto_backup_task]:
            if task is not None and not task.done():
                task.cancel()
                try:
                    ex = task.exception()
                    print(ex)
                except:
                    pass
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

    def open_project(self, *_):
        self.open_project_from_dir(self.last_open_dir_var.get())

    def open_project_from_backup_dir(self, *_):
        self.open_project_from_dir(tempfile.gettempdir())

    def save_project(self, *_):
        if self.project:
            if self.project.project_file_path:
                project.save_project(self.project, self.project.project_file_path)
                self.project = self.project.set_saved()
                self.update_saved_label()
                return True
            else:
                return self.save_as_project()
        return False

    def save_as_project(self, *_):
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

    def set_project_video(self, *_):
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

    def render_video(self, *_):
        if self.export_window:
            return
        self.export_window = ttk.Toplevel('Render Video', size=(500, 300), transient=self)
        def del_window(*_):
            self.export_window = None
        self.export_window.bind('<Destroy>', del_window)
        frame = video_export.VideoExport(self.export_window, self)
        frame.pack(fill=ttkc.BOTH)

    def shortcut_keys(self, *_):
        if self.shortcut_window:
            return
        self.shortcut_window = ttk.Toplevel('Shortcut Key Assignment', size=(500, 800), transient=self)
        def del_window(*_):
            self.shortcut_window = None
        self.shortcut_window.bind('<Destroy>', del_window)
        frame = action.KeybindSettings(self.shortcut_window, action.Action.action_registry.values())
        frame.pack(fill=ttkc.BOTH, expand=True)

    def update_to_selected(self):
        if self.project:
            state = self.project.get_current()
            if state.selected_index is not None:
                self.video_canvas.set_frame_pos(state.selected_index)

    def undo(self, *_):
        if self.project:
            self.project = self.project.undo()
            self.update_to_selected()
            self.update_view()

    def redo(self, *_):
        if self.project:
            self.project = self.project.redo()
            self.update_to_selected()
            self.update_view()

    def previous_keyframe(self, *_):
        if self.project:
            index = self.video_canvas.get_frame_pos()
            state = self.project.get_current()
            keyframe = state.get_previous_keyframe(index)
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def next_keyframe(self, *_):
        if self.project:
            index = self.video_canvas.get_frame_pos()
            state = self.project.get_current()
            keyframe = state.get_next_keyframe(index)
            if not keyframe:
                return
            self.video_canvas.set_frame_pos(keyframe.index)

    def add_blank_keyframe(self, *_):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe and keyframe.index == index:
                return
            data = self.video_canvas.get_blank_image_array()
            keyframe = project.Keyframe(index=index, data=data)
            state = state.insert_keyframe(keyframe).set(selected_index=index)
            self.project = self.project.append(state, self.undo_limit)
            self.update_view()

    def clone_keyframe(self, *_):
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

    def delete_keyframe(self, *_):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe:
                state = state.remove_keyframe(index).set(selected_index=None)
                self.project = self.project.append(state, self.undo_limit)
            self.update_view()

    def cut_keyframe(self, *_):
        self.copy_keyframe()
        self.delete_keyframe()

    def copy_keyframe(self, *_):
        if self.project:
            index, state, keyframe = self.get_current()
            if keyframe:
                self.project = self.project.set(copy_buffer=keyframe)

    def paste_keyframe(self, *_):
        if self.project and self.project.copy_buffer:
            index, state, keyframe = self.get_current()
            buffer = self.project.copy_buffer
            if keyframe and keyframe.index == index:
                state = state.update_keyframe(index, buffer.data)
            else:
                state = state.insert_keyframe(buffer.set(index=index))
            self.project = self.project.append(state, self.undo_limit)
            self.update_view()

    def paste_keyframe_into(self, *_):
        if self.project and self.project.copy_buffer:
            index, state, keyframe = self.get_current()
            buffer = self.project.copy_buffer

    def play_pause_video(self, *_):
        if self.video_canvas.is_playing():
            self.video_canvas.pause()
        else:
            self.video_canvas.play()

    def previous_frame(self, *_):
        self.video_canvas.previous_frame()

    def next_frame(self, *_):
        self.video_canvas.next_frame()

    def toggle_repeat(self, *_):
        self.video_canvas.set_repeat(self.repeat_var.get())

    def reset_view(self, *_):
        self.video_canvas.reset_view()

async def async_main():
    await App().async_main_loop()

def main():
    asyncio.run(async_main())