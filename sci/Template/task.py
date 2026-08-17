import sys

sys.dont_write_bytecode = True
from ..base import Task
from ..vm import VTask
from .template import RawManager, VMManager


class TaskMixin:
    def __init__(self) -> None:
        raise

    @Task._config_handler
    def check_config(self, eval_item) -> None:
        ...


class RawTask(Task, TaskMixin):
    def __init__(
        self,
        config_path: str,
        manager: RawManager,
        *args,
        **kwargs
    ) -> None:
        # to enable Pylance type checker
        assert isinstance(manager, RawManager)
        self.manager = manager

        super().__init__(config_path, manager, *args, **kwargs)
        self.check_config()

    def _init(self) -> bool:
        ...
        return True

    @Task._stop_handler
    def eval(self) -> bool:
        raise NotImplementedError


class VMTask(VTask, TaskMixin):
    def __init__(
        self,
        config_path: str,
        manager: VMManager,
        *args,
        **kwargs
    ) -> None:
        # to enable Pylance type checker
        assert isinstance(manager, VMManager)
        self.manager = manager

        super().__init__(config_path, manager, *args, **kwargs)
        self.check_config()

    @Task._stop_handler
    def eval(self) -> bool:
        raise NotImplementedError
