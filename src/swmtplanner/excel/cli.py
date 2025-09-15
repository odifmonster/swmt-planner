#!/usr/bin/env python

import typer

from .excel import update_file

app = typer.Typer()
app.command('update', no_args_is_help=True)(update_file)

if __name__ == '__main__':
    app()