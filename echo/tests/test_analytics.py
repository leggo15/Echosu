from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from echo.analytics_filters import is_automated_user_agent
from echo.models import AnalyticsClickEvent, AnalyticsSearchEvent, Beatmap


BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
GOOGLEBOT_UA = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class AnalyticsFilteringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='analytics-admin', is_staff=True)
        cls.beatmap = Beatmap.objects.create(beatmap_id='123', title='Test map', mode='osu')

    def setUp(self):
        self.client.cookies['analytics_id'] = str(uuid4())

    def post(self, name, payload, user_agent=BROWSER_UA):
        return self.client.post(reverse(name), payload, content_type='application/json', HTTP_USER_AGENT=user_agent)

    def assert_no_activity(self):
        self.assertEqual(AnalyticsSearchEvent.objects.count(), 0)
        self.assertEqual(AnalyticsClickEvent.objects.count(), 0)
        self.beatmap.refresh_from_db()
        self.assertEqual(self.beatmap.shown_in_search, 0)

    def test_known_bots_do_not_record_search_click_or_impressions(self):
        for user_agent in [
            GOOGLEBOT_UA, 'bingbot/2.0', 'Discordbot/2.0', 'GPTBot/1.0',
            'ClaudeBot/1.0', 'HeadlessChrome/140.0.0.0', 'python-requests/2.31.0',
            'curl/8.0', 'AhrefsBot/7.0', 'UptimeRobot/2.0',
        ]:
            for name, payload in [
                ('analytics_log_search', {'query': 'streams'}),
                ('analytics_log_click', {'action': 'direct', 'beatmap_id': '123'}),
                ('analytics_log_click', {'action': 'impression', 'beatmap_id': '123'}),
                ('analytics_log_impressions', {'beatmap_ids': ['123']}),
            ]:
                with self.subTest(user_agent=user_agent, endpoint=name):
                    response = self.post(name, payload, user_agent)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {'ok': False, 'ignored': True})
        self.assert_no_activity()

    def test_normal_anonymous_traffic_and_conversions_are_preserved(self):
        search = self.post('analytics_log_search', {'query': 'streams'}).json()
        self.assertTrue(search['ok'])
        response = self.post('analytics_log_click', {
            'action': 'direct', 'beatmap_id': '123', 'search_event_id': search['event_id'],
        })
        self.assertTrue(response.json()['ok'])
        response = self.post('analytics_log_impressions', {'beatmap_ids': ['123', '123']})
        self.assertEqual(response.json()['updated'], 1)
        self.assertEqual(AnalyticsSearchEvent.objects.get().client_id, self.client.cookies['analytics_id'].value)
        self.assertEqual(AnalyticsClickEvent.objects.count(), 1)
        self.beatmap.refresh_from_db()
        self.assertEqual(self.beatmap.shown_in_search, 1)

    def test_missing_or_invalid_anonymous_identity_does_not_create_activity(self):
        for raw in [None, '', 'anonymous', 'x' * 64, 'x' * 36]:
            for name, payload in [
                ('analytics_log_search', {'query': 'streams'}),
                ('analytics_log_click', {'action': 'direct'}),
                ('analytics_log_impressions', {'beatmap_ids': ['123']}),
            ]:
                with self.subTest(cookie=raw, endpoint=name):
                    self.client.cookies.clear()
                    if raw is not None:
                        self.client.cookies['analytics_id'] = raw
                    response = self.post(name, payload)
                    self.assertEqual(response.json(), {'ok': False, 'ignored': True})
        self.assert_no_activity()

    def test_normal_page_issues_cookie_and_known_bots_stay_crawlable(self):
        self.client.cookies.clear()
        response = self.client.get(reverse('about'), HTTP_USER_AGENT=BROWSER_UA)
        self.assertEqual(response.status_code, 200)
        self.assertIn('analytics_id', response.cookies)
        self.assertTrue(self.post('analytics_log_search', {'query': 'streams'}).json()['ok'])

        self.client.cookies.clear()
        response = self.client.get(reverse('about'), HTTP_USER_AGENT=GOOGLEBOT_UA)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="robots" content="index,follow"')
        self.assertNotIn('analytics_id', response.cookies)

    def test_authenticated_visitors_can_use_account_identity_without_cookie(self):
        self.client.force_login(self.staff)
        del self.client.cookies['analytics_id']
        self.assertTrue(self.post('analytics_log_search', {'query': 'streams'}).json()['ok'])
        event = AnalyticsSearchEvent.objects.get()
        self.assertIsNone(event.client_id)
        self.assertTrue(event.logged_in_user_id)
        self.assertTrue(event.is_staff)
        self.post('analytics_log_search', {'query': 'jumps'}, GOOGLEBOT_UA)
        self.assertEqual(AnalyticsSearchEvent.objects.count(), 1)

    def test_similar_phone_or_browser_names_are_not_treated_as_bots(self):
        for user_agent in [
            BROWSER_UA,
            'Mozilla/5.0 (Linux; Android 13; CUBOT P80) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1',
        ]:
            with self.subTest(user_agent=user_agent):
                self.assertFalse(is_automated_user_agent(user_agent))

    def test_filtered_events_do_not_inflate_admin_search_or_unique_totals(self):
        self.post('analytics_log_search', {'query': 'streams'})
        self.client.cookies['analytics_id'] = str(uuid4())
        self.post('analytics_log_search', {'query': 'jumps'}, GOOGLEBOT_UA)
        self.post('analytics_log_click', {'action': 'direct'}, GOOGLEBOT_UA)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('statistics_admin_data'), HTTP_USER_AGENT=BROWSER_UA)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['download_conversion']['searches_all_time'], 1)
        for period in ['hour', 'day', 'year', 'all']:
            with self.subTest(period=period):
                self.assertEqual(sum(data['searches'][period]['counts']), 1)
                self.assertEqual(sum(data['uniques'][period]['counts']), 1)

    def test_existing_events_are_not_reclassified_or_deleted(self):
        legacy = AnalyticsSearchEvent.objects.create(client_id='legacy-client', query='streams')
        self.post('analytics_log_search', {'query': 'jumps'}, GOOGLEBOT_UA)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('statistics_admin_data'), HTTP_USER_AGENT=BROWSER_UA)
        self.assertEqual(response.json()['download_conversion']['searches_all_time'], 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.client_id, 'legacy-client')
