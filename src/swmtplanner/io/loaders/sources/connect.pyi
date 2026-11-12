import pyodbc

def conn_str(cfg: dict) -> str:
    """
    Build the ``pyodbc`` connection string from the config's ``sql``
    block: ``DRIVER`` (default ``{ODBC Driver 17 for SQL Server}``),
    ``SERVER=<HOST>,<PORT>``, then every other key as ``<KEY>=<value>``,
    joined with ``;``.

    :raises KeyError: if ``cfg`` has no ``sql`` block or it is missing any
        of ``HOST``, ``PORT``, ``DATABASE``, ``UID``, ``PWD``. The password
        is never included in the error.
    """
    ...

def connect(cfg: dict) -> pyodbc.Connection:
    """
    Open a connection to the SQL database from the config's ``sql`` block
    (see ``conn_str``). The result is what ``SQLTableLoader.load`` is
    given as ``conn``.
    """
    ...
