# -*- coding: utf-8 -*-
"""
Filtres de logging utilisés par config/settings.py.

SlowQueryFilter : ne garde que les requêtes SQL dont la durée (attribut
`duration` posé par Django sur le logger `django.db.backends`) dépasse un
seuil. La durée est en SECONDES (Django la mesure avec time.monotonic()).
"""
import logging


class SlowQueryFilter(logging.Filter):
    def __init__(self, threshold=0.2):  # secondes
        super().__init__()
        self.threshold = threshold

    def filter(self, record):
        duration = getattr(record, 'duration', None)
        return duration is not None and duration >= self.threshold
