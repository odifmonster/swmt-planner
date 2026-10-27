#!/usr/bin/env python

"""`SQLQuery` — a complete SQL statement plus the date arguments it takes —
and, below the class, every query the planner's inputs need as a named
`SQLQuery` constant. Each constant's result shape is the `Table` of the same
name in `.tables`.

`raw_str` holds one positional `{}` placeholder per argument (literal braces
doubled, as for `str.format`); `get_query(*args)` renders each `date` /
`datetime` argument with `date_fmt` — which carries whatever quoting the SQL
needs — and substitutes them in the order passed. `date_fmt` is `None` only
for a query with no arguments. The format is `strftime`'s, plus the
unpadded directives `%-d`, `%-m`, `%-H` … (a numeric directive with `-`
after the `%`), which `render_date` handles itself so they work on every
platform.

See `planners/infinite/swmtio/DESIGN.md` ("Queries with date arguments").
"""

import re
from dataclasses import dataclass
from datetime import date

_UNPADDED = re.compile(r'%%|%-([A-Za-z])')


def render_date(value: date, fmt: str) -> str:
    """`value.strftime(fmt)`, with `%-<directive>` rendered as that numeric
    directive without zero padding (`%-d` → `7`, not `07`) on every
    platform; `%%` is left to `strftime`. A non-numeric directive after
    `%-` raises `ValueError`."""
    def unpad(m: re.Match) -> str:
        if m[0] == '%%':
            return '%%'
        text = value.strftime('%' + m[1])
        try:
            return str(int(text))
        except ValueError:
            raise ValueError(f'%-{m[1]} is not a numeric directive') from None
    return value.strftime(_UNPADDED.sub(unpad, fmt))


class QueryArgumentError(ValueError):
    """`get_query` was given the wrong number of arguments."""


@dataclass(frozen=True)
class SQLQuery:
    """A query's SQL text (`raw_str`), how many date arguments it takes
    (`num_args`), and the `strftime` format each is rendered with
    (`date_fmt`, through `render_date`; `None` iff `num_args == 0`)."""
    raw_str: str
    num_args: int
    date_fmt: str | None

    def __post_init__(self) -> None:
        if self.num_args < 0:
            raise ValueError(f'num_args must be >= 0, got {self.num_args}')
        if (self.num_args == 0) != (self.date_fmt is None):
            raise ValueError(
                'date_fmt must be None exactly when num_args is 0 '
                f'(num_args={self.num_args}, date_fmt={self.date_fmt!r})')

    def get_query(self, *args: date) -> str:
        """Render the statement: exactly `num_args` dates, each formatted with
        `date_fmt`, substituted into `raw_str` in order. The wrong count
        raises `QueryArgumentError`; types are not checked beyond what
        `strftime` enforces."""
        if len(args) != self.num_args:
            raise QueryArgumentError(
                f'query takes {self.num_args} date argument(s), got {len(args)}')
        rendered = [render_date(a, self.date_fmt) for a in args]  # type: ignore[arg-type]
        return self.raw_str.format(*rendered)


# --- the queries -----------------------------------------------------------
# One `SQLQuery` constant per input, named for the input; its `Table` is the
# constant of the same name in `.tables`.

# A date argument rendered as the first six parts of `DATETIMEFROMPARTS(...)`,
# each unpadded (`2026, 10, 7, 0, 0, 0`); the query supplies the trailing
# milliseconds itself. A `date` renders its time parts as zeros; a `datetime`
# keeps them.
DATETIMEFROMPARTS_FMT = '%Y, %-m, %-d, %-H, %-M, %-S'

# Beam-set inventory: active sets with weight on them, not threaded.
ACTIVE = SQLQuery("""\
SELECT
    sh.new_name AS "set_no",
    sh.new_ReceivedDate AS "rcv_date",
    sh.new_Assn_Date AS "assign_date",
    sh.new_CurrentWeight AS "lbs",
    sh.new_Beams AS "beams",
    sh.new_Ends AS "ends",
    y.new_merge AS "merge",
    ac."Name" AS "vendor",
    y.new_Denier AS "denier",
    y.new_Luster AS "luster",
    d.new_yarntype AS "yarn_type",
    sh.new_Comments AS "comments",
    bsz.new_name AS "beam_size"
FROM new_sethistoryBase AS sh
    LEFT JOIN new_yarnBase AS y ON sh.new_MergeId=y.new_yarnId
    LEFT JOIN new_yarndescriptionBase AS d ON d.new_yarndescriptionId=y.new_YarnDesc
    LEFT JOIN AccountBase AS ac ON y.new_Producer=ac.AccountId
    LEFT JOIN new_beamsizeBase AS bsz ON sh.new_BeamSizeId=bsz.new_beamsizeId
WHERE
    sh.new_name NOT LIKE '%_del' AND
    sh.new_EmptyDateandTime IS NULL AND
    (sh.new_Active='A' OR sh.new_Active IS NULL) AND
    sh.new_CurrentWeight>50 AND
    sh.new_ThreadingDateandTime IS NULL AND
    sh.new_SetNumber NOT LIKE '%_del' AND
    sh.new_Status='I'
ORDER BY sh.new_name
""", 0, None)

# Sets assigned to a machine's bars but not yet threaded: the last five
# assignments per (machine, bar), newest first by assignment date.
ASSIGNED = SQLQuery("""\
WITH ranked_bars AS (
    SELECT s.*, ROW_NUMBER() OVER (
        PARTITION BY new_Location, new_Bars
        ORDER BY new_Assn_Date ASC
    ) AS rn
    FROM new_sethistoryBase AS s
    WHERE s.new_Assn_Date IS NOT NULL
        AND s.new_ThreadingDateandTime IS NULL
        AND s.new_TapeOutDateandTime IS NULL
        AND s.new_EmptyDateandTime IS NULL
        AND (s.new_Active='A' OR s.new_Active IS NULL)
        AND s.new_SetNumber NOT LIKE '%_del'
        AND s.new_Bars IS NOT NULL
        AND s.new_Status='I'
) SELECT
    ranked_bars.new_Location AS "machine",
    ranked_bars.new_Bars AS "bar",
    ranked_bars.new_Assn_Date AS "assn_ts",
    ranked_bars.new_SetNumber AS "set_no",
    ranked_bars.new_CurrentWeight AS "lbs",
    ranked_bars.new_Beams AS "beams",
    ranked_bars.new_Ends AS "ends",
    y.new_Merge AS "merge",
    y.new_Denier AS "denier",
    ac."Name" AS "vendor",
    y.new_Luster AS "luster",
    d.new_yarntype AS "yarn_type",
    bsz.new_name AS "beam_size"
    FROM ranked_bars
        LEFT JOIN new_yarnBase AS y ON y.new_yarnId=ranked_bars.new_MergeId
        LEFT JOIN AccountBase AS ac ON y.new_Producer=ac.AccountId
        LEFT JOIN new_yarndescriptionBase AS d ON y.new_YarnDesc=d.new_yarndescriptionId
        LEFT JOIN new_beamsizeBase AS bsz ON ranked_bars.new_BeamSizeId=bsz.new_beamsizeId
    WHERE rn<=5
    ORDER BY ranked_bars.new_Location, ranked_bars.new_Bars
""", 0, None)

# Piece tickets scanned since a date, per machine, each with the next
# ticket's scan as its end: the rolls doffed since then. One date argument.
DOFFED = SQLQuery("""\
WITH unq_tkts AS (
    SELECT
        *,
        SUBSTRING(new_Ticket, 1, 3) AS "location",
        ROW_NUMBER() OVER (
            PARTITION BY new_Ticket
            ORDER BY new_ScanCreatedDate DESC
        ) AS tkt_rn
    FROM new_scanneditemsBase
    WHERE new_TicketType='PIECE' AND new_Isvalid=1
), prev_tkts AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY "location"
            ORDER BY new_ScanCreatedDate DESC
        ) AS loc_rn
    FROM unq_tkts
    WHERE tkt_rn=1
)
SELECT
    prev_tkts."location" AS "machine",
    prev_tkts.new_Ticket AS "ticket",
    prev_tkts.new_ScanCreatedDate AS "start_ts",
    prev_end.new_ScanCreatedDate AS "end_ts",
    sxref.new_Style AS "style",
    sxref.new_RackWt AS "rack_wt",
    CASE
        WHEN txref.new_Dracks IS NULL
        THEN txref.new_Racks
        ELSE txref.new_Dracks
    END AS "racks"
FROM prev_tkts
    LEFT JOIN new_ticketsBase AS txref ON prev_tkts.new_Ticket=txref.new_Ticket
    LEFT JOIN new_styleBase AS sxref ON sxref.new_styleId=txref.new_StyleId
    LEFT JOIN prev_tkts AS prev_end ON
        prev_tkts."location" = prev_end."location" AND
        prev_tkts.loc_rn = prev_end.loc_rn+1
WHERE
    prev_tkts.new_ScanCreatedDate>DATETIMEFROMPARTS({}, 0)
ORDER BY prev_tkts."location", prev_tkts.new_ScanCreatedDate
""", 1, DATETIMEFROMPARTS_FMT)

# The set currently threaded on each (machine, bar): the latest threading
# not yet taped out.
THREADED = SQLQuery("""\
WITH threaded AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY new_Location, new_Bars
            ORDER BY new_ThreadingDateandTime DESC
        ) AS rn
    FROM new_sethistoryBase
    WHERE
        new_ThreadingDateandTime IS NOT NULL AND
        new_TapeOutDateandTime IS NULL AND
        new_SetNumber NOT LIKE '%_del'
), yarnt AS (
    SELECT
        new_yarnId AS "yarnId",
        new_merge AS "merge",
        AccountBase."Name" AS "vendor",
        new_Denier AS "denier"
    FROM new_yarnBase
        LEFT JOIN AccountBase ON new_yarnBase.new_Producer=AccountBase.AccountId
)
SELECT
    threaded.new_Location AS "machine",
    threaded.new_Bars AS "bar",
    threaded.new_CurrentWeight AS "rem_lbs",
    threaded.new_Beams AS "nbeams",
    threaded.new_SetNumber AS "set_no",
    yarnt."merge" AS "merge",
    yarnt.vendor AS "vendor",
    yarnt.denier AS "denier"
FROM threaded
    LEFT JOIN yarnt ON yarnt.yarnId=threaded.new_MergeId
WHERE threaded.rn=1
ORDER BY threaded.new_Location, threaded.new_Bars
""", 0, None)

# The last piece ticket scanned on each machine, with its style and the
# four bars' sets / merges / percentages (the source's REPEAT 1..4 block,
# expanded).
LAST_TKT = SQLQuery("""\
WITH last_tkt AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY SUBSTRING(new_Ticket, 1, 3) ORDER BY new_ScanCreatedDate DESC
        ) AS rn
    FROM new_scanneditemsBase
    WHERE new_TicketType='PIECE' AND new_Isvalid=1
), merges AS (
    SELECT
        new_yarnId AS "yarnId",
        new_merge AS "merge",
        AccountBase."Name" AS "vendor",
        new_Denier AS "denier"
    FROM new_yarnBase
        LEFT JOIN AccountBase ON new_yarnBase.new_Producer=AccountBase.AccountId
)
SELECT
    SUBSTRING(last_tkt.new_Ticket, 1, 3) AS "machine",
    last_tkt.new_Ticket AS "ticket",
    last_tkt.new_ScanCreatedDate AS "scan_ts",
    sxref.new_Style AS "style",
    sxref.new_Beams AS "nbeams",
    shist1.new_SetNumber AS "bar1_set_no",
    y1."merge" AS "bar1_merge",
    y1."vendor" AS "bar1_vendor",
    y1.denier AS "bar1_denier",
    sxref.new_b1pct AS "bar1_pct",
    shist2.new_SetNumber AS "bar2_set_no",
    y2."merge" AS "bar2_merge",
    y2."vendor" AS "bar2_vendor",
    y2.denier AS "bar2_denier",
    sxref.new_b2pct AS "bar2_pct",
    shist3.new_SetNumber AS "bar3_set_no",
    y3."merge" AS "bar3_merge",
    y3."vendor" AS "bar3_vendor",
    y3.denier AS "bar3_denier",
    sxref.new_b3pct AS "bar3_pct",
    shist4.new_SetNumber AS "bar4_set_no",
    y4."merge" AS "bar4_merge",
    y4."vendor" AS "bar4_vendor",
    y4.denier AS "bar4_denier",
    sxref.new_b4pct AS "bar4_pct",
    sxref.new_RackWt AS "rack_wt",
    txref.new_Racks AS "racks"
FROM last_tkt
    LEFT JOIN new_ticketsBase AS txref ON txref.new_Ticket=last_tkt.new_Ticket
    LEFT JOIN new_styleBase AS sxref ON sxref.new_styleId=txref.new_StyleId
    LEFT JOIN new_sethistoryBase AS shist1 ON shist1.new_sethistoryId=txref.new_B1SetLookupId
    LEFT JOIN merges AS y1 ON y1.yarnId=sxref.new_b1mergeId
    LEFT JOIN new_sethistoryBase AS shist2 ON shist2.new_sethistoryId=txref.new_B2SetLookupId
    LEFT JOIN merges AS y2 ON y2.yarnId=sxref.new_b2mergeId
    LEFT JOIN new_sethistoryBase AS shist3 ON shist3.new_sethistoryId=txref.new_B3SetLookupId
    LEFT JOIN merges AS y3 ON y3.yarnId=sxref.new_b3mergeId
    LEFT JOIN new_sethistoryBase AS shist4 ON shist4.new_sethistoryId=txref.new_B4SetLookupId
    LEFT JOIN merges AS y4 ON y4.yarnId=sxref.new_b4mergeId
WHERE rn=1
ORDER BY last_tkt.new_Ticket
""", 0, None)

# Every ticket in the system whose doff started on or after a date, from the
# tickets table itself rather than the scans — so it includes rolls on dummy
# tickets, which cannot be scanned and are created after the fact (once the
# shipping warehouse processes them) so the rolls can ship. One date
# argument.
TKTS_SINCE = SQLQuery("""\
SELECT
    tkt.new_Location AS "machine",
    tkt.new_Ticket AS "ticket",
    tkt.new_DSDate AS "start_ts",
    tkt.new_DDDate AS "end_ts",
    stl.new_Style AS "style",
    stl.new_RackWt AS "rack_wt",
    tkt.new_DRacks AS "racks"
FROM new_ticketsBase AS tkt
    LEFT JOIN new_styleBase AS stl ON stl.new_styleId=tkt.new_StyleId
WHERE tkt.new_DSDate IS NOT NULL AND
    tkt.new_DSDate>=DATETIMEFROMPARTS({}, 0)
""", 1, DATETIMEFROMPARTS_FMT)

# Every threading ticket scanned since a date. A threading ticket's text
# encodes the machine, the item and the set and bars it was threaded on
# (`<machine>-<...><item>##<set_no>B<bars>`), which the CTEs split apart;
# the scan carries the racks wound on the machine's current roll at the
# time, and the set's record supplies its initial weight, merge and vendor.
# One date argument.
THREADINGS_SINCE = SQLQuery("""\
WITH split_idx AS (
    SELECT
        *,
        CHARINDEX('##', new_Ticket, 6) AS "hash_idx"
    FROM new_scanneditemsBase
    WHERE new_TicketType='THREADING' AND
        new_Isvalid=1 AND
        new_Ticket<>''
), split1 AS (
    SELECT
        LEFT(new_Ticket, 3) AS "machine",
        SUBSTRING(new_Ticket, 6, "hash_idx" - 6) AS "item",
        RIGHT(new_Ticket, LEN(new_Ticket) - "hash_idx" - 1) AS "rem",
        *
    FROM split_idx
), split1_idx AS (
    SELECT
        CHARINDEX('B', REVERSE("rem"), 1) AS "b_idx",
        *
    FROM split1
), split2 AS (
    SELECT
        "machine",
        "item",
        LEFT("rem", LEN("rem") - "b_idx") AS "set_no",
        RIGHT("rem", "b_idx" - 1) AS "bars",
        new_RacksAtRO AS "racks",
        new_ScanCreatedDate AS "start_ts"
    FROM split1_idx
)
SELECT
    split2."machine" AS "machine",
    split2."item" AS "item",
    split2."set_no" AS "set_no",
    split2."bars" AS "bars",
    split2."racks" AS "racks",
    split2."start_ts" AS "start_ts",
    sh.new_Weight AS "init_lbs",
    y.new_merge AS "merge",
    ac."Name" AS "vendor"
FROM split2
    LEFT JOIN new_sethistoryBase AS sh ON sh.new_name=split2."set_no"
    LEFT JOIN new_yarnBase AS y ON y.new_yarnId=sh.new_MergeId
    LEFT JOIN AccountBase AS ac ON ac.AccountId=y.new_Producer
WHERE start_ts>=DATETIMEFROMPARTS({}, 0)
""", 1, DATETIMEFROMPARTS_FMT)

# Every ticket (any type) scanned since a date, its latest scan. One date
# argument.
SCANNED = SQLQuery("""\
WITH unq_tkts AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY new_Ticket
            ORDER BY new_ScanCreatedDate DESC
        ) AS tkt_rn
    FROM new_scanneditemsBase
    WHERE new_Isvalid=1
)
SELECT
    new_Ticket AS "ticket",
    new_TicketType AS "kind",
    new_ScanCreatedDate AS "scan_ts"
FROM unq_tkts
WHERE tkt_rn=1 AND new_ScanCreatedDate>=DATETIMEFROMPARTS({}, 0)
""", 1, DATETIMEFROMPARTS_FMT)

# Every knittable style variant with its width / rack weight / gauge and the
# four bars' ends, merge, percentage, run length, stitch and thread pattern.
ALL_VARIANTS = SQLQuery("""\
WITH merges AS (
    SELECT
        new_yarnId AS "yarnId",
        new_merge AS "merge",
        AccountBase."Name" AS "vendor",
        new_Denier AS "denier",
        new_Luster AS "luster",
        new_yarndescriptionBase.new_yarntype AS "desc"
    FROM new_yarnBase
        LEFT JOIN new_yarndescriptionBase ON new_yarndescriptionId=new_YarnDesc
        LEFT JOIN AccountBase ON new_yarnBase.new_Producer=AccountBase.AccountId )
SELECT
    s.new_Style AS "variant",
    s.new_ktgwidth AS "width",
    s.new_RackWt AS "rack_wt",
    s.new_Gauge AS "gauge",
    s.new_Beams AS "beams",
    s.new_b1ends_crct1 AS "bar1_ends",
    m1."merge" AS "bar1_merge", m1."vendor" AS "bar1_vendor", m1.denier AS "bar1_denier",
    m1.luster AS "bar1_luster", m1."desc" AS "bar1_desc",
    s.new_b2ends_crct1 AS "bar2_ends",
    m2."merge" AS "bar2_merge", m2."vendor" AS "bar2_vendor", m2.denier AS "bar2_denier",
    m2.luster AS "bar2_luster", m2."desc" AS "bar2_desc",
    s.new_b3ends_crct1 AS "bar3_ends",
    m3."merge" AS "bar3_merge", m3."vendor" AS "bar3_vendor", m3.denier AS "bar3_denier",
    m3.luster AS "bar3_luster", m3."desc" AS "bar3_desc",
    s.new_b4ends_crct1 AS "bar4_ends",
    m4."merge" AS "bar4_merge", m4."vendor" AS "bar4_vendor", m4.denier AS "bar4_denier",
    m4.luster AS "bar4_luster", m4."desc" AS "bar4_desc",
    s.new_b1pct AS "bar1_pct", s.new_b1run AS "bar1_rl",
    st1.new_name AS "bar1_stitch", thr1.new_name AS "bar1_thread",
    s.new_b2pct AS "bar2_pct", s.new_b2run AS "bar2_rl",
    st2.new_name AS "bar2_stitch", thr2.new_name AS "bar2_thread",
    s.new_b3pct AS "bar3_pct", s.new_b3run AS "bar3_rl",
    st3.new_name AS "bar3_stitch", thr3.new_name AS "bar3_thread",
    s.new_b4pct AS "bar4_pct", s.new_b4run AS "bar4_rl",
    st4.new_name AS "bar4_stitch", thr4.new_name AS "bar4_thread"
FROM new_styleBase AS s
    LEFT JOIN merges AS m1 ON m1.yarnId=s.new_b1mergeId
    LEFT JOIN merges AS m2 ON m2.yarnId=s.new_b2mergeId
    LEFT JOIN merges AS m3 ON m3.yarnId=s.new_b3mergeId
    LEFT JOIN merges AS m4 ON m4.yarnId=s.new_b4mergeId
    LEFT JOIN new_stitchBase AS st1 ON s.new_b1stitchId=st1.new_stitchId
    LEFT JOIN new_stitchBase AS st2 ON s.new_b2stitchId=st2.new_stitchId
    LEFT JOIN new_stitchBase AS st3 ON s.new_b3stitchId=st3.new_stitchId
    LEFT JOIN new_stitchBase AS st4 ON s.new_b4stitchId=st4.new_stitchId
    LEFT JOIN new_threadpatternBase AS thr1 ON s.new_b1threadId=thr1.new_threadpatternId
    LEFT JOIN new_threadpatternBase AS thr2 ON s.new_b2threadId=thr2.new_threadpatternId
    LEFT JOIN new_threadpatternBase AS thr3 ON s.new_b3threadId=thr3.new_threadpatternId
    LEFT JOIN new_threadpatternBase AS thr4 ON s.new_b4threadId=thr4.new_threadpatternId
WHERE
    s.new_ktgwidth>0 AND s.new_RackWt>0 AND s.new_Gauge IS NOT NULL
""", 0, None)

__all__ = [
    'QueryArgumentError', 'SQLQuery', 'render_date', 'DATETIMEFROMPARTS_FMT',
    'ACTIVE', 'ASSIGNED', 'DOFFED', 'THREADED', 'LAST_TKT', 'TKTS_SINCE',
    'THREADINGS_SINCE', 'SCANNED', 'ALL_VARIANTS',
]
