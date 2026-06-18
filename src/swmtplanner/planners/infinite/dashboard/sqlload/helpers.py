#!/usr/bin/env python

"""Query-building helpers for the read path: the `Filter` and `FKLookup`
dataclasses that describe how a single column constrains a `Query`.
See `planners/infinite/dashboard/DESIGN.md` (Read path — `sqlload/`).

Each carries a `to_sql_str()` that returns a **format string** the `Query` fills
in to assemble SQL — a `Filter` yields `WHERE`-clause text (`s.format(colname=…)`),
an `FKLookup` yields an `INNER JOIN` (`s.format(ftable=…, fcol=…, run_id=…)`).
Values are inlined as MySQL literals. Neither validates at construction; a bad
`Filter.rule` raises `FilterError` on the first `to_sql_str()` call.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Collection, Literal

__all__ = ['Filter', 'FKLookup', 'FilterError']

# The four per-column filter modes (see manifest column types for which apply).
FilterKind = Literal['selection', 'exclusion', 'range', 'pattern']


class FilterError(ValueError):
    """A `Filter`'s `rule` doesn't match its `kind` (wrong type, empty set, a
    range unbounded on both ends, or an unknown kind). Raised lazily by
    `to_sql_str()`, never at construction."""


def _sql_literal(value: Any) -> str:
    """Render one Python value as a MySQL literal for inlining into a clause.
    `None` -> `NULL`; numbers verbatim; everything else single-quoted with `'`
    and `\\` escaped. Values are assumed free of `{`/`}` (they would collide with
    the format placeholders the `Query` resolves later — true for all real
    keys/items/dates in this schema)."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):                  # bool is an int subclass
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return "'" + str(value) + "'"
    text = str(value).replace('\\', '\\\\').replace("'", "''")
    return "'" + text + "'"


def _literal_list(vals: Collection[Any]) -> str:
    """Comma-joined SQL literals, sorted for a deterministic statement (order is
    irrelevant inside `IN (...)`)."""
    return ', '.join(sorted(_sql_literal(v) for v in vals))


@dataclass
class Filter:
    """A per-column value filter. `kind` selects the mode and `rule` is its
    payload (a set for selection/exclusion, a `(low, high)` tuple for range, a
    MySQL `LIKE` pattern string for pattern). `to_sql_str()` returns the
    `WHERE`-clause format string, e.g. `'{colname} IN (1, 2)'`."""
    kind: FilterKind
    rule: Any

    def to_sql_str(self) -> str:
        """The `WHERE`-clause fragment as a `{colname}`-format string. Raises
        `FilterError` if `rule` doesn't match `kind`."""
        if self.kind == 'selection' or self.kind == 'exclusion':
            return self._membership_sql()
        if self.kind == 'range':
            return self._range_sql()
        if self.kind == 'pattern':
            return self._pattern_sql()
        raise FilterError(f'unknown filter kind {self.kind!r}')

    def _membership_sql(self) -> str:
        if not isinstance(self.rule, (set, frozenset)):
            raise FilterError(
                f'{self.kind} filter rule must be a set, got '
                f'{type(self.rule).__name__}'
            )
        if not self.rule:
            raise FilterError(f'{self.kind} filter rule is an empty set')
        op = 'IN' if self.kind == 'selection' else 'NOT IN'
        return '{colname} ' + op + ' (' + _literal_list(self.rule) + ')'

    def _range_sql(self) -> str:
        if not isinstance(self.rule, tuple) or len(self.rule) != 2:
            raise FilterError('range filter rule must be a (low, high) tuple')
        low, high = self.rule
        if low is None and high is None:
            raise FilterError('range filter rule cannot be unbounded on both ends')
        parts = []
        if low is not None:
            parts.append('{colname} >= ' + _sql_literal(low))
        if high is not None:
            parts.append('{colname} <= ' + _sql_literal(high))
        return ' AND '.join(parts)

    def _pattern_sql(self) -> str:
        if not isinstance(self.rule, str):
            raise FilterError(
                f'pattern filter rule must be a string, got '
                f'{type(self.rule).__name__}'
            )
        return '{colname} LIKE ' + _sql_literal(self.rule)


@dataclass
class FKLookup:
    """A foreign-key navigation constraint: restrict the main table to rows whose
    FK matches one of `vals` in `ref_table.ref_col` (the reference table's own
    PK column). `to_sql_str()` returns an `INNER JOIN` format string keyed on
    `{ftable}` (the table holding the FK), `{fcol}` (its FK column), and
    `{run_id}`; the join target is an indexed sub-query over the reference
    table."""
    ref_table: str
    ref_col: str
    vals: Collection[Any]

    def to_sql_str(self) -> str:
        """The `INNER JOIN` fragment as a `{ftable}`/`{fcol}`/`{run_id}`-format
        string. Raises `FilterError` if there are no values to look up."""
        if not self.vals:
            raise FilterError('FK lookup has no values to match')
        sub = (
            'SELECT `run_id`, `' + self.ref_col + '` FROM `' + self.ref_table +
            '` WHERE `run_id` = {run_id} AND `' + self.ref_col +
            '` IN (' + _literal_list(self.vals) + ')'
        )
        return (
            'INNER JOIN (' + sub + ') AS `fk_{fcol}` '
            'ON `{ftable}`.`run_id` = `fk_{fcol}`.`run_id` '
            'AND `{ftable}`.`{fcol}` = `fk_{fcol}`.`' + self.ref_col + '`'
        )
