"""
The Shelf — MVP schema.

Five tables and Django's User. Runs on SQLite in WAL mode; every constraint here is
SQLite-compatible (partial unique indexes and check constraints are both supported).

Two rules survive from the larger design and must not be dropped for convenience:

1.  Shelving is append-only. Un-shelving sets removed_at. The record that somebody held
    a piece in 2019 is the durability signal, and deleting it erases the thing the whole
    product is built on.
2.  Rating and Shelving are separate. Logging is the primary act and a rating is optional
    commentary on top of it, the same order Goodreads and Letterboxd use. Plenty of rows
    will have a Shelving and no Rating, and that is the expected state.

Deferred on purpose, with the trigger for adding each:

- Publication / Author as foreign keys — when you have enough essays that a publication
  page is worth visiting.
- EssayAlias and content-hash dedupe — the first day a user can submit a URL.
- IngestSource / IngestItem — when you want the catalogue to grow without you.
- EssayStats denormalisation — when the ranking annotate shows up in slow query logs.
- Follow — when browsing shelves by hand stops scaling for an active user.
- Report / moderation — before any public write path opens to strangers.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from .palette import ink_for


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Essay(TimestampedModel):
    """
    The permanent object. Everything hangs off it.

    Author and publication are plain text at this size. A join table for 150 rows is
    bookkeeping with no payoff, and promoting them to foreign keys later is a data
    migration rather than a rewrite.
    """

    slug = models.SlugField(max_length=255, unique=True)
    url = models.URLField(max_length=1000, unique=True)

    title = models.CharField(max_length=500)
    author = models.CharField(max_length=300)
    publication = models.CharField(max_length=200, blank=True)
    published_year = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    reading_minutes = models.PositiveSmallIntegerField(default=0)

    # One line on why it is worth reading. Written once, offline, and committed with the seed.
    blurb = models.TextField(blank=True)
    # Plain list of lowercase strings, e.g. ["cities", "policy", "growth"].
    # Similarity is tag overlap, which works from the first essay and needs no index.
    tags = models.JSONField(default=list, blank=True)

    is_published = models.BooleanField(default=True)
    # True for backfilled seed history, so it can be stripped once real activity exists.
    is_seed = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["is_published", "-published_year"])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("essay", args=[self.slug])

    @property
    def ink(self):
        """Riso spine colour, stable per essay, used everywhere the essay appears."""
        return ink_for(self.pk)


class Shelf(TimestampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shelves"
    )
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160)
    description = models.CharField(max_length=280, blank=True)
    is_public = models.BooleanField(default=True)
    # Created at signup so "shelve it" always has somewhere to go.
    is_default = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "slug"], name="uniq_shelf_slug_per_owner"),
            models.UniqueConstraint(
                fields=["owner"], condition=Q(is_default=True), name="one_default_shelf_per_owner"
            ),
        ]

    def __str__(self):
        return f"{self.owner} / {self.name}"

    def get_absolute_url(self):
        return reverse("shelf", args=[self.owner.profile.handle, self.slug])


class Shelving(TimestampedModel):
    """The stamp. One row per (person, essay, shelf). Never hard-deleted."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shelvings"
    )
    essay = models.ForeignKey(Essay, on_delete=models.CASCADE, related_name="shelvings")
    shelf = models.ForeignKey(Shelf, on_delete=models.CASCADE, related_name="shelvings")
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["essay", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["user", "essay", "shelf"], name="uniq_shelving"),
        ]

    @property
    def is_active(self):
        return self.removed_at is None


class Rating(TimestampedModel):
    """
    Half-stars, stored as 1..10 so the column stays an integer. 10 means five stars.
    Same trick Letterboxd uses.

    Ordinal for free: nobody has to work out whether four beats three. That matters at
    the moment of the tap, which is the moment the whole product is competing for.

    Ten points also give the low end teeth. A one-star verdict on a famous essay is a
    statement worth making in public, and a scale that only runs from lukewarm to warm
    has nothing for the person who thought a piece was rubbish.

    Note what this scale is NOT doing: it is not forecasting whether a piece will last.
    Durability is measured behaviourally from Shelving dates, which is a better signal
    than asking somebody ninety seconds after finishing whether they will still care in
    eight months.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings"
    )
    essay = models.ForeignKey(Essay, on_delete=models.CASCADE, related_name="ratings")
    half_stars = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="1..10, where 10 is five stars.",
    )

    class Meta:
        indexes = [models.Index(fields=["essay", "half_stars"])]
        constraints = [
            models.UniqueConstraint(fields=["user", "essay"], name="uniq_rating_per_user_essay"),
            models.CheckConstraint(
                condition=Q(half_stars__gte=1) & Q(half_stars__lte=10),
                name="half_stars_in_range",
            ),
        ]

    @property
    def stars(self):
        return self.half_stars / 2


class Note(TimestampedModel):
    """Optional, unthreaded, and carries no weight in ranking."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    essay = models.ForeignKey(Essay, on_delete=models.CASCADE, related_name="notes")
    body = models.TextField(max_length=2000)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["essay", "-created_at"])]


class Profile(TimestampedModel):
    """Handle and display name. Split from User so auth stays swappable."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    handle = models.SlugField(max_length=40, unique=True)
    display_name = models.CharField(max_length=120, blank=True)
    bio = models.CharField(max_length=280, blank=True)

    def __str__(self):
        return f"@{self.handle}"

    def get_absolute_url(self):
        return reverse("profile", args=[self.handle])

    @property
    def initials(self):
        """Avatar text, taken from the handle rather than the display name.

        The handle is the identity here and it is what sits beside the avatar, so the
        two should agree. Display names are free text and produce nonsense initials
        the moment somebody uses a stopword ("Notes in Margin" gives "NI").
        """
        parts = [p for p in self.handle.replace("-", " ").replace("_", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()
