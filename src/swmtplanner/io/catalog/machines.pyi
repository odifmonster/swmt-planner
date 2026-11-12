from ..loaders import Table, JSONFile, JSONTableLoader

KNIT_MACHINES_FILE: JSONFile
"""``knit-machine-master.json``, in the folder under the ``inputs``
config key: a JSON object keyed by knitting machine id. Undated; read
with ``orient='index'``."""

KNIT_MACHINES: Table
"""
Every knitting machine. Index ``machine`` (machine id, e.g. ``B4``).
Columns: ``gauge`` (needles per inch), ``width`` (knitting width,
inches), ``is_new`` (whether it is one of the new, faster machines),
``rpm`` (rated speed, revolutions per minute), and ``attrs`` (a tuple of
attribute flags such as ``"tall"``).
"""

KNIT_MACHINE_LOADER: JSONTableLoader
"""Loads ``KNIT_MACHINES`` from ``KNIT_MACHINES_FILE``."""

NEW_MACHINES_ONLY: frozenset[str]
"""The master style names that may run only on machines with ``is_new``
set."""
