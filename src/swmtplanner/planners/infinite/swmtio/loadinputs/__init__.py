#!/usr/bin/env python

"""`loadinputs` — the planner's input files from the loaded tables: one
function per input (`gen_machines`, `gen_inventory`, `gen_doffed`,
`compute_runout`), each returning a JSON-serialisable object, and the entry
point `make_input_file` that names one and writes it. See
`planners/infinite/swmtio/DESIGN.md` ("Producing the planner's inputs")."""

from .inventory import gen_inventory
from .doffed import gen_doffed
from .runout import compute_runout
from .machines import gen_machines
from .make_input import InputName, make_input_file

__all__ = ['gen_inventory', 'gen_doffed', 'compute_runout', 'gen_machines',
           'InputName', 'make_input_file']
