"""One rule about enums, enforced across the package rather than per file.

``class X(str, Enum)`` inherits ``Enum.__str__``, so ``str(X.A)`` returns
``"X.A"`` and not ``"A"``. That value then flows into hashes, JSON, and --
twice now -- onto a screen a compliance officer reads. ``model.StrEnum``
exists to prevent it.

The trap was found by hand twice: ``Ground``/``Level`` in enforcement.py after
"Ground.SCOPE" reached the rendered regulatory page, and ``Status``/
``Conclusion`` here. Both times the fix was one word. Finding it a third time
by reading a screen would be a failure of this test suite, not of the author.
"""

from __future__ import annotations

import enum
import importlib
import pkgutil

import vinzor
from vinzor.model import StrEnum


def _every_enum():
    """Every enum defined anywhere in the package, with where it lives."""
    seen = set()
    for info in pkgutil.iter_modules(vinzor.__path__):
        module = importlib.import_module(f"vinzor.{info.name}")
        for name in dir(module):
            value = getattr(module, name)
            if not isinstance(value, type) or not issubclass(value, enum.Enum):
                continue
            if value in (enum.Enum, enum.IntEnum, StrEnum):
                continue
            if value.__module__ != module.__name__:
                continue  # imported from elsewhere; counted at its origin
            if value in seen:
                continue
            seen.add(value)
            yield module.__name__, value


def test_there_are_enums_to_check():
    """A sweep that walks nothing passes for the wrong reason."""
    found = list(_every_enum())
    assert len(found) >= 15, f"only found {len(found)} enums; the walk is broken"


def test_every_string_enum_stringifies_to_its_value():
    offenders = []
    for where, kind in _every_enum():
        if not issubclass(kind, str):
            continue
        member = next(iter(kind), None)
        if member is None:
            continue
        if str(member) != member.value:
            offenders.append(
                f"{where}.{kind.__name__}: str() gives {str(member)!r}, "
                f"not {member.value!r} -- inherit from model.StrEnum"
            )
    assert not offenders, "enums that poison anything they touch:\n  " + \
        "\n  ".join(offenders)


def test_the_guard_would_catch_a_new_one():
    """Written because the two real offenders are now fixed: without this,
    nobody would ever see this test fail."""

    class Sloppy(str, enum.Enum):
        A = "A"

    assert str(Sloppy.A) != Sloppy.A.value

    class Careful(StrEnum):
        A = "A"

    assert str(Careful.A) == Careful.A.value
