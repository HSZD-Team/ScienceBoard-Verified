import sys
import os
import subprocess

from typing import List, Dict, Union, Self

import requests
from PIL import Image

sys.dont_write_bytecode = True
from ..base import Manager
from ..vm import VManager


class ManagerMixin:
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

    def status_vars(self) -> Dict[str, str]:
        return self._get("/vars").json()

    def status_func(
        self,
        points: List[List[float]],
        dim: int = None
    ) -> List[Dict["str", Union[bool, str]]]:
        if dim is None:
            dim = len(points[0])

        result = self._post(f"/func/{dim}d", json=points).json()
        if isinstance(result, dict):
            result = [result]
        return result

    def operate_tab(self, index: int) -> bool:
        assert isinstance(index, int)
        assert index >= 0 and index < 4
        return self._post("/tab", json=index).text == "OK"

    def operate_func2d(self, expr: str) -> bool:
        return self._post("/add/2d", data=expr).text == "OK"

    def operate_func3d(self, expr: str) -> bool:
        return self._post("/add/3d", data=expr).text == "OK"

class RawManager(Manager, ManagerMixin):
    def __init__(
        self,
        bin_path: str,
        lib_path: str,
        version: str = "0.3",
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
            stdout=subprocess.PIPE,
            text=True
        )

        Manager.pause()
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
