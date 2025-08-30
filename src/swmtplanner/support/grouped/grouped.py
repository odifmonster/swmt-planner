#!/usr/bin/env python

from swmtplanner.support import SwmtBase, Viewer, setter_like
from .data import match_props, repr_props
from .atom import Atom

class Grouped[T, U](SwmtBase,
                    priv=('prop_names','prop_vals','unbound',
                          'ids_map','subgrps','view')):

    def __init__(self, *args, **kwargs):
        prop_names = tuple(kwargs.keys())
        if not set(prop_names).isdisjoint(set(args)):
            overlap = set(prop_names).intersection(set(args))
            msg = 'Unbound properties '
            msg += ', '.join(map(repr, overlap))
            msg += ' cannot be bound to values'
            raise ValueError(msg)
        
        prop_vals = tuple([kwargs[name] for name in prop_names])
        super().__init__(_prop_names=prop_names, _prop_vals=prop_vals,
                         _unbound=args, _ids_map={}, _subgrps={},
                         _view=GroupedView(self))
        
    def __len__(self):
        return sum(map(lambda subgrp: 1 if subgrp.n_items > 0 else 0,
                       self._subgrps.values()))
    
    def __iter__(self):
        for key in self._subgrps:
            if self._subgrps[key].n_items > 0:
                yield key

    def __contains__(self, key):
        return key in self._subgrps and self._subgrps[key].n_items > 0
    
    def __getitem__(self, key):
        if type(key) is not tuple:
            key = (key,)
        if len(key) == 0:
            return self.view()
        if key[0] not in self._subgrps or len(self._subgrps[key[0]]) == 0:
            raise KeyError(f'Object does not contain items with {self._unbound[0]}={repr(key[0])}')
        try:
            return self._subgrps[key[0]][key[1:]]
        except KeyError as err:
            if 'Key is too long' in str(err) or \
                '-dim key incompatible with' in str(err):
                raise KeyError(f'{len(key)}-dim key incompatible with {self.depth}-dim Grouped object')
            raise err
    
    def __repr__(self):
        contents: list[str] = []

        if self.depth == 1:
            for val in self._subgrps.values():
                vrep = repr(val)
                if not vrep: continue
                contents.append('  ' + vrep)
        else:
            max_k = max(map(lambda k: len(repr(k)), self._subgrps.keys()))
            kprefix = ' '*(max_k+4)

            for key, val in self._subgrps.items():
                if len(val) == 0: continue
                krep = repr(key)
                vrep = repr(val)

                vrep_start, *vrep_lines = vrep.split('\n')

                gap = ' '*(max_k-len(krep)+1)
                item_start = '  '+krep+':'+gap+vrep_start
                item_lines = list(map(lambda l: kprefix+l, vrep_lines))

                contents.append('\n'.join([item_start] + item_lines))
        
        if not contents:
            return ''
        return 'grouped({\n' + '\n'.join(contents) + '\n})'
    
    @property
    def depth(self):
        return len(self._unbound)
    
    @property
    def n_items(self):
        return len(self._ids_map)
    
    def get(self, id):
        if id not in self._ids_map:
            raise KeyError(f'Object has no data with id={repr(id)}')
        subkey = self._ids_map[id]
        return self._subgrps[subkey].get(id)
    
    @setter_like
    def add(self, data):
        if not match_props(data, self._prop_names, self._prop_vals):
            msg = 'This object only accepts data with the following properties:\n'
            msg += repr_props(self._prop_names, self._prop_vals)
            raise ValueError(msg)

        if data.id in self._ids_map:
            return
        
        subkey = getattr(data, self._unbound[0])
        self._ids_map[data.id] = subkey

        if subkey not in self._subgrps:
            subkwargs = { self._prop_names[i]: self._prop_vals[i] 
                          for i in range(len(self._prop_names)) }
            subkwargs[self._unbound[0]] = subkey

            if self.depth == 1:
                newgrp = Atom(**subkwargs)
            else:
                newgrp = Grouped(*self._unbound[1:], **subkwargs)
            
            self._subgrps[subkey] = newgrp
        
        self._subgrps[subkey].add(data)
    
    @setter_like
    def remove(self, dview, remkey = False):
        if self.n_items == 0:
            raise ValueError('Cannot remove data from empty \'Grouped\' object')
        if dview.id not in self._ids_map:
            dview_props = tuple([getattr(dview, name) for name in self._prop_names])
            msg = 'Object has no data with properties\n'
            msg += repr_props(self._prop_names, dview_props)
            raise ValueError(msg)
        
        subkey = getattr(dview, self._unbound[0])
        ret = self._subgrps[subkey].remove(dview, remkey=remkey)
        if remkey and self._subgrps[subkey].n_items == 0:
            del self._subgrps[subkey]
        del self._ids_map[dview.id]
        return ret
    
    def iterkeys(self):
        for key in self:
            remkeys = self._subgrps[key].iterkeys()
            for remkey in remkeys:
                yield (key, *remkey)
    
    def itervalues(self):
        for key in self:
            yield from self._subgrps[key].itervalues()
    
    def view(self):
        return self._view
        
class GroupedView[T, U](Viewer[Grouped[T, U]],
                        dunders=('len','iter','contains','getitem','repr'),
                        attrs=('depth','n_items'),
                        funcs=('get','iterkeys','itervalues')):
    pass