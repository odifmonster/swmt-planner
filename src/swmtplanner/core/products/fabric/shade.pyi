from enum import Enum

class Shade(Enum):
    """
    The shade category of a dye formula, used to sequence dye lots on a
    jet. A lighter shade cannot run after a darker shade without a strip
    cycle between them. Under that rule ``LIGHT0`` and ``LIGHT1`` are "the
    same" shade, as are ``SD_BLACK`` and ``BLACK``; the pairs are split
    because the number of strips required differs within each. The exact
    sequencing and strip rules belong to the dye scheduling design.
    """

    LIGHT0 = 'LIGHT0'
    """Light shades that cannot run immediately after a strip cycle."""
    LIGHT1 = 'LIGHT1'
    """Light shades that can run immediately after a strip cycle."""
    MEDIUM = 'MEDIUM'
    """Medium shades."""
    SD_BLACK = 'SD_BLACK'
    """Solution-dyed black."""
    BLACK = 'BLACK'
    """Black. Stains the jet more than solution-dyed black, so requires
    more strips after it."""
