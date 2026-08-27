from . import yarn, greige, fabric
from .yarn import Yarn, BeamSetItem
from .greige import Greige
from .fabric import Fabric, Color


type Product = Fabric | Greige | BeamSetItem


__all__ = [
    'yarn', 'Yarn', 'BeamSetItem',
    'greige', 'Greige',
    'fabric', 'Fabric', 'Color',
    'Product',
]
