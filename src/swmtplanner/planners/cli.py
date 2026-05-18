#!/usr/bin/env python

import typer

from .infinite import run

app = typer.Typer()
app.command('infinite', no_args_is_help=True, help='Run infinite scheduler.')(run)

if __name__ == '__main__':
    app()