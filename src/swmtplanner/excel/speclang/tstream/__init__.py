#!/usr/bin/env python

from . import tokens
from ._tokenize import tokenize
from .tstream import TStream

Token = tokens.Token

__all__ = ['tokens', 'tokenize', 'TStream', 'Token']