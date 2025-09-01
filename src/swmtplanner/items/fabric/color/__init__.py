#!/usr/bin/env python

from .color import Shade, EMPTY, HEAVYSTRIP, STRIP, LIGHT, MEDIUM, BLACK, \
    Color
from .dye_formulae import init, get_color

__all__ = ['Shade', 'EMPTY', 'HEAVYSTRIP', 'STRIP', 'LIGHT', 'MEDIUM',
           'BLACK', 'Color', 'init', 'get_color']