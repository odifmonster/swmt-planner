#!/usr/bin/env python

from swmtplanner.support import HasID, SwmtBase, Viewer

class Data[T](SwmtBase, HasID[T]):

    def __init_subclass__(cls, mut_in_group, read_only = tuple(), priv = tuple()):
        cls._mut_in_group = mut_in_group
        super().__init_subclass__(read_only=('prefix','id')+read_only,
                                  priv=('view','in_group')+priv)
        
    def __init__(self, prefix, id, view, **kwargs):
        SwmtBase.__init__(self, _prefix=prefix, _id=id, _view=view, _in_group=False,
                          **kwargs)
        
    def __setattr__(self, name, value):
        cls = type(self)
        if hasattr(self, '_in_group') and not self._mut_in_group and self._in_group:
            raise RuntimeError(f'\'{cls.__name__}\' objects cannot be mutated while ' + \
                               'in a group')
        super(SwmtBase, self).__setattr__(name, value)
    
    def _add_to_group(self):
        super(SwmtBase, self).__setattr__('_in_group', True)

    def _rem_from_group(self):
        super(SwmtBase, self).__setattr__('_in_group', False)

    def view(self):
        return self._view
    
class DataView[T](Viewer[Data[T]]):

    def __init_subclass__(cls, dunders = tuple(), attrs = tuple(), funcs = tuple(),
                          read_only = tuple(), priv = tuple()):
        super().__init_subclass__(dunders=('hash','eq','repr')+dunders,
                                  attrs=('prefix','id')+attrs, funcs=funcs,
                                  read_only=read_only, priv=priv)