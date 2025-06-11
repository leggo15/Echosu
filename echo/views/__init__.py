# echosu/views/__init__.py

# This file makes the 'views' directory a Python package.
# It imports all the view functions and classes from the other modules
# in this directory, so they can be easily accessed from urls.py.

from .auth import *
from .beatmap import *
from .tags import *
from .search import *
from .home import *
from .profile import *
from .settings import *
from .api import *
from .misc import *
