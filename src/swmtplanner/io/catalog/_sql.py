#!/usr/bin/env python

from importlib.resources import files


def read_sql(name: str) -> str:
    return files(__package__).joinpath('sql', name).read_text(encoding='utf-8')
