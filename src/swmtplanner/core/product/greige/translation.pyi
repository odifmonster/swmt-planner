from .greige import Greige


__all__ = [
    'load_variant_translation', 'load_alt_translation',
    'variant_to_master', 'alt_greige_to_greige',
]


def load_variant_translation(contents: str) -> None:
    """Populate the variant->master translation table from the file contents
    (a string): a list of JSON objects, each with `variant` and `master`
    fields."""
    ...


def load_alt_translation(greiges: list[Greige]) -> None:
    """Populate the alt-greige->Greige translation table from the alt_names of
    each given Greige."""
    ...


def variant_to_master(variant: str) -> str | None:
    """The master (product-BOM) greige string for an inventory variant, or None
    if the variant is not in the table."""
    ...


def alt_greige_to_greige(alt_greige: str) -> Greige | None:
    """The knitting-plant Greige a product-BOM greige style maps to, or None if
    the style is not in the table."""
    ...
