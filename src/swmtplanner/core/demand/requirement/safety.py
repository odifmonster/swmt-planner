#!/usr/bin/env python

from swmtplanner.core.product import Product

from .requirement import Requirement


class Safety[T: Product](Requirement[T]):

    @property
    def id(self) -> str:
        return f'S@{self.item.id}'
