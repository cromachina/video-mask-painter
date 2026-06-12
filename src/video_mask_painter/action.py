import tkinter as tk

import ttkbootstrap as ttk
import ttkbootstrap.constants as ttkc
from ttkbootstrap import scrolled
from pyrsistent import *

from . import util

def is_control(keysym:str):
    return keysym.startswith('Control')

def is_alt(keysym:str):
    return keysym.startswith('Alt')

def is_shift(keysym:str):
    return keysym.startswith('Shift')

def is_modifier(keysym:str):
    return is_control(keysym) or is_alt(keysym) or is_shift(keysym)

def get_modifier_or_key(keysym:str):
    if is_control(keysym):
        return 'control'
    if is_alt(keysym):
        return 'alt'
    if is_shift(keysym):
        return 'shift'
    return keysym.casefold()

_mods = ('shift', 'lock', 'control', 'alt', 'mod2', 'mod3', 'mod4', 'mod5', 'mouse1', 'mouse2', 'mouse3', 'mouse4', 'mouse5')

def modifier_names(state:int):
    s = []
    for i, n in enumerate(_mods):
        if state & (1 << i):
            s.append(n)
    return s

class Action():
    action_registry = {}

    def __init__(self, name:str, default_shortcuts:list[set[str]]=None, icon:str=None):
        self.action_registry[name] = self
        self.name = name
        self.icon = icon
        self._shortcuts_box = util.settings.get(f'shortcut/{name}', default_shortcuts or [])
        self.shortcuts = self._shortcuts_box.get()
        self._shortcuts_box.set(self.shortcuts)
        self.trigger = util.Observable()
        self.trigger_release = util.Observable()

class ActionRunner():
    def __init__(self, widget:tk.Widget, actions:list[Action]=None):
        self._widget = widget
        if actions is None:
            actions = []
        self._actions = actions
        self._shortcut = pset()
        self._released_keys = pset()
        self._widget.bind('<Key>', self._on_key)
        self._widget.bind('<Button>', self._on_button)
        self._widget.bind('<KeyRelease>', self._on_key_release_debounce)
        self._widget.bind('<ButtonRelease>', self._on_button_release)
        self._widget.bind('<MouseWheel>', self._on_mousewheel)
        self._key_release_idle = None

    def add_action(self, action:Action):
        self._actions.append(action)
        return action

    def _trigger_shortcut(self, next_shortcut, event:tk.Event):
        shortcut_changed = next_shortcut != self._shortcut
        for action in self._actions:
            for shortcut in action.shortcuts:
                if not shortcut:
                    continue
                if shortcut_changed and shortcut == self._shortcut:
                    action.trigger_release(event)
                if shortcut == next_shortcut:
                    action.trigger(event)
        self._shortcut = next_shortcut

    def _on_key(self, event:tk.Event):
        shortcut = self._shortcut
        shortcut = shortcut.update(modifier_names(event.state))
        shortcut = shortcut.add(get_modifier_or_key(event.keysym))
        self._trigger_shortcut(shortcut, event)

    def _on_button(self, event:tk.Event):
        shortcut = self._shortcut
        shortcut = shortcut.update(modifier_names(event.state))
        shortcut = shortcut.add(f'mouse{event.num}')
        self._trigger_shortcut(shortcut, event)

    def _on_key_release_debounce(self, event:tk.Event):
        self._released_keys = self._released_keys.update(modifier_names(event.state))
        self._released_keys = self._released_keys.add(get_modifier_or_key(event.keysym))
        if self._key_release_idle:
            self._widget.after_cancel(self._key_release_idle)
        self._key_release_idle = self._widget.after(100, self._on_key_release, event)

    def _on_key_release(self, event:tk.Event):
        self._key_release_idle = None
        shortcut = self._shortcut.difference(self._released_keys)
        self._released_keys = pset()
        self._trigger_shortcut(shortcut, event)

    def _on_button_release(self, event:tk.Event):
        shortcut = self._shortcut
        shortcut = shortcut.difference(modifier_names(event.state))
        shortcut = shortcut.discard(f'mouse{event.num}')
        self._trigger_shortcut(shortcut, event)

    def _on_mousewheel(self, event:tk.Event):
        event.num = 5 if event.delta > 0 else 4
        self._on_button(event)

class ShortcutKeyEntry(ttk.Entry):
    def __init__(self, master, initial_value:set, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self.var = ttk.StringVar(self)
        self.config(state=ttkc.READONLY, textvariable=self.var)
        self.bind('<Key>', self._on_key)
        self.bind('<Button>', self._on_button)
        self.bind('<KeyRelease>', self._on_key_release)
        self.bind('<ButtonRelease>', self._on_button_release)
        self.bind('<MouseWheel>', self._on_mousewheel)
        self._key_grabbing_mode = False
        self._last_key_event:tk.Event = None
        self._last_mouse_event:tk.Event = None
        self._value = initial_value
        self.edit_started_event = util.Observable()
        self.edit_finished_event = util.Observable()
        self._update_view()

    def _on_key(self, event):
        if self._key_grabbing_mode:
            self._last_key_event = event
            self._update_value()

    def _on_button(self, event):
        if self._key_grabbing_mode:
            self._last_mouse_event = event
            self._update_value()
        elif event.num == 1:
            self.config(bootstyle=ttkc.DANGER)
            self._key_grabbing_mode = True
            self._last_key_event = None
            self._last_mouse_event = None
            self.grab_set()
            self.edit_started_event()

    def _update_value(self):
        self._value.clear()
        if self._last_key_event:
            self._value.update(modifier_names(self._last_key_event.state))
            self._value.add(get_modifier_or_key(self._last_key_event.keysym))
        if self._last_mouse_event:
            self._value.update(modifier_names(self._last_mouse_event.state))
            self._value.add(f'mouse{self._last_mouse_event.num}')
        self._update_view()

    def _update_view(self):
        self.var.set(' '.join(self._value))

    def _finish_selection(self):
        self.config(bootstyle=ttkc.NORMAL)
        self.grab_release()
        self.edit_finished_event()

    def _has_event(self):
        return self._key_grabbing_mode and (self._last_key_event or self._last_mouse_event)

    def _on_key_release(self, event):
        if self._has_event():
            self._key_grabbing_mode = False
            self._finish_selection()

    def _on_button_release(self, event):
        if self._has_event():
            self._key_grabbing_mode = False
            self._finish_selection()

    def _on_mousewheel(self, event:tk.Event):
        event.num = 5 if event.delta > 0 else 4
        self._on_button(event)

class ActionEdit(ttk.Frame):
    def __init__(self, master, action:Action, *args, **kwargs):
        super().__init__(master=master, *args, **kwargs)
        self._action = action
        row = ttk.Frame(self)
        row.pack(fill=ttkc.X)
        button = util.make_button(row, 'Add shortcut', 'add', self._on_add_shortcut, 16)
        button.pack(side=ttkc.LEFT)
        label = ttk.Label(row, text=action.name)
        label.pack(side=ttkc.LEFT)
        self.shortcut_rows = []
        self.edit_started_event = util.Observable()
        self.edit_finished_event = util.Observable()
        for shortcut in action.shortcuts:
            self._on_add_shortcut(shortcut)

    def _on_add_shortcut(self, shortcut=None):
        if shortcut is None:
            shortcut = set()
            self._action.shortcuts.append(shortcut)
        row = ttk.Frame(self)
        row.pack()
        entry = ShortcutKeyEntry(row, shortcut)
        entry.pack(side=ttkc.RIGHT)
        entry.edit_started_event += self.edit_started_event
        entry.edit_finished_event += self.edit_finished_event
        def delete_shortcut():
            self._action.shortcuts.remove(shortcut)
            row.destroy()
        button = util.make_button(row, 'Delete shortcut', 'delete', delete_shortcut, 16)
        button.pack(side=ttkc.RIGHT)

# BUG Fixes an issue with ScrolledFrame https://github.com/israel-dryer/ttkbootstrap/pull/1064
class PatchedScrolledFrame(scrolled.ScrolledFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scroll_enabled = True

    def _add_scroll_binding(self, parent):
        if not self._scroll_enabled:
            return
        return super()._add_scroll_binding(parent)

    def enable_scrolling(self):
        self._scroll_enabled = True
        return super().enable_scrolling()

    def disable_scrolling(self):
        self._scroll_enabled = False
        return super().disable_scrolling()

    def _on_enter(self, event) -> None:
        self._add_scroll_binding(self)
        if self.autohide:
            self.show_scrollbars()

    def _on_leave(self, event) -> None:
        self._del_scroll_binding(self)
        if self.autohide:
            self.hide_scrollbars()

class KeybindSettings(ttk.Frame):
    def __init__(self, master, actions:list[Action], *args, **kwargs):
        super().__init__(master=master, padding=3, *args, **kwargs)
        scroll_area = PatchedScrolledFrame(self)
        scroll_area.pack(fill=ttkc.BOTH, expand=True)
        for action in actions:
            edit = ActionEdit(scroll_area, action)
            edit.edit_started_event += scroll_area.disable_scrolling
            edit.edit_finished_event += scroll_area.enable_scrolling
            edit.pack(fill=ttkc.X)
            sep = ttk.Separator(scroll_area, orient=ttkc.HORIZONTAL)
            sep.pack(fill=ttkc.X, pady=1)