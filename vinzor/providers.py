"""Which model this workspace talks to, if any.

There are two providers and there will be more, and without this the choice
between them would be an ``if`` repeated at every place the assistant is
reached -- five in ``server.py`` alone. Repeated branching is how one of them
ends up saying something different from the others: a provider added to four
of five call sites is a chat box that works and a suggestion panel that says
the assistant is not configured.

So the question "is there a model, and whose" is answered once, here.

**The order is Azure first, then Bedrock, and it is deliberate.** Azure is
configured by setting a key; nobody does that by accident. Bedrock, on the
deployed instance, is configured by a role being attached to the machine --
which is ambient, and is exactly the sort of thing that should not silently
win over something a person went and typed. Configure both and the one you
typed is used.

**Neither provider reads a clock and this module does not either.** Bedrock's
signatures are time-scoped, so ``now`` is threaded through from the boundary
that calls in -- ``server.py`` and ``__main__.py``, the two files allowed to
read one. It is required rather than defaulted, because a default here would
be this module reading a clock on behalf of a module that may not.
"""

from __future__ import annotations

import datetime as _datetime
from typing import Any, Callable, Mapping, Optional

from .assist import Drafter, DraftingUnavailable

#: What a caller gets when nothing at all is set up. Not an error: running
#: without an assistant is an ordinary way to run, and every surface that
#: reaches for one already treats this as "there is just no model".
NoModel = DraftingUnavailable


def which(env: Optional[Mapping[str, str]] = None) -> str:
    """``"azure"``, ``"bedrock"``, or ``""`` when there is no model.

    Named rather than boolean because the answer is worth showing: a firm
    should be able to see whose model read its records, and "configured" is
    not that.
    """
    from . import azure, bedrock

    if azure.configured(env):
        return "azure"
    if bedrock.configured(env):
        return "bedrock"
    return ""


def configured(env: Optional[Mapping[str, str]] = None) -> bool:
    """Is there any model to talk to?"""
    return bool(which(env))


def check_region(env: Optional[Mapping[str, str]] = None) -> None:
    """Refuse to start on a provider pointed outside India.

    Called from the boundaries at start-up. Both providers raise
    ``DataResidencyError`` from their own configuration; this only makes sure
    both are asked, so adding a provider cannot quietly skip the check that
    is the point of the whole arrangement.
    """
    from . import azure, bedrock

    azure.check_region(env)
    bedrock.check_region(env)


def drafter(*, now: Callable[[], _datetime.datetime],
            env: Optional[Mapping[str, str]] = None) -> Drafter:
    """The configured drafter, ready for ``assist.prepare_drafts``."""
    from . import azure, bedrock

    chosen = which(env)
    if chosen == "azure":
        return azure.drafter(env=env)
    if chosen == "bedrock":
        return bedrock.drafter(now=now, env=env)
    raise NoModel("the assistant is not configured")


def conversation(*, now: Callable[[], _datetime.datetime],
                 env: Optional[Mapping[str, str]] = None) -> Any:
    """The configured transport for the chat box."""
    from .ask import AskingUnavailable, azure_conversation, bedrock_conversation

    chosen = which(env)
    if chosen == "azure":
        return azure_conversation(env)
    if chosen == "bedrock":
        return bedrock_conversation(now=now, env=env)
    raise AskingUnavailable("the assistant is not configured")


def eyes(*, now: Callable[[], _datetime.datetime],
         env: Optional[Mapping[str, str]] = None) -> Any:
    """The configured reader for photographed documents, or None.

    None rather than an exception, because there being no such reader is an
    ordinary state and not a fault: the product worked without one for its
    whole life and still does, saying plainly that a photograph has to be
    read by a person. The caller passes this straight to ``extraction.read``,
    which reaches for it only where a file has no text to parse.

    Bedrock only, for now. Azure's vision deployments are a separate resource
    from the chat one and this account has none, and a provider named here
    that does not answer would be worse than one that is absent.
    """
    from . import photo

    if which(env) != "bedrock":
        return None
    try:
        return photo.bedrock_eyes(now=now, env=env)
    except Exception:               # noqa: BLE001 - unconfigured is not a fault
        return None
