# Shawmut planner tool

This is a python tool for Shawmut's supply chain planning. It is mostly python scripts and some types and functions that emulate elements of the supply chain and planning process. This readme is currently only a documentation of the scripts and how to run them.

## Excel module

The excel submodule of this package defines a very simple language for describing to the program how to read input excel files, and provides a few related scripts (including one that generates a default info file). I will not describe the syntax in detail here, if you have any questions, you know where to reach me!

### Scripts

The `excel-data` command contains the `gen-info`, `update`, and `report` sub commands. The `gen-info` command simply generates a template file in the excel info mini language. This file will include some comments with lightweight explanations of how it works. Both the `update` and `report` commands take the path to this file as an argument. If you want to write the file yourself, that is of course also an option. The `update` command is not currently relevant, so will not be documented here. The `report` command requires at the very least information for `pa_reqs` and `pa_floor_mos`, which expect data in the format of the "Fab shortage" and "1427" tabs of the planning file, respectively.

# Running reports

These are instructions for generating reports from excel files. There is some setup required on the first run, but the subsequent reports will require significantly fewer steps.

## Installation

These are the instructions for installing on a Windows machine, as that appears to be what everyone uses. If at some point Linux instructions are needed, someone can notify me, and I will add them.

1. This package requires at least Python 3.12. Python distributions can be found on the Microsoft store or directly on [the Python website](https://www.python.org). You can follow the download and installation instructions from there.
2. You should now ensure that python and the package installation manager `pip` (which comes automatically with every or almost every python distribution) were properly installed.
    1. Open a Windows PowerShell.
    2. Run `python --version`. If installed correctly, you should see something like the following:
    ```
    PS C:\Users\yourname> python --version
    Python 3.13.7
    ```
    3. Run `pip --version`. If installed correctly, you should see something like the following:
    ```
    PS C:\Users\yourname> pip --version
    pip 25.2 from C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.2032.0_x64__qbz5n2kfra8p0\Lib\site-packages\pip (python 3.13)
    ```
3. It is best practice to create a virtual environment. It does not need to go anywhere in particular, but if you have a specific directory where you would like to put it, you can navigate to that directory by running `Set-Location <path to directory>` in the PowerShell.
4. Run `python -m venv swmt-venv`. This creates a directory called `swmt-venv` and places a new virtual environment inside of it.
5. Activate the environment by running `.\swmt-venv\Scripts\activate`. You should see a new element in your prefix now:
```
PS C:\Users\yourname\remaining\path> .\swmt-venv\Scripts\activate
(swmt-venv) PS C:\Users\yourname\remaining\path>
```
6. You will need to install the dependencies separately, as I can not figure out how to make it automatic.
    1. Run `pip install "pandas[excel]"`. This will allow the scripts to handle excel files.
    2. Run `pip install typer`. This will provide some nicely-formatted help messages for the command-line tools in this package.
7. Finally, you can install this planner tool! Run `pip install -i https://test.pypi.org/simple/ swmtplanner`.
8. You have successfully installed the swmtplanner package! It is fairly bare-bones at the moment, but as new changes are made, downloading the updates will be much easier.

If you wish to stop here, you can simply run `deactivate` and exit PowerShell. Otherwise, continue to the "Setup and run" section.

## Setup and run

The program needs to know where to find the relevant excel files and how to read them. It has its own simplified specification language for defining this information. Again, I will not go into detail about it here. I think the layout is pretty self-explanatory, but feel free to send me any questions you have.

1. Open a Windows PowerShell.
2. Create a directory for the relevant files for this activity. (This is not strictly necessary, but it will make your life easier.) You can do this by running `New-Item -Path <path to new directory> -ItemType Directory`.
3. Navigate to the new directory using `Set-Location`.
4. Download the planning file to your machine and move it to this directory.
5. Activate the virtual environment (if not currently active) by running `<path to venv>\Scripts\activate`.
6. Run `excel-data gen-info`. This will generate an `excel-info.txt` file in the current directory with a pretty complete template.
7. Open the new file using whichever text editor you prefer. You can read through the file to get a general idea of how it works.
    1. You will see on lines 11 and 12 two variables (`FOLDER` and `WORKBOOK`) whose values need to be set.
    2. Set the `FOLDER` value to the absolute path pointing to the folder containing the latest planning file. It needs to be wrapped in quotes, and backlashes need to be escaped (i.e. doubled).
    3. Set the `WORKBOOK` value to the name of the latest planning file. If it contains spaces or non-alpha-numeric characters aside from '.', it needs to be wrapped in quotes.
    4. Navigate to line 99. You will see a block labeled "pa_reqs" with information on how to read the fabric shortage tab. Make sure `sheet` refers to the correct sheet in the file (again, if there are non-alpha-numeric characters or spaces, it needs to be wrapped in quotes).
8. In the Windows PowerShell, run `excel-data report all_pa_1427 <path to excel info> <path to desired output file>`. The output file will be created if it doesn't exist and overwritten if it does. If you want more details about the report command, you can run `excel-data report --help`.
9. All set! You should see an excel file at the location you provided with 3 tabs: "summary", "reworks", and "mo_priorities". In future runs, you only need to follow steps 7.3, 7.4 (possibly 7.2 if you use a different folder), and 8 to generate new reports.