#!/usr/bin/env python

from collections import namedtuple
import math

from swmtplanner.support import Quantity, FloatRange
from swmtplanner.support.misc.contrange import min_float_rng
from swmtplanner.support.grouped import Grouped
from swmtplanner.swmttypes.materials import Status
from .roll import PortLoad, KnitPlant, GrgRollSize, GrgRoll

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
                          ['n_ports', 'create', 'create_date', 'new_only',
                           'max_date', 'plt'],
                          defaults=[False, None, False, None, KnitPlant.EITHER])

class PAInv(Grouped[str, Status]):

    def __init__(self):
        super().__init__('status','plant','item','size','id')
    
    def _all_matching(self, greige, sizes: list[GrgRollSize], params: SearchParams):
        views = set()

        for status in self:
            if params.new_only and status == Status.ARRIVED: continue
            for plant in self[status]:
                if plant not in (KnitPlant.EITHER, params.plt): continue
                if greige not in self[status, plant]: continue

                for size in self[status, plant, greige]:
                    if size not in sizes: continue
                    views |= self[status, plant, greige].itervalues()
        
        return views
    
    def _least_removed(self, roll_lbs, wt_rng: FloatRange):
        min_sub = math.inf
        min_div = -1

        for n in range(1,4):
            scaled_rng = FloatRange(wt_rng.minval*n, wt_rng.maxval*n)
            if scaled_rng.is_above(roll_lbs): continue

            if scaled_rng.is_below(roll_lbs) \
                and roll_lbs - scaled_rng.maxval < min_sub:
                min_sub = roll_lbs - scaled_rng.maxval
                min_div = n
            elif scaled_rng.contains(roll_lbs):
                min_sub = 0
                min_div = n
        
        return min_sub, min_div
    
    def _can_divide(self, roll_lbs: float, wt_rng: FloatRange, n: int):
        scaled_rng = FloatRange(wt_rng.minval*n, wt_rng.maxval*n)
        diff = roll_lbs - scaled_rng.maxval
        return scaled_rng.contains(roll_lbs) or diff >= 0 and diff <= 20
    
    def _get_needed_sub(self, roll_lbs: float, wt_rng: FloatRange, n: int):
        scaled_rng = FloatRange(wt_rng.minval*n, wt_rng.maxval*n)
        if scaled_rng.contains(roll_lbs):
            return 0
        if scaled_rng.is_above(roll_lbs):
            return None
        return roll_lbs - scaled_rng.maxval

    def _comb_loads_helper(self, snapshot, greige, wt_rng: FloatRange,
                           params: SearchParams):
        odd_rviews = list(self._all_matching(greige,
                                             [GrgRollSize.PARTIAL, GrgRollSize.ODD],
                                             params))

        for i in range(len(odd_rviews)):
            for j in range(i+1, len(odd_rviews)):
                rview1 = odd_rviews[i]
                rview2 = odd_rviews[j]
                comb_lbs = (rview1.weight + rview2.weight).lbs

                if self._can_divide(comb_lbs, wt_rng, params.n_ports):
                    x = self._get_needed_sub(comb_lbs, wt_rng, params.n_ports)

                    wt1, wt2 = rview1.weight, rview2.weight
                    if x > 0:
                        if wt1 >= wt2:
                            wt2 -= Quantity(lbs=x-1)
                        else:
                            wt1 -= Quantity(lbs=x-1)

                    roll1: GrgRoll = self.remove(rview1)
                    roll2: GrgRoll = self.remove(rview2)
                    piece1 = roll1.allocate(wt1.lbs, snapshot=snapshot)
                    piece2 = roll2.allocate(wt2.lbs, snapshot=snapshot)
                    self.add(roll1)
                    self.add(roll2)

                    return PortLoad((piece1, piece2),
                                    _reduce_status(piece1.status, piece2.status),
                                    _reduce_plant(piece1.plant, piece2.plant),
                                    max(piece1.avail_date, piece2.avail_date),
                                    piece1.weight + piece2.weight)
        
        return None
    
    def add_all_pieces(self, snapshot, loads: list[PortLoad]):
        for load in loads:
            for piece in load.rolls:
                roll: GrgRoll = self.remove(self.get(piece.roll_id))
                roll.deallocate(piece, snapshot=snapshot)
                self.add(roll)

    def get_comb_loads(self, snapshot, greige, wt_rng: FloatRange,
                       params: SearchParams):
        loads: list[PortLoad] = []
        rem_ports = params.n_ports
        plt = params.plt
        
        for n in (4, 2, 1):
            while rem_ports > 0:
                if rem_ports < n: break
                pl = self._comb_loads_helper(snapshot, greige, wt_rng,
                                             params._replace(n_ports=n, plt=plt))
                if pl is None: break
                loads.append(pl)
                plt = pl.plant
                pl_avg = pl.weight.lbs / n
                pl_rng = FloatRange(pl_avg-20, pl_avg+20)
                wt_rng = min_float_rng(wt_rng, pl_rng)
        
        if rem_ports > 0:
            self.add_all_pieces(snapshot, loads)
            loads = []
        
        return loads, rem_ports
    
    def get_port_loads(self, snapshot, greige, wt_rng: FloatRange,
                       params: SearchParams):
        for rview in self.itervalues():
            roll: GrgRoll = self.remove(rview)
            roll.snapshot = snapshot
            self.add(roll)
        
        loads: list[PortLoad] = []
        rem_ports = params.n_ports
        plt = params.plt

        rviews = list(self._all_matching(greige, [GrgRollSize.TWO_PORT,
                                                  GrgRollSize.ONE_PORT],
                                         params))
        rviews += list(self._all_matching(greige, [GrgRollSize.ODD], params))
        for rview in rviews:
            to_sub, div = self._least_removed(rview.weight.lbs, wt_rng)
            if to_sub > 20 or div > rem_ports: continue
            if to_sub % 2 != 0 and rem_ports % 2 == 0: continue

            roll: GrgRoll = self.remove(rview)
            load_lbs = rview.weight.lbs - to_sub
            piece = roll.allocate(load_lbs, snapshot=snapshot)
            self.add(roll)

            loads.append(PortLoad((piece,), rview.status, rview.plant, rview.received,
                                  Quantity(lbs=load_lbs)))
            rem_ports -= div
            plt = _reduce_plant(plt, rview.plant)
            load_avg = load_lbs / div
            wt_rng = min_float_rng(wt_rng,
                                   FloatRange(load_avg-20, load_avg+20))
        
        if rem_ports == 0:
            return loads
        
        combs, rem_ports = self.get_comb_loads(
            snapshot, greige, wt_rng, params._replace(plt=plt, n_ports=rem_ports))
        loads += combs
        
        if rem_ports == 0:
            return loads
        
        if not params.create:
            self.add_all_pieces(snapshot, loads)
            return []
        
        if params.create_date is None:
            raise ValueError('If allowing creation of new rolls, must provide creation date')
        
        while rem_ports > 0:
            new_lbs = greige.roll_rng.average()
            globals()['_CTR'] += 1
            roll_ports = round(new_lbs / greige.port_rng.average())
            if roll_ports > rem_ports:
                new_lbs = new_lbs * (rem_ports / roll_ports)
                roll_ports = rem_ports

            new_roll = GrgRoll(f'NEW{globals()['_CTR']:06}', greige,
                               KnitPlant.EITHER, Status.NEW, params.create_date,
                               new_lbs)
            
            piece = new_roll.allocate(new_lbs, snapshot=snapshot)
            self.add(new_roll)
            loads.append(PortLoad((piece,), Status.NEW, KnitPlant.EITHER,
                                  params.create_date, Quantity(lbs=new_lbs)))
            rem_ports -= roll_ports
        
        return loads