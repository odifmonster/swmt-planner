#!/usr/bin/env python

import typer

from .excel import write_excel_info

app = typer.Typer()
app.command('gen-info', no_args_is_help=True)(write_excel_info)

if __name__ == '__main__':
    app()