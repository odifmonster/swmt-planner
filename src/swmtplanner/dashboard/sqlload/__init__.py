#!/usr/bin/env python

"""`sqlload` — the read path: load runs and their tables from the MySQL store
with pagination, for the `knit-debug` app. This is the data layer kept
**separate from the GUI**; it uses the shared `..manifest` and `..config`
(reader connection). Design in progress — see ../DESIGN.md."""
