#!/usr/bin/env python

"""Greige *variants* -> the planner's master styles and beam-set vocabulary.

A short-term mapping tool (deliberately outside the design-first pipeline): it
lets actual beam-set inventory be matched to the planner's items. In inventory a
yarn "item" is a specific **merge**, so each master greige style is split into
many *variants* — one per combination of merges on its bars. This module reads
the plant's variant table (a TSV: one row per variant, per bar its construction
and the yarn on it in `bar{i}_*`) and the **master list** (`greige-master-
styles.json`: each master style with its *representative variant*), and builds
three maps plus a report of everything it could not place:

- **merge -> beam-set descriptions** — a normalised yarn (`Merge`) to the
  planner beam-set strings it appears in (which sets a merge can feed);
- **(top, btm) beam-set combination -> variant names**;
- **variant -> master style**.

For production use the same information is written per master style to a JSON
file (`write_variant_map` / `read_variant_map`): each master lists its
*recipes* — one merge combination at one construction — with every variant name
the plant has for that recipe (comma-separated; the database can't say which
one they actually use), and the file carries a merge-code -> yarn description
table so an inventory beam set can be given its planner beam-set string. The
reverse translation, variant name -> master, is a second flat JSON file
(`write_variant_masters` / `read_variant_masters`).

**A master is defined by its representative variant.** The master list names
one variant per master; that variant's row supplies the master's construction
— per bar the ends, split lease, **runner length** and yarn — and its planner
beam-set labels. Another row is a variant of that master when it matches the
representative on every bar: the same ends and split lease, the same beam
count, the same **yarn** as the planner tells yarns apart — denier class,
colour, cationic or recycled (Repreve) finish, textured or flat; a black
yarn where the representative's is white, or recycled where it is plain, is
a different product — and the same runner length — exactly, or failing an
exact match anywhere, within
`RL_TOLERANCE` (2) on every bar, the row then going to the **nearest** such
master by summed runner-length distance (older constructions of a style share
its number but sit further off, and are no longer used; two masters equally
close is ambiguous and the row is excluded). Bars are paired with the
representative's by construction and runner length, so no bar-position or
yarn heuristic is needed to tell top from bottom (bar 1 is the bottom bar in
the representative).

Plant conventions applied (see `VariantMap.report()` for what actually occurred):

- Our styles are 2-bar in the planner but appear as **3-bar rows**: one set runs
  **split lease** (`S/L`) across two half-bars. The split pair is told by its
  **threading** (`bar{i}_thread`): the two bars threaded one in, one out
  (`1 IN, 1 OUT` / `1 OUT, 1 IN`, either order on either bar) are merged into
  one set (ends / pct summed) and marked `S/L`; they must carry the same yarn
  as the planner describes it, whether or not their merge codes agree. Every
  other bar (`SOLID`, or any other threading) is a set of its own — two
  solid bars of the **same** merge are two distinct sets that happen to be
  beamed from one merge. A row still needs exactly two sets, and a row using
  **more than two distinct merges** is excluded.
- Denier classes: 70/75 -> **75D**, 40/45 -> **40D** (others as-is: 50D, 80D).
- Colour: a luster naming a colour (`BK`/`BLK` -> `BLK`, `GY`/`GRY` -> `GRY`,
  the recycled greener black `RGB` -> `GBK`) else white; a `BLK ID` /
  `BK SOL DYE` yarn type is black too. `GBK` is its own colour — a style on
  it does not run on regular black.
- Yarn type: everything we plan is polyester, so `POLY` is implicit and a
  **non-polyester** merge is unusable; `TEXT`/`TX` marks a textured (`TX`) set;
  `CAT` -> `CAT` and `REPREVE` / `RECYCLE*` -> `REP` are the only modifiers
  kept — every other one (`NP`, `WD`, `LR`, `BIO-MEG`, …) is dropped, those
  yarns being interchangeable with the plain one for our purposes.
- Variants are found by the 4-digit style number (left-anchored, so `SR7368`
  and `AUSR7368` count but `97980` does not) and placed under whichever
  same-numbered master's representative they match; a row matching none is
  excluded, the report naming the nearest master and what differed.

The optional `styles` (the greige-styles JSON records) are used only to
cross-check the representative's beam-set labels against the styles file.
"""

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    'Merge', 'RawYarn', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'denier_class', 'read_greige_variants', 'load_master_styles', 'load_master_list',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants',
    'Recipe', 'BarRecipe', 'MergeInfo', 'MasterSpec', 'MasterSetSpec',
    'write_variant_masters', 'read_variant_masters', 'RL_TOLERANCE',
]

_TEX_TOKENS = {'TEXT', 'TX', 'TEX'}
_REP_TOKENS = {'REPREVE', 'RECYCLE', 'RECYCLED'}
_KEEP_FINISH = {'CAT', 'REP'}
_BLACK_LUSTER = ('BLK', 'BK')
_GREY_LUSTER = ('GRY', 'GRAY', 'GY')
# "Recycled greener black" — the plant's RGB luster. Its own colour, `GBK`:
# a style knit on it is not interchangeable with one on regular black.
_GREENER_BLACK_LUSTER = ('RGB',)
_NUMBER = re.compile(r'\d{4}')
_NULL = (None, '', 'NULL', 'None', 'none', 'null')
_RL_EPS = 1e-6
# A row that matches no representative exactly still belongs to the nearest
# master whose construction it shares when every bar's runlength is within
# this much of the representative's.
RL_TOLERANCE = 2.0


# ----- yarn normalisation --------------------------------------------------

def denier_class(denier: Any) -> int:
    """Fold the plant's deniers into the planner's classes: 70/75 -> 75,
    40/45 -> 40, anything else unchanged."""
    d = int(float(denier))
    if d in (70, 75):
        return 75
    if d in (40, 45):
        return 40
    return d


def _tokens(ytype: str) -> list[str]:
    return [t for t in re.split(r'[\s/]+', (ytype or '').upper().strip()) if t]


def is_polyester(ytype: str) -> bool:
    """`POLY…` (incl. `POLYESTER`, `TEXT POLY`) or the trailing `P` abbreviation
    (`REPREVE TX P`, `RECYCLED P`). Nylon, Lycra, etc. are not usable here."""
    return any(t == 'P' or t.startswith('POLY') for t in _tokens(ytype))


def is_textured(ytype: str) -> bool:
    return bool(set(_tokens(ytype)) & _TEX_TOKENS)


def is_recycled(ytype: str) -> bool:
    """Repreve / recycled polyester."""
    return bool(set(_tokens(ytype)) & _REP_TOKENS)


def _finish_and_black(ytype: str) -> tuple[tuple[str, ...], bool]:
    """The yarn-type modifiers that survive normalisation — only `CAT` and
    `REP` (`REPREVE`/`RECYCLE*`); everything else is dropped — and whether the
    type itself says black (`BLK ID …`, `BK SOL DYE …`)."""
    toks = _tokens(ytype)
    out: list[str] = []
    black = False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _REP_TOKENS:
            if 'REP' not in out:
                out.append('REP')
            i += 1
        elif t == 'CAT':
            if 'CAT' not in out:
                out.append('CAT')
            i += 1
        elif t == 'BLK' and toks[i + 1:i + 2] == ['ID']:
            black = True
            i += 2
        elif t == 'BK' and toks[i + 1:i + 3] == ['SOL', 'DYE']:
            black = True
            i += 3
        else:                     # POLY / texture words / other modifiers
            i += 1
    return tuple(out), black


def color_of(luster: str, black_from_type: bool = False) -> str:
    """`GBK` for the recycled greener-black luster (`RGB`); `BLK` for a black
    luster (`SDBK`, `BLK`, …) or a black yarn type; `GRY` for a grey luster;
    otherwise `WHT` — a luster that names no colour (`SD`, `DULL`, `BRT`,
    `CL`, `SDIM`, …) is white."""
    lus = (luster or '').upper()
    if any(k in lus for k in _GREENER_BLACK_LUSTER):
        return 'GBK'
    if black_from_type or any(k in lus for k in _BLACK_LUSTER):
        return 'BLK'
    if any(k in lus for k in _GREY_LUSTER):
        return 'GRY'
    return 'WHT'


@dataclass(frozen=True)
class Merge:
    """A yarn as the planner distinguishes it: denier class, colour, surviving
    finish modifiers, textured or flat. Two inventory merges that normalise to
    the same `Merge` are interchangeable for our styles."""
    denier: int
    color: str
    finish: tuple[str, ...]
    textured: bool

    @property
    def recycled(self) -> bool:
        return 'REP' in self.finish

    @property
    def yarn_desc(self) -> str:
        """The yarn part of a beam-set string: `40D WHT`, `40D W CAT`,
        `75D W REP TX`, `45D BLK`, … (white abbreviates to `W` before a finish,
        matching the existing `W CAT` / `W REP` strings)."""
        fin = ' '.join(self.finish)
        if self.color == 'WHT':
            col = f'W {fin}' if fin else 'WHT'
        else:
            col = f'{self.color} {fin}' if fin else self.color
        return f'{self.denier}D {col}' + (' TX' if self.textured else '')


def normalize_merge(denier: Any, luster: str, ytype: str) -> 'Merge | None':
    """The `Merge` for an inventory yarn's raw `(denier, luster, ytype)`, or
    `None` when the yarn is not polyester (unusable for these styles). This is
    the entry point for matching real beam-set inventory."""
    if not is_polyester(ytype):
        return None
    finish, black = _finish_and_black(ytype)
    return Merge(denier_class(denier), color_of(luster, black), finish,
                 is_textured(ytype))


@dataclass(frozen=True)
class RawYarn:
    """A yarn as the plant identifies it — the merge code is the inventory
    "item"; the rest describes it."""
    merge: str | None
    vendor: str | None
    denier: str
    luster: str
    ytype: str


def _beamset_desc(yarn_desc: str, ends: int, n_beams: int, split: bool) -> str:
    return f'{yarn_desc} {ends}X{n_beams}' + (' S/L' if split else '')


@dataclass(frozen=True)
class BeamSetSpec:
    """A merge beamed at a construction, split-lease or not — one planner beam
    set. `desc` is the planner's beam-set string; `yarn` keeps the plant's
    merge identity so the exact variant can be reported."""
    merge: Merge
    ends: int
    n_beams: int
    split: bool
    yarn: 'RawYarn | None' = None

    @property
    def desc(self) -> str:
        return _beamset_desc(self.merge.yarn_desc, self.ends, self.n_beams, self.split)


@dataclass(frozen=True)
class Variant:
    """One variant row, resolved. `issues` lists anything that makes it
    unusable (non-polyester yarn, no master matching its construction and
    yarns, …) or merely noteworthy (a runlength matched within tolerance)."""
    name: str
    number: str
    master: str | None
    top: 'BeamSetSpec | None'
    btm: 'BeamSetSpec | None'
    rack_wt: float | None
    split_bars: tuple[int, ...]     # TSV bar numbers carrying the split-lease set
    split_is_top: bool | None       # whether the split set landed on the master's TOP
    issues: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return not any(i.startswith('!') for i in self.issues)


# ----- masters -------------------------------------------------------------

@dataclass(frozen=True)
class _RepSet:
    """One of the representative variant's two sets: what a variant's set must
    match exactly (runlength, construction, recycled) and the yarn label."""
    ends: int
    n_beams: int
    split: bool
    rl: float
    merge: Merge
    bars: tuple[int, ...]

    @property
    def beamset(self) -> str:
        return _beamset_desc(self.merge.yarn_desc, self.ends, self.n_beams, self.split)


@dataclass(frozen=True)
class _Master:
    id: str
    number: str
    rep: str             # the representative variant's name
    top: _RepSet
    btm: _RepSet
    width: int
    gauge: int
    stitches: tuple[str, ...]    # bar1..bar4 stitch patterns, in bar order
    pattern_key: tuple           # see `_pattern_key`
    top_pct: float
    btm_pct: float


def _norm_stitch(s: str) -> str:
    return re.sub(r'\s+', '', s or '')


def _pattern_key(sets: list[dict], row: Mapping[str, str]) -> tuple:
    """The pattern family key: the stitch patterns knit by each **set**, not
    by bar position — a style that swaps which bar carries the 75D set and
    which the split 40D set is the same pattern. The single-bar set's stitch
    and the split set's two half-bar stitches **in bar order** (which
    half-bar knits which matters); whitespace in the plant's strings is
    ignored. When the two sets can't be told apart that way (both split or
    neither) the sets' stitch tuples are compared unordered."""
    per_set = []
    for s in sets:
        stitches = tuple(_norm_stitch(_str(row, f'bar{i}_stitch') or '')
                         for i in sorted(s['bars']))
        per_set.append((s['split'], stitches))
    singles = [st for split, st in per_set if not split]
    splits = [st for split, st in per_set if split]
    if len(singles) == 1 and len(splits) == 1:
        return ('single', singles[0], 'split', splits[0])
    return ('sets', tuple(sorted(st for _, st in per_set)))


@dataclass(frozen=True)
class MasterSetSpec:
    """One of a master's two beam sets as its representative defines it."""
    beamset: str          # planner label, e.g. `40D WHT 1172X4 S/L`
    ends: int
    n_beams: int
    split: bool
    runlen: float
    pct: float            # share of the fabric weight, %
    denier: int           # planner denier class
    textured: bool
    yarn_desc: str
    bars: tuple[int, ...]


@dataclass(frozen=True)
class MasterSpec:
    """A master style as its representative variant defines it — what the
    greige-styles file needs beyond the rates: construction, weight split,
    stitch patterns (the family), width and gauge."""
    id: str
    representative: str
    number: str
    width: int
    gauge: int
    stitches: tuple[str, ...]    # bar1..bar4 stitch patterns, in bar order
    pattern_key: tuple           # the pattern family: stitches per set, position-free
    top: MasterSetSpec
    btm: MasterSetSpec

    @property
    def wide(self) -> bool:
        """Over 200 inches: only wide machines, at their wide rpm."""
        return self.width > 200

    @property
    def heavy_on_top(self) -> bool:
        """The 75-denier (textured) set on the top bar: only tall machines."""
        return self.top.denier == 75


def load_master_styles(path: 'str | Path') -> list[dict]:
    """The greige-styles JSON records (used only to cross-check labels)."""
    with open(path) as fh:
        return json.load(fh)


def load_master_list(path: 'str | Path') -> list[dict]:
    """The master list: `[{"master": <id>, "variant": <representative>, …}, …]`
    (other keys, such as the `safety` target the styles generator reads, are
    passed through)."""
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, list) or not all(
            isinstance(d, dict) and 'master' in d and 'variant' in d for d in data):
        raise ValueError(f'{path}: expected a list of {{master, variant}} objects')
    return data


# ----- rows -> sets ----------------------------------------------------------

def _num(s: Any) -> 'float | None':
    if s in _NULL:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _str(row: Mapping[str, str], *names: str) -> str | None:
    """The first of `names` the row has a value for (old and new column names)."""
    for n in names:
        v = row.get(n)
        if v not in _NULL:
            return str(v)
    return None


def _bars(row: Mapping[str, str]) -> list[dict]:
    out = []
    for i in (1, 2, 3, 4):
        ends = _num(row.get(f'bar{i}_ends'))
        if not ends or ends <= 0:
            continue
        out.append({
            'i': i, 'ends': int(ends), 'pct': _num(row.get(f'bar{i}_pct')) or 0.0,
            'rl': _num(row.get(f'bar{i}_rl')),
            'merge': _str(row, f'bar{i}_merge', f'b{i}_merge'),
            'vendor': _str(row, f'bar{i}_vendor'),
            'den': _str(row, f'bar{i}_denier', f'b{i}_denier') or '',
            'lus': _str(row, f'bar{i}_luster', f'b{i}_luster') or '',
            'yt': _str(row, f'bar{i}_desc', f'b{i}_ytype') or '',
            'thread': _str(row, f'bar{i}_thread', f'b{i}_thread') or '',
        })
    return out


# The split-lease threading: one end in, one out — `1 IN, 1 OUT` or
# `1 OUT, 1 IN`, spacing and the comma optional.
_SPLIT_THREAD = re.compile(r'^1(IN|OUT),?1(IN|OUT)$')


def _is_split_thread(thread: str) -> bool:
    m = _SPLIT_THREAD.match(re.sub(r'\s+', '', (thread or '').upper()))
    return bool(m) and m.group(1) != m.group(2)


def _sets(bars: list[dict]) -> tuple[list[dict], list[str]]:
    """The row's beam sets from its bars, by **threading**: the bars threaded
    one in, one out are the split-lease pair and collapse into one `S/L` set
    (ends / pct summed; they must carry the same planner yarn, merge codes
    aside); every other bar is a set of its own, even one sharing another
    bar's merge. Returns `(sets, problems)` — the problems (`!`-prefixed, the
    row is unusable) being a split threading on other than two bars, a split
    pair of two different yarns, or more than two distinct merge codes."""
    problems: list[str] = []
    split = [b for b in bars if _is_split_thread(b['thread'])]
    solo = [b for b in bars if not _is_split_thread(b['thread'])]
    groups: list[list[dict]] = [[b] for b in solo]
    if len(split) == 2:
        yarns = [normalize_merge(b['den'], b['lus'], b['yt']) for b in split]
        if all(yarns) and yarns[0] != yarns[1]:
            problems.append(f'!split-lease bars carry different yarns: '
                            f'{yarns[0].yarn_desc} vs {yarns[1].yarn_desc}')
        groups.append(split)
    elif split:
        problems.append(f'!split-lease threading on {len(split)} bar(s) (need 2)')
        groups.extend([b] for b in split)
    groups.sort(key=lambda bs: bs[0]['i'])
    merges = {b['merge'] for b in bars if b['merge']}
    if len(merges) > 2:
        problems.append(f'!{len(merges)} distinct merge(s) (at most 2)')
    sets = []
    for bs in groups:
        b0 = bs[0]
        sets.append({
            'den': b0['den'], 'lus': b0['lus'], 'yt': b0['yt'],
            'yarn': RawYarn(b0['merge'], b0['vendor'], b0['den'], b0['lus'], b0['yt']),
            'bars': tuple(b['i'] for b in bs),
            'ends': sum(b['ends'] for b in bs),
            'pct': sum(b['pct'] for b in bs),
            'rl': bs[0]['rl'],
            'split': len(bs) > 1,
        })
    return sets, problems


def _n_beams(row: Mapping[str, str]) -> int:
    return int(_num(_str(row, 'beams', 'n_beams')) or 0)


def _build_master(mid: str, rep: str, row: Mapping[str, str]) -> _Master:
    """The master's definition from its representative variant's row: two
    polyester sets (by threading — see `_sets`), the one holding bar 1 being
    the bottom."""
    sets, problems = _sets(_bars(row))
    if problems:
        raise ValueError(f'master {mid!r}: representative {rep!r} '
                         + '; '.join(p[1:] for p in problems))
    if len(sets) != 2:
        raise ValueError(
            f'master {mid!r}: representative {rep!r} has {len(sets)} set(s) by '
            f'threading, need 2')
    n_beams = _n_beams(row)
    reps = []
    for s in sets:
        mg = normalize_merge(s['den'], s['lus'], s['yt'])
        if mg is None:
            raise ValueError(f'master {mid!r}: representative {rep!r} uses '
                             f'non-polyester yarn {s["yt"]!r}')
        if s['rl'] is None:
            raise ValueError(f'master {mid!r}: representative {rep!r} has no '
                             f'runlength on bars {s["bars"]}')
        reps.append(_RepSet(s['ends'], n_beams, s['split'], s['rl'], mg, s['bars']))
    btm = next(r for r in reps if 1 in r.bars)
    top = next(r for r in reps if r is not btm)
    num = _NUMBER.search(mid)
    if not num:
        raise ValueError(f'master {mid!r}: no 4-digit style number')
    stitches = tuple(s for s in (_str(row, f'bar{i}_stitch') for i in (1, 2, 3, 4)) if s)
    pct_of = {s['bars']: s['pct'] for s in sets}
    return _Master(mid, num.group(0), rep, top, btm,
                   int(_num(row.get('width')) or 0), int(_num(row.get('gauge')) or 0),
                   stitches, _pattern_key(sets, row), pct_of[top.bars], pct_of[btm.bars])


def _master_spec(m: _Master) -> MasterSpec:
    def spec(r: _RepSet, pct: float) -> MasterSetSpec:
        return MasterSetSpec(r.beamset, r.ends, r.n_beams, r.split, r.rl, pct,
                             r.merge.denier, r.merge.textured, r.merge.yarn_desc, r.bars)
    return MasterSpec(m.id, m.rep, m.number, m.width, m.gauge, m.stitches,
                      m.pattern_key, spec(m.top, m.top_pct), spec(m.btm, m.btm_pct))


# ----- matching --------------------------------------------------------------

def _differences(s: dict, mg: Merge, r: _RepSet, n_beams: int, bar: str) -> list[str]:
    """What keeps variant set `s` (normalised `mg`) from being the
    representative's `r` on `bar`, other than runlength: empty when the
    construction, beam count and recycled status all match."""
    out = []
    if s['ends'] != r.ends or s['split'] != r.split:
        out.append(f'{bar} construction {s["ends"]}{" S/L" if s["split"] else ""} '
                   f'vs {r.ends}{" S/L" if r.split else ""}')
    if n_beams != r.n_beams:
        out.append(f'{n_beams} beams vs {r.n_beams}')
    if mg != r.merge:
        # The yarn as the planner tells yarns apart: denier class, colour,
        # cationic / recycled finish, textured or flat — all of it.
        out.append(f'{bar} yarn {mg.yarn_desc} vs {r.merge.yarn_desc}')
    return out


@dataclass(frozen=True)
class _Fit:
    """How a variant's two sets fit a master's representative, for the best
    pairing onto (top, btm): the non-runlength differences, and the
    runlength gap per bar (`rl_gaps`, top then btm; None when a set has no
    runlength)."""
    order: tuple[int, int]
    diffs: tuple[str, ...]
    rl_gaps: tuple[float | None, float | None]

    @property
    def exact(self) -> bool:
        return not self.diffs and all(g is not None and g <= _RL_EPS for g in self.rl_gaps)

    def within(self, tol: float) -> bool:
        """Same construction, every bar's runlength within `tol`."""
        return not self.diffs and all(g is not None and g <= tol + _RL_EPS for g in self.rl_gaps)

    @property
    def rl_distance(self) -> float:
        return sum(g for g in self.rl_gaps if g is not None)

    def rl_text(self, m: '_Master', sets: list[dict]) -> str:
        parts = []
        for i, (bar, r) in enumerate((('top', m.top), ('btm', m.btm))):
            s = sets[self.order[i]]
            if self.rl_gaps[i] is None or self.rl_gaps[i] > _RL_EPS:
                parts.append(f'{bar} runlength {s["rl"]} vs {r.rl}')
        return '; '.join(parts)


def _match(sets: list[dict], merges: list[Merge], n_beams: int, m: _Master) -> _Fit:
    """The pairing of the variant's two sets onto `m`'s (top, btm) that fits
    best: fewest non-runlength differences, then the smallest runlength
    distance, then the pairing whose yarns read like the representative's."""
    best = None
    for order in ((0, 1), (1, 0)):
        diffs = tuple(_differences(sets[order[0]], merges[order[0]], m.top, n_beams, 'top')
                      + _differences(sets[order[1]], merges[order[1]], m.btm, n_beams, 'btm'))
        gaps = tuple(
            None if sets[order[i]]['rl'] is None else abs(sets[order[i]]['rl'] - r.rl)
            for i, r in enumerate((m.top, m.btm)))
        yarn_off = sum(merges[order[i]].yarn_desc != r.merge.yarn_desc
                       for i, r in enumerate((m.top, m.btm)))
        key = (len(diffs), sum(g if g is not None else float('inf') for g in gaps), yarn_off)
        if best is None or key < best[0]:
            best = (key, _Fit(order, diffs, gaps))
    return best[1]


def _resolve(row: Mapping[str, str], number: str, cands: list[_Master],
             rl_tolerance: float) -> Variant:
    name = row['variant']
    issues: list[str] = []
    bars = _bars(row)
    sets, problems = _sets(bars)
    issues.extend(problems)
    n_beams = _n_beams(row)
    split_bars = tuple(b for s in sets if s['split'] for b in s['bars'])

    merges = []
    for s in sets:
        mg = normalize_merge(s['den'], s['lus'], s['yt'])
        if mg is None:
            issues.append(f"!non-polyester yarn: {s['yt']!r}")
        merges.append(mg)
    if len(sets) != 2:
        issues.append(f'!{len(sets)} set(s) by threading (need 2)')
    if issues:
        return Variant(name, number, None, None, None, _num(row.get('rack_wt')),
                       split_bars, None, tuple(issues))

    # The master whose representative this row matches exactly; failing that
    # the nearest one within the runlength tolerance (same construction, every
    # bar within `rl_tolerance`, smallest summed distance — a tie is
    # ambiguous); failing that, excluded with the nearest master's differences.
    fits = {m.id: (m, _match(sets, merges, n_beams, m)) for m in cands}
    exact = [(m, f) for m, f in fits.values() if f.exact]
    if exact:
        if len(exact) > 1:
            issues.append('several masters match exactly: ' + ', '.join(m.id for m, _ in exact))
        master, fit = exact[0]
    else:
        close = sorted(((m, f) for m, f in fits.values() if f.within(rl_tolerance)),
                       key=lambda mf: mf[1].rl_distance)
        if not close:
            m, f = min(fits.values(), key=lambda mf: (len(mf[1].diffs), mf[1].rl_distance))
            what = '; '.join(list(f.diffs) + ([f.rl_text(m, sets)] if f.rl_text(m, sets) else []))
            issues.append(f'!no master matched exactly; nearest {m.id} ({m.rep}): {what}')
            return Variant(name, number, None, None, None, _num(row.get('rack_wt')),
                           split_bars, None, tuple(issues))
        if len(close) > 1 and abs(close[0][1].rl_distance - close[1][1].rl_distance) <= _RL_EPS:
            names = ', '.join(f'{m.id} ({f.rl_distance:g})' for m, f in close[:2])
            issues.append(f'!ambiguous: equally close within the runlength tolerance to {names}')
            return Variant(name, number, None, None, None, _num(row.get('rack_wt')),
                           split_bars, None, tuple(issues))
        master, fit = close[0]
        issues.append(f'runlength within tolerance of {master.id}: {fit.rl_text(master, sets)}')
    order = fit.order
    top_s, btm_s = sets[order[0]], sets[order[1]]
    top_m, btm_m = merges[order[0]], merges[order[1]]

    def spec(s: dict, mg: Merge) -> BeamSetSpec:
        return BeamSetSpec(mg, s['ends'], n_beams, s['split'], s['yarn'])

    top, btm = spec(top_s, top_m), spec(btm_s, btm_m)
    split_is_top = top_s['split'] if (top_s['split'] != btm_s['split']) else None
    return Variant(name, number, master.id, top, btm, _num(row.get('rack_wt')),
                   split_bars, split_is_top, tuple(issues))


# ----- the map -------------------------------------------------------------

@dataclass
class VariantMap:
    """The three maps plus everything needed to audit them."""
    variants: dict[str, Variant]
    merges_to_beamsets: dict[Merge, frozenset[str]]
    combos_to_variants: dict[tuple[str, str], tuple[str, ...]]
    variant_to_master: dict[str, str]
    excluded: dict[str, tuple[str, ...]]
    masters_without_variants: tuple[str, ...]
    master_beamsets: dict[str, tuple[str, str]]     # master id -> (top, btm) beamset
    master_reps: dict[str, str]                      # master id -> representative variant
    label_mismatches: dict[str, tuple[str, str]]     # master -> (ours, styles file's)
    masters_skipped: dict[str, str]                  # master -> why it couldn't be defined
    master_specs: dict[str, MasterSpec]              # master -> its representative's definition

    def rack_wt(self, master: str) -> float | None:
        """The master's rack weight: the average over its usable variants'
        `rack_wt` (the representative included), None when none has one."""
        wts = [v.rack_wt for v in self.variants.values()
               if v.usable and v.master == master and v.rack_wt is not None]
        return sum(wts) / len(wts) if wts else None

    def master_map(self) -> dict:
        """The per-master variant map, JSON-ready (see `write_variant_map`):

        ```
        {"merges": {"<merge code>": {"denier", "vendor", "luster", "ytype",
                                     "yarn_desc"}},
         "masters": {"<master id>": {
             "representative": "<variant>",
             "beamsets": {"top": "...", "btm": "..."},
             "recipes": [{"names": "A, B", "n_beams": 4,
                          "top": {"merge", "ends", "split", "beamset"},
                          "btm": {...}}]}}}
        ```

        A recipe is one merge combination at one construction under a master;
        every variant name sharing it is listed, comma-separated, since the
        plant uses one of them and the database doesn't say which."""
        merges: dict[str, dict] = {}
        masters: dict[str, dict] = {}
        groups: dict[tuple, list[str]] = {}
        specs: dict[tuple, tuple[str, BeamSetSpec, BeamSetSpec]] = {}
        for v in sorted(self.variants.values(), key=lambda v: v.name):
            if not v.usable:
                continue
            for bs in (v.top, v.btm):
                if bs.yarn and bs.yarn.merge:
                    merges.setdefault(bs.yarn.merge, {
                        'denier': bs.yarn.denier, 'vendor': bs.yarn.vendor,
                        'luster': bs.yarn.luster, 'ytype': bs.yarn.ytype,
                        'yarn_desc': bs.merge.yarn_desc})
            key = (v.master,
                   v.top.yarn.merge if v.top.yarn else None, v.top.ends, v.top.split,
                   v.btm.yarn.merge if v.btm.yarn else None, v.btm.ends, v.btm.split,
                   v.top.n_beams)
            groups.setdefault(key, []).append(v.name)
            specs.setdefault(key, (v.master, v.top, v.btm))
        for key, names in groups.items():
            master, top, btm = specs[key]
            m = masters.setdefault(master, {
                'representative': self.master_reps.get(master),
                'beamsets': {'top': self.master_beamsets[master][0],
                             'btm': self.master_beamsets[master][1]},
                'recipes': []})
            m['recipes'].append({
                'names': ', '.join(names), 'n_beams': top.n_beams,
                'top': {'merge': top.yarn.merge if top.yarn else None, 'ends': top.ends,
                        'split': top.split, 'beamset': top.desc},
                'btm': {'merge': btm.yarn.merge if btm.yarn else None, 'ends': btm.ends,
                        'split': btm.split, 'beamset': btm.desc},
            })
        return {'merges': dict(sorted(merges.items())),
                'masters': dict(sorted(masters.items()))}

    def to_dict(self) -> dict:
        """JSON-ready form of the three maps (+ exclusions). Merges are keyed
        by their yarn description; combos by `'<top> | <btm>'`."""
        return {
            'merge_to_beamsets': {
                m.yarn_desc: sorted(s)
                for m, s in sorted(self.merges_to_beamsets.items(),
                                   key=lambda kv: kv[0].yarn_desc)},
            'combo_to_variants': {
                f'{t} | {b}': list(vs)
                for (t, b), vs in sorted(self.combos_to_variants.items())},
            'variant_to_master': dict(sorted(self.variant_to_master.items())),
            'variant_beamsets': {
                v.name: {'top': v.top.desc, 'btm': v.btm.desc}
                for v in sorted(self.variants.values(), key=lambda v: v.name)
                if v.usable},
            'excluded': {n: list(i) for n, i in sorted(self.excluded.items())},
        }

    def report(self) -> str:
        """A human-readable audit: coverage, exclusions by reason, per-master
        representative / beam sets / combinations / yarn notes, the split-set
        bar-position check, and label cross-checks against the styles file."""
        usable = [v for v in self.variants.values() if v.usable]
        lines = [
            f'variants carrying a master number: {len(self.variants)}',
            f'  usable (mapped to a master): {len(usable)}',
            f'  excluded: {len(self.excluded)}',
        ]
        reasons: dict[str, int] = {}
        for iss in self.excluded.values():
            for i in iss:
                if i.startswith('!'):
                    r = re.sub(r"'.*'", '…', i[1:])
                    r = re.sub(r';.*', '', re.sub(r'nearest .*?\(.*?\)', 'nearest …', r))
                    reasons[r] = reasons.get(r, 0) + 1
        for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f'    - {n:4d}  {r}')
        if self.masters_without_variants:
            lines.append(f'  masters with NO usable variants: {", ".join(self.masters_without_variants)}')
        for m, why in sorted(self.masters_skipped.items()):
            lines.append(f'  master SKIPPED — {why}')
        if self.label_mismatches:
            lines.append('  beam-set labels differing from the styles file:')
            for m, (ours, theirs) in sorted(self.label_mismatches.items()):
                lines.append(f'    {m}: {ours}  (styles file: {theirs})')

        lines.append('\nper master (usable variants):')
        by_master: dict[str, list[Variant]] = {}
        for v in usable:
            by_master.setdefault(v.master, []).append(v)
        for m, vs in sorted(by_master.items()):
            combos: dict[tuple[str, str], int] = {}
            fins: dict[str, int] = {}
            near = sum('within tolerance' in ' '.join(v.issues) for v in vs)
            for v in vs:
                combos[(v.top.desc, v.btm.desc)] = combos.get((v.top.desc, v.btm.desc), 0) + 1
                for spec in (v.top, v.btm):
                    for f in spec.merge.finish:
                        fins[f] = fins.get(f, 0) + 1
            top, btm = self.master_beamsets[m]
            lines.append(f'  {m} (rep {self.master_reps.get(m)}; top={top!r} btm={btm!r}): '
                         f'{len(vs)} variants'
                         + (f'; runlength-within-tolerance={near}' if near else '')
                         + (f'; finishes={dict(sorted(fins.items()))}' if fins else ''))
            for (t, b), n in sorted(combos.items(), key=lambda kv: -kv[1]):
                lines.append(f'      {n:4d}  top={t!r:32} btm={b!r}')

        lines.append('\nexcluded as not matching any master exactly (nearest master, what differed):')
        near: dict[str, int] = {}
        for iss in self.excluded.values():
            for i in iss:
                if i.startswith('!no master matched'):
                    key = i.split('nearest ', 1)[1]
                    near[key] = near.get(key, 0) + 1
        for key, n in sorted(near.items(), key=lambda kv: -kv[1])[:60]:
            lines.append(f'  {n:4d}  {key}')

        lines.append('\nsplit-lease set: TSV bar position vs the master label it landed on '
                     '(bar 1 is the bottom bar; styles differ in which yarn is split)')
        pos: dict[tuple[str, str], int] = {}
        for v in usable:
            if v.split_is_top is None:
                continue
            key = (','.join(map(str, v.split_bars)), 'TOP' if v.split_is_top else 'BTM')
            pos[key] = pos.get(key, 0) + 1
        for (bars, label), n in sorted(pos.items()):
            lines.append(f'  split set on bars {bars:5} -> master {label}: {n}')
        return '\n'.join(lines)


def read_greige_variants(
    tsv_path: 'str | Path', masters: Iterable[Mapping[str, Any]], *,
    styles: Iterable[Mapping[str, Any]] | None = None,
    rl_tolerance: float = RL_TOLERANCE,
) -> VariantMap:
    """Build the maps from the variant TSV and the master list (`{master,
    variant}` records — see `load_master_list`). Each master is defined by its
    representative variant's row; other rows sharing its style number are its
    variants when they match that row exactly or, failing that, are the
    nearest master with every bar's runlength within `rl_tolerance` (see the
    module doc), else they are recorded as excluded. `styles` (the
    greige-styles records) only cross-checks the representatives' beam-set
    labels."""
    master_list = list(masters)
    with open(tsv_path, encoding='utf-8-sig', newline='') as fh:
        rows = {r.get('variant', ''): r for r in csv.DictReader(fh, delimiter='\t')}

    by_number: dict[str, list[_Master]] = {}
    reps: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for rec in master_list:
        mid, rep = str(rec['master']), str(rec['variant'])
        if rep not in rows:
            raise ValueError(f'master {mid!r}: representative variant {rep!r} is not in {tsv_path}')
        try:
            m = _build_master(mid, rep, rows[rep])
        except ValueError as e:
            # A master the two-set model can't represent (one merge on both
            # bars, non-polyester, no runlength): left out, reported.
            skipped[mid] = str(e)
            continue
        by_number.setdefault(m.number, []).append(m)
        reps[mid] = rep
    anchored = {n: re.compile(rf'(?<!\d){n}') for n in by_number}

    variants: dict[str, Variant] = {}
    for name, row in rows.items():
        hits = [n for n, rx in anchored.items() if rx.search(name)]
        if not hits:
            continue
        number = hits[0]
        variants[name] = _resolve(row, number, by_number[number], rl_tolerance)

    merges: dict[Merge, set[str]] = {}
    combos: dict[tuple[str, str], list[str]] = {}
    v2m: dict[str, str] = {}
    excluded: dict[str, tuple[str, ...]] = {}
    for v in variants.values():
        if not v.usable:
            excluded[v.name] = v.issues
            continue
        v2m[v.name] = v.master
        for spec in (v.top, v.btm):
            merges.setdefault(spec.merge, set()).add(spec.desc)
        combos.setdefault((v.top.desc, v.btm.desc), []).append(v.name)

    all_masters = [m for ms in by_number.values() for m in ms]
    covered = set(v2m.values())
    missing = tuple(sorted(m.id for m in all_masters if m.id not in covered))
    beamsets = {m.id: (m.top.beamset, m.btm.beamset) for m in all_masters}

    label_mismatches: dict[str, tuple[str, str]] = {}
    if styles is not None:
        for s in styles:
            if s.get('id') in beamsets:
                theirs = (s['beam_cfg']['top']['beamset'], s['beam_cfg']['btm']['beamset'])
                ours = beamsets[s['id']]
                if ours != theirs:
                    label_mismatches[s['id']] = (' | '.join(ours), ' | '.join(theirs))

    return VariantMap(
        variants=variants,
        merges_to_beamsets={k: frozenset(s) for k, s in merges.items()},
        combos_to_variants={k: tuple(sorted(vs)) for k, vs in combos.items()},
        variant_to_master=v2m,
        excluded=excluded,
        masters_without_variants=missing,
        master_beamsets=beamsets,
        master_reps=reps,
        label_mismatches=label_mismatches,
        masters_skipped=skipped,
        master_specs={m.id: _master_spec(m) for m in all_masters},
    )


# ----- the per-master map file -------------------------------------------

def write_variant_map(vm: VariantMap, path: 'str | Path') -> None:
    """Write `vm.master_map()` as JSON."""
    with open(path, 'w') as fh:
        json.dump(vm.master_map(), fh, indent=2)
        fh.write('\n')


def write_variant_masters(vm: VariantMap, path: 'str | Path') -> None:
    """The reverse translation: a flat JSON object from each usable variant
    name to its master style id."""
    with open(path, 'w') as fh:
        json.dump(dict(sorted(vm.variant_to_master.items())), fh, indent=2)
        fh.write('\n')


def read_variant_masters(path: 'str | Path') -> dict[str, str]:
    """Load a file written by `write_variant_masters`: variant name -> master."""
    with open(path) as fh:
        return json.load(fh)


@dataclass(frozen=True)
class MergeInfo:
    """One inventory merge: the plant's description and the planner's yarn."""
    merge: str
    denier: str
    vendor: str | None
    luster: str
    ytype: str
    yarn_desc: str

    def beamset(self, ends: int, n_beams: int, split: bool) -> str:
        """The planner beam-set string for this merge beamed at a construction."""
        return _beamset_desc(self.yarn_desc, ends, n_beams, split)


@dataclass(frozen=True)
class BarRecipe:
    merge: str | None
    ends: int
    split: bool
    beamset: str


@dataclass(frozen=True)
class Recipe:
    """One merge combination at one construction under a master. `names` is the
    comma-separated list of every variant name the plant has for it."""
    master: str
    names: str
    n_beams: int
    top: BarRecipe
    btm: BarRecipe

    @property
    def key(self) -> tuple[str | None, str | None]:
        return (self.top.merge, self.btm.merge)


@dataclass(frozen=True)
class MasterVariants:
    """A master's planner beamsets and its recipes, indexed by merge pair."""
    id: str
    top_beamset: str
    btm_beamset: str
    recipes: tuple[Recipe, ...]
    by_merges: dict[tuple[str | None, str | None], tuple[Recipe, ...]]
    representative: str | None = None

    def lookup(self, top_merge: str, btm_merge: str) -> tuple[Recipe, ...]:
        """Recipes using `top_merge` on the top bar and `btm_merge` on the
        bottom (several only if the same merges run at different
        constructions); empty when the plant has no such variant."""
        return self.by_merges.get((top_merge, btm_merge), ())


@dataclass(frozen=True)
class VariantMapFile:
    """The loaded map file: merge descriptions plus one `MasterVariants` per
    master style."""
    merges: dict[str, MergeInfo]
    masters: dict[str, MasterVariants]

    def beamset(self, merge: str, ends: int, n_beams: int, split: bool) -> str | None:
        """Planner beam-set string for an inventory beam set, or `None` for a
        merge the map has never seen."""
        info = self.merges.get(merge)
        return info.beamset(ends, n_beams, split) if info else None


def read_variant_map(path: 'str | Path') -> VariantMapFile:
    """Load a file written by `write_variant_map`."""
    with open(path) as fh:
        data = json.load(fh)
    merges = {}
    for code, info in data['merges'].items():
        info = dict(info)
        info.setdefault('vendor', None)
        info.pop('flmnt', None)                 # older files
        merges[code] = MergeInfo(code, **info)
    masters: dict[str, MasterVariants] = {}
    for mid, m in data['masters'].items():
        recipes = tuple(
            Recipe(mid, r['names'], int(r['n_beams']),
                   BarRecipe(r['top']['merge'], int(r['top']['ends']),
                             bool(r['top']['split']), r['top']['beamset']),
                   BarRecipe(r['btm']['merge'], int(r['btm']['ends']),
                             bool(r['btm']['split']), r['btm']['beamset']))
            for r in m['recipes'])
        by: dict[tuple[str | None, str | None], list[Recipe]] = {}
        for r in recipes:
            by.setdefault(r.key, []).append(r)
        masters[mid] = MasterVariants(
            mid, m['beamsets']['top'], m['beamsets']['btm'], recipes,
            {k: tuple(v) for k, v in by.items()}, m.get('representative'))
    return VariantMapFile(merges, masters)
