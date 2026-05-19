from pathlib import Path
import bisect
import zipfile
import json
import tempfile

from pyrsistent import *
import numpy as np
import cv2

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

def save_project(project:Project, file_path:Path):
    with (tempfile.NamedTemporaryFile(dir=file_path.parent, prefix=file_path.name, delete=False, delete_on_close=False) as temp,
        zipfile.ZipFile(temp.name, mode='w', compression=zipfile.ZIP_STORED, compresslevel=5) as zfile):
        try:
            metadata = {
                'video_file_path': str(project.video_file_path),
            }
            zfile.writestr('metadata.json', json.dumps(metadata).encode())
            state = project.get_current()
            for keyframe in state.keyframes:
                res, data = cv2.imencode('.png', keyframe.data)
                zfile.writestr(f'frames/{keyframe.index}', data.tobytes())
            zfile.close()
            Path(temp.name).rename(file_path)
        except Exception as ex:
            zfile.close()
            temp.close()
            Path(temp.name).unlink(True)
            raise ex

def load_project(file_path:Path) -> Project:
    with zipfile.ZipFile(file_path, mode='r') as zfile:
        metadata = json.loads(zfile.read('metadata.json').decode())
        state = ProjectState()
        for sub_file in zfile.namelist():
            sub_file_path = Path(sub_file)
            if str(sub_file_path.parent) != 'frames':
                continue
            index = int(sub_file_path.name)
            data = zfile.read(sub_file)
            data = cv2.imdecode(np.frombuffer(data, dtype=np.ubyte), cv2.IMREAD_GRAYSCALE)
            data = data.reshape(data.shape + (1,))
            data.flags.writeable = False
            state = state.insert_keyframe(Keyframe(index=index, data=data))
        return Project(
            initial_state=state,
            video_file_path=Path(metadata['video_file_path']),
            project_file_path=Path(file_path))

project_file_types = (('VMP', '*.vmp'), ('Any', '*.*'))