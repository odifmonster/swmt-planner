from ..loaders import Table, JSONFile, JSONTableLoader

MASTER_STYLES_FILE: JSONFile
"""``greige-master-styles.json``, in the folder under the ``inputs``
config key: a list of objects, one per master style. Undated."""

MASTER_STYLES: Table
"""The master style map. Index ``master`` (master style name, the
``Greige.id``); column ``variant`` (the representative variant chosen for
that master). Any other key in the file is dropped."""

MASTER_STYLE_LOADER: JSONTableLoader
"""Loads ``MASTER_STYLES`` from ``MASTER_STYLES_FILE``."""
