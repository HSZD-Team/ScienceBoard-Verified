import sys
import os
import json
import subprocess

from typing import Dict, Any, Self

import requests
from PIL import Image

sys.dont_write_bytecode = True
from ..base import Manager
from ..vm import VManager


class ManagerMixin:
    STARTUP_WAIT_TIME = 5

    def __init__(self, ip: str, port: int) -> None:
        # legality is not checked due to inner usage
        self.base_url = f"http://{ip}:{port}"
        self._get = lambda path: requests.get(
            self.base_url + path,
            timeout=Manager.HOMO_TIMEOUT
        )
        self._post = lambda path, **kwargs: requests.post(
            self.base_url + path,
            timeout=Manager.HOMO_TIMEOUT,
            **kwargs
        )

    def status_version(self) -> str:
        return self._get("/version").text

    def status_dump(self, query) -> Dict[str, Any]:
        return self._post("/dump", data=json.dumps(query)).json()


class RawManager(Manager, ManagerMixin):
    def __init__(
        self,
        bin_path: str,
        lib_path: str,
        version: str = "0.1",
        port: int = 8000
    ) -> None:
        super().__init__(version)

        assert port in range(1024, 65536)
        self.port = port

        # MRO: RawManager -> Manager -> ManagerMixin -> object
        super(Manager, self).__init__("localhost", port)

        assert os.path.isfile(bin_path)
        self.bin_path = bin_path

        assert os.path.isdir(lib_path)
        self.lib_path = lib_path

    def __call__(self, _) -> None:
        raise NotImplementedError

    def __enter__(self) -> Self:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = self.lib_path
        self.process = subprocess.Popen(
            [self.bin_path, str(self.port)],
            env=env,
            text=True
        )

        Manager.pause(self.STARTUP_WAIT_TIME)
        assert self.status_version() == self.version
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.process.kill()
        super().__exit__(exc_type, exc_value, traceback)

    def screenshot(self) -> Image.Image:
        raise NotImplementedError


class VMManager(VManager, ManagerMixin):
    def __init__(
        self,
        *args,
        port: int = 8000,
        **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)

        assert port in range(1024, 65536)
        self.port = port

    def _post__enter__(self) -> None:
        # MRO: VMManager -> VManager -> Manager -> ManagerMixin -> object
        super(Manager, self).__init__(self.controller.vm_ip, self.port)

    def __enter__(self) -> Self:
        self = super().__enter__()
        self._post__enter__()
        return self
