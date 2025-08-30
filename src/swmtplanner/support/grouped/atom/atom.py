#!/usr/bin/env python

from swmtplanner.support import SwmtBase, Viewer, setter_like
from ..data import match_props, repr_props

class Atom[T](SwmtBase, priv=('prop_names','prop_vals','data','view')):
    
    def __init__(self, **kwargs):
        if 'id' not in kwargs.keys():
            raise ValueError('\'Atom\' initializer missing required keyword ' + \
                             'argument \'id\'')
        
        prop_names = tuple(kwargs.keys())
        prop_vals = tuple([kwargs[name] for name in prop_names])
        super().__init__(_prop_names=prop_names, _prop_vals=prop_vals, _data=None,
                         _view=AtomView(self))
    
    def __len__(self):
        return self.n_items
    
    def __iter__(self):
        if len(self) == 1:
            yield tuple()
        return
    
    def __contains__(self, key):
        return len(self) == 1 and key == tuple()
    
    def __getitem__(self, key):
        if type(key) is not tuple:
            raise TypeError('\'Atom\' object cannot be indexed with ' + \
                            f'\'{type(key).__name__}\'')
        if len(key) > 0:
            raise KeyError('Key is too long')
        if len(self) == 0:
            raise KeyError(f'\'Atom\' object does not contain key {repr(key)}')
        return self.view()
    
    def __repr__(self):
        if len(self) == 0:
            return ''
        return repr(self.data)

    @property
    def depth(self):
        return 0

    @property
    def n_items(self):
        if self._data is None:
            return 0
        return 1
    
    @property
    def data(self):
        if self._data is None:
            raise AttributeError('Empty \'Atom\' object has no data')
        return self._data.view()
    
    def get(self, id):
        if self._data is None or self.data.id != id:
            raise KeyError(f'Object has no data with id={repr(id)}')
        return self.data
    
    @setter_like
    def add(self, data):
        if not match_props(data, self._prop_names, self._prop_vals):
            msg = 'This object only accepts data with the following properties:\n'
            msg += repr_props(self._prop_names, self._prop_vals)
            raise ValueError(msg)
        
        data._add_to_group()
        if self._data is not None:
            return
        
        data._add_to_group()
        self._data = data
    
    @setter_like
    def remove(self, dview, remkey = False):
        if self._data is None:
            raise RuntimeError('Cannot remove data from empty \'Atom\' object')
        if dview != self._data:
            dview_props = tuple([getattr(dview, name) for name in self._prop_names])
            msg = 'Object has no data with properties\n'
            msg += repr_props(self._prop_names, dview_props)
            raise ValueError(msg)
        
        ret = self._data
        self._data = None
        ret._rem_from_group()
        return ret
    
    def iterkeys(self):
        return iter(self)
    
    def itervalues(self):
        if len(self) > 0:
            yield self.data
        return
    
    def view(self):
        return self._view

class AtomView[T](Viewer[Atom[T]],
                  dunders=('len','iter','contains','getitem','repr'),
                  attrs=('depth','n_items','data'),
                  funcs=('get','iterkeys','itervalues')):
    pass