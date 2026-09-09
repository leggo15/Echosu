"""Expose canonical public pages and tags with searchable beatmaps."""

from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from .models import Tag, TagApplication
from .seo import BEATMAP_MODES, PUBLIC_PAGES


class PublicSitemap(Sitemap):
    def get_urls(self, page=1, site=None, protocol=None):
        origin = urlsplit(settings.SITE_URL)
        return super().get_urls(
            page=page,
            site=SimpleNamespace(domain=origin.netloc),
            protocol=origin.scheme,
        )


class PageSitemap(PublicSitemap):
    def items(self):
        return PUBLIC_PAGES

    def location(self, item):
        return reverse(item)


class TagSitemap(PublicSitemap):
    def items(self):
        matching_mode = Q()
        for tag_mode, beatmap_mode in BEATMAP_MODES.items():
            matching_mode |= Q(tag__mode=tag_mode, beatmap__mode__iexact=beatmap_mode)
        applications = TagApplication.objects.filter(
            matching_mode, tag_id=OuterRef('pk'), true_negative=False,
            beatmap__difficulty_rating__gte=0, beatmap__difficulty_rating__lte=10,
        )
        # Match the default search window; omit empty and negative-only tags.
        return Tag.objects.filter(Exists(applications)).only('id', 'name', 'mode').order_by('pk')


sitemaps = {'pages': PageSitemap, 'tags': TagSitemap}
