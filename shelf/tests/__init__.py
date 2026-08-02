"""Test helpers shared across the suite."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from shelf.models import Essay, Shelf, Shelving

User = get_user_model()

PASSWORD = "not-a-real-password-1"


def make_user(handle, **kwargs):
    """A user with the profile and default shelf the signal creates at signup."""
    user = User.objects.create_user(
        username=handle, email=f"{handle}@example.test", password=PASSWORD, **kwargs
    )
    profile = user.profile
    profile.handle = handle
    profile.save(update_fields=["handle", "updated_at"])
    return user


def make_essay(title, *, slug=None, url=None, tags=None, year=2015, **kwargs):
    base = slug or title.lower().replace(" ", "-").replace(",", "")
    return Essay.objects.create(
        slug=base,
        url=url or f"https://example.test/{base}",
        title=title,
        author=kwargs.pop("author", "A Writer"),
        publication=kwargs.pop("publication", "Somewhere"),
        published_year=year,
        reading_minutes=kwargs.pop("reading_minutes", 12),
        blurb=kwargs.pop("blurb", "Worth the time."),
        tags=tags if tags is not None else ["systems"],
        **kwargs,
    )


def make_shelf(owner, name, *, slug=None, is_default=False, is_public=True):
    if is_default:
        # Signup already made one, and the schema allows exactly one per owner.
        shelf = owner.shelves.get(is_default=True)
        shelf.name = name
        shelf.is_public = is_public
        shelf.save()
        return shelf
    return Shelf.objects.create(
        owner=owner,
        name=name,
        slug=slug or name.lower().replace(" ", "-"),
        is_default=False,
        is_public=is_public,
    )


def stamp(user, essay, shelf, *, months_ago=None, when=None):
    """Create a shelving at a chosen time, working around auto_now_add."""
    shelving = Shelving.objects.create(user=user, essay=essay, shelf=shelf)
    if months_ago is not None and when is None:
        when = timezone.now() - timedelta(days=int(months_ago * 30.4))
    if when is not None:
        Shelving.objects.filter(pk=shelving.pk).update(created_at=when, updated_at=when)
        shelving.refresh_from_db()
    return shelving
