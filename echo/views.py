# echosu/views.py
"""
Imports all view functions and classes from views/ 
making them available for use in URL routing and other parts of the application.
"""

from importlib import import_module
import pkgutil, pathlib

_pkg = import_module('echosu.views')
_mod_path = pathlib.Path(_pkg.__file__).parent

for m in pkgutil.iter_modules([str(_mod_path)]):
    if not m.ispkg and m.name != '__init__':
        module = import_module(f'echosu.views.{m.name}')
        globals().update({k: v for k, v in module.__dict__.items()
                          if k[0].islower()})

del import_module, pkgutil, pathlib, _pkg, _mod_path
