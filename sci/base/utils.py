import sys
import os
import inspect
import multiprocessing
import traceback

from enum import Enum
from typing import Optional, Dict, Any
from typing import Callable, ClassVar, Self
from dataclasses import dataclass
from contextlib import contextmanager

class SortVM:
    def __get__(self, _, obj_type=None) -> Optional["TypeSort"]:
        if inspect.signature(obj_type).parameters.__len__():
            return TypeSort("", TypeSort.Sort.VM)


@dataclass
class TypeSort:
    class Sort(Enum):
        Raw = 0
        VM = 1

    type: str
    sort: Sort

    VM: ClassVar[Optional[Self]] = SortVM()
    Raw: ClassVar[Callable] = lambda type: TypeSort(type, TypeSort.Sort.Raw)

    def __repr__(self) -> str:
        if self.sort == TypeSort.Sort.VM:
            return self.sort.name
        else:
            return f"{self.sort.name}:{self.type}"

    def __hash__(self) -> int:
        return hash(self.__repr__())

    # crucial for hash comparison
    def __eq__(self, __value: "TypeSort") -> bool:
        return self.__repr__() == __value.__repr__()

    def __str__(self) -> str:
        return f"{self.type}_{self.sort.name}"

    def __call__(self, postfix: str) -> Any:
        return self.sort.name + postfix

RawType = lambda type: TypeSort(type, TypeSort.Sort.Raw)
VMType = lambda type: TypeSort(type, TypeSort.Sort.VM)


def error_factory(default_value: Any):
    def error_handler(method: Callable) -> Callable:
        def error_wrapper(self, *args, **kwargs) -> bool:
            try:
                return method(self, *args, **kwargs)
            except:
                if "DEBUG_ERR_FACT" in os.environ:
                    import traceback
                    from .log import GLOBAL_VLOG
                    GLOBAL_VLOG.error(
                        "Error when evaluating."
                            + "\n"
                            + traceback.format_exc()
                    )
                    breakpoint()
                return default_value
        return error_wrapper
    return error_handler

def getitem(obj: Dict, name: str, default: Any) -> Any:
    return obj[name] if name in obj else default

# if MRO is shaped like A -> B -> C -> D -> object, then
# - `want(C)` in methods of A equals to `super(B, self)`
# - `want(A)` in methods of A equals to `self`
def want(cls):
    self = sys._getframe(1).f_locals["self"]
    mro_chain = self.__class__.mro()
    cls_index = mro_chain.index(cls)
    if cls_index > 0:
        return super(mro_chain[cls_index - 1], self)
    else:
        return self


@contextmanager
def temp_chdir(path):
    last_path = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(last_path)


# only viable under UNIX-like OSs
def block(timeout, func, *args, **kwargs):
    def wrapper(queue, *args, **kwargs):
        try:
            result = func(*args, **kwargs)
            queue.put(("result", result))
        except Exception as e:
            queue.put(("error", traceback.format_exc()))

    obj = {}
    queue = multiprocessing.Queue()
    proc = multiprocessing.Process(
        target=wrapper,
        args=(queue, *args),
        kwargs=kwargs
    )
    proc.start()
    proc.join(timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join()
        assert False, f"Timeout after waiting for {timeout}s."

    if not queue.empty():
        status, value = queue.get()
        if status == "result":
            obj["result"] = value
        elif status == "error":
            obj["error"] = value

    assert "error" not in obj, obj["error"]
    return obj.get("result")


def relative_resolver() -> str:
    relative_path = os.path.join(os.path.split(__file__)[0], "relative.py")
    with open(relative_path, mode="r", encoding="utf-8") as readable:
        return readable.read().strip()

relative_py = relative_resolver()
