import sys
import os
import re
import time
import tempfile

from typing import Union, Tuple, Optional
from typing import Callable, Self, NoReturn, TypeVar
from PIL import Image

sys.dont_write_bytecode = True
from .log import VirtualLog
from .utils import error_factory

T = TypeVar("T")

# abstract base class of all apps
# - subclass should include
#   - __init__(): super().__init__() is required
#     - entered: whether app is opened
#     - vlog: virtual global log
#   - __call__(): execute code
#     - no feedback expected if obs_types is None
#     - return value is expected for CLI tasks
#   - __enter__() / __exit__(): open / close app
#   - textual() / screenshot(): one of them for RawManager
#     - for CLI app: textual() only
#     - for GUI Raw: screenshot() only
# - subclass can also include
#   - a11y_tree(): get a11y tree of app
#   - set_of_marks(): get som of app
#   - record_start() / record_stop(): record video for log
class Manager:
    ACTION_INTERVAL = 1
    HOMO_TIMEOUT = 240
    HETERO_TIMEOUT = 120

    @staticmethod
    def pause(span: Optional[int] = None) -> None:
        time.sleep(Manager.ACTION_INTERVAL if span is None else span)

    def __init__(self, version: str) -> None:
        self.entered = False
        self.vlog = VirtualLog()

        self.__temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir = self.__temp_dir.name
        if sys.platform == "win32":
            self.temp_dir = self.temp_dir.replace("\\", "/")

        assert re.match(r'^\d+\.\d+$', version) is not None
        self.version = version

    def __del__(self) -> None:
        self.__temp_dir.cleanup()

    def temp(self, name: str) -> str:
        assert isinstance(name, str)
        return os.path.join(self.temp_dir, name)

    def __call__(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> Self:
        self.entered = True
        return self

    def _post__enter__(self) -> None:
        ...

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.entered = False

    # return whether subclass's screenshot() is implemented
    # basically used by raw manager
    @property
    def is_gui(self) -> None:
        return self.__class__.screenshot != Manager.screenshot

    @staticmethod
    def _assert_handler(
        method: Callable[[Self], T]
    ) -> Callable[[Self], Union[T, NoReturn]]:
        def _assert_wrapper(self: Self) -> Union[T, NoReturn]:
            result = method(self)
            assert result is not None
            return result
        return _assert_wrapper

    def textual(self) -> Union[str, NoReturn]:
        """textual information extracted from terminal"""
        raise NotImplementedError

    def screenshot(self) -> Union[Image.Image, NoReturn]:
        """a screenshot"""
        raise NotImplementedError

    def a11y_tree(self) -> Union[str, NoReturn]:
        """an accessibility tree, which is based on AT-SPI library"""
        raise NotImplementedError

    def set_of_marks(self) -> Union[Tuple[Image.Image, str], NoReturn]:
        """a screenshot with interact-able elements marked with numerical tags"""
        raise NotImplementedError

    def record_start(self) -> None:
        if self.is_gui:
            self.vlog.warning("record_start() is not implemented.")

    def record_stop(self, dest_path: str) -> None:
        if self.is_gui:
            self.vlog.warning(f"record_stop({dest_path}) is not implemented.")

    @error_factory(None)
    def read_file(self, file_path: str) -> Optional[str]:
        return open(file_path, mode="r", encoding="utf-8").read()

    @error_factory(False)
    def write_file(self, file_path: str, data: str) -> bool:
        with open(file_path, mode="w", encoding="utf-8") as writable:
            writable.write(data)
        return True

    @error_factory(False)
    def append_file(self, file_path: str, data: str) -> bool:
        with open(file_path, mode="a", encoding="utf-8") as appendable:
            appendable.write(data)
        return True

class OBS:
    textual = Manager.textual.__name__
    screenshot = Manager.screenshot.__name__
    a11y_tree = Manager.a11y_tree.__name__
    set_of_marks = Manager.set_of_marks.__name__
    schedule = "schedule"
    cloze = "cloze"
