from django.contrib import admin

from .models import Essay, Note, Profile, Rating, Shelf, Shelving


@admin.register(Essay)
class EssayAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "author",
        "publication",
        "published_year",
        "is_published",
        "is_seed",
    )
    list_filter = ("is_published", "is_seed", "published_year")
    search_fields = ("title", "author", "publication", "url", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "is_public", "is_default", "position")
    list_filter = ("is_public", "is_default")
    search_fields = ("name", "owner__username", "owner__profile__handle")


@admin.register(Shelving)
class ShelvingAdmin(admin.ModelAdmin):
    list_display = ("essay", "user", "shelf", "created_at", "removed_at", "is_seed_row")
    list_filter = ("removed_at",)
    search_fields = ("essay__title", "user__username", "user__profile__handle")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="Seed?")
    def is_seed_row(self, obj):
        return obj.essay.is_seed


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("essay", "user", "half_stars", "created_at")
    search_fields = ("essay__title", "user__username")


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("essay", "user", "is_hidden", "created_at")
    list_filter = ("is_hidden",)
    search_fields = ("body", "essay__title", "user__username")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("handle", "display_name", "user")
    search_fields = ("handle", "display_name", "user__username")
