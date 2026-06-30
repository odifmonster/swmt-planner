from .fabric import Fabric


__all__ = ['load_ply1_translation', 'ply1_to_fabric']


def load_ply1_translation(fabrics: list[Fabric]) -> None:
    """Populate the ply1->fabric translation table from the ply1_parts of
    each given Fabric."""
    ...


def ply1_to_fabric(ply1: str) -> Fabric | None:
    """The finished fabric product the ply1 part number refers to, or None
    if the ply1 part is not in the translation table."""
    ...