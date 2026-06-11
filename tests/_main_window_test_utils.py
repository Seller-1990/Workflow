# -*- coding: utf-8 -*-
"""MainWindow 测试共享桩对象。"""


class DummyStepEditor:
    def __init__(self, step_id=0, *, dirty=False, save_result=True):
        self._step_id = step_id
        self._dirty = dirty
        self.save_result = save_result
        self.cleared = False
        self.loaded_step_id = None
        self.reset_calls = 0
        self.discard_calls = 0
        self.save_calls = 0

    def clear(self):
        self.cleared = True

    def load_step(self, step_id):
        self.loaded_step_id = step_id

    def is_dirty(self):
        return self._dirty

    def save_step(self):
        self.save_calls += 1
        if self.save_result:
            self._dirty = False
        return self.save_result

    def reset_dirty_state(self):
        self.reset_calls += 1
        self._dirty = False

    def discard_changes(self):
        self.discard_calls += 1
        self._dirty = False
