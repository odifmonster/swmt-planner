# Audit reporting app and project expectations

Currently, the process for producing an audit report involves multiple steps spread out across
several programs and two operating systems. The goal is to have a single, installable app with
a GUI that is intuitive and easy to run. For now, we'll just have the audit report, but over time
we'll probably layer in more things.

## Overview

The current workflow is to run 3 SQL queries, copy over the requirements from the weekly planning file,
run the command line tool on the SQL output, paste the resultant data into the shared audit file,
and run the Excel macro to update all the other tabs accordingly. The SQL queries and internal code
for the CLI app are written, we just need to link them together and put the entire thing in a single
script wrapped in a nice PyQT6 app. Since the whole thing will be automated, we also have no reason
to continue using Excel formulas that update the spreadsheet live, so those calculations will have to
be turned into python code as well. So the project components as I see it are as follows:

1. Figure out how to hit an Oracle database directly via python
2. Recreate entire excel spreadsheet in python (translate formulas to python code)
3. Wrap full script in a single app with a simple dashboard

### Querying database

You will need to discuss this with Wayne. I can send you the queries, but I am not set up to do this and
I think it will require some extra configuration on either the database or your laptop. If the latter,
you will also need a way to reliably recreate the same environment on other machines so the app is easily
portable without too much additional setup. You might also want your own access to the database via SSMS
in the meantime, which you should also ask Wayne about.