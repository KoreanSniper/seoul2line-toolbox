"""Shared port policy and strict runtime value checks."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Port:
    type: str
    required: bool = False
    multiple: bool | None = None

    @property
    def allows_multiple(self):
        return self.multiple if self.multiple is not None else self.type in {"Flow", "FileList"}


def compatible(output, input_port):
    return (output.type == input_port.type or
            (input_port.type == "Any" and output.type != "Flow") or
            (input_port.type == "FileList" and input_port.allows_multiple and output.type == "FilePath"))


def value_matches(value, type_id):
    if type_id == "Any":
        return True
    if type_id in {"String", "FilePath"}:
        return isinstance(value, str)
    if type_id == "Number":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    if type_id == "Boolean":
        return isinstance(value, bool)
    if type_id == "FileList":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if type_id == "JSON":
        import json
        try:
            json.dumps(value, allow_nan=False)
            return True
        except (ValueError, TypeError):
            return False
    return False


def missing(value, port):
    return value is None or (port.type == "FilePath" and value == "")
