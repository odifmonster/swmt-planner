# Shawmut planner tool

This is a python tool for Shawmut's supply chain planning. It is mostly python scripts and some types and functions that emulate elements of the supply chain and planning process. This readme is currently only a documentation of the scripts and how to run them.

## Excel module

The excel submodule of this package defines a very simple language for describing to the program how to read input excel files, and provides a few related scripts (including one that generates a default info file). I will not describe the syntax in detail here, if you have any questions, you know where to reach me!

### Scripts

The `excel-data` command contains the `gen-info`, `update`, and `report` sub commands. The `gen-info` command simply generates a template file in the excel info mini language. This file will include some comments with lightweight explanations of how it works. Both the `update` and `report` commands take the path to this file as an argument. If you want to write the file yourself, that is of course also an option. The `update` command is not currently relevant, so will not be documented here. The `report` command requires at the very least information for `pa_reqs` and `pa_floor_mos`, which expect data in the format of the "Fab shortage" and "1427" tabs of the planning file, respectively.