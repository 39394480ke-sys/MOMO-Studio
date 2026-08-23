"""Small JSON-compatible immutable containers for persisted snapshot values."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Never, Self, TypeVar

from pydantic import JsonValue

Key = TypeVar("Key")
Value = TypeVar("Value")
Item = TypeVar("Item")


def _immutable_error() -> Never:
    raise TypeError("snapshot mappings and sequences are immutable")


class FrozenDict(dict[Key, Value]):
    """A ``dict`` subclass that remains natively JSON/Pydantic serializable."""

    def __setitem__(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def __delitem__(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def clear(self) -> Never:
        _immutable_error()

    def pop(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def popitem(self) -> Never:
        _immutable_error()

    def setdefault(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def update(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    # Typeshed cross-checks in-place operators against both ``dict.__ior__`` and
    # ``dict.__or__`` overloads. This method always raises, so no result-type contract
    # is observable; keeping the override closes the ``|=`` mutation escape hatch.
    def __ior__(self, value: object, /) -> Self:  # type: ignore[override,misc]
        _immutable_error()


class FrozenList(list[Item]):
    """A ``list`` subclass used for recursively frozen JSON arrays."""

    def __setitem__(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def __delitem__(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def append(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def clear(self) -> Never:
        _immutable_error()

    def extend(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def insert(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def pop(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def remove(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    def reverse(self) -> Never:
        _immutable_error()

    def sort(self, *args: Any, **kwargs: Any) -> Never:
        _immutable_error()

    # As above, this deliberate always-raising override closes the ``+=`` escape hatch.
    def __iadd__(self, value: object, /) -> Self:  # type: ignore[override,misc]
        _immutable_error()

    def __imul__(self, value: object, /) -> Self:
        _immutable_error()


def freeze_mapping(value: Mapping[Key, Value]) -> FrozenDict[Key, Value]:
    """Copy a mapping into an immutable, serialization-compatible value."""

    return FrozenDict(value)


def freeze_sequence(value: Iterable[Item]) -> FrozenList[Item]:
    """Copy a sequence into an immutable, serialization-compatible value."""

    return FrozenList(value)


def deep_freeze_json(value: JsonValue) -> JsonValue:
    """Recursively copy and freeze every JSON object and array."""

    if isinstance(value, dict):
        return FrozenDict({key: deep_freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return FrozenList(deep_freeze_json(item) for item in value)
    return value
