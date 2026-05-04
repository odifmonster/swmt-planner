#!/usr/bin/env python

from . import workcal
from .has_id import HasID

WorkCal = workcal.WorkCal

__all__ = ['HasID', 'workcal', 'WorkCal']