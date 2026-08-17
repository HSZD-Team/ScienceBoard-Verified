import sys
import functools

from typing import List, Dict, Union, Any, Callable

sys.dont_write_bytecode = True
from ..base import Task
from ..base.utils import error_factory
from .vmanager import VManager


class VTask(Task):
    PATH_LIKE = "«PORTLIKE»"

    def __init__(
        self,
        config_path: str,
        manager: VManager,
        *args,
        **kwargs
    ) -> None:
        # to enable Pylance type checker
        assert isinstance(manager, VManager)
        self.manager = manager

        super().__init__(config_path, manager, *args, **kwargs)
        self.__check_config()

    def __check_config(self) -> None:
        self.snapshot = self.config["snapshot"] \
            if "snapshot" in self.config \
            else VManager.INIT_NAME

    # requires VMManager to possess "port" attribute
    def __fill_port(self, command: str) -> str:
        assert isinstance(command, str)
        return command.replace(VTask.PATH_LIKE, str(self.manager.port)) \
            if hasattr(self.manager, "port") else command

    @error_factory(False)
    def _init(self) -> bool:
        result = self.manager.revert(self.snapshot)
        VManager.pause()
        assert self._execute(
            command="/bin/bash /home/user/server/reset.sh",
            shell=True
        ) is not False
        return result

    # OSWorld's request does not check success
    # rewrite requests to make up this flaw
    @staticmethod
    def _request_factory(query: str):
        def _request_decorator(method: Callable) -> Callable:
            @functools.wraps(method)
            def _request_wrapper(self: "VTask", **kwargs) -> bool:
                param: Dict["str", Any] = method(self, **kwargs)
                try:
                    response = self.manager._request(query, param)
                    succeed = response.status_code == 200
                    if not succeed:
                        self.vlog.error(f"Failed when requesting {query}: {response.status_code}")
                    return succeed
                except Exception as err:
                    self.vlog.error(f"Error when requesting {query}: {err}")
                    return False
            return _request_wrapper
        return _request_decorator

    @_request_factory("POST/setup/execute")
    def _execute(self, command: Union[str, List[str]], shell: bool = False) -> Dict:
        assert isinstance(shell, bool)
        if isinstance(command, list):
            for index, part in enumerate(command):
                command[index] = self.__fill_port(part)
        else:
            command = self.__fill_port(command)

        return {
            "json": {
                "command": command,
                "shell": shell
            }
        }

    @_request_factory("POST/setup/launch")
    def _launch(self, command: Union[str, List[str]], shell: bool = False) -> Dict:
        return self._execute.__wrapped__(self, command, shell)

    @_request_factory("POST/opt")
    def _opt(self, depth: int) -> Dict:
        return {
            "json": {
                "depth": depth
            }
        }

    @_request_factory("POST/append")
    def _append(self, path: str, content: str) -> Dict:
        return {
            "json": {
                "path": path,
                "content": content
            }
        }
