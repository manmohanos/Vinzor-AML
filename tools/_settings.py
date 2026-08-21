"""The same settings the product reads, for the scripts that measure it.

``vinzor/__main__.py`` loads ``.env`` on start-up; a script under ``tools/``
never went near it. So a tool and the product could be -- and were --
configured differently while appearing to test the same thing.

``against_real_lists.py`` is the case that proved it. It defaulted to
``VINZOR_SCREENING_SCOPE=sanctions``; the repo's own ``.env`` sets ``default``,
and the index on the machine is ``yente-entities-default-…`` with 3,989,103
documents. There is no ``sanctions`` index, and Elasticsearch answers a
wildcard matching nothing with HTTP 200 and zero hits -- so the tool drew zero
listed people, screened 25 invented ones against an empty scope, and printed::

    0 genuinely listed people, 25 invented ones
    caught, of people really on a list   0/0
    quiet, of people on no list at all   25/25
    exit 0

Both halves vacuous, neither saying so, and a clean exit code so nothing
downstream could notice. Run with the scope the product actually uses, the
same tool reports recall 25/25 and a **20% false-positive rate** -- a real
calibration finding it was hiding from its own author.

Import this before reading any ``VINZOR_*`` variable::

    from _settings import load
    load()
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def load() -> None:
    """Read the project's ``.env`` exactly as the product does.

    A variable already set in the real environment still wins, which is what
    lets ``VINZOR_SCREENING_SCOPE=default python tools/...`` override it for
    one run.
    """
    from vinzor.__main__ import _load_dotenv

    _load_dotenv(_ROOT / ".env")
