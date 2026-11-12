#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

type DefaultVal = None | Callable[[], datetime]


@dataclass(frozen=True)
class SQLQuery:
    raw_str: str
    date_params: int | tuple[str, ...]
    date_fmt: str | None = None
    defaults: tuple[DefaultVal, ...] | tuple[tuple[str, DefaultVal], ...] = ()

    def __post_init__(self) -> None:
        if self._nparams and self.date_fmt is None:
            raise ValueError('date_fmt is required for a query with date parameters')
        if not self.defaults:
            return
        if self._positional:
            if len(self.defaults) != self.date_params:
                raise ValueError(f'expected {self.date_params} positional defaults, '
                                 f'got {len(self.defaults)}')
            bad = [d for d in self.defaults if d is not None and not callable(d)]
        else:
            names = set(self.date_params)
            bad = [d for d in self.defaults
                   if not (isinstance(d, tuple) and len(d) == 2 and d[0] in names
                           and (d[1] is None or callable(d[1])))]
        if bad:
            raise ValueError(f'invalid defaults for date_params {self.date_params!r}: {bad!r}')

    @property
    def _positional(self) -> bool:
        return isinstance(self.date_params, int)

    @property
    def _nparams(self) -> int:
        return self.date_params if self._positional else len(self.date_params)

    def _render(self, value: datetime) -> str:
        return value.strftime(self.date_fmt)

    def get_query(self, *args: datetime | None, **kwargs: datetime | None) -> str:
        if args and kwargs:
            raise ValueError('pass either positional or keyword date arguments, not both')
        if not self._nparams:
            if args or kwargs:
                raise ValueError('query takes no date parameters')
            return self.raw_str
        if self._positional:
            if kwargs:
                raise ValueError('query takes positional date parameters, not keywords')
            if len(args) > self.date_params:
                raise ValueError(f'query takes at most {self.date_params} date parameters, '
                                 f'got {len(args)}')
            defaults = self.defaults or (None,) * self.date_params
            values = []
            for i in range(self.date_params):
                given = args[i] if i < len(args) else None
                if given is None:
                    if defaults[i] is None:
                        raise ValueError(f'date parameter {i} has no value and no default')
                    given = defaults[i]()
                values.append(self._render(given))
            return self.raw_str.format(*values)
        if args:
            raise ValueError('query takes keyword date parameters, not positionals')
        unknown = set(kwargs) - set(self.date_params)
        if unknown:
            raise ValueError(f'unknown date parameters {sorted(unknown)!r}')
        defaults = dict(self.defaults)
        values = {}
        for name in self.date_params:
            given = kwargs.get(name)
            if given is None:
                if defaults.get(name) is None:
                    raise ValueError(f'date parameter {name!r} has no value and no default')
                given = defaults[name]()
            values[name] = self._render(given)
        return self.raw_str.format(**values)
