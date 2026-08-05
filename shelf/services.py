"""Write paths for logging and adding essays.

Logging is the identity act. Rating is commentary on top of it. Both go through here so
every surface — essay page, shelf listing, discover — hits the same code and swaps the
same button partial.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Essay, Note, Rating, Shelf, Shelving
from .urlnorm import normalise_url


class LogResult:
    __slots__ = ("shelving", "rating", "created", "essay")

    def __init__(self, *, essay, shelving, rating=None, created=False):
        self.essay = essay
        self.shelving = shelving
        self.rating = rating
        self.created = created


def default_shelf_for(user) -> Shelf:
    shelf = user.shelves.filter(is_default=True).first()
    if shelf:
        return shelf
    return Shelf.objects.create(
        owner=user,
        name="Your shelf",
        slug="shelf",
        description="Everything I have logged.",
        is_public=True,
        is_default=True,
        position=0,
    )


@transaction.atomic
def log_essay(user, essay, *, half_stars=None, shelf=None) -> LogResult:
    """File an essay to the user's default shelf. Optionally rate in the same gesture.

    Re-logging an already-active shelving is a no-op on the shelving row (the stamp
    already exists). Clearing a rating is done by passing half_stars=0.
    """
    shelf = shelf or default_shelf_for(user)
    shelving, created = Shelving.objects.get_or_create(
        user=user,
        essay=essay,
        shelf=shelf,
        defaults={},
    )
    if shelving.removed_at is not None:
        # Soft-deleted earlier: restore it. The original created_at stays — the
        # first stamp is the durability signal, and resetting it would erase that.
        shelving.removed_at = None
        shelving.save(update_fields=["removed_at", "updated_at"])
        created = True

    rating = None
    if half_stars is not None:
        if half_stars == 0:
            Rating.objects.filter(user=user, essay=essay).delete()
        elif 1 <= half_stars <= 10:
            rating, _ = Rating.objects.update_or_create(
                user=user,
                essay=essay,
                defaults={"half_stars": half_stars},
            )
        else:
            raise ValueError("half_stars must be 0..10")
    else:
        rating = Rating.objects.filter(user=user, essay=essay).first()

    return LogResult(essay=essay, shelving=shelving, rating=rating, created=created)


@transaction.atomic
def unshelve(user, essay, *, shelf=None) -> None:
    """Soft-delete. Never hard-delete a shelving row."""
    qs = Shelving.objects.filter(user=user, essay=essay, removed_at__isnull=True)
    if shelf is not None:
        qs = qs.filter(shelf=shelf)
    qs.update(removed_at=timezone.now())


def unique_essay_slug(title: str) -> str:
    base = slugify(title)[:220] or "essay"
    candidate = base
    n = 2
    while Essay.objects.filter(slug=candidate).exists():
        suffix = f"-{n}"
        candidate = f"{base[: 255 - len(suffix)]}{suffix}"
        n += 1
    return candidate


@transaction.atomic
def add_essay(user, *, title, url, blurb, half_stars=None) -> LogResult:
    """Create an essay (or collide onto an existing one) and log it for the submitter.

    On a URL collision we do not error. A duplicate submission is somebody telling you
    they rate a piece — show the existing essay and log it for them.
    """
    normalised = normalise_url(url)
    if not normalised:
        raise ValueError("URL is required")

    essay = Essay.objects.filter(url=normalised).first()
    created_essay = False
    if essay is None:
        essay = Essay.objects.create(
            slug=unique_essay_slug(title),
            url=normalised,
            title=title.strip(),
            submitted_by=user,
            author=user.profile.display_name or f"@{user.profile.handle}",
            publication="",
            published_year=None,
            reading_minutes=0,
            blurb=blurb.strip(),
            tags=[],
            is_published=True,
            is_seed=False,
        )
        created_essay = True

    result = log_essay(user, essay, half_stars=half_stars)
    result.created = created_essay or result.created
    return result


def add_note(user, essay, body: str) -> Note:
    body = (body or "").strip()
    if not body:
        raise ValueError("Note body is required")
    return Note.objects.create(user=user, essay=essay, body=body[:2000])


def user_has_logged(user, essay) -> bool:
    if not user.is_authenticated:
        return False
    return Shelving.objects.filter(
        user=user, essay=essay, removed_at__isnull=True
    ).exists()


def user_rating(user, essay):
    if not user.is_authenticated:
        return None
    return Rating.objects.filter(user=user, essay=essay).first()
