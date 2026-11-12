def read_sql(name: str) -> str:
    """
    Return the text of the query file ``name`` (e.g.
    ``"si_variants.sql"``) from the ``sql`` folder packaged with
    ``catalog``.

    :raises FileNotFoundError: if there is no such file.
    """
    ...
