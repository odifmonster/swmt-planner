#!/usr/bin/env python

import json

from .greige import Greige


_variant_to_master: dict[str, str] = {}
_alt_to_greige: dict[str, Greige] = {}


def load_variant_translation(contents: str) -> None:
    table: dict[str, str] = {}
    for obj in json.loads(contents):
        table[obj['variant']] = obj['master']
    _variant_to_master.clear()
    _variant_to_master.update(table)


def load_alt_translation(greiges: list[Greige]) -> None:
    table: dict[str, Greige] = {}
    for greige in greiges:
        for name in greige.alt_names:
            table[name] = greige
    _alt_to_greige.clear()
    _alt_to_greige.update(table)


def variant_to_master(variant: str) -> str | None:
    return _variant_to_master.get(variant)


def alt_greige_to_greige(alt_greige: str) -> Greige | None:
    return _alt_to_greige.get(alt_greige)
