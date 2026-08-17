import sys
from typing import Union, Callable

sys.dont_write_bytecode = True
from ..base import Task
from ..vm import VTask

from ..base.utils import error_factory
from .celestia import RawManager, VMManager


class TaskMixin:
    def __init__(self) -> None:
        # this class is not independent: manager, evaluate, vlog needed
        raise

    @Task._config_handler
    def check_config(self: Union["RawTask", "VMTask"], eval_item) -> None:
        assert eval_item["type"] == "info"
        assert "key" in eval_item
        assert "value" in eval_item

        if "pred" in eval_item:
            assert hasattr(eval(eval_item["pred"]), "__call__")

        if "query" in self.config:
            self.query = self.config["query"]
            assert isinstance(self.query, list)
            for entry in self.query:
                assert isinstance(entry, dict)
                assert "name" in entry
                assert "type" in entry
                assert isinstance(entry["name"], str)
                assert isinstance(entry["type"], int)
        else:
            self.query = []

    @error_factory(False)
    def eval(self: Union["RawTask", "VMTask"]) -> bool:
        info = self.manager.status_dump(self.query)
        for eval_item in self.evaluate:
            hkey: Callable = lambda info: info[eval_item["key"]]
            pred: Callable = lambda left, right: left == right

            if hasattr(key_eval := eval(eval_item["key"]), "__call__"):
                hkey = key_eval
            if "pred" in eval_item:
                pred = eval(eval_item["pred"])
            if not pred(hkey(info), eval_item["value"]):
                self.vlog.info(f"Evaluation failed at {eval_item['type']} of {eval_item['key']}.")
                return False
        return True


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

    @Task._stop_handler
    def eval(self) -> bool:
        # MRO: RawTask -> Task -> TaskMixin -> object
        return super(Task, self).eval()


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
        # MRO: VMTask -> VTask -> Task -> TaskMixin -> object
        return super(Task, self).eval()
