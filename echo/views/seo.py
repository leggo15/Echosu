import json

from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_safe

from ..models import Tag
from ..seo import SEARCH_MODES, absolute_url
from ..sitemaps import sitemaps
from .search import search_results


@require_safe
def tag_search(request, tag_id, slug):
    tag = get_object_or_404(Tag, pk=tag_id)
    canonical_path = tag.get_absolute_url()
    if request.path != canonical_path:
        query_string = request.GET.urlencode()
        return HttpResponsePermanentRedirect(canonical_path + (f'?{query_string}' if query_string else ''))

    # Filters submitted to an existing tag URL still work as a regular search.
    # The dedicated landing page itself has a fixed tag and mode for every visitor.
    filters = {
        'query', 'mode', 'star_min', 'star_max', 'sort', 'keys', 'include_predicted',
        'exclude_player', 'fetch_exclude_now', 'status_ranked', 'status_loved', 'status_unranked',
    }
    if filters.intersection(request.GET):
        params = request.GET.copy()
        params.setdefault('query', '.' + json.dumps(tag.name, ensure_ascii=False))
        params.setdefault('mode', SEARCH_MODES[tag.mode])
        return redirect(reverse('search_results') + '?' + params.urlencode())
    return search_results(request, landing_tag=tag)


@require_safe
def robots_txt(request):
    return HttpResponse(
        'User-agent: *\nAllow: /\n\nSitemap: ' + absolute_url(reverse('sitemap')) + '\n',
        content_type='text/plain',
    )


@require_safe
def sitemap_index(request):
    locations = []
    for section, sitemap_class in sitemaps.items():
        location = absolute_url(reverse('sitemap_section', kwargs={'section': section}))
        for page in range(1, sitemap_class().paginator.num_pages + 1):
            locations.append(location + (f'?p={page}' if page > 1 else ''))
    return render(request, 'seo_sitemap_index.xml', {'locations': locations}, content_type='application/xml')
