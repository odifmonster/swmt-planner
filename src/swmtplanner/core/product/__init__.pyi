from . import greige, fabric
from .greige import Greige
from .fabric import Fabric, Color


type Product = Fabric | Greige


__all__ = ['greige', 'Greige', 'fabric', 'Fabric', 'Color', 'Product']
