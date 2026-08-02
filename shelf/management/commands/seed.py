"""Load the curated catalogue and backfill plausible shelving history.

Idempotent on essay URL. Seed shelvings and notes are marked via Essay.is_seed and
via seed curator usernames so they can be stripped once real activity exists.

    manage.py seed
    manage.py seed --flush-seed   # remove seed users/shelvings/notes, keep essays
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from shelf.models import Essay, Note, Rating, Shelf, Shelving
from shelf.urlnorm import normalise_url

User = get_user_model()

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "seed_essays.json"

CURATORS = [
    {
        "username": "tom",
        "handle": "tom",
        "display_name": "Notes in Margin",
        "bio": "Building The Shelf. Logging the ones I go back to.",
        "shelves": [
            {
                "name": "Recent strong reads",
                "slug": "recent-strong-reads",
                "desc": "The last two years, only the ones I went back to.",
                "match": ["marginal", "peer", "great", "einstein", "housing", "tyranny"],
            },
            {
                "name": "Operator essays that held up",
                "slug": "operator-essays",
                "desc": "Read while building. All survived a reread three years on.",
                "match": ["detail", "fast", "maker", "allowed", "slack", "complex", "bitter"],
            },
            {
                "name": "New voices",
                "slug": "new-voices",
                "desc": "Independent writers nobody was listing five years ago.",
                "match": ["peer", "marginal", "einstein", "tyranny", "biology"],
            },
        ],
    },
    {
        "username": "marginalia",
        "handle": "marginalia",
        "display_name": "Marginalia",
        "bio": "First principles, preferably the uncomfortable ones.",
        "shelves": [
            {
                "name": "First principles, properly",
                "slug": "first-principles",
                "desc": "Pieces that rebuild an idea rather than summarise one.",
                "match": ["bitter", "cook", "legibility", "hamming", "copenhagen", "moloch"],
            },
        ],
    },
    {
        "username": "jpike",
        "handle": "jpike",
        "display_name": "J. Pike",
        "bio": "Six years of arguing about why school keeps missing.",
        "shelves": [
            {
                "name": "How anyone learns anything",
                "slug": "how-anyone-learns",
                "desc": "Curriculum, retention, and the essays that changed both.",
                "match": ["books", "biology", "einstein", "hamming", "matuschak", "norvig"],
            },
        ],
    },
    {
        "username": "holloway",
        "handle": "holloway",
        "display_name": "Holloway",
        "bio": "Institutions, and why they rot.",
        "shelves": [
            {
                "name": "Institutions, and why they rot",
                "slug": "institutions",
                "desc": "Read in order. The last only works after the first three.",
                "match": ["peer", "legibility", "complex", "moloch", "build", "cost disease"],
            },
        ],
    },
]

SEED_NOTES = [
    ("moloch", "holloway", "The trap it describes is not a failure of anyone in particular, which is exactly why it keeps happening. I reread it every time a team argues about metrics."),
    ("moloch", "marginalia", "Overlong in the middle third. Still the best thing on the shelf."),
    ("detail", "jpike", "Handed this to two junior engineers this year. Both estimates improved immediately."),
    ("maker", "tom", "Seventeen years old and I have quoted it in a calendar invite this month."),
    ("peer", "marginalia", "Reread after a grant rejection. Holds up, annoyingly."),
    ("marginal", "tom", "The bit about optimising for the person who barely opens the app explains about eight products I have stopped using."),
    ("books", "jpike", "Pairs with the biology one. Same complaint, different room."),
    ("hamming", "holloway", "The door-open section still rearranges how I think about collaboration."),
    ("bitter", "marginalia", "Shorter than most blog posts. Ended more arguments than most books."),
    ("complex", "holloway", "Sitting on my shelf since 2011. That is the whole product thesis in one line."),
]


def _parse_month(s: str) -> datetime:
    year, month = map(int, s.split("-"))
    return datetime(year, month, 15, 12, 0, 0, tzinfo=dt_timezone.utc)


def _title_match(essay: Essay, needles: list[str]) -> bool:
    hay = f"{essay.title} {essay.slug}".lower()
    return any(n.lower() in hay for n in needles)


class Command(BaseCommand):
    help = "Load seed_essays.json and backfill seed shelving history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush-seed",
            action="store_true",
            help="Remove seed curators, their shelvings/notes/ratings, keep essays.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush_seed"]:
            self._flush_seed()
            return

        rng = random.Random(31072026)
        essays = self._load_essays()
        self.stdout.write(f"Catalogue: {len(essays)} essays")

        curators = self._ensure_curators()
        self._populate_named_shelves(essays, curators, rng)
        self._backfill_history(essays, curators, rng)
        self._seed_notes(essays, curators)
        self._seed_ratings(essays, curators, rng)

        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _flush_seed(self):
        from django.db.models import Q

        names = [c["username"] for c in CURATORS]
        users = User.objects.filter(
            Q(username__in=names) | Q(username__startswith="seedreader")
        )
        Shelving.objects.filter(user__in=users).delete()
        Rating.objects.filter(user__in=users).delete()
        Note.objects.filter(user__in=users).delete()
        Shelf.objects.filter(owner__in=users).delete()
        users.delete()
        # Essays stay; clear the seed flag so real activity is unambiguous later.
        Essay.objects.filter(is_seed=True).update(is_seed=False)
        self.stdout.write(self.style.SUCCESS("Flushed seed curators and history."))

    def _load_essays(self) -> list[Essay]:
        raw = json.loads(SEED_PATH.read_text())
        loaded = []
        for row in raw:
            url = normalise_url(row["url"])
            slug_base = slugify(row["title"])[:220] or "essay"
            essay, created = Essay.objects.update_or_create(
                url=url,
                defaults={
                    "slug": self._unique_slug(slug_base, url),
                    "title": row["title"],
                    "author": row["author"],
                    "publication": row.get("publication") or "",
                    "published_year": row.get("year"),
                    "reading_minutes": row.get("minutes") or 0,
                    "blurb": row.get("blurb") or "",
                    "tags": row.get("tags") or [],
                    "is_published": True,
                    "is_seed": True,
                },
            )
            # Stash history on the instance for backfill; not a model field.
            essay._seed_first = row.get("first")
            essay._seed_last = row.get("last")
            essay._seed_n = row.get("n")
            loaded.append(essay)
            if created:
                self.stdout.write(f"  + {essay.title}")
        return loaded

    def _unique_slug(self, base: str, url: str) -> str:
        existing = Essay.objects.filter(url=url).first()
        if existing:
            return existing.slug
        candidate = base
        n = 2
        while Essay.objects.filter(slug=candidate).exists():
            suffix = f"-{n}"
            candidate = f"{base[: 255 - len(suffix)]}{suffix}"
            n += 1
        return candidate

    def _ensure_curators(self) -> dict:
        out = {}
        for spec in CURATORS:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={"email": f"{spec['username']}@seed.theshelf.local"},
            )
            if created:
                user.set_password("seed-password-change-me")
                user.save()
            profile = user.profile
            profile.handle = spec["handle"]
            profile.display_name = spec["display_name"]
            profile.bio = spec["bio"]
            profile.save()
            # Named shelves (in addition to the default created by signal).
            for s in spec["shelves"]:
                Shelf.objects.get_or_create(
                    owner=user,
                    slug=s["slug"],
                    defaults={
                        "name": s["name"],
                        "description": s["desc"],
                        "is_public": True,
                        "is_default": False,
                        "position": 1,
                    },
                )
            out[spec["username"]] = {"user": user, "spec": spec}
        return out

    def _populate_named_shelves(self, essays, curators, rng):
        """Fill the curated shelves, spreading the stamps over recent weeks.

        Stamping them all at import time would give every row the same created_at,
        and the newly-logged feed would open on one person filing eight things in the
        same second. Real shelves are built a piece at a time.
        """
        now = timezone.now()
        planned = []
        for bundle in curators.values():
            user = bundle["user"]
            for s in bundle["spec"]["shelves"]:
                shelf = Shelf.objects.get(owner=user, slug=s["slug"])
                matches = [e for e in essays if _title_match(e, s["match"])][:8]
                if not matches:
                    matches = rng_sample(essays, 4)
                for essay in matches:
                    planned.append((user, essay, shelf))

        rng.shuffle(planned)
        for i, (user, essay, shelf) in enumerate(planned):
            # Newest first through the list, back to roughly ten weeks ago.
            when = now - timedelta(
                hours=i * 5 + rng.randint(0, 4), minutes=rng.randint(0, 59)
            )
            self._stamp(user, essay, shelf, when=when, force_when=True)

    def _backfill_history(self, essays, curators, rng):
        """Create many seed shelvings so log counts and timelines have something to show."""
        users = [b["user"] for b in curators.values()]
        # Extra synthetic seed readers so volume looks real without inventing personas in the UI.
        extras = []
        for i in range(1, 161):
            u, created = User.objects.get_or_create(
                username=f"seedreader{i:03d}",
                defaults={"email": f"seedreader{i:03d}@seed.theshelf.local"},
            )
            if created:
                u.set_password("seed-password-change-me")
                u.save()
            # Keep handle in sync for re-runs; these accounts are marked as seed.
            profile = u.profile
            profile.handle = f"reader{i:03d}"
            profile.display_name = f"Seed Reader {i}"
            profile.bio = "Seed account. Strip with manage.py seed --flush-seed."
            profile.save()
            extras.append(u)
        pool = users + extras

        for essay in essays:
            n = essay._seed_n
            first = essay._seed_first
            last = essay._seed_last
            if not n or not first or not last:
                # Light backfill even without explicit history.
                n = rng.randint(12, 60)
                year = essay.published_year or 2018
                first = f"{max(year, 2008)}-06"
                last = "2026-06"

            start = _parse_month(first)
            end = _parse_month(last)
            if end <= start:
                end = start + timedelta(days=90)

            # Cap synthetic rows: enough for timelines and log counts, not a dump.
            target = min(int(n), 140)
            already = set(
                Shelving.objects.filter(essay=essay).values_list("user_id", flat=True)
            )
            need = max(0, target - len(already))
            # Prefer unused readers so the unique (user, essay, shelf) constraint
            # does not silently no-op and leave famous pieces under-counted.
            unused = [u for u in pool if u.id not in already]
            rng.shuffle(unused)
            defaults = {
                u.id: u.shelves.filter(is_default=True).first() for u in unused[:need]
            }
            for i in range(need):
                user = unused[i] if i < len(unused) else rng.choice(pool)
                shelf = defaults.get(user.id) or user.shelves.filter(is_default=True).first()
                if shelf is None:
                    continue
                frac = rng.random() ** 1.4  # bias toward more recent stamps
                when = start + (end - start) * frac
                self._stamp(user, essay, shelf, when=when)

    def _stamp(self, user, essay, shelf, when=None, force_when=False):
        shelving, created = Shelving.objects.get_or_create(
            user=user, essay=essay, shelf=shelf, defaults={}
        )
        if when is not None and (created or force_when):
            # Bypass auto_now_add by updating after create. force_when re-dates rows
            # on a re-run, which keeps the curated shelves reading as recent activity
            # however long ago the database was first seeded.
            Shelving.objects.filter(pk=shelving.pk).update(
                created_at=when, updated_at=when
            )

    def _seed_notes(self, essays, curators):
        by_slug_part = essays
        for needle, username, body in SEED_NOTES:
            essay = next((e for e in by_slug_part if needle in e.slug or needle in e.title.lower()), None)
            if not essay:
                continue
            user = curators[username]["user"]
            Note.objects.get_or_create(
                user=user,
                essay=essay,
                body=body,
                defaults={"is_hidden": False},
            )

    def _seed_ratings(self, essays, curators, rng):
        for username, bundle in curators.items():
            user = bundle["user"]
            logged = list(
                Shelving.objects.filter(user=user, removed_at__isnull=True).values_list(
                    "essay_id", flat=True
                )
            )
            for essay_id in logged:
                if rng.random() < 0.55:
                    Rating.objects.update_or_create(
                        user=user,
                        essay_id=essay_id,
                        defaults={"half_stars": rng.choice([6, 7, 8, 8, 9, 9, 10])},
                    )


def rng_sample(items, k):
    rng = random.Random(31072026)
    return rng.sample(list(items), min(k, len(items)))
