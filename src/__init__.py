"""Trading system MVP package."""

from __future__ import annotations

import dataclasses as _dataclasses
import sys


if sys.version_info < (3, 10):
    _orig_dataclass = _dataclasses.dataclass

    def _compat_dataclass(*args, **kwargs):
        """Drop unsupported `slots` kwarg for Python < 3.10."""
        kwargs.pop("slots", None)
        return _orig_dataclass(*args, **kwargs)

    _dataclasses.dataclass = _compat_dataclass
