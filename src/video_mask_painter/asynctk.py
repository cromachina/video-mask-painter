import asyncio
import tkinter as tk

from . import util

class AsyncTk(tk.Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protocol('WM_DELETE_WINDOW', self.close_requested)
        self.running = False
        self.sleep_time = 1.0 / 60.0
        self.update_hook = util.Observable()

    def close_requested(self):
        self.stop()

    def stop(self):
        self.running = False

    async def async_main_loop(self):
        self.running = True
        while self.running:
            self.update()
            self.update_idletasks()
            self.update_hook.call_catch()
            await asyncio.sleep(0)
        self.destroy()

class AsyncTkCallback:
    tasks = set()

    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        task = asyncio.create_task(self.func(*args, **kwargs))
        AsyncTkCallback.tasks.add(task)
        task.add_done_callback(AsyncTkCallback.tasks.discard)