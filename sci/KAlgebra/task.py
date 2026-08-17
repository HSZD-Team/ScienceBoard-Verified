import sys
from typing import Dict, Union, Any

sys.dont_write_bytecode = True
from ..base import Task
from ..vm import VTask

from ..base.utils import error_factory
from .kalgebra import RawManager, VMManager


class TaskMixin:
    def __init__(self) -> None:
        # this class is not independent: manager, evaluate, vlog needed
        raise

    @Task._config_handler
    def check_config(self, eval_item) -> None:
        assert eval_item["type"] in ("val", "var", "eqn")
        single = (int, float, str)

        assert "key" in eval_item
        key = eval_item["key"]
        if not isinstance(key, str):
            assert isinstance(key, list)
            for item in key:
                assert isinstance(item, list)
                assert len(item) in (2, 3)
                for sub_item in item:
                    assert type(sub_item) in single

        assert "value" in eval_item
        value = eval_item["value"]
        if type(value) not in single:
            assert isinstance(value, dict)
            for sub_key, sub_value in value.items():
                assert isinstance(sub_key, str)
                assert type(sub_value) in (bool, str, int)

    def _tab(self: Union["RawTask", "VMTask"], index: int) -> bool:
        return self.manager.operate_tab(index)

    def _func_2d(self: Union["RawTask", "VMTask"], expr: str) -> bool:
        return self.manager.operate_func2d(expr)

    def _func_3d(self: Union["RawTask", "VMTask"], expr: str) -> bool:
        return self.manager.operate_func3d(expr)

    @staticmethod
    def is_near(left: Any, right: Any) -> bool:
        return abs(float(left) - float(right)) <= 1e-6

    @error_factory(False)
    def _eval_val(
        self: Union["RawTask", "VMTask"],
        eval_item: Dict[str, Any]
    ) -> bool:
        return TaskMixin.is_near(
            self.manager.status_vars()[eval_item["key"]],
            eval_item["value"]
        )

    @error_factory(False)
    def _eval_var(
        self: Union["RawTask", "VMTask"],
        eval_item: Dict[str, Any]
    ) -> bool:
        vars = self.manager.status_vars()
        if eval_item["value"] == "#UNDEF":
            return eval_item["key"] not in vars
        else:
            return vars[eval_item["key"]] == eval_item["value"]

    @error_factory(False)
    def _eval_eqn(
        self: Union["RawTask", "VMTask"],
        eval_item: Dict[str, Any]
    ) -> bool:
        if eval_item["key"] == "#SIZE":
            size = len(self.manager.status_func([], dim=2))
            return size == eval_item["value"]

        eqns = self.manager.status_func(eval_item["key"])
        return any([all([
            value == eqn[key]
            for key, value in eval_item["value"].items()
        ]) for eqn in eqns])

    def eval(self: Union["RawTask", "VMTask"]) -> bool:
        for eval_item in self.evaluate:
            eval_type = eval_item["type"]
            eval_func = getattr(self, f"_eval_{eval_type}")
            if not eval_func(eval_item):
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
