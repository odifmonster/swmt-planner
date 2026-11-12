from ..loaders import Table, ExcelFile, ExcelTableLoader

PA_DEMAND_FILE: ExcelFile
"""The ``Fab shortage`` tab of the dated ``pa_dmnd_<YYYYMMDD>.xlsx``, in
the folder under the ``scheduling`` config key."""

PA_DEMAND: Table
"""
The finished fabric demand view for the next eight weeks, one row per
ply 1 part number.

Index ``part_no`` (ply 1 part number; joins to ``FABRICS``). Columns:
``item`` (finished item code), ``bill_to`` (customer bill-to number),
``plant`` (lamination plant code, possibly two as in ``12/50``),
``ship_day``, ``past_due`` (fabric required that is already past due),
and ``wk0`` to ``wk8`` (fabric required in each week, week 0 being the
current one). Quantities are in yards and read blanks as ``0.0``.
"""

PA_DEMAND_LOADER: ExcelTableLoader
"""Loads ``PA_DEMAND`` from ``PA_DEMAND_FILE``. The file is dated, so
``load(cfg)`` reads today's view and ``load(cfg, dt)`` a given day's."""
