"""Mobile keyword entrypoint.

Session support covers both Appium and WDA-direct backends. Importing the
submodules triggers keyword registration. The Appium package remains optional
and lazily loaded.
"""

from . import session       # noqa: F401
from . import element       # noqa: F401
from . import misc          # noqa: F401
from . import ios_alert     # noqa: F401

__all__ = ["session", "element", "misc", "ios_alert"]
