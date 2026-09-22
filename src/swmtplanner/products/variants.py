#!/usr/bin/env python

"""Greige *variants* -> the planner's master styles and beam-set vocabulary.

A short-term mapping tool (deliberately outside the design-first pipeline): it
lets actual beam-set inventory be matched to the planner's items. In inventory a
yarn "item" is a specific **merge**, so each master greige style is split into
many *variants* — one per combination of merges on its bars. This module reads
the plant's variant table (a TSV: one row per variant, per-bar construction in
`bar{i}_*`, the yarn on that bar in `b{i}_*`) and builds three maps, plus a
report of everything it could not place:

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

Plant conventions applied (see `VariantMap.report()` for what actually occurred):

- Our styles are 2-bar in the planner but appear as **3-bar rows**: one set runs
  **split lease** (`S/L`) across two half-bars — visible as the *same merge on two
  bars* — so bars sharing a merge are merged (ends / pct summed) and marked `S/L`.
- Denier classes: 70/75 -> **75D**, 40/45 -> **40D** (others as-is: 50D, 80D).
- Colour: a luster naming a colour (`BK`/`BLK` -> `BLK`, `GY`/`GRY` -> `GRY`)
  else white; a `BLK ID` / `BK SOL DYE` yarn type is black too.
- Yarn type: everything we plan is polyester, so `POLY` is implicit and a
  **non-polyester** merge is unusable; `TEXT`/`TX` marks a textured (`TX`) set;
  `CAT` -> `CAT` and `REPREVE` / `RECYCLE*` -> `REP` are the only modifiers
  kept — every other one (`NP`, `WD`, `LR`, `BIO-MEG`, …) is dropped, those
  yarns being interchangeable with the plain one for our purposes.
- A **cationic or Repreve variant of a master whose own beamsets don't use that
  yarn** is a version we no longer produce (many styles were switched off
  cationic) and is excluded.
- Constructions **1048** and **1472** (and their halves) are no longer used.
- Masters in `NOT_KNIT_IN_HOUSE` (bought finished, e.g. `AU7368H`) are skipped;
  their variants land in the exclusions.
- Variant -> master: by the 4-digit style number (left-anchored, so `SR7368` and
  `AUSR7368` count but `97980` does not), disambiguated among same-numbered
  masters by the **nearest bar runlengths** (rack weight drifts with the merge;
  runlength doesn't), then by which master's beamset yarns the variant's merges
  match (`AU4782` vs `AU4782DREP` share runlengths and differ only in the REP
  yarn), the plainer master winning a remaining tie. The letter after the
  number is only a cross-check, reported when runlength didn't settle the choice.
- Top/btm are assigned by matching each set's yarn to the master's `beam_cfg`;
  only when the yarns don't identify the bars does bar position decide (bar 1
  is the **bottom** bar; the highest-numbered bar is the top). Note that
  styles differ in which yarn runs on which bar — the master's `beam_cfg` is
  authoritative per style. The report cross-checks the two.

The master styles are the parsed **greige-styles JSON records** (they carry the
per-bar `runlen` the `Greige` model drops).
"""

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    'Merge', 'RawYarn', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'denier_class', 'read_greige_variants', 'load_master_styles',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants',
    'Recipe', 'BarRecipe', 'MergeInfo',
    'write_variant_masters', 'read_variant_masters',
    'KNOWN_ENDS', 'OBSOLETE_ENDS', 'NOT_KNIT_IN_HOUSE', 'RL_TOLERANCE',
]

# Merged (full-bar) end counts the masters use, and the retired constructions
# (their halves — 524 / 736 — only ever appear as split-lease pairs).
KNOWN_ENDS = frozenset({1172, 1300, 1340})
OBSOLETE_ENDS = frozenset({1048, 1472})
# Masters in the styles file that the knitting plant does not make itself.
NOT_KNIT_IN_HOUSE = frozenset({'AU7368H'})

_TEX_TOKENS = {'TEXT', 'TX', 'TEX'}
_REP_TOKENS = {'REPREVE', 'RECYCLE', 'RECYCLED'}
_KEEP_FINISH = {'CAT', 'REP'}
# Summed |variant - master| bar runlength beyond which a row is taken to be a
# sibling construction (a different letter version) rather than a variant.
RL_TOLERANCE = 10.0
_BLACK_LUSTER = ('BLK', 'BK')
_GREY_LUSTER = ('GRY', 'GRAY', 'GY')
_NUMBER = re.compile(r'\d{4}')


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
            out.append('REP')
            i += 1
        elif t == 'CAT':
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
    """`BLK` for a black luster (`SDBK`, `BLK`, …) or a black yarn type; `GRY`
    for a grey luster; otherwise `WHT` — a luster that names no colour (`SD`,
    `DULL`, `BRT`, `CL`, `SDIM`, …) is white."""
    lus = (luster or '').upper()
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
    denier: str
    flmnt: str
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
    unusable (non-polyester yarn, retired construction, no master, …) or merely
    noteworthy (letter/runlength disagreement, yarn mismatch with the master)."""
    name: str
    number: str
    master: str | None
    top: 'BeamSetSpec | None'
    btm: 'BeamSetSpec | None'
    rack_wt: float | None
    rl_distance: float | None       # sum |set runlen - master runlen| over both bars
    split_bars: tuple[int, ...]     # TSV bar numbers carrying the split-lease set
    split_is_top: bool | None       # whether the split set landed on the master's TOP
    issues: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return not any(i.startswith('!') for i in self.issues)


# ----- masters -------------------------------------------------------------

@dataclass(frozen=True)
class _Bar:
    beamset: str
    pct: float
    runlen: float
    denier: int
    textured: bool
    yarn_desc: str       # the beamset's yarn part, denier folded (`45D BLK` -> `40D BLK`)


@dataclass(frozen=True)
class _Master:
    id: str
    number: str
    suffix: str          # the letter right after the number ('' if none)
    top: _Bar
    btm: _Bar


_BEAMSET = re.compile(r'^(\d+)D (.+?) (\d+)X(\d+)( S/L)?$')


def _parse_bar(cfg: Mapping[str, Any]) -> _Bar:
    beamset = cfg['beamset']
    m = _BEAMSET.match(beamset)
    if not m:
        raise ValueError(f'unparseable beamset {beamset!r}')
    denier = denier_class(int(m.group(1)))
    yarn = f'{denier}D {m.group(2)}'
    return _Bar(beamset, float(cfg['pct']), float(cfg['runlen']),
                denier, yarn.endswith(' TX'), yarn)


def load_master_styles(path: 'str | Path') -> list[dict]:
    """The greige-styles JSON records (the raw list — they carry `runlen`)."""
    with open(path) as fh:
        return json.load(fh)


def _masters(styles: Iterable[Mapping[str, Any]]) -> dict[str, list[_Master]]:
    by_number: dict[str, list[_Master]] = {}
    for s in styles:
        m = _NUMBER.search(s['id'])
        if not m:                                   # e.g. the NONE placeholder
            continue
        rest = re.sub(r'[^A-Z]', '', s['id'][m.end():].upper())
        by_number.setdefault(m.group(0), []).append(_Master(
            s['id'], m.group(0), rest[:1],
            _parse_bar(s['beam_cfg']['top']), _parse_bar(s['beam_cfg']['btm']),
        ))
    return by_number


# ----- rows -> sets ----------------------------------------------------------

def _num(s: Any) -> 'float | None':
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _bars(row: Mapping[str, str]) -> list[dict]:
    out = []
    for i in (1, 2, 3, 4):
        ends = _num(row.get(f'bar{i}_ends'))
        if not ends or ends <= 0:
            continue
        merge = row.get(f'b{i}_merge') or None
        out.append({
            'i': i, 'ends': int(ends), 'pct': _num(row.get(f'bar{i}_pct')) or 0.0,
            'rl': _num(row.get(f'bar{i}_rl')),
            'merge': None if merge in (None, '', 'NULL') else merge,
            'den': row.get(f'b{i}_denier', ''), 'flm': row.get(f'b{i}_flmnt', ''),
            'lus': row.get(f'b{i}_luster', ''), 'yt': row.get(f'b{i}_ytype', ''),
        })
    return out


def _sets(bars: list[dict]) -> list[dict]:
    """Bars sharing a merge collapse into one split-lease set. The merge code
    is the identity when the file has it; otherwise the yarn's attributes."""
    groups: dict[tuple, list[dict]] = {}
    for b in bars:
        key = ('merge', b['merge']) if b['merge'] else ('attrs', b['den'], b['lus'], b['yt'])
        groups.setdefault(key, []).append(b)
    sets = []
    for bs in groups.values():
        b0 = bs[0]
        sets.append({
            'den': b0['den'], 'lus': b0['lus'], 'yt': b0['yt'],
            'yarn': RawYarn(b0['merge'], b0['den'], b0['flm'], b0['lus'], b0['yt']),
            'bars': tuple(b['i'] for b in bs),
            'ends': sum(b['ends'] for b in bs),
            'pct': sum(b['pct'] for b in bs),
            'rl': bs[0]['rl'],
            'split': len(bs) > 1,
        })
    return sets


def _assign(sets: list[dict], merges: list[Merge], m: _Master) -> tuple[dict, dict, int, bool]:
    """Put the two sets on `m`'s top/btm. Prefer the ordering whose yarns match
    the master's beamset yarns outright, then by denier class + textured, then
    by bar position (bar 1 is the bottom bar, so the set on the higher bars is
    the top). Returns `(top_set, btm_set, yarn_mismatches, identified_by_yarn)`."""
    bars = (m.top, m.btm)
    best = None
    for order in ((0, 1), (1, 0)):
        mg = [merges[order[0]], merges[order[1]]]
        full = sum(mg[i].yarn_desc != bars[i].yarn_desc for i in range(2))
        loose = sum((mg[i].denier, mg[i].textured) != (bars[i].denier, bars[i].textured)
                    for i in range(2))
        pos_ok = 0 if sets[order[0]]['bars'][0] > sets[order[1]]['bars'][0] else 1
        key = (full, loose, pos_ok)
        if best is None or key < best[0]:
            best = (key, order)
    (full, loose, _), order = best
    return sets[order[0]], sets[order[1]], full, loose == 0


def _pick_master(
    sets: list[dict], merges: list[Merge], candidates: list[_Master],
    rl_tolerance: float,
) -> tuple[_Master, dict, dict, float | None, list[str]]:
    """Choose among same-numbered masters by (1) summed runlength distance of
    the two bars, (2) how many yarns differ from the master's beamsets (this is
    what separates e.g. `AU4782` from `AU4782DREP`, which share runlengths),
    (3) the plainer master (fewer CAT/REP yarns) when still tied. Returns the
    best `(master, top_set, btm_set, distance, notes)`."""
    best = None
    for m in candidates:
        top, btm, full, by_yarn = _assign(sets, merges, m)
        dist = None
        if top['rl'] is not None and btm['rl'] is not None:
            dist = abs(top['rl'] - m.top.runlen) + abs(btm['rl'] - m.btm.runlen)
        special = sum(t in _KEEP_FINISH for bar in (m.top, m.btm)
                      for t in bar.yarn_desc.split())
        score = (dist if dist is not None else float('inf'), full, special)
        if best is None or score < best[0]:
            best = (score, m, top, btm, dist, by_yarn)
    _, m, top, btm, dist, by_yarn = best
    notes = [] if by_yarn else ['yarn mismatch with master (assigned by bar position)']
    if dist is not None and dist > rl_tolerance:
        notes.append(f'!runlengths {dist:.1f} off {m.id} (a sibling construction?)')
    return m, top, btm, dist, notes


def _variant_letter(name: str, number: str) -> str:
    """The letter immediately after the style number (`AU2958G-HA` -> `G`)."""
    m = re.search(rf'(?<!\d){number}([A-Z])?', name.upper())
    return (m.group(1) or '') if m else ''


def _resolve(
    row: Mapping[str, str], number: str, cands: list[_Master], skipped: list[str],
    rl_tolerance: float,
) -> Variant:
    name = row['variant']
    issues: list[str] = []
    bars = _bars(row)
    sets = _sets(bars)
    n_beams = int(_num(row.get('n_beams')) or 0)
    if not cands:
        issues.append(f"!master not knit in-house: {', '.join(skipped)}")

    merges = []
    for s in sets:
        mg = normalize_merge(s['den'], s['lus'], s['yt'])
        if mg is None:
            issues.append(f"!non-polyester yarn: {s['yt']!r}")
        merges.append(mg)
    if len(sets) != 2:
        issues.append(f'!{len(sets)} distinct merge(s) (need 2)')
    for s in sets:
        if s['ends'] in OBSOLETE_ENDS:
            issues.append(f"!retired construction {s['ends']}")
        elif s['ends'] not in KNOWN_ENDS:
            issues.append(f"!unknown construction {s['ends']}")
    if any(i.startswith('!') for i in issues) or any(m is None for m in merges):
        return Variant(name, number, None, None, None, _num(row.get('rack_wt')),
                       None, tuple(b for s in sets if s['split'] for b in s['bars']),
                       None, tuple(issues))

    letter = _variant_letter(name, number)
    master, top_s, btm_s, dist, notes = _pick_master(sets, merges, cands, rl_tolerance)
    issues += notes
    # The letter is only worth flagging when runlength didn't settle it.
    if (letter and letter != master.suffix and (dist is None or dist > 0.5)
            and any(c.suffix == letter for c in cands)):
        issues.append(f'letter {letter!r} disagrees with runlength choice {master.id!r}')

    def spec(s: dict) -> BeamSetSpec:
        return BeamSetSpec(merges[sets.index(s)], s['ends'], n_beams, s['split'], s['yarn'])

    top, btm = spec(top_s), spec(btm_s)
    # A CAT / REP yarn on a bar whose master beamset isn't CAT / REP is a version
    # of the style we no longer make.
    for bs, mbar in ((top, master.top), (btm, master.btm)):
        for f in bs.merge.finish:
            if f not in mbar.yarn_desc.split():
                what = 'cationic' if f == 'CAT' else 'Repreve'
                issues.append(f'!{what} version of {master.id} (no longer produced)')

    split_bars = tuple(b for s in sets if s['split'] for b in s['bars'])
    split_is_top = top_s['split'] if (top_s['split'] != btm_s['split']) else None
    return Variant(name, number, master.id, top, btm,
                   _num(row.get('rack_wt')), dist, split_bars, split_is_top,
                   tuple(issues))


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

    def master_map(self) -> dict:
        """The per-master variant map, JSON-ready (see `write_variant_map`):

        ```
        {"merges": {"<merge code>": {"denier", "flmnt", "luster", "ytype",
                                     "yarn_desc"}},
         "masters": {"<master id>": {
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
                        'denier': bs.yarn.denier, 'flmnt': bs.yarn.flmnt,
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
        beam-set combinations / runlength fit / finish modifiers, the split-set
        bar-position vs master-label check, and per-master yarn mismatches."""
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
                    reasons[re.sub(r"'.*'", "…", i[1:])] = reasons.get(re.sub(r"'.*'", "…", i[1:]), 0) + 1
        for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f'    - {n:4d}  {r}')
        if self.masters_without_variants:
            lines.append(f'  masters with NO usable variants: {", ".join(self.masters_without_variants)}')

        lines.append('\nper master (usable variants):')
        by_master: dict[str, list[Variant]] = {}
        for v in usable:
            by_master.setdefault(v.master, []).append(v)
        for m, vs in sorted(by_master.items()):
            combos: dict[tuple[str, str], int] = {}
            fins: dict[str, int] = {}
            dists = [v.rl_distance for v in vs if v.rl_distance is not None]
            mism = sum('yarn mismatch' in ' '.join(v.issues) for v in vs)
            letter_dis = sum('disagrees' in ' '.join(v.issues) for v in vs)
            for v in vs:
                combos[(v.top.desc, v.btm.desc)] = combos.get((v.top.desc, v.btm.desc), 0) + 1
                for spec in (v.top, v.btm):
                    for f in spec.merge.finish:
                        fins[f] = fins.get(f, 0) + 1
            lines.append(f'  {m}: {len(vs)} variants; rl distance median='
                         f'{sorted(dists)[len(dists)//2] if dists else "n/a"} '
                         f'max={max(dists) if dists else "n/a"}'
                         + (f'; yarn-mismatch={mism}' if mism else '')
                         + (f'; letter-disagreements={letter_dis}' if letter_dis else '')
                         + (f'; finishes={dict(sorted(fins.items()))}' if fins else ''))
            for (t, b), n in sorted(combos.items(), key=lambda kv: -kv[1]):
                lines.append(f'      {n:4d}  top={t!r:32} btm={b!r}')

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
    tsv_path: 'str | Path', styles: Iterable[Mapping[str, Any]], *,
    skip_masters: Iterable[str] = NOT_KNIT_IN_HOUSE,
    rl_tolerance: float = RL_TOLERANCE,
) -> VariantMap:
    """Build the maps from the variant TSV and the master greige-styles records
    (the parsed JSON list — see `load_master_styles`). Variants of a master in
    `skip_masters`, and rows whose bar runlengths are more than `rl_tolerance`
    off their master, are recorded as excluded rather than mapped."""
    skip = set(skip_masters)
    all_masters = _masters(styles)
    masters = {n: [m for m in ms if m.id not in skip] for n, ms in all_masters.items()}
    skipped = {n: [m.id for m in ms if m.id in skip] for n, ms in all_masters.items()}
    anchored = {n: re.compile(rf'(?<!\d){n}') for n in all_masters}

    variants: dict[str, Variant] = {}
    with open(tsv_path, encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh, delimiter='\t'):
            name = row.get('variant', '')
            hits = [n for n, rx in anchored.items() if rx.search(name)]
            if not hits:
                continue
            number = hits[0]
            variants[name] = _resolve(row, number, masters[number], skipped[number],
                                      rl_tolerance)

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

    covered = set(v2m.values())
    missing = tuple(sorted(m.id for ms in masters.values() for m in ms
                           if m.id not in covered))
    return VariantMap(
        variants=variants,
        merges_to_beamsets={k: frozenset(s) for k, s in merges.items()},
        combos_to_variants={k: tuple(sorted(vs)) for k, vs in combos.items()},
        variant_to_master=v2m,
        excluded=excluded,
        masters_without_variants=missing,
        master_beamsets={m.id: (m.top.beamset, m.btm.beamset)
                         for ms in all_masters.values() for m in ms},
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
    flmnt: str
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
    merges = {code: MergeInfo(code, **info) for code, info in data['merges'].items()}
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
            {k: tuple(v) for k, v in by.items()})
    return VariantMapFile(merges, masters)
