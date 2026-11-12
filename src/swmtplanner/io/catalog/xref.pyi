from dataclasses import dataclass
from datetime import date

import pandas as pd

from ...core.products import Shade
from ..loaders import Table, ExcelFile, ExcelTableLoader

XREF_FILE: ExcelFile
"""The ``Xref`` tab of ``PA Master Xref.xlsx``, in the folder under the
``pa_supply`` config key. Undated."""

FABRICS: Table
"""
The finished fabric cross-reference, one row per ply 1 part number.

Index ``part_no`` (ply 1 part number, text). Columns: ``item`` (finished
item code, ``FF <style>-<formula>-<width>``), ``greige`` (greige style
name), ``style`` (fabric style name), ``width`` (finished width, inches),
``yld`` (yards per pound), ``formula`` (dye formula number, nullable),
``color`` (dye formula name), ``shade`` (shade rating 0-4, nullable; a key
of ``SHADE_RATINGS``), ``active`` (false only where the status is ``I``),
``jet1`` to ``jet10`` (whether the fabric can run on each jet), and
``tanks``.

Text columns are stripped and read blanks as ``""``. Blank sheet rows
come through with an empty ``part_no`` and ``item``; row filtering is
left to the product builder.
"""

SHADE_RATINGS: dict[int, Shade]
"""Maps the ``shade`` rating of ``FABRICS`` to a ``Shade``: 0 is
``LIGHT0``, 1 ``LIGHT1``, 2 ``MEDIUM``, 3 ``BLACK``, 4 ``SD_BLACK``."""

GREIGE_STYLES_SHEET: ExcelFile
"""The ``Greige Styles`` tab of ``PA Master Xref.xlsx``. Undated."""

GREIGE_STYLES: Table
"""
The greige styles sheet, one row per greige name used in the ``Xref``
tab.

Index ``alias`` (the ``GreigeAlt`` name). Columns: ``master`` (the
``GreigeAlt2`` name, which the knitters use and which is the
``Greige.id``) and ``std_wt`` (target roll weight, pounds).

Read by ``alias`` to get ``master`` it is the alias map; read by a
master's own name it gives that master's ``std_wt``.
"""

GREIGE_STYLE_LOADER: ExcelTableLoader
"""Loads ``GREIGE_STYLES`` from ``GREIGE_STYLES_SHEET``."""

@dataclass(frozen=True)
class XrefFabricLoader(ExcelTableLoader):
    """
    The loader for ``FABRICS``. Besides reading the ``Xref`` tab it
    converts the ``greige`` column from the ``GreigeAlt`` name the sheet
    holds to the ``GreigeAlt2`` (master) name, using the greige styles
    table from the same workbook.
    """

    aliases: ExcelTableLoader
    """The loader for the greige styles table, whose index is the alias
    and whose ``master`` column is the name to convert to."""

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        """
        Load the fabrics frame as ``ExcelTableLoader.load`` does, load
        the greige styles frame with ``aliases.load`` (passing the same
        ``cfg``, ``dt``, and ``override_name``, since both sheets are in
        one workbook), and replace each ``greige`` value that is an alias
        with its master. A value that is not an alias is left as it is.
        """
        ...

FABRIC_LOADER: XrefFabricLoader
"""Loads ``FABRICS`` from ``XREF_FILE``, converting ``greige`` through
``GREIGE_STYLE_LOADER``."""
