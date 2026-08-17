import sys
import json

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

sys.dont_write_bytecode = True
from ..base.override import *


@dataclass
class REPLInput:
    def __dict_factory_override__(self) -> Dict[str, Any]:
        return eliminate_nonetype(self)

    def dumps(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False) + "\n\n"

    @staticmethod
    def from_dict(query: dict) -> Optional["REPLInput"]:
        if isinstance(query, dict) \
            and ("cmd" in query) \
            and isinstance(query["cmd"], str) \
            and (
                "env" not in query \
                or query["env"] is None \
                or (isinstance(query["env"], int) and query["env"] >= 0)
            ) and all([key in ("cmd", "env") for key in query]):
            return REPLInputCommand(**query)

        elif isinstance(query, dict) \
            and ("tactic" in query) \
            and ("proofState" in query) \
            and len(query) == 2 \
            and isinstance(query["tactic"], str) \
            and isinstance(query["proofState"], int) \
            and query["proofState"] >= 0:
            return REPLInputTactic(**query)

        else:
            return None


@dataclass
class REPLInputCommand(REPLInput):
    cmd: str
    env: Optional[int] = None


@dataclass
class REPLInputTactic(REPLInput):
    tactic: str
    proofState: int


@dataclass
class REPLOutput:
    input: Optional[Any] = None
    message: Optional[str] = None
    messages: Optional[List] = None

    def __dict_factory_override__(self) -> Dict[str, Any]:
        return eliminate_nonetype(self)

    def dumps(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_dict(input: Optional[REPLInput], output: dict) -> "REPLOutput":
        input = None if input is None else asdict(input)

        return REPLOutputCommand(input=input, **output) \
            if "env" in output \
            else REPLOutputTactic(input=input, **output)

    @staticmethod
    def from_sorry(sorry: dict) -> "REPLOutputTactic":
        return REPLOutputTactic(
            proofState=sorry["proofState"],
            goals=[sorry["goal"]]
        )

    def is_error(self) -> bool:
        message_error = self.message is not None
        messages_error = self.messages is not None \
            and any([item["severity"] == "error" for item in self.messages])
        return message_error or messages_error

    def is_success(self) -> bool:
        return False


@dataclass
class REPLOutputCommand(REPLOutput):
    env: int = -1
    sorries: Optional[List] = None


@dataclass
class REPLOutputTactic(REPLOutput):
    proofState: Optional[int] = None
    goals: Optional[List] = None

    def is_success(self) -> bool:
        return not self.is_error() \
            and isinstance(self.goals, list) \
            and len(self.goals) == 0
