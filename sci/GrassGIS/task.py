import sys
from typing import Dict, Union, Callable

sys.dont_write_bytecode = True
from ..base import Task
from ..vm import VTask

from ..base.utils import error_factory
from .grass import RawManager, VMManager


class TaskMixin:
    def __init__(self) -> None:
        # this class is not independent: manager, evaluate, vlog needed
        raise

    @Task._config_handler
    def check_config(self, eval_item) -> None:
        if eval_item["type"] == "db":
            assert "cmd" in eval_item
            assert "kwargs" in eval_item
        else:
            assert eval_item["type"] == "info"

        assert "key" in eval_item
        assert "value" in eval_item

    def _cmd(self: Union["RawTask", "VMTask"]) -> bool:
        return self.manager.operate_cmd()

    def _map(
        self: Union["RawTask", "VMTask"],
        grassdb: str,
        location: str,
        mapset: str
    ) -> bool:
        return self.manager.operate_map(grassdb, location, mapset)

    def _layer(
        self: Union["RawTask", "VMTask"],
        query: Dict[str, str]
    ) -> bool:
        return self.manager.operate_layer(query)

    def _scale(
        self: Union["RawTask", "VMTask"],
        scale: int
    ) -> bool:
        return self.manager.operate_scale(scale)

    def _eval_info(self: Union["RawTask", "VMTask"], eval_item, info) -> bool:
        hkey: Callable = lambda info: info[eval_item["key"]]
        pred: Callable = lambda left, right: left == right

        if hasattr(key_eval := eval(eval_item["key"]), "__call__"):
            hkey = key_eval
        if "pred" in eval_item:
            pred = eval(eval_item["pred"])

        return pred(hkey(info), eval_item["value"])

    def _eval_db(self: Union["RawTask", "VMTask"], eval_item, _) -> bool:
        obj = self.manager.operate_gcmd(
            eval_item["cmd"],
            kwargs=eval_item["kwargs"]
        )

        hkey: Callable = lambda info: info[eval_item["key"]]
        pred: Callable = lambda left, right: left == right
        if hasattr(key_eval := eval(eval_item["key"]), "__call__"):
            hkey = key_eval
        if "pred" in eval_item:
            pred = eval(eval_item["pred"])
        return pred(hkey(obj["stdout"]), eval_item["value"])

    @error_factory(False)
    def eval(self: Union["RawTask", "VMTask"]) -> bool:
        info = self.manager.status_dump()
        for eval_item in self.evaluate:
            eval_type = eval_item["type"]
            eval_func = getattr(self, f"_eval_{eval_type}")
            if not eval_func(eval_item, info):
                self.vlog.info(f"Evaluation failed at {eval_type} of {eval_item['key']}.")
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
