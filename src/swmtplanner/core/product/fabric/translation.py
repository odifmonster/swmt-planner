#!/usr/bin/env python

from .fabric import Fabric


_ply1_to_fab: dict[str, Fabric] = {}


def load_ply1_translation(fabrics: list[Fabric]) -> None:
    table: dict[str, Fabric] = {}
    for f in fabrics:
        for ply1 in f.ply1_parts:
            table[ply1] = f
    _ply1_to_fab.clear()
    _ply1_to_fab.update(table)


def ply1_to_fabric(ply1: str) -> Fabric | None:
    return _ply1_to_fab.get(ply1, None)