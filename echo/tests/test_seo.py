from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from echo.models import Beatmap, Tag, TagApplication, UserSettings
from echo.seo import HOME_TITLE


class HeadParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_head = False
        self.in_title = False
        self.titles = []
        self.descriptions = []
        self.robots = []
        self.canonicals = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'head':
            self.in_head = True
        if not self.in_head:
            return
        if tag == 'title':
            self.in_title = True
            self.titles.append('')
        if tag == 'meta' and attrs.get('name') == 'description':
            self.descriptions.append(attrs['content'])
        if tag == 'meta' and attrs.get('name') == 'robots':
            self.robots.append(attrs['content'])
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_head and self.in_title:
            self.titles[-1] += data


@override_settings(
    SITE_URL='https://www.echosu.com',
    ALLOWED_HOSTS=['testserver', 'localhost'],
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class SeoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='seo-tester')
        cls.streams = Tag.objects.create(name='streams', description='Continuous patterns to practice stream control.', description_author=None)
        cls.mania = Tag.objects.create(name='streams', mode='mania', description_author=None)
        cls.empty = Tag.objects.create(name='empty tag', description_author=None)
        cls.negative = Tag.objects.create(name='negative only', description_author=None)
        for index in range(12):
            beatmap = cls.make_map(str(1000 + index))
            TagApplication.objects.create(beatmap=beatmap, tag=cls.streams, user=cls.user)
        cls.unrelated_map = cls.make_map('2000', title='streams')
        TagApplication.objects.create(beatmap=cls.unrelated_map, tag=cls.streams, true_negative=True)
        TagApplication.objects.create(beatmap=cls.unrelated_map, tag=cls.negative, true_negative=True)
        cls.mania_map = cls.make_map('3000', mode='mania', cs=7)
        TagApplication.objects.create(beatmap=cls.mania_map, tag=cls.mania, is_prediction=True, prediction_confidence=0.8)

    @classmethod
    def make_map(cls, beatmap_id, **kwargs):
        fields = {
            'title': 'Test Song', 'artist': 'Test Artist', 'version': 'Expert',
            'creator': 'Test Mapper', 'listed_owner': 'Test Mapper', 'mode': 'osu',
            'status': 'Ranked', 'difficulty_rating': 5, 'bpm': 180,
            'total_length': 120, 'playcount': 1000, 'favourite_count': 10,
            'last_updated': timezone.now(),
        }
        fields.update(kwargs)
        return Beatmap.objects.create(beatmap_id=beatmap_id, **fields)

    def head(self, response):
        self.assertEqual(response.status_code, 200)
        head = HeadParser(response.content.decode())
        self.assertEqual(len(head.titles), 1)
        self.assertEqual(len(head.descriptions), 1)
        self.assertTrue(head.titles[0])
        self.assertTrue(head.descriptions[0])
        return head

    def test_tag_landing_renders_matching_maps_and_search_form_in_html(self):
        response = self.client.get(self.streams.get_absolute_url())
        head = self.head(response)
        self.assertEqual(head.titles, ['Streams osu! Beatmaps - echosu'])
        self.assertEqual(head.canonicals, ['https://www.echosu.com' + self.streams.get_absolute_url()])
        self.assertEqual(head.robots, ['index,follow'])
        self.assertEqual(response.context['results_total'], 12)
        self.assertEqual(response.context['query'], '."streams"')
        self.assertEqual(response.context['active_mode'], 'osu')
        self.assertContains(response, '<h1 id="tag-search-heading">Streams osu! Beatmaps</h1>')
        self.assertContains(response, 'Continuous patterns to practice stream control.')
        self.assertContains(response, 'bulk-select-checkbox')
        self.assertContains(response, 'href="?page=2"')
        self.assertNotContains(response, 'beatmap-card-2000')
        self.assertNotContains(response, 'beatmap-card-3000')

    def test_tag_mode_overrides_personal_mode_and_key_preferences(self):
        UserSettings.objects.create(user=self.user, default_mode='mania', default_mania_keys='4')
        self.client.force_login(self.user)
        response = self.client.get(self.streams.get_absolute_url())
        self.assertEqual(response.context['active_mode'], 'osu')
        response = self.client.get(self.mania.get_absolute_url())
        self.assertEqual(response.context['selected_keys'], 'any')
        self.assertEqual(response.context['results_total'], 1)
        self.assertContains(response, 'beatmap-card-3000')
        self.assertIn('osu!mania', self.head(response).titles[0])

    def test_pagination_has_own_canonical_and_invalid_pages_are_404(self):
        response = self.client.get(self.streams.get_absolute_url(), {'page': 2})
        head = self.head(response)
        self.assertIn('Page 2', head.titles[0])
        self.assertEqual(head.canonicals, ['https://www.echosu.com' + self.streams.get_absolute_url() + '?page=2'])
        self.assertEqual(len(response.context['beatmaps']), 2)
        for page in ['0', '-1', '999', 'invalid']:
            with self.subTest(page=page):
                self.assertEqual(self.client.get(self.streams.get_absolute_url(), {'page': page}).status_code, 404)

    def test_empty_tags_are_noindex_and_unknown_tag_is_404(self):
        for tag in [self.empty, self.negative]:
            with self.subTest(tag=tag.name):
                response = self.client.get(tag.get_absolute_url())
                self.assertEqual(self.head(response).robots, ['noindex,follow'])
                self.assertEqual(response.context['results_total'], 0)
        self.assertEqual(self.client.get('/tags/99999/missing/').status_code, 404)

    def test_slugs_survive_collisions_non_ascii_names_and_renames(self):
        first = Tag.objects.create(name='jump aim', description_author=None)
        second = Tag.objects.create(name='jump-aim', description_author=None)
        unicode_tag = Tag.objects.create(name='連打', description_author=None)
        self.assertNotEqual(first.get_absolute_url(), second.get_absolute_url())
        self.head(self.client.get(unicode_tag.get_absolute_url()))
        previous_url = first.get_absolute_url()
        first.name = 'new name'
        first.save()
        response = self.client.get(previous_url, {'page': 2})
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], first.get_absolute_url() + '?page=2')

    def test_tag_names_are_not_interpreted_as_search_operators(self):
        for name in ['bpm>=999', '12345', 'a,b', 'a "quoted" tag']:
            with self.subTest(name=name):
                tag = Tag.objects.create(name=name, description_author=None)
                TagApplication.objects.create(tag=tag, beatmap=self.unrelated_map, user=self.user)
                response = self.client.get(tag.get_absolute_url())
                self.assertEqual(response.context['results_total'], 1)
                self.assertContains(response, 'beatmap-card-2000')

    def test_filtering_a_tag_url_preserves_query_and_mode(self):
        response = self.client.get(self.mania.get_absolute_url(), {'star_min': '4'})
        self.assertEqual(response.status_code, 302)
        location = urlsplit(response['Location'])
        self.assertEqual(location.path, reverse('search_results'))
        self.assertEqual(parse_qs(location.query), {'query': ['."streams"'], 'mode': ['mania'], 'star_min': ['4']})
        response = self.client.get(self.streams.get_absolute_url(), {'query': 'jumps'})
        self.assertEqual(parse_qs(urlsplit(response['Location']).query)['query'], ['jumps'])

    def test_home_metadata_and_filtered_search_indexing(self):
        for path in [reverse('home'), reverse('search_results')]:
            head = self.head(self.client.get(path))
            self.assertEqual(head.titles, [HOME_TITLE])
            self.assertEqual(head.canonicals, ['https://www.echosu.com/'])
            self.assertEqual(head.robots, ['index,follow'])
        for params in [{'query': 'streams'}, {'star_min': '5'}, {'mode': 'mania'}, {'page': '2'}]:
            with self.subTest(params=params):
                head = self.head(self.client.get(reverse('search_results'), params))
                self.assertEqual(head.robots, ['noindex,follow'])
                self.assertFalse(head.canonicals)
        head = self.head(self.client.get(reverse('home'), {'utm_source': 'test'}))
        self.assertEqual(head.robots, ['index,follow'])

    def test_metadata_escapes_untrusted_content(self):
        query = '"><script>alert(1)</script>'
        response = self.client.get(reverse('search_results'), {'query': query})
        self.head(response)
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.unrelated_map.title = 'A "song" & <test>'
        self.unrelated_map.save()
        response = self.client.get(reverse('beatmap_detail', args=[self.unrelated_map.beatmap_id]))
        head = self.head(response)
        self.assertIn(self.unrelated_map.title, head.titles[0])
        self.assertIn(self.unrelated_map.title, head.descriptions[0])

    def test_public_and_account_pages_have_specific_metadata(self):
        titles = set()
        descriptions = set()
        for name in ['about', 'tag_library', 'statistics', 'error_page']:
            with self.subTest(name=name):
                head = self.head(self.client.get(reverse(name)))
                titles.add(head.titles[0])
                descriptions.add(head.descriptions[0])
        self.assertEqual(len(titles), 4)
        self.assertEqual(len(descriptions), 4)
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        for name in ['settings', 'edit_tags', 'confirm_data_deletion']:
            with self.subTest(name=name):
                head = self.head(self.client.get(reverse(name)))
                self.assertEqual(head.robots, ['noindex,follow'])
                self.assertFalse(head.canonicals)

    def test_custom_404_has_metadata(self):
        with override_settings(DEBUG=False):
            response = self.client.get('/not-a-page/')
        self.assertEqual(response.status_code, 404)
        head = HeadParser(response.content.decode())
        self.assertEqual(head.titles, ['Page Not Found - echosu'])
        self.assertTrue(head.descriptions[0])
        self.assertEqual(head.robots, ['noindex,follow'])

    def test_library_links_and_sitemaps_use_canonical_tag_urls(self):
        response = self.client.get(reverse('tag_library'))
        self.assertContains(response, f'href="{self.streams.get_absolute_url()}"')
        self.assertContains(response, f'href="{self.mania.get_absolute_url()}"')
        robots = self.client.get(reverse('robots_txt'))
        self.assertEqual(robots.status_code, 200)
        self.assertContains(robots, 'Sitemap: https://www.echosu.com/sitemap.xml')
        index = self.client.get(reverse('sitemap'))
        root = ElementTree.fromstring(index.content)
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        self.assertEqual(len(root.findall('s:sitemap', ns)), 2)
        tags = self.client.get(reverse('sitemap_section', args=['tags']))
        root = ElementTree.fromstring(tags.content)
        urls = {node.text for node in root.findall('s:url/s:loc', ns)}
        self.assertEqual(urls, {
            'https://www.echosu.com' + self.streams.get_absolute_url(),
            'https://www.echosu.com' + self.mania.get_absolute_url(),
        })
        pages = self.client.get(reverse('sitemap_section', args=['pages']))
        self.assertContains(pages, '<loc>https://www.echosu.com/</loc>')
        self.assertNotContains(pages, '/settings/')
