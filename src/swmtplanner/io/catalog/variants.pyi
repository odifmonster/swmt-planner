from ..loaders import Column, Table, SQLQuery, CSVFile, SQLTableLoader, CSVTableLoader

SI_VARIANTS_QUERY: SQLQuery
"""The style master query (``sql/si_variants.sql``): every style with a
positive knitting width and rack weight and a gauge, with its four bars
joined out to the yarn item, stitch, and threading tables. It has no date
parameters."""

VARIANTS_TSV: CSVFile
"""The same table as a tab-separated extract, ``variants.tsv``, in the
folder under the ``inputs`` config key. Undated."""

def _bar_columns(i: int) -> tuple[Column, ...]:
    """The ten columns describing bar ``i``: ``bar{i}_ends``, ``_merge``,
    ``_vendor``, ``_denier``, ``_luster``, ``_desc``, ``_pct``, ``_rl``,
    ``_stitch``, and ``_thread``."""
    ...

VARIANTS: Table
"""
Greige style variants, one row per style as recorded in the database.
No index: ``variant`` is not unique in the source (a few rows are exact
duplicates).

Columns: ``variant`` (style name), ``width`` (knitting width, inches),
``rack_wt`` (pounds per 100 racks), ``gauge`` (needles per inch),
``beams``, and for each bar ``i`` in 1-4: ``bar{i}_ends`` (0 when the bar
is unused), ``bar{i}_merge`` (yarn item code), ``bar{i}_vendor``,
``bar{i}_denier`` (0 when null), ``bar{i}_luster``, ``bar{i}_desc``,
``bar{i}_pct`` and ``bar{i}_rl`` (0.0 when null), ``bar{i}_stitch``, and
``bar{i}_thread``. The text columns keep nulls as nulls.
"""

VARIANT_LOADER: SQLTableLoader
"""Loads ``VARIANTS`` from the database with ``SI_VARIANTS_QUERY``."""

VARIANT_TSV_LOADER: CSVTableLoader
"""Loads ``VARIANTS`` from the ``VARIANTS_TSV`` extract. The extract
writes nulls as the literal ``None``, which ``pd.read_csv`` reads as
null, so it gives the same frame as ``VARIANT_LOADER``."""
