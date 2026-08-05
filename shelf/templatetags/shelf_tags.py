from django import template
from django.utils.safestring import mark_safe

from shelf.palette import ink_for
from shelf.ranking import months_between
from django.utils import timezone

register = template.Library()


@register.filter
def ink(essay):
    return ink_for(getattr(essay, "pk", None))


@register.filter
def ink_bg(essay):
    return ink_for(getattr(essay, "pk", None))["bg"]


@register.filter
def ink_fg(essay):
    return ink_for(getattr(essay, "pk", None))["fg"]


@register.filter
def spine_height(essay):
    minutes = getattr(essay, "reading_minutes", 0) or 12
    return 132 + min(104, int(minutes * 2.1))


@register.filter
def half_stars_display(half_stars):
    # A bound form hands back the raw POST string rather than a cleaned int, so this
    # has to cope with "7" as well as 7, and with the junk an unvalidated field allows.
    try:
        value = float(half_stars) / 2
    except (TypeError, ValueError):
        return ""
    if not value:
        return ""
    text = f"{value:g}"
    return mark_safe(f'{text} <em>/ 5</em>')


@register.simple_tag
def circulation_bar(first_year, last_year, still_going, min_year=None, max_year=None):
    """Positions for the engraved-range style timeline bar on discover rows."""
    now_year = timezone.now().year
    lo = min_year if min_year is not None else first_year
    hi = max_year if max_year is not None else now_year
    span = max(1, hi - lo)
    left = ((first_year - lo) / span) * 100
    right = (1 - ((last_year - lo) / span)) * 100
    label_right = "still going" if still_going else f"last {last_year}"
    return {
        "left": f"{left:.1f}",
        "right": f"{right:.1f}",
        "label_left": f"on shelves since {first_year}",
        "label_right": label_right,
    }


@register.filter
def months_ago(dt):
    if not dt:
        return None
    return months_between(dt, timezone.now())
