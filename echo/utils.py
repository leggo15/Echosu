
###################################################### - manages query states in search.
from collections import defaultdict
from django.db.models import Q

class QueryContext:
    def __init__(self, beatmaps):
        self.beatmaps = beatmaps
        self.include_q = Q()
        self.exclude_q = Q()
        self.required_tags = set()
        self.include_tags = set()
        self.exclude_tags = set()
        self.include_tag_names = set()
        self.exclude_tag_names = set()