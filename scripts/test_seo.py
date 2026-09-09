"""Run SEO integration tests against a temporary database without external API calls."""

import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'echoOsu.settings')

from django.core.management import execute_from_command_line

if __name__ == '__main__':
    # The existing app initializes authenticated osu! clients during import.
    # SEO tests exercise real Django views/queries/templates but need no osu! API.
    with patch('ossapi.Ossapi'), patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network request')):
        execute_from_command_line(['manage.py', 'test', 'echo.tests.test_seo', *sys.argv[1:]])
