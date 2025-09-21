#!/usr/bin/env python

from collections import namedtuple
import math, functools

from swmtplanner.support import Quantity, FloatRange
from swmtplanner.support.misc.contrange import min_float_rng
from swmtplanner.support.grouped import Grouped
from swmtplanner.swmttypes.materials import Status
from .roll import PortLoad, KnitPlant, GrgRollSize, GrgRoll, GrgRollView

_CTR = 0

def _reduce_status(prev: Status, cur: Status):
    if prev == Status.NEW or cur == Status.NEW:
        return Status.NEW
    if prev == Status.PLANNED or cur == Status.PLANNED:
        return Status.PLANNED
    return Status.ARRIVED

def _reduce_plant(prev: KnitPlant, cur: KnitPlant):
    if prev != cur and KnitPlant.EITHER not in (prev, cur):
        raise ValueError(f'Cannot combine plants \'{prev.name}\' and ' + \
                         f'\'{cur.name}\'')
    if prev == KnitPlant.EITHER:
        return cur
    return prev

SearchParams = namedtuple('SearchParams',
                          ['snapshot', 'greige', 'wt_rng', 'n_ports', 'split_date',
                           'create', 'create_date', 'new_only', 'max_date',
                           'plt'],
                          defaults=[-1, False, None, False, None, KnitPlant.EITHER])

class PAInv(Grouped[str, Status]):

    def __init__(self):
        super().__init__('status','plant','item','size','id')
    
    def _get_needed_sub(self, roll_lbs, n_splits: int, wt_rng: FloatRange):
        if n_splits * wt_rng.minval > roll_lbs:
            return None
        
        scaled_rng = FloatRange(wt_rng.minval*n_splits,
                                wt_rng.maxval*n_splits)
        if scaled_rng.contains(roll_lbs):
            return 0
        return roll_lbs - scaled_rng.maxval

    def _best_split(self, roll_lbs, wt_rng: FloatRange, max_div: int = -1):
        x = int(roll_lbs / wt_rng.minval)
        if max_div > 0:
            max_div = min(x, max_div)
        else:
            max_div = x

        if x < 1:
            return -1, 0
        
        best_n = -1
        best_sub = math.inf
        for n in range(1, max_div+1):
            cur_sub = self._get_needed_sub(roll_lbs, n, wt_rng)
            if cur_sub is None: continue
            if cur_sub < best_sub:
                best_n = n
                best_sub = cur_sub

        return best_n, best_sub
    
    def _start_roll_helper(self, greige, wt_rng: FloatRange):
        if Status.ARRIVED not in self:
            return []
        
        opts: list[tuple[GrgRollView, int, float, int]] = []
        for plt in self[Status.ARRIVED]:
            if greige not in self[Status.ARRIVED, plt]: continue
            for start in self[Status.ARRIVED, plt, greige].itervalues():
                start: GrgRollView
                div, sub = self._best_split(start.weight.lbs, wt_rng)
                if div < 0 or sub > 26: continue
                cur_avg = (start.weight.lbs - sub) / div
                cur_rng = FloatRange(cur_avg-20, cur_avg+20)
                cur_rng = min_float_rng(cur_rng, wt_rng)

                n, to_sub = div, sub
                count = 0

                for other in self.itervalues():
                    other: GrgRollView
                    if other.item != greige: continue
                    if other.status == Status.NEW: continue
                    if other.plant != start.plant: continue
                    if other == start: continue
                    
                    if other.status == Status.PLANNED:
                        count += 1
                        continue

                    div, sub = self._best_split(other, cur_rng)
                    if div > 0 and sub == 0:
                        count += 1
                
                opts.append((start, n, to_sub, count))
        
        return opts
    
    def _get_start_roll(self, greige, wt_rng: FloatRange):
        start_opts = self._start_roll_helper(greige, wt_rng)
        if not start_opts:
            return None, -1, 0, -1
        start_opts = sorted(start_opts, key=lambda x: (x[1] % 2, -1 * x[3], x[2]))
        return start_opts[0]
    
    def _get_cur_loads(self, params: SearchParams, at_start = True):
        if at_start:
            start, n, to_sub, _ = self._get_start_roll(params.greige, params.wt_rng)
            if start is None:
                return [], params
        
            load_avg = (start.weight.lbs - to_sub) / n
            new_rng = FloatRange(load_avg-20, load_avg+20)
            params = params._replace(wt_rng=min_float_rng(new_rng, params.wt_rng),
                                    plt=start.plant)

        opts: list[tuple[GrgRollView, int, float]] = []
        for rview in self[Status.ARRIVED, start.plant, params.greige].itervalues():
            rview: GrgRollView
            if rview == start: continue
            div, sub = self._best_split(rview.weight.lbs, params.wt_rng)
            if div < 0 or sub > 26: continue
            opts.append((rview, div, sub))

        if opts:
            opts = sorted(opts, key=lambda x: (x[1] % 2, x[2]))
        opts.insert(0, (start, n, 0))

        loads: list[PortLoad] = []
        rem_ports = params.n_ports
        wt_rng = params.wt_rng

        for tup in opts:
            rview = tup[0]
            div, sub = self._best_split(rview.weight.lbs, wt_rng, max_div=rem_ports)
            if div < 0 or sub > 26: continue

            roll: GrgRoll = self.remove(rview)
            piece = roll.allocate(rview.weight.lbs - sub, snapshot=params.snapshot)
            load = PortLoad((piece,), div, Status.ARRIVED, rview.plant,
                            rview.received, piece.weight)
            self.add(roll)

            loads.append(load)
            rem_ports -= load.nports
            cur_load_avg = load.weight.lbs / load.nports
            wt_rng = min_float_rng(wt_rng,
                                   FloatRange(cur_load_avg-20, cur_load_avg+20))
            
            if rem_ports == 0:
                break
        
        return loads, params._replace(n_ports=rem_ports, wt_rng=wt_rng)
    
    def _comb_loads_helper(self, rviews: list[GrgRollView], params: SearchParams):
        for rview in rviews:
            to_sub = self._get_needed_sub(rview.weight.lbs, params.n_ports,
                                          params.wt_rng)
            if to_sub is not None:
                roll: GrgRoll = self.remove(rview)
                piece = roll.allocate(roll.weight.lbs - to_sub, snapshot=params.snapshot)
                self.add(roll)
                load = PortLoad((piece,), params.n_ports, rview.status,
                                rview.plant, rview.received, piece.weight)
                return load

        for i in range(len(rviews)):
            rview1 = rviews[i]
            if rview1.weight.lbs < 50: continue
            if params.plt != KnitPlant.EITHER and rview1.plant != params.plt: continue
            for j in range(i+1, len(rviews)):
                rview2 = rviews[j]
                if rview2.weight.lbs < 50: continue
                if rview2.plant != rview1.plant: continue

                comb_lbs = (rview1.weight + rview2.weight).lbs
                to_sub = self._get_needed_sub(comb_lbs, params.n_ports, params.wt_rng)
                if to_sub is not None:
                    if rview1.weight > rview2.weight:
                        lbs1 = rview1.weight.lbs - to_sub
                        lbs2 = rview2.weight.lbs
                    else:
                        lbs1 = rview1.weight.lbs
                        lbs2 = rview2.weight.lbs - to_sub

                    roll1: GrgRoll = self.remove(rview1)
                    roll2: GrgRoll = self.remove(rview2)
                    piece1 = roll1.allocate(lbs1, snapshot=params.snapshot)
                    piece2 = roll2.allocate(lbs2, snapshot=params.snapshot)
                    self.add(roll1)
                    self.add(roll2)

                    load = PortLoad((piece1, piece2), params.n_ports,
                                    _reduce_status(rview1.status, rview2.status),
                                    _reduce_plant(rview1.plant, rview2.plant),
                                    max(rview1.received, rview2.received),
                                    piece1.weight + piece2.weight)
                    return load
        
        return None
    
    def _get_comb_loads(self, params: SearchParams):
        if Status.ARRIVED not in self:
            return [], params
        
        rviews: set[GrgRollView] = set()
        for plt in self[Status.ARRIVED]:
            if params.plt != KnitPlant.EITHER and \
                plt not in (KnitPlant.EITHER, params.plt): continue
            if params.greige not in self[Status.ARRIVED, plt]: continue
            if GrgRollSize.ODD not in self[Status.ARRIVED, plt, params.greige]: continue

            rviews |= set(self[Status.ARRIVED, plt, params.greige, GrgRollSize.ODD].itervalues())
        
        loads: list[PortLoad] = []
        rem_ports = params.n_ports
        wt_rng = params.wt_rng
        plt = params.plt
        for n in (4, 2, 1):
            while rem_ports > 0:
                if n > rem_ports: break
                pl = self._comb_loads_helper(list(rviews),
                                             params._replace(n_ports=rem_ports,
                                                             wt_rng=wt_rng,
                                                             plt=plt))
                if pl is None: break
                loads.append(pl)
                rem_ports -= pl.nports
                load_avg = pl.weight.lbs / pl.nports
                wt_rng = min_float_rng(wt_rng,
                                       FloatRange(load_avg-20, load_avg+20))
                plt = _reduce_plant(plt, pl.plant)
        
        return loads, params._replace(n_ports=rem_ports, wt_rng=wt_rng,
                                      plt=plt)
    
    def _get_new_loads(self, params: SearchParams):
        rem_ports = params.n_ports

        plt = params.plt
        if plt == KnitPlant.EITHER:
            plant_lbs = {
                KnitPlant.WVILLE: 0,
                KnitPlant.INFINITE: 0
            }
            for status in self:
                if status == Status.ARRIVED: continue
                for plant in self[status]:
                    if params.greige not in self[status, plant]: continue
                    for rview in self[status, plant, params.greige].itervalues():
                        rview: GrgRollView
                        if params.max_date is not None and rview.received > params.max_date:
                            continue
                        plant_lbs[plant] += rview.weight.lbs
            
            if plant_lbs[KnitPlant.INFINITE] == plant_lbs[KnitPlant.WVILLE]:
                plt = KnitPlant.EITHER
            else:
                plt = max(KnitPlant.WVILLE, KnitPlant.INFINITE,
                          key=lambda p: plant_lbs[p])
        
        loads: list[PortLoad] = []
        for status in self:
            if status == Status.ARRIVED: continue
            if plt not in self[status] or params.greige not in self[status, plt]:
                continue

            rviews: list[GrgRollView] = list(self[status, plt, params.greige].itervalues())
            for rview in rviews:
                if params.max_date is not None and rview.received > params.max_date:
                    continue

                if rview.size == GrgRollSize.TWO_PORT:
                    cur_ports = 2
                else:
                    cur_ports = 1
                
                if cur_ports > rem_ports and rview.received < params.split_date:
                    continue
                load_lbs = rview.weight.lbs
                if cur_ports > rem_ports:
                    load_lbs = rview.weight.lbs / 2
                
                roll: GrgRoll = self.remove(rview)
                piece = roll.allocate(load_lbs, snapshot=params.snapshot)
                self.add(roll)
                load = PortLoad((piece,), min(cur_ports, rem_ports),
                                rview.status, plt, rview.received, Quantity(lbs=load_lbs))
                loads.append(load)

                rem_ports -= load.nports
                if rem_ports == 0:
                    return loads, 0
        
        if params.create:
            if params.create_date is None:
                raise ValueError(f'Cannot create new rolls without a creation date')
            
            load_avg = params.greige.load_rng.average()
            std_roll_ports = round(params.greige.roll_rng.average() / load_avg)
            
            while rem_ports > 0:
                globals()['_CTR'] += 1
                new_roll = GrgRoll(f'NEW{globals()['_CTR']:06}', params.greige,
                                   KnitPlant.EITHER, Status.NEW, params.create_date,
                                   params.greige.roll_rng.average())
                new_roll.snapshot = params.snapshot
                if std_roll_ports > rem_ports:
                    load_lbs = rem_ports * load_avg
                else:
                    load_lbs = new_roll.weight.lbs
                
                piece = new_roll.allocate(load_lbs, snapshot=params.snapshot)
                load = PortLoad((piece,), min(std_roll_ports, rem_ports),
                                Status.NEW, KnitPlant.EITHER, params.create_date,
                                Quantity(lbs=load_lbs))
                loads.append(load)
                self.add(new_roll)

                rem_ports -= load.nports
        
        return loads, rem_ports
    
    def _get_port_loads(self, params: SearchParams, at_start: bool = True):
        loads: list[PortLoad] = []
        cur_params = params

        if not params.new_only:
            even_loads, cur_params = self._get_cur_loads(cur_params, at_start=at_start)
            if cur_params.n_ports == 0:
                return even_loads, cur_params
            comb_loads, cur_params = self._get_comb_loads(cur_params)
            if cur_params.n_ports == 0:
                return even_loads + comb_loads, cur_params
            
            if params.n_ports % 2 != cur_params.n_ports % 2 and \
                params.max_date is not None and \
                params.max_date < params.split_date:
                if comb_loads and comb_loads[-1].nports % 2 == 1:
                    removed = comb_loads.pop()
                else:
                    removed = even_loads.pop()
                
                self.add_all_pieces(params.snapshot, [removed])
                rem_ports = cur_params.n_ports + removed.nports

                def _pl_load_rng(pl: PortLoad):
                    avg = pl.weight.lbs / pl.nports
                    return FloatRange(avg-20, avg+20)
                wt_rng = functools.reduce(
                    min_float_rng, map(_pl_load_rng, even_loads + comb_loads),
                    params.wt_rng)
                
                plt = functools.reduce(
                    _reduce_plant, map(lambda pl: pl.plant, even_loads + comb_loads),
                    params.plt)
                
                cur_params = params._replace(n_ports=rem_ports, wt_rng=wt_rng,
                                             plt=plt)
            
            loads = even_loads + comb_loads
        
        new_loads, rem_ports = self._get_new_loads(cur_params)
        if rem_ports > 0:
            self.add_all_pieces(params.snapshot, loads + new_loads)
            return None, params
        
        return loads + new_loads, cur_params
    
    def add_all_pieces(self, snapshot, loads: list[PortLoad]):
        for load in loads:
            for piece in load.rolls:
                roll: GrgRoll = self.remove(self.get(piece.roll_id))
                roll.deallocate(piece, snapshot=snapshot)
                self.add(roll)
    
    def get_port_loads(self, split_point, **kwargs):
        params = SearchParams(**kwargs)

        if split_point is not None:
            loads1, cur_params = self._get_port_loads(params._replace(n_ports=split_point))
            if loads1 is None:
                return None
            loads2, cur_params = self._get_port_loads(
                cur_params._replace(n_ports=params.n_ports-split_point),
                at_start=False)
            if loads2 is None:
                return None
            return loads1, loads2
        
        loads, _ = self._get_port_loads(params)
        return loads