__all__ = ['init', 'translate_name']

def init() -> None:
    """
    Initialize the translate submodule. Do not use any methods
    in this submodule before running the initializer.
    """
    ...

def translate_name(name: str) -> str | None:
    """
    Translates a greige item in the PA inventory report to its
    equivalent in the Xref and Demand Planning sheets. Returns
    None if the translation is unknown.
    """
    ...