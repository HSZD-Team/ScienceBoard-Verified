import sys
import os
import subprocess

from typing import Self
from PIL import Image

sys.dont_write_bytecode = True
from ..base import Manager
from ..vm import VManager


class RawManager(Manager):
    def __init__(self, version: str = "0.1") -> None:
        assert os.system("texstudio --version") == 0
        super().__init__(version)

    def __call__(self, _) -> None:
        raise NotImplementedError

    def __enter__(self) -> Self:
        self.process = subprocess.Popen(["texstudio"], text=True)
        Manager.pause()
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.process.kill()
        super().__exit__(exc_type, exc_value, traceback)

    def screenshot(self) -> Image.Image:
        raise NotImplementedError


class VMManager(VManager):
    def __init__(
        self,
        *args,
        port: int = 8000,
        **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)

        assert port in range(1024, 65536)
        self.port = port

    def _chimerax_execute(self, command: str):
        return self._request(
            f"POST:{VManager.SERVER_PORT}/chimerax/run",
            param={"json": {"command": command}}
        ).json()["error"] is None
