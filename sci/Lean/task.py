import sys
import time
from typing import List

sys.dont_write_bytecode = True
from .. import Prompts
from ..base import Task
from ..vm import VTask
from .lean import RawManager, VMManager
from .format import *


class TaskMixin:
    def __init__(self) -> None:
        raise

    # DO NOT use `@Task._config_handler` here
    def check_config(self: Task) -> None:
        assert len(self.evaluate) > 0

        queries = [
            item for item in self.initialize
            if item["func"] == "query"
        ]
        assert len(queries) == 1
        assert queries[0]["expr"].endswith("by sorry")
        self.query = queries[0]["expr"][:-6]


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
        self.env = None

        super().__init__(config_path, manager, *args, **kwargs)
        self.check_config()

        self.imported: List[str] = []
        self.opened: List[str] = []
        self.defs: List[str] = []
        self.initial: Optional[REPLOutputTactic] = None

    @property
    def header(self) -> Optional[str]:
        if len(self.imported) == 0 \
            and len(self.opened) == 0 \
            and len(self.defs) == 0:
            return "No imported files, opened namespaces or extra definitions."

        results = ["Headers or definitions of the file: "]
        if len(self.imported) > 0:
            results.append(f"import {' '.join(self.imported)}")
        if len(self.opened) > 0:
            results.append(f"open {' '.join(self.opened)}")
        if len(self.defs) > 0:
            results += self.defs
        return "\n".join(results)

    @property
    def origin(self) -> Optional[str]:
        if self.initial is None:
            return None

        return "Initial state of the problem: \n" + self.initial.dumps()

    def _import(self, libs: List[str]) -> bool:
        output = self.manager._call({
            "cmd": f"import {' '.join(libs)}",
            "env": self.env
        })
        assert isinstance(output, REPLOutputCommand)

        self.env = output.env
        self.imported.extend(libs)
        return True

    def _open(self, libs: List[str]) -> bool:
        output = self.manager._call({
            "cmd": f"open {' '.join(libs)}",
            "env": self.env
        })
        assert isinstance(output, REPLOutputCommand)

        self.env = output.env
        self.opened.extend(libs)
        return True

    def _def(self, expr: str):
        output = self.manager._call({
            "cmd": expr,
            "env": self.env
        })
        assert isinstance(output, REPLOutputCommand)

        self.env = output.env
        self.defs.append(expr)
        return True

    def _query(self, expr: str) -> bool:
        output = self.manager._call({"cmd": expr, "env": self.env})
        assert isinstance(output, REPLOutputCommand)
        assert output.sorries is not None and len(output.sorries) == 1

        self.initial = REPLOutput.from_sorry(output.sorries[0])
        return True

    def __call__(self) -> bool:
        # LONG LIVE THE CLOSURE!!
        self.manager.set_headers(lambda _: filter(
            lambda item: item is not None,
            [self.header, self.origin]
        ))
        return super().__call__()

    @Task._stop_handler
    def eval(self) -> bool:
        return any([item.is_success() for item in self.manager.history])

class VMTask(VTask, TaskMixin):
    BASE_PATH = "/home/user/sci/Sci/Basic.lean"
    KEYRING_WAIT_SECONDS = 30
    KEYRING_POLL_SECONDS = 1
    KEYRING_CANCEL_RATIO = (0.419, 0.633)

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

        self.buffer: List[str] = []

    def _launch(self, command, shell: bool = False) -> bool:
        if not super()._launch(command=command, shell=shell):
            return False

        # This VM snapshot may show a locked GNOME keyring shortly after VS
        # Code opens.  Its Cancel button is light while the editor behind it
        # is dark at the same relative screen position, so do not type until
        # the modal has actually appeared.
        deadline = time.monotonic() + self.KEYRING_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                screenshot = self.manager.screenshot().convert("RGB")
                width, height = screenshot.size
                x = round(width * self.KEYRING_CANCEL_RATIO[0])
                y = round(height * self.KEYRING_CANCEL_RATIO[1])
                pixel = screenshot.getpixel((x, y))
            except Exception:
                time.sleep(self.KEYRING_POLL_SECONDS)
                continue

            if min(pixel) >= 180:
                self.vlog.info("Unlocking the GNOME keyring for Lean setup.")
                self.manager(
                    f"pyautogui.write({Prompts.VM_PASSWORD!r}, interval=0.04); "
                    "pyautogui.press('enter')"
                )
                break
            time.sleep(self.KEYRING_POLL_SECONDS)
        return True

    def __probe(self):
        if len(self.buffer) == 0 or self.buffer[-1] != "":
            self.buffer.append("")

    # ignore `import Mathlib` because vm has loaded it
    def _import(self, libs: List[str]) -> bool:
        libs = [lib for lib in libs if lib != "Mathlib"]
        if len(libs) > 0:
            self.__probe()
            self.buffer.append(f"import {' '.join(libs)}")
        return True

    def _open(self, libs: List[str]) -> bool:
        self.__probe()
        self.buffer.append(f"open {' '.join(libs)}")
        self.__probe()
        return True

    def _def(self, expr: str):
        self.buffer.append(expr)
        return True

    def _query(self, expr: str) -> bool:
        self.__probe()
        self.buffer.append(self.query + "\n  sorry\n")
        return self._append(
            path=self.BASE_PATH,
            content="\n".join(self.buffer)
        )

    @Task._stop_handler
    def eval(self) -> bool:
        response = self.manager._request("POST/lean/check", {
            "json": {
                "header": self.query
            }
        })
        return response.json()["pass"]
