from pathlib import Path
import bisect

from pyrsistent import *
import numpy as np

from .util import *

class Keyframe(PClass):
    index = field(type=int)
    data = field(type=np.ndarray)

class ProjectState(PClass):
    keyframes = pvector_field(Keyframe)
    selected_index = field(initial=None)

    def print_keyframes(self):
        print('----------')
        for keyframe in self.keyframes:
            print(keyframe.index, id(keyframe.data))

    def get_keyframe(self, index):
        if not self.keyframes:
            return None
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return None
        return self.keyframes[ix]

    def get_previous_keyframe(self, index):
        if not self.keyframes:
            return None
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return None
        keyframe = self.keyframes[ix]
        if keyframe.index == index:
            ix -= 1
        if ix < 0:
            return None
        return self.keyframes[ix]

    def get_next_keyframe(self, index):
        if not self.keyframes:
            return None
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index)
        if ix >= len(self.keyframes):
            return None
        keyframe = self.keyframes[ix]
        if keyframe.index == index:
            ix += 1
        if ix >= len(self.keyframes):
            return None
        return self.keyframes[ix]

    def insert_keyframe(self, keyframe:Keyframe):
        ix = bisect.bisect(self.keyframes, keyframe.index, key=lambda x: x.index)
        return self.set(keyframes=pvector_insert(self.keyframes, keyframe, ix))

    def remove_keyframe(self, index:int):
        if not self.keyframes:
            return self
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return self
        return self.set(keyframes=self.keyframes.delete(ix))

    def update_keyframe(self, index, data):
        data.flags.writeable = False
        keyframe = self.get_keyframe(index).set(data=data)
        return self.remove_keyframe(keyframe.index).insert_keyframe(keyframe)

class Project():
    def __init__(self, initial_state:ProjectState, video_file_path:Path, project_file_path:Path|None=None):
        self.video_file_path = video_file_path
        self.project_file_path = project_file_path
        self._states = pvector()
        self._current_index = 0
        self._next_id = 0
        self._saved_id = 0
        self.append(initial_state)

    def get_current(self) -> ProjectState:
        return self._states[self._current_index][1]

    def update_current(self, state:ProjectState):
        self._states = self._states.set(self._current_index, (self.self._get_current_id(), state))

    def _get_current_id(self):
        return self._states[self._current_index][0]

    def append(self, state:ProjectState, state_limit:int|None=None):
        state = (self._next_id, state)
        self._next_id += 1
        self._states = self._states[:self._current_index + 1]
        self._states = self._states.append(state)
        if state_limit is not None and len(self._states) > state_limit:
            delta = len(self._states) - state_limit
            self._states = self._states[delta:]
        self._current_index = len(self._states) - 1

    def undo(self):
        self._current_index = max(0, self._current_index - 1)
        return self.get_current()

    def redo(self):
        self._current_index = min(self._current_index + 1, len(self._states) - 1)
        return self.get_current()

    def can_undo(self):
        return self._current_index != 0

    def can_redo(self):
        return self._current_index != (len(self._states) - 1)

    def is_saved(self):
        return self._saved_id == self._get_current_id()

    def set_saved(self):
        self._saved_id = self._get_current_id()

    def set_dirty(self):
        self._saved_id = None