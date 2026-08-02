"""Signup side-effects: a Profile and a default shelf for every new user.

"Log it" always has somewhere to go. Without a default shelf the primary action would
have to open a picker, and that is the two-decision flow the product is built to avoid.
"""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, Shelf

User = get_user_model()


@receiver(post_save, sender=User)
def ensure_profile_and_default_shelf(sender, instance, created, **kwargs):
    if not created:
        return

    handle = _unique_handle(instance.username)
    Profile.objects.get_or_create(
        user=instance,
        defaults={
            "handle": handle,
            "display_name": instance.get_full_name() or instance.username,
        },
    )
    Shelf.objects.get_or_create(
        owner=instance,
        is_default=True,
        defaults={
            "name": "Your shelf",
            "slug": "shelf",
            "description": "Everything I have logged.",
            "is_public": True,
            "position": 0,
        },
    )


def _unique_handle(seed: str) -> str:
    from django.utils.text import slugify

    base = slugify(seed)[:36] or "reader"
    candidate = base
    n = 2
    while Profile.objects.filter(handle=candidate).exists():
        suffix = f"-{n}"
        candidate = f"{base[: 40 - len(suffix)]}{suffix}"
        n += 1
    return candidate
