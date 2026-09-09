"""Server-rendered metadata and canonical URLs for public pages."""

from django.conf import settings
from django.urls import reverse
from django.utils.html import strip_tags
from django.utils.text import Truncator


HOME_TITLE = 'echosu - Find osu! Beatmaps by Tags'
HOME_DESCRIPTION = (
    'Find osu! beatmaps by community tags such as streams, jumps, tech and stamina. '
    'Filter maps by star rating, BPM, game mode and more on echosu.'
)
MODE_LABELS = {'std': 'osu!', 'taiko': 'osu!taiko', 'catch': 'osu!catch', 'mania': 'osu!mania'}
SEARCH_MODES = {'std': 'osu', 'taiko': 'taiko', 'catch': 'catch', 'mania': 'mania'}
BEATMAP_MODES = {'std': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}
PAGE_METADATA = {
    'home': (HOME_TITLE, HOME_DESCRIPTION),
    'search_results': (HOME_TITLE, HOME_DESCRIPTION),
    'about': (
        'About echosu - osu! Beatmap Search and Community Tags',
        'Learn how echosu helps you discover osu! beatmaps with community tags, '
        'predicted tags and advanced search filters.',
    ),
    'tag_library': (
        'osu! Beatmap Tag Library - echosu',
        'Explore osu! beatmap tags, mapping styles and patterns. Browse tags such as '
        'streams, jumps and tech to find maps, and see the community\'s top contributors.',
    ),
    'statistics': (
        'osu! Beatmap and Tagging Statistics - echosu',
        'Explore echosu beatmap and tagging statistics, recently added maps, '
        'community activity and mapper profiles.',
    ),
    'settings': (
        'Account and Search Settings - echosu',
        'Manage your echosu account, default game mode, beatmap display preferences and API access.',
    ),
    'edit_tags': (
        'Edit osu! Beatmap Tag Descriptions - echosu',
        'Help the echosu community explain osu! mapping styles by editing and voting on beatmap tag descriptions.',
    ),
    'confirm_data_deletion': (
        'Confirm Account Data Deletion - echosu',
        'Review the removal of your echosu account data and contributions before confirming deletion.',
    ),
    'error_page': (
        'Something Went Wrong - echosu',
        'An error occurred on echosu. Return to osu! beatmap search or try again.',
    ),
}
PUBLIC_PAGES = ('home', 'about', 'tag_library', 'statistics')


def absolute_url(path):
    return settings.SITE_URL + path


def plain_description(text):
    return Truncator(' '.join(strip_tags(text or '').split())).chars(160)


def tag_search_label(name):
    """Use singular-style tag wording in metadata without changing stored tags."""
    label = name.strip()
    # Preserve singular words such as "infamous", "focus" and "cross".
    word = label.rsplit(' ', 1)[-1].lower()
    if len(word) <= 1 or not word.endswith('s'):
        return label
    if word.endswith(('ss', 'us', 'is', 'ous')) or word in {'news', 'series', 'species'}:
        return label
    return label[:-1]


def page_metadata(request):
    match = getattr(request, 'resolver_match', None)
    name = match.url_name if match else None
    title, description = PAGE_METADATA.get(name, (HOME_TITLE, HOME_DESCRIPTION))
    public = name in PUBLIC_PAGES or name in ('search_results', 'beatmap_detail', 'tag_search')
    # Statistics can include personal/user-specific views selected via query parameters.
    if name == 'statistics' and request.GET:
        public = False
    canonical_path = reverse('home') if name == 'search_results' else request.path
    return {
        'page_title': title,
        'page_description': description,
        'canonical_url': absolute_url(canonical_path) if public else '',
        'page_robots': 'index,follow' if public else 'noindex,follow',
    }


def search_metadata(request, query, page, tag=None):
    suffix = f' - Page {page.number}' if page.number > 1 else ''
    if tag is not None:
        label = tag_search_label(tag.name)
        title = f'{MODE_LABELS[tag.mode]} {label.title()} Maps'
        description = plain_description(
            f'Find {MODE_LABELS[tag.mode]} {label} maps on echosu. '
            + (tag.description or 'Browse matching maps and refine your search by difficulty, BPM and more.')
        )
        path = tag.get_absolute_url()
        if page.number > 1:
            path += f'?page={page.number}'
        return {
            'page_title': f'{title}{suffix} - echosu',
            'page_description': description,
            'page_robots': 'index,follow' if page.paginator.count else 'noindex,follow',
            'canonical_url': absolute_url(path),
            'landing_tag': tag,
        }

    # Only the unfiltered first page is a search landing page. Arbitrary searches
    # have their own descriptions but should not create an unlimited index.
    tracking_keys = {'gclid', 'fbclid'}
    filtered = any(
        value and key not in tracking_keys and not key.startswith('utm_')
        for key, value in request.GET.items()
    )
    return {
        'page_title': f'{Truncator(query).chars(70)} - osu! Beatmap Search{suffix} - echosu' if query else HOME_TITLE + suffix,
        'page_description': plain_description(
            f'Find osu! beatmaps matching {query} on echosu. Refine results by tags, '
            'star rating, BPM, game mode and more.'
        ) if query else HOME_DESCRIPTION,
        'page_robots': 'noindex,follow' if filtered else 'index,follow',
        'canonical_url': '' if filtered else absolute_url(reverse('home')),
    }
