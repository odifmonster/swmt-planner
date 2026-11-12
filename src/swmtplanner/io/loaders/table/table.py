#!/usr/bin/env python

from dataclasses import dataclass

from .column import Column


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    index: Column | None = None
