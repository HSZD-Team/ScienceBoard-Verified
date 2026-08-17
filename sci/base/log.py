import logging
import os
import re
import json
import random
import string

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from typing import Callable, Self, TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from .task import Task
    from .agent import CodeLike
    from .community import Community


GLOBAL_VLOG = None
HAVE_CALLED = False

class Log:
    # IGNORE: refuse all calls outside of Log.log()
    # NATURALIZATION: print output in ways of Log
    # OVERLOOK: print output as it is
    class Tactic(Enum):
        IGNORE = 0
        NATURALIZATION = 1
        OVERLOOK = 2

    # no influence on logging if module is imported without __init__
    # but TACTIC will be set to NATURALIZATION once log is created
    TACTIC = Tactic.OVERLOOK
    UNIQUE_PREFIX = "«"
    UNIQUE_SUFFIX = "»"

    # use self.PROPERTY instead of Log.PROPERTY to
    # make it easier to change according to different obj
    ANSI_ESCAPE = r'\033(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
    LOG_PATTERN = (
        "\033[1m[%(asctime)s "
        "\033[1m%(levelname)-5s "
        "\033[1mID=%(domain)-s "
        "\033[1m%(module)s::%(funcName)s@%(filename)s:%(lineno)d"
        "\033[1m] "
        "\033[1;30m%(log)s"
        "\033[0m%(message)s"
    )

    # but DO NOT change this
    LEVELS = [
        "log",
        "debug",
        "info",
        "warn",
        "warning",
        "exception",
        "error",
        "fatal",
        "critical"
    ]

    @property
    def FILE_LOG_PATTERN(self) -> str:
        return re.sub(self.ANSI_ESCAPE, "", self.LOG_PATTERN)

    LEGACY_MARKER = "LAGACY@"
    SUM_LOG_PREFIX = "SUM@"
    DEFAULT_DOMAIN = "GLOBAL"
    TIMESTAMP_PATTERN = "%y%m%d%H%M%S"

    @property
    def __timestamp(self) -> str:
        return datetime.now().strftime(self.TIMESTAMP_PATTERN)

    IMAGE_FILENAME   = "step_{index}@{timestamp}.png"
    TEXT_FILENAME    = "step_{index}@{timestamp}.txt"

    TRAJ_FILENAME    = "traj.jsonl"
    RESULT_FILENAME  = "result.out"
    RECORD_FILENAME  = "record.mp4"
    REQUEST_FILENAME = "request_{agent}.json"
    SIMP_FILENAME    = "request_{agent}.simp.json"
    PROMPT_FILENAME  = "prompt_{agent}.txt"

    @property
    def save_path(self) -> Optional[str]:
        return os.path.split(self.file_handler.baseFilename)[0] \
            if self.file_handler is not None else None

    @property
    def save_name(self) -> str:
        assert self.file_handler is not None
        return os.path.split(self.file_handler.baseFilename)[1]

    @property
    def traj_file_path(self) -> str:
        assert self.file_handler is not None
        return os.path.join(self.save_path, self.TRAJ_FILENAME)

    @property
    def result_file_path(self) -> str:
        assert self.file_handler is not None
        return os.path.join(self.save_path, Log.RESULT_FILENAME)

    @property
    def record_file_path(self) -> str:
        assert self.file_handler is not None
        return os.path.join(self.save_path, self.RECORD_FILENAME)

    @property
    def request_file_path(self) -> str:
        assert self.file_handler is not None
        return os.path.join(self.save_path, self.REQUEST_FILENAME)

    @property
    def simp_file_path(self) -> str:
        assert self.file_handler is not None
        return os.path.join(self.save_path, self.SIMP_FILENAME)

    @property
    def prompt_file_path(self) -> str:
        assert self.file_handler is not None
        return os.path.join(self.save_path, self.PROMPT_FILENAME)

    def __init__(
        self,
        level: int = logging.INFO,
        disabled: bool = False,
        global_vlog: Optional[bool] = None
    ) -> None:
        global HAVE_CALLED
        if not HAVE_CALLED:
            Log.TACTIC = Log.Tactic.NATURALIZATION
            HAVE_CALLED = True

        assert isinstance(level, int)
        self.level = level

        # if two logs' name clashes
        # you should buy yourself some lotteries
        log_name = "".join(random.choice(
            string.ascii_uppercase + string.digits
        ) for _ in range(64))
        self.logger = logging.getLogger(f"«{log_name}»")
        self.logger.propagate = False
        self.logger.setLevel(self.level)

        self.extra = {"domain": self.DEFAULT_DOMAIN, "log": ""}
        self.adapter = logging.LoggerAdapter(self.logger, self.extra)
        self.logger = self.adapter.logger

        assert isinstance(disabled, bool)
        self.logger.disabled = disabled

        if not self.logger.disabled:
            self.__add_stream_handler()

        self.file_handler = None
        self._registered = []
        self._independent = []
        self.register_callback = None

        global GLOBAL_VLOG
        if global_vlog or (global_vlog is None and GLOBAL_VLOG.is_none()):
            self.assign()

    # can be also used as static method via Log.assign(log)
    def assign(self: Self):
        global GLOBAL_VLOG
        assert isinstance(GLOBAL_VLOG, VirtualLog)
        GLOBAL_VLOG.set(self)

    @staticmethod
    def replace_ansi(file_path: str) -> Callable[["Log"], None]:
        def handler(self: Log) -> None:
            log_content = open(file_path, mode="r", encoding="utf-8").read()
            with open(file_path, mode="w", encoding="utf-8") as writable:
                writable.write(re.sub(self.ANSI_ESCAPE, "", log_content))
        return handler

    @staticmethod
    def delete(file_path: str) -> Callable[["Log"], None]:
        def handler(self: Log) -> None:
            try:
                os.remove(file_path)
            except FileNotFoundError: ...
        return handler

    def register(
        self,
        handler: Callable[[str], Callable[["Log"], None]],
        file_path: Optional[str] = None
    ) -> None:
        if file_path is None:
            assert self.file_handler is not None
            file_path = self.file_handler.baseFilename
        self._registered.append(handler(file_path))

    # this cannot be called in __del__()
    # because open (__builtin__) cannot be found then
    # so callback() should be manually called by its owner
    # or use with(callback=True) block
    def callback(self) -> None:
        for file_handler in self._independent:
            self.__remove_file_handler(file_handler)

        for handler in self._registered:
            handler(self)
        self._registered.clear()

    def __add_stream_handler(self) -> None:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(self.level)
        stream_handler.setFormatter(logging.Formatter(self.LOG_PATTERN))
        self.logger.addHandler(stream_handler)
        self.stream_handler = stream_handler

    def __add_file_handler(
        self,
        log_path: str,
        log_name: str,
        dependent: bool = True
    ) -> None:
        log_file_path = os.path.join(log_path, f"{log_name}.log")
        log_formatter = logging.Formatter(self.FILE_LOG_PATTERN)

        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setLevel(self.level)
        file_handler.setFormatter(log_formatter)

        self.logger.addHandler(file_handler)
        if dependent:
            self.file_handler = file_handler
        else:
            self._independent.append(file_handler)
        self.register(Log.replace_ansi, file_handler.baseFilename)

    def __remove_file_handler(
        self,
        file_handler: Optional[logging.FileHandler] = None
    ) -> None:
        if self.file_handler is None and file_handler is None:
            return

        if file_handler is None:
            file_handler = self.file_handler

        if file_handler == self.file_handler:
            self.file_handler = None

        self.logger.removeHandler(file_handler)

    # dependent=True: to remove previous file_handler if exists
    def trigger(
        self,
        log_path: str,
        log_name: str = "",
        prefix: str = "",
        dependent: bool = True
    ) -> None:
        assert isinstance(log_path, str)
        log_path = os.path.expanduser(log_path)
        os.makedirs(log_path, exist_ok=True)

        assert isinstance(log_name, str)
        if log_name == "":
            log_name = self.__timestamp

        assert isinstance(prefix, str)

        if dependent:
            self.__remove_file_handler()
        self.__add_file_handler(
            log_path,
            prefix + log_name,
            dependent=dependent
        )

    def __clear(self, ignore: bool) -> bool:
        if os.path.exists(self.result_file_path) and ignore:
            return

        for filename in os.listdir(self.save_path):
            file_path = os.path.join(self.save_path, filename)
            # the org of tasks dir is never assumed
            # so there might be dirs in extreme cases
            if os.path.isfile(file_path) and not filename.endswith(".log"):
                os.remove(file_path)
            # automatically add LEGACY_MARKER to old log file
            elif os.path.isfile(file_path) \
                and not filename.startswith(self.LEGACY_MARKER) \
                and filename != self.save_name:
                new_file_path = os.path.join(
                    self.save_path,
                    self.LEGACY_MARKER + filename
                )
                os.rename(file_path, new_file_path)

    # tricks of passing args to `with` block
    # ref: https://stackoverflow.com/a/10252925
    # this is called before __enter__()
    def __call__(
        self,
        base_path: str,
        ident: Optional[str] = None,
        callback: bool = False,
        ignore: bool = True
    ) -> Self:
        assert self.register_callback == None, (
            "__call__() should not be called twice "
            "without calling __exit__() in between; ",
            "usage: with log(...): ..."
        )

        assert isinstance(base_path, str)
        assert isinstance(ident, str) or ident is None

        self.trigger(os.path.join(base_path, ident))
        self.extra["domain"] = self.DEFAULT_DOMAIN if ident is None else ident

        assert isinstance(ignore, bool)
        self.__clear(ignore)

        assert isinstance(callback, bool)
        self.register_callback = callback
        return self

    def __enter__(self) -> bool:
        return os.path.exists(self.result_file_path)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        assert isinstance(self.register_callback, bool)
        if self.register_callback:
            self.callback()
        self.register_callback = None

        self.__remove_file_handler()
        self.extra["domain"] = self.DEFAULT_DOMAIN

    def set_external(self, log_name: str = "") -> None:
        assert isinstance(log_name, str)

        if len(log_name) > 0:
            self.extra["log"] = f"({log_name.strip()}) "
        else:
            self.extra["log"] = log_name

    def save(
        self,
        step_index: int,
        obs: Dict[str, Any],
        codes: List["CodeLike"],
        community: "Community",
        is_textual: bool
    ) -> None:
        assert self.save_path is not None, "Call trigger() first"

        timestamp = self.__timestamp
        traj_obj = {
            "step_index": step_index,
            "timestamp": self.__timestamp,
            "actions": [code_like.code for code_like in codes]
        }

        text_filename = self.TEXT_FILENAME.format(
            index=step_index,
            timestamp=timestamp
        )
        text_file_path = os.path.join(self.save_path, text_filename)

        image_filename = self.IMAGE_FILENAME.format(
            index=step_index,
            timestamp=timestamp
        )
        image_file_path = os.path.join(self.save_path, image_filename)

        # save textual/a11y_tree to new file
        filtered_text = [
            item for item in obs.values()
            if isinstance(item, str)
        ]
        if len(filtered_text) == 1:
            key_name = "textual" if is_textual else "a11y_tree"
            traj_obj[key_name] = text_filename
            with open(text_file_path, mode="w", encoding="utf-8") as writable:
                writable.write(filtered_text[0])

        # save screenshot (or SoM screenshot) to new file
        filtered_image = [
            item for item in obs.values()
            if isinstance(item, Image.Image)
        ]
        if len(filtered_image) == 1:
            traj_obj["screenshot"] = image_filename
            filtered_image[0].save(image_file_path)

        # save trajetories by appending previous records
        with open(self.traj_file_path, mode="a", encoding="utf-8") as appendable:
            appendable.write(json.dumps(traj_obj, ensure_ascii=False) + "\n")

        # save requests by overwriting previous record
        for name, agent in community:
            full_request = agent.dump_history(False)
            simp_request = agent.dump_history(True)
            with open(
                self.request_file_path.format(agent=name),
                mode="w",
                encoding="utf-8"
            ) as writable:
                json.dump(
                    full_request,
                    writable,
                    ensure_ascii=False,
                    indent=2
                )

            with open(
                self.simp_file_path.format(agent=name),
                mode="w",
                encoding="utf-8"
            ) as writable:
                json.dump(
                    simp_request,
                    writable,
                    ensure_ascii=False,
                    indent=2
                )

            with open(
                self.prompt_file_path.format(agent=name),
                mode="w",
                encoding="utf-8"
            ) as writable:
                writable.write(full_request[0]["content"][0]["text"])

    # should not be set as protected method
    # as they will be used by Task objects
    @staticmethod
    def result_handler(method: Callable) -> Callable:
        def result_wrapper(
            self: "Task",
            stop_type: staticmethod,
            stop_args: List[str]
        ) -> bool:
            return_value = method(self, stop_type, stop_args)
            with open(
                self.vlog.result_file_path,
                mode="w",
                encoding="utf-8"
            ) as writable:
                writable.write(str(int(return_value)))
            return return_value
        return result_wrapper

    @staticmethod
    def record_handler(method: Callable) -> Callable:
        def record_wrapper(self: "Task") -> bool:
            self.manager.record_start()
            return_value = method(self)
            self.manager.record_stop(self.vlog.record_file_path)
            return return_value
        return record_wrapper

    # use log.info() directly instead of self.adapter.info()
    # WARNING:
    #   __getattr__ will not be called if property can be found directly
    #   in these functions, self.logger (:= self.adapter.logger) is used, while
    #   in __getattr__, self.adapter is used (to fill domain formatter)
    def __getattr__(self, attr: str) -> Any:
        return getattr(self.adapter if attr in Log.LEVELS else self.logger, attr)

    def input(
        self,
        msg: str,
        level: int = logging.INFO,
        end: str ="\n"
    ) -> str:
        if hasattr(self, "stream_handler"):
            stored_end = self.stream_handler.terminator
            self.stream_handler.terminator = end

        self.adapter.log(level=level, msg=msg)
        if hasattr(self, "stream_handler"):
            self.stream_handler.terminator = stored_end
        return input()


class VirtualLog:
    def __init__(self) -> None:
        self._log = None

    def is_none(self) -> bool:\
        return self._log is None

    def set(self, log: Log):
        assert isinstance(log, Log)
        self._log = log

    def __call__(self, log_name: str = "") -> Self:
        self._log.set_external(log_name)
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self()

    # use vlog.fallback() when vlog might be nil
    # use GLOBAL_VLOG directly when vlog must be nil
    def fallback(self) -> "VirtualLog":
        return GLOBAL_VLOG \
            if GLOBAL_VLOG is not None and self._log is None \
            else self

    # use vlog.info() directly instead of vlog._log.adapter.info()
    def __getattr__(self, attr: str) -> Any:
        log = Log(disabled=True) if self._log is None else self._log
        return getattr(log, attr)


if GLOBAL_VLOG is None:
    GLOBAL_VLOG = VirtualLog()
    _logger_log = logging.Logger._log

    def _log(self, level, msg, *args, stacklevel=1, **kwargs):
        internal = self.name.startswith(Log.UNIQUE_PREFIX) \
            or self.name.endswith(Log.UNIQUE_SUFFIX)

        # _log defined here cannot pass check of _is_internal_frame(f)
        # thus stacklevel should be increased every time _log() is called
        stacklevel += 1

        if internal:
            _logger_log(self, level, msg, *args, stacklevel=stacklevel, **kwargs)
        elif Log.TACTIC == Log.Tactic.IGNORE:
            return
        elif Log.TACTIC == Log.Tactic.NATURALIZATION:
            with GLOBAL_VLOG(self.name) as vlog:
                vlog.log(level, msg, stacklevel=stacklevel)
        elif Log.TACTIC == Log.Tactic.OVERLOOK:
            _logger_log(self, level, msg, *args, stacklevel=stacklevel, **kwargs)

    logging.Logger._log = _log
