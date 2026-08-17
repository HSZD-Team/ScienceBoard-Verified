import sys
import re

from typing import Union, Dict, Any

sys.dont_write_bytecode = True
from ..base import Task
from ..vm import VTask

from ..base.utils import error_factory
from .texstudio import RawManager, VMManager


class TaskMixin:
    def __init__(self) -> None:
        # this class is not independent: manager, evaluate, vlog needed
        raise

    @Task._config_handler
    def check_config(self, eval_item) -> None:
        if eval_item["type"] == "compile":
            assert "file" in eval_item
        elif eval_item["type"] == "include":
            assert "pattern" in eval_item
        else:
            assert eval_item["type"] == "file"

        assert "path" in eval_item

    def reverse_touch(self: Union["RawTask", "VMTask"], path: str) -> str:
        return [
            item for item in self.initialize
            if item["func"] == "touch" and item["path"] == path
        ][0]["text"]

    @error_factory(False)
    def _eval_file(
        self: Union["RawTask", "VMTask"],
        eval_item: Dict[str, Any]
    ) -> bool:
        before = self.reverse_touch(eval_item["path"])
        after = self.manager.read_file(eval_item["path"])
        if "source" in eval_item and "target" in eval_item:
            before = before.replace(eval_item["source"], eval_item["target"])
        return before == after

    @error_factory(False)
    def _eval_include(
        self: Union["RawTask", "VMTask"],
        eval_item: Dict[str, Any]
    ) -> bool:
        after = self.manager.read_file(eval_item["path"])
        return re.search(eval_item["pattern"], after) is not None

    def eval(self) -> bool:
        for eval_item in self.evaluate:
            eval_type = eval_item["type"]
            eval_func = getattr(self, f"_eval_{eval_type}")
            if not eval_func(eval_item):
                self.vlog.info(f"Evaluation failed at {eval_type} of {eval_item['path']}.")
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

    @error_factory(False)
    def _eval_compile(self, eval_item: Dict[str, Any]) -> bool:
        raise NotImplementedError

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

    def _chimerax_open(self, name: str) -> bool:
        return self.manager._chimerax_execute(f"open {name}")

    def _chimerax_turn(self, axis: str, angle: int) -> bool:
        return self.manager._chimerax_execute(f"turn {axis} {angle}")

    def _chimerax_clear_log(self) -> bool:
        return self.manager._chimerax_execute(f"log clear")

    @error_factory(False)
    def _eval_compile(self, eval_item: Dict[str, Any]) -> bool:
        response = self.manager._request("POST/tex/check", {
            "json": {
                "path": eval_item["path"],
                "file": eval_item["file"],
                "bibtex": len([
                    item for item in self.initialize
                    if item["func"] == "touch" and item["path"].endswith(".bib")
                ]) > 0
            }
        })
        return response.json()["pass"]

    @Task._stop_handler
    def eval(self) -> bool:
        # MRO: VMTask -> VTask -> Task -> TaskMixin -> object
        return super(Task, self).eval()
