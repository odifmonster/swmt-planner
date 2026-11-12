#!/usr/bin/env python

from typing import Any


def _strip(v: Any) -> str:
    return str(v).strip()


def _is_x(v: Any) -> bool:
    return _strip(v).upper() == 'X'


def _is_active(v: Any) -> bool:
    return _strip(v).upper() != 'I'
