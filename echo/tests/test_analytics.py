from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from echo.analytics_filters import admin_analytics_events, is_automated_user_agent
from echo.models import AnalyticsClickEvent, AnalyticsSearchEvent, Beatmap, Tag


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
        self.post('analytics_log_click', {'action': 'view_details'})
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

    def test_existing_events_can_be_included_without_deleting_them(self):
        legacy = AnalyticsSearchEvent.objects.create(client_id='legacy-client', query='streams')
        self.post('analytics_log_search', {'query': 'jumps'}, GOOGLEBOT_UA)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('statistics_admin_data'), HTTP_USER_AGENT=BROWSER_UA)
        self.assertEqual(response.json()['download_conversion']['searches_all_time'], 0)
        response = self.client.get(reverse('statistics_admin_data'), {'include_likely_bots': '1'}, HTTP_USER_AGENT=BROWSER_UA)
        self.assertEqual(response.json()['download_conversion']['searches_all_time'], 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.client_id, 'legacy-client')


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class LikelyBotAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(username='bot-filter-admin', password=None)
        Tag.objects.create(name='streams', mode='std', description_author=None)
        cls.lonely = AnalyticsSearchEvent.objects.create(
            client_id='one-search', query='streams lonely', tags=['streams'], flags={'mode': 'std'},
        )
        cls.single_click = AnalyticsClickEvent.objects.create(client_id='one-click', action='nav_about')
        cls.active = AnalyticsSearchEvent.objects.create(
            client_id='active', query='streams active', tags=['streams'], flags={'mode': 'std'},
        )
        AnalyticsClickEvent.objects.create(client_id='active', action='direct', search_event_id=cls.active.event_id)
        cls.signed = AnalyticsSearchEvent.objects.create(
            client_id='signed', logged_in_user_id='a' * 64, query='streams signed',
            tags=['streams'], flags={'mode': 'std'},
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def data(self, endpoint='statistics_admin_data', **params):
        response = self.client.get(reverse(endpoint), params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_toggle_filters_every_period_conversions_buttons_and_top_tags(self):
        for include, searches, uniques in [('0', 2, 2), ('1', 3, 4)]:
            with self.subTest(include=include):
                data = self.data(include_likely_bots=include)
                conversion = data['download_conversion']
                self.assertEqual(conversion['searches_all_time'], searches)
                self.assertEqual(conversion['searches_with_download_all_time'], 1)
                self.assertAlmostEqual(conversion['percent_with_download_all_time'], 100 / searches)
                for period in ['hour', 'day', 'year', 'all']:
                    self.assertEqual(sum(data['searches'][period]['counts']), searches)
                    self.assertEqual(sum(data['uniques'][period]['counts']), uniques)
                    self.assertEqual(sum(data['uniques'][period]['logged_in_nonstaff_counts']), 1)
                    self.assertEqual(sum(data['searches'][period]['dl_followups']), 1)
                    self.assertAlmostEqual(sum(data['searches'][period]['dl_pct']), 100 / searches)
                self.assertEqual(data['top_tags'], [{'name': 'streams', 'mode': 'std', 'count': searches}])
                self.assertEqual(data['click_counts_30d']['direct'], 1)
                for key in ['click_counts_30d', 'avg_clicks_per_action_per_day', 'last_used_per_action']:
                    self.assertEqual('nav_about' in data[key], include == '1')
                if include == '1':
                    self.assertEqual(data['click_counts_30d']['nav_about'], 1)
                    self.assertAlmostEqual(data['avg_clicks_per_action_per_day']['nav_about'], 1 / 30)
        self.assertEqual(AnalyticsSearchEvent.objects.count(), 3)
        self.assertEqual(AnalyticsClickEvent.objects.count(), 2)

    def test_tag_detail_uses_the_same_filter(self):
        for include, count in [('0', 2), ('1', 3)]:
            with self.subTest(include=include):
                data = self.data('statistics_admin_tag', tag='streams', mode='std', include_likely_bots=include)
                for key in ['searches_all_time', 'searches_last_30d', 'unique_users_all_time', 'unique_users_last_30d']:
                    self.assertEqual(data['totals'][key], count)
                self.assertEqual(data['click_through']['searches_with_direct_or_view_all_time'], 1)
                self.assertAlmostEqual(data['click_through']['percent_with_direct_or_view_all_time'], 100 / count)
                for period in ['hour', 'day', 'year']:
                    self.assertEqual(sum(data['searches'][period]['counts']), count)
                    self.assertAlmostEqual(sum(data['searches'][period]['dl_pct']), 100 / count)

    def test_logs_hide_singletons_by_default_and_label_them_when_included(self):
        for endpoint, label_count in [('statistics_latest_events', 2), ('statistics_latest_searches', 1)]:
            with self.subTest(endpoint=endpoint):
                filtered = self.data(endpoint)['html']
                self.assertNotIn('streams lonely', filtered)
                self.assertNotIn('Likely bot', filtered)
                self.assertIn('streams active', filtered)
                self.assertIn('streams signed', filtered)
                included = self.data(endpoint, include_likely_bots='1')['html']
                self.assertIn('streams lonely', included)
                self.assertEqual(included.count('Likely bot'), label_count)

    def test_second_interaction_restores_the_original_search_in_metrics_and_logs(self):
        self.assertFalse(admin_analytics_events(AnalyticsSearchEvent).filter(pk=self.lonely.pk).exists())
        AnalyticsClickEvent.objects.create(client_id=self.lonely.client_id, action='view_details')
        self.assertFalse(admin_analytics_events(AnalyticsSearchEvent, include_bots=True).get(pk=self.lonely.pk).is_likely_bot)
        self.assertEqual(self.data()['download_conversion']['searches_all_time'], 3)
        html = self.data('statistics_latest_events')['html']
        self.assertIn('streams lonely', html)
        self.assertNotIn('Likely bot', html)

    def test_two_searches_or_two_clicks_also_establish_engagement(self):
        AnalyticsSearchEvent.objects.create(client_id=self.lonely.client_id, query='jumps')
        AnalyticsClickEvent.objects.create(client_id=self.single_click.client_id, action='nav_search')
        self.assertEqual(admin_analytics_events(AnalyticsSearchEvent).count(), 4)
        self.assertEqual(admin_analytics_events(AnalyticsClickEvent).count(), 3)

    def test_classification_uses_history_outside_the_selected_period_tag_and_mode(self):
        previous = AnalyticsSearchEvent.objects.create(
            client_id=self.lonely.client_id, query='chords', flags={'mode': 'mania'},
        )
        AnalyticsSearchEvent.objects.filter(pk=previous.pk).update(created_at=timezone.now() - timezone.timedelta(days=400))
        self.assertEqual(self.data()['download_conversion']['searches_all_time'], 4)
        self.assertEqual(sum(self.data()['searches']['hour']['counts']), 3)
        data = self.data('statistics_admin_tag', tag='streams', mode='std')
        self.assertEqual(data['totals']['searches_all_time'], 3)
        self.assertEqual(data['totals']['searches_last_30d'], 3)

    def test_impressions_do_not_turn_a_single_search_into_engagement(self):
        for _ in range(3):
            AnalyticsClickEvent.objects.create(client_id=self.lonely.client_id, action='impression')
        self.assertFalse(admin_analytics_events(AnalyticsSearchEvent).filter(pk=self.lonely.pk).exists())
        self.assertFalse(admin_analytics_events(AnalyticsClickEvent).filter(client_id=self.lonely.client_id).exists())
        self.assertEqual(admin_analytics_events(AnalyticsClickEvent, include_bots=True).filter(
            client_id=self.lonely.client_id, is_likely_bot=True,
        ).count(), 3)

    def test_unidentified_events_are_not_pooled_and_logged_in_events_are_retained(self):
        for identity in [None, '']:
            with self.subTest(identity=identity):
                for _ in range(2):
                    anonymous = AnalyticsSearchEvent.objects.create(client_id=identity, query='anonymous')
                    self.assertFalse(admin_analytics_events(AnalyticsSearchEvent).filter(pk=anonymous.pk).exists())
                for account in [{'logged_in_user_id': 'b' * 64}, {'is_staff': True}]:
                    authenticated = AnalyticsSearchEvent.objects.create(client_id=identity, query='signed in', **account)
                    self.assertTrue(admin_analytics_events(AnalyticsSearchEvent).filter(pk=authenticated.pk).exists())

    def test_log_pagination_filters_before_applying_limits(self):
        AnalyticsSearchEvent.objects.bulk_create([
            AnalyticsSearchEvent(client_id=f'new-bot-{i}', query=f'new singleton {i}') for i in range(65)
        ])
        first = self.data('statistics_latest_events', offset=0, limit=1)
        second = self.data('statistics_latest_events', offset=1, limit=1)
        third = self.data('statistics_latest_events', offset=2, limit=1)
        self.assertIn('streams signed', first['html'])
        self.assertIn('Button', second['html'])
        self.assertIn('streams active', third['html'])
        self.assertTrue(first['has_more'])
        self.assertTrue(second['has_more'])
        self.assertFalse(third['has_more'])
        included = self.data('statistics_latest_events', offset=0, limit=1, include_likely_bots='1')
        self.assertIn('new singleton', included['html'])
        self.assertIn('Likely bot', included['html'])

    def test_click_only_traffic_is_counted_without_any_included_searches(self):
        AnalyticsSearchEvent.objects.all().delete()
        AnalyticsClickEvent.objects.create(client_id='active', action='view_details')
        data = self.data()
        self.assertEqual(data['download_conversion']['searches_all_time'], 0)
        for period in ['hour', 'day', 'year', 'all']:
            self.assertEqual(sum(data['uniques'][period]['counts']), 1)

    def test_all_time_includes_events_in_the_current_fractional_second(self):
        now = timezone.now().replace(hour=0, minute=0, second=52, microsecond=900000)
        event_time = now - timezone.timedelta(microseconds=200000)
        AnalyticsSearchEvent.objects.update(created_at=event_time)
        AnalyticsClickEvent.objects.update(created_at=event_time)
        with patch('echo.views.statistics.timezone.now', return_value=now):
            data = self.data()
        self.assertEqual(sum(data['searches']['all']['counts']), 2)
        self.assertEqual(sum(data['uniques']['all']['counts']), 2)

    def test_django_admin_lists_share_default_filter_and_labels(self):
        for model_name, count in [('analyticssearchevent', 2), ('analyticsclickevent', 1)]:
            with self.subTest(model=model_name):
                url = reverse(f'admin:echo_{model_name}_changelist')
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['cl'].result_count, count)
                self.assertContains(response, 'Exclude likely bots')
                included = self.client.get(url, {'include_likely_bots': '1'})
                self.assertEqual(included.status_code, 200)
                self.assertEqual(included.context['cl'].result_count, count + 1)
                self.assertContains(included, '>Likely bot<', count=1)

    def test_statistics_toggle_replaces_old_explanation(self):
        for params, checked in [({}, False), ({'include_likely_bots': '1'}, True)]:
            response = self.client.get(reverse('statistics'), {'tab': 'admin', **params})
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            toggle = html.split('id="adminIncludeLikelyBots"', 1)[1].split('>', 1)[0]
            self.assertEqual('checked' in toggle, checked)
            self.assertNotIn('Historical events may still include bots.', html)
            self.assertNotIn('Anonymous unique users are estimated from browser cookies.', html)

    def test_include_parameter_does_not_bypass_staff_authorization(self):
        self.client.logout()
        for endpoint in ['statistics_admin_data', 'statistics_admin_tag', 'statistics_latest_events', 'statistics_latest_searches']:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(reverse(endpoint), {'include_likely_bots': '1', 'tag': 'streams'})
                self.assertEqual(response.status_code, 403)
