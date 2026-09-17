from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from echo.admin import UserProfileAdmin
from echo.models import UserProfile
from echo.views.auth import (
    USER_RANK_REFRESH_LOCK_KEY,
    extract_global_rank,
    refresh_all_user_ranks,
    save_user_data,
)


class ExtractGlobalRankTests(TestCase):
    def test_reads_statistics_global_rank(self):
        self.assertEqual(extract_global_rank({'statistics': {'global_rank': 1234}}), 1234)

    def test_reads_legacy_rank_global(self):
        self.assertEqual(extract_global_rank({'statistics': {'rank': {'global': 50}}}), 50)

    def test_falls_back_to_osu_ruleset(self):
        self.assertEqual(
            extract_global_rank({
                'statistics': {},
                'statistics_rulesets': {'osu': {'global_rank': 99}},
            }),
            99,
        )

    def test_unranked_is_none(self):
        self.assertIsNone(extract_global_rank({'statistics': {'global_rank': None}}))
        self.assertIsNone(extract_global_rank({'statistics': {'global_rank': 0}}))
        self.assertIsNone(extract_global_rank({}))

    def test_reads_rank_from_ossapi_user_object(self):
        user = SimpleNamespace(
            statistics=SimpleNamespace(global_rank=42, rank=None),
            statistics_rulesets=None,
        )
        self.assertEqual(extract_global_rank(user), 42)


class SaveUserDataRankTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def make_request(self):
        request = self.factory.get('/osu-callback')
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        return request

    def osu_payload(self, osu_id=123, username='rankplayer', rank=4567):
        return {
            'id': osu_id,
            'username': username,
            'avatar_url': 'https://example.com/a.png',
            'statistics': {'global_rank': rank},
        }

    @patch('echo.views.auth.get_user_data_from_api')
    def test_stores_rank_on_first_login(self, mock_api):
        mock_api.return_value = self.osu_payload()
        save_user_data('token', self.make_request())
        profile = UserProfile.objects.get(osu_id='123')
        self.assertEqual(profile.rank_at_last_login, 4567)

    @patch('echo.views.auth.get_user_data_from_api')
    def test_updates_rank_on_returning_login(self, mock_api):
        user = User.objects.create(username='rankplayer')
        UserProfile.objects.create(user=user, osu_id='123', rank_at_last_login=10)
        mock_api.return_value = self.osu_payload(rank=2)
        save_user_data('token', self.make_request())
        profile = UserProfile.objects.get(osu_id='123')
        self.assertEqual(profile.rank_at_last_login, 2)

    @patch('echo.views.auth.get_user_data_from_api')
    def test_clears_rank_when_unranked(self, mock_api):
        user = User.objects.create(username='rankplayer')
        UserProfile.objects.create(user=user, osu_id='123', rank_at_last_login=10)
        mock_api.return_value = self.osu_payload(rank=None)
        save_user_data('token', self.make_request())
        profile = UserProfile.objects.get(osu_id='123')
        self.assertIsNone(profile.rank_at_last_login)


class UserProfileAdminRankTests(TestCase):
    def setUp(self):
        cache.delete(USER_RANK_REFRESH_LOCK_KEY)
        self.staff = User.objects.create_superuser(
            username='rank-admin',
            email='admin@example.com',
            password='pass',
        )
        self.client.force_login(self.staff)

    def test_changelist_can_sort_by_rank_at_last_login(self):
        low = User.objects.create(username='low-rank')
        high = User.objects.create(username='high-rank')
        UserProfile.objects.create(user=low, osu_id='1', rank_at_last_login=10)
        UserProfile.objects.create(user=high, osu_id='2', rank_at_last_login=5000)

        # Admin prepends the action checkbox, so list_display indexes are shifted by 1.
        rank_index = 1 + list(UserProfileAdmin.list_display).index('get_rank_at_last_login')
        response = self.client.get(
            reverse('admin:echo_userprofile_changelist'),
            {'o': str(rank_index)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rank at last login')
        self.assertContains(response, '#10')
        self.assertContains(response, '#5,000')
        ranks = [obj.rank_at_last_login for obj in response.context['cl'].result_list]
        self.assertEqual(ranks, [10, 5000])

    def test_changelist_has_update_all_ranks_button(self):
        response = self.client.get(reverse('admin:echo_userprofile_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update all ranks')
        self.assertContains(response, reverse('admin:echo_userprofile_refresh_ranks'))

    @patch('echo.admin.threading.Thread')
    def test_refresh_ranks_starts_background_job(self, mock_thread):
        response = self.client.get(reverse('admin:echo_userprofile_refresh_ranks'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Background rank refresh started')
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        self.assertTrue(cache.get(USER_RANK_REFRESH_LOCK_KEY))
        cache.delete(USER_RANK_REFRESH_LOCK_KEY)

    def test_refresh_ranks_rejects_if_already_running(self):
        cache.set(USER_RANK_REFRESH_LOCK_KEY, True)
        try:
            response = self.client.get(reverse('admin:echo_userprofile_refresh_ranks'), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'already running')
        finally:
            cache.delete(USER_RANK_REFRESH_LOCK_KEY)


class FakeOsuApi:
    def __init__(self, ranks=None, errors=None):
        self.ranks = ranks or {}
        self.errors = errors or {}
        self.calls = []

    def user(self, osu_id, key=None):
        self.calls.append(osu_id)
        if osu_id in self.errors:
            raise self.errors[osu_id]
        return SimpleNamespace(
            statistics=SimpleNamespace(global_rank=self.ranks.get(osu_id), rank=None),
            statistics_rulesets=None,
        )


class RefreshAllUserRanksTests(TestCase):
    def test_updates_changed_ranks_and_skips_unchanged(self):
        first = User.objects.create(username='first')
        second = User.objects.create(username='second')
        UserProfile.objects.create(user=first, osu_id='10', rank_at_last_login=None)
        UserProfile.objects.create(user=second, osu_id='20', rank_at_last_login=5)
        api = FakeOsuApi({10: 100, 20: 5})

        result = refresh_all_user_ranks(delay_s=0, wait_for_idle=False, api_client=api)

        self.assertEqual(result, {'updated': 1, 'unchanged': 1, 'failed': 0})
        self.assertEqual(UserProfile.objects.get(osu_id='10').rank_at_last_login, 100)
        self.assertEqual(UserProfile.objects.get(osu_id='20').rank_at_last_login, 5)
        self.assertCountEqual(api.calls, [10, 20])

    def test_counts_api_failures_without_clearing_existing_rank(self):
        user = User.objects.create(username='broken')
        UserProfile.objects.create(user=user, osu_id='30', rank_at_last_login=9)
        api = FakeOsuApi(errors={30: RuntimeError('osu down')})

        result = refresh_all_user_ranks(delay_s=0, wait_for_idle=False, api_client=api)

        self.assertEqual(result, {'updated': 0, 'unchanged': 0, 'failed': 1})
        self.assertEqual(UserProfile.objects.get(osu_id='30').rank_at_last_login, 9)
