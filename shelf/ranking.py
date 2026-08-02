"""Ordering for essay lists.

No denormalised stats table. At 150 essays we annotate and sort in Python. Add a cached
stats table when this annotate shows up in slow query logs, and not before.

The score orders lists and is never rendered. What gets shown is the record underneath
it: "on shelves since 2008", "still going". Facts, not the algorithm's opinion of them.
"""

from math import exp, log

from django.db.models import Avg, Count, Max, Min, Q
from django.utils import timezone

VOLUME_CEILING = log(1201)
ALIVE_HALFLIFE_MONTHS = 16
SPAN_CEILING_MONTHS = 96  # eight years of circulation counts as a full span

WEIGHTS = {"hold": 0.40, "volume": 0.16, "alive": 0.20, "span": 0.24}


def with_stats(qs):
    """Annotate the counts and dates every list view needs.

    Only active shelvings count towards volume and dates. A removed shelving keeps its
    row — that is the append-only rule — but it should not keep propping up a ranking.
    """
    active = Q(shelvings__removed_at__isnull=True)
    return qs.annotate(
        avg_hold=Avg("ratings__half_stars"),
        n_shelvings=Count("shelvings", filter=active, distinct=True),
        first_shelved=Min("shelvings__created_at", filter=active),
        last_shelved=Max("shelvings__created_at", filter=active),
    )


def months_between(earlier, later):
    if earlier is None or later is None:
        return 0
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(0, months)


def score(essay, now=None):
    """Score an essay annotated by with_stats(). Never render this."""
    now = now or timezone.now()

    avg = getattr(essay, "avg_hold", None)
    hold = (float(avg) - 1) / 9 if avg else 0.0

    n = getattr(essay, "n_shelvings", 0) or 0
    volume = min(1.0, log(1 + n) / VOLUME_CEILING)

    first = getattr(essay, "first_shelved", None)
    last = getattr(essay, "last_shelved", None)

    alive = exp(-months_between(last, now) / ALIVE_HALFLIFE_MONTHS) if last else 0.0
    span = min(1.0, months_between(first, last) / SPAN_CEILING_MONTHS) if first else 0.0

    return (
        WEIGHTS["hold"] * hold
        + WEIGHTS["volume"] * volume
        + WEIGHTS["alive"] * alive
        + WEIGHTS["span"] * span
    )


def ranked(qs, limit=None, now=None):
    """Materialise a queryset in score order. Returns a list, not a queryset."""
    now = now or timezone.now()
    essays = sorted(with_stats(qs), key=lambda e: score(e, now), reverse=True)
    return essays[:limit] if limit else essays


def circulation(essay, now=None):
    """The bar under a discover row: where an essay's run sits, in plain facts.

    Returns None when nothing has been shelved yet, so the template can skip the bar
    rather than draw an empty one.
    """
    now = now or timezone.now()
    first = getattr(essay, "first_shelved", None)
    last = getattr(essay, "last_shelved", None)
    if not first:
        return None
    months_quiet = months_between(last, now)
    return {
        "first_year": first.year,
        "last_year": last.year,
        "still_going": months_quiet <= 1,
        "months_quiet": months_quiet,
    }
