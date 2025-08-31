#!/usr/bin/env python

import typer

from .excel import init, to_tsv_file

init()
app = typer.Typer()
app.command()(to_tsv_file)

if __name__ == '__main__':
    app()