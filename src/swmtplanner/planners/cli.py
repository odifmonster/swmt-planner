#!/usr/bin/env python

import typer

from .infinite import run
from .variants_cmd import variants
from .manual_cmd import manual
from .machines_cmd import machines
from .styles_cmd import styles
from .retime_cmd import retime_cmd
from .infinite.swmtio.loadinputs import make_input_file

app = typer.Typer(no_args_is_help=True)
app.command('infinite', no_args_is_help=True, help='Run infinite scheduler.')(run)
app.command(
    'variants', no_args_is_help=True,
    help='Build the greige variant map files from the plant variant table.',
)(variants)
app.command(
    'manual', no_args_is_help=True,
    help='Replay a manual step file into a schedule JSON.',
)(manual)
app.command(
    'machines', no_args_is_help=True,
    help="Convert the plant's runtime export into a planner machines JSON.",
)(machines)
app.command(
    'retime', no_args_is_help=True,
    help='Carry an existing plan forward to the current machine status.',
)(retime_cmd)
app.command(
    'styles', no_args_is_help=True,
    help='Generate greige-styles.json from the master list, variants.tsv and '
         'the knit-machine master.',
)(styles)
app.command(
    'inputs', no_args_is_help=True,
    help="Produce one of the planner's input files from the plant's database "
         "and the day's status TSVs.",
)(make_input_file)

if __name__ == '__main__':
    app()
