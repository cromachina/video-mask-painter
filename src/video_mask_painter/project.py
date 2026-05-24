from pathlib import Path
import bisect
import zipfile
import json
import tempfile

from pyrsistent import *
import numpy as np
import cv2

from . import util

NoneType = type(None)

def _lock_array(array:np.ndarray) -> np.ndarray:
    array.flags.writeable = False
    return array

def _try_path(obj: Path | str | None):
    try:
        return Path(obj)
    except:
        return obj

class Keyframe(PClass):
    index = field(type=int, initial=0)
    data = field(type=np.ndarray, factory=_lock_array)

class ProjectState(PClass):
    keyframes = pvector_field(Keyframe)
    selected_index = field([int, NoneType], initial=None)
    id = field(int, initial=0)

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
        return self.set(keyframes=util.pvector_insert(self.keyframes, keyframe, ix))

    def remove_keyframe(self, index:int):
        if not self.keyframes:
            return self
        ix = bisect.bisect(self.keyframes, index, key=lambda x: x.index) - 1
        if ix < 0:
            return self
        return self.set(keyframes=self.keyframes.delete(ix))

    def update_keyframe(self, index, data):
        keyframe = self.get_keyframe(index).set(data=data)
        return self.remove_keyframe(keyframe.index).insert_keyframe(keyframe)

class Project(PClass):
    video_file_path = field([Path, NoneType], factory=_try_path, initial=None)
    project_file_path = field([Path, NoneType], factory=_try_path, initial=None)
    states = pvector_field(ProjectState, initial=[ProjectState()])
    current_index = field(int, initial=0)
    next_id = field(int, initial=0)
    saved_id = field([int, NoneType], initial=None)

    def get_current(self) -> ProjectState:
        return self.states[self.current_index]

    def update_current(self, state:ProjectState):
        state = state.set(id=self._get_current_id())
        return self.set(states=self.states.set(self.current_index, state))

    def _get_current_id(self):
        return self.states[self.current_index].id

    def append(self, state:ProjectState, state_limit:int|None=None):
        state = state.set(id=self.next_id)
        next_id = self.next_id + 1
        states = self.states[:self.current_index + 1].append(state)
        if state_limit is not None and len(states) > state_limit:
            delta = len(states) - state_limit
            states = states[delta:]
        current_index = len(states) - 1
        return self.set(next_id=next_id, states=states, current_index=current_index)

    def undo(self):
        return self.set(current_index=max(0, self.current_index - 1))

    def redo(self):
        return self.set(current_index=min(self.current_index + 1, len(self.states) - 1))

    def can_undo(self):
        return self.current_index != 0

    def can_redo(self):
        return self.current_index != (len(self.states) - 1)

    def is_saved(self):
        return self.saved_id == self._get_current_id()

    def set_saved(self):
        return self.set(saved_id=self._get_current_id())

    def set_dirty(self):
        return self.set(saved_id=None)

project_extension = '.vmp'
project_file_types = (('VMP', f'*{project_extension};*{project_extension}~'), ('Any', '*.*'))

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
            state = state.insert_keyframe(Keyframe(index=index, data=data))
        return Project(
            video_file_path=metadata['video_file_path'],
            project_file_path=file_path.with_suffix(project_extension)).update_current(ProjectState).set_saved()