#!/usr/bin/env python

from swmtplanner.core.product import Product

from .order import Order


class SafetyOrder[T: Product](Order[T]):
    pass
