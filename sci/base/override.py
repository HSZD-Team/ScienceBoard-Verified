import dataclasses
from typing import Dict, Any

# modify asdict() for class Content
# ref: https://stackoverflow.com/a/78289335
_asdict_inner_actual = dataclasses._asdict_inner
def _asdict_inner(obj, dict_factory):
    if dataclasses._is_dataclass_instance(obj):
        if getattr(obj, "__dict_factory_override__", None):
            user_dict = obj.__dict_factory_override__()
            for key, value in user_dict.items():
                if dataclasses._is_dataclass_instance(value):
                    user_dict[key] = _asdict_inner(value, dict_factory)
            return user_dict
    return _asdict_inner_actual(obj, dict_factory)
dataclasses._asdict_inner = _asdict_inner

def eliminate_nonetype(self) -> Dict[str, Any]:
    return {
        key: getattr(self, key)
        for key in self.__dataclass_fields__
        if getattr(self, key) is not None
    }
