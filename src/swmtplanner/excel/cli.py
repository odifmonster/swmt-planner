#!/usr/bin/env python

import typer

from .excel import update_file, generate_report, gen_info_template

app = typer.Typer()
app.command('update', no_args_is_help=True,
            help='Update a product data file.')(update_file)
app.command('report', no_args_is_help=True,
            help='Generate a named report to an output file.')(generate_report)
app.command('gen-info', help='Generate an info file template.')(gen_info_template)

if __name__ == '__main__':
    app()