#!/usr/bin/env python

import typer

from .infinite import run
from .variants_cmd import variants
from .manual_cmd import manual
from .machines_cmd import machines

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

if __name__ == '__main__':
    app()
