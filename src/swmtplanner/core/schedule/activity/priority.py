#!/usr/bin/env python


class Priority:

    def __init__(self, value: 'int | str | None'):
        self._value = None
        self.value = value

    @property
    def value(self) -> 'int | str | None':
        return self._value

    @value.setter
    def value(self, value: 'int | str | None') -> None:
        if isinstance(value, str) and value != 'S':
            raise ValueError("the only valid string priority is 'S'")
        self._value = value
