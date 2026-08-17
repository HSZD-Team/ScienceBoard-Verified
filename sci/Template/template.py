import sys

from typing import Self
from PIL import Image

sys.dont_write_bytecode = True
from ..base import Manager
from ..vm import VManager


class ManagerMixin:
    def __init__(self) -> None:
        raise


class RawManager(Manager, ManagerMixin):
    def __init__(self, version: str) -> None:
        super().__init__(version)

    def __call__(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> Self:
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        super().__exit__(exc_type, exc_value, traceback)

    def screenshot(self) -> Image.Image:
        raise NotImplementedError


class VMManager(VManager, ManagerMixin):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
