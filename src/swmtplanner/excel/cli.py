#!/usr/bin/env python

import typer

from .excel import update_file, generate_report

app = typer.Typer()
app.command('update', no_args_is_help=True)(update_file)
app.command('report', no_args_is_help=True)(generate_report)

if __name__ == '__main__':
    app()