from django.test import TestCase
from django.utils import timezone

from shelf.models import Essay, Rating, Shelving
from shelf.services import add_essay, default_shelf_for, log_essay, unshelve
from shelf.tests import make_essay, make_user, stamp


class LogEssayTests(TestCase):
    def setUp(self):
        self.user = make_user("logger")
        self.essay = make_essay("A Piece", slug="a-piece")

    def test_log_files_to_the_default_shelf(self):
        result = log_essay(self.user, self.essay)
        self.assertTrue(result.created)
        self.assertEqual(result.shelving.shelf, default_shelf_for(self.user))
        self.assertIsNone(result.shelving.removed_at)

    def test_logging_twice_does_not_duplicate_the_stamp(self):
        log_essay(self.user, self.essay)
        log_essay(self.user, self.essay)
        self.assertEqual(Shelving.objects.filter(essay=self.essay).count(), 1)

    def test_log_without_a_rating_creates_no_rating(self):
        """Rating and Shelving are separate; a log must never imply a verdict."""
        log_essay(self.user, self.essay)
        self.assertFalse(Rating.objects.filter(essay=self.essay).exists())

    def test_log_with_a_rating_does_both_in_one_gesture(self):
        result = log_essay(self.user, self.essay, half_stars=7)
        self.assertTrue(result.created)
        self.assertEqual(result.rating.half_stars, 7)
        self.assertTrue(Shelving.objects.filter(essay=self.essay).exists())

    def test_rating_can_be_changed(self):
        log_essay(self.user, self.essay, half_stars=4)
        log_essay(self.user, self.essay, half_stars=9)
        self.assertEqual(Rating.objects.get(user=self.user, essay=self.essay).half_stars, 9)
        self.assertEqual(Rating.objects.filter(user=self.user, essay=self.essay).count(), 1)

    def test_zero_clears_the_rating_but_keeps_the_log(self):
        log_essay(self.user, self.essay, half_stars=8)
        result = log_essay(self.user, self.essay, half_stars=0)
        self.assertIsNone(result.rating)
        self.assertFalse(Rating.objects.filter(essay=self.essay).exists())
        self.assertTrue(
            Shelving.objects.filter(essay=self.essay, removed_at__isnull=True).exists(),
            "clearing a rating must not un-log the essay",
        )

    def test_none_leaves_an_existing_rating_alone(self):
        log_essay(self.user, self.essay, half_stars=6)
        result = log_essay(self.user, self.essay, half_stars=None)
        self.assertEqual(result.rating.half_stars, 6)

    def test_out_of_range_rating_is_rejected(self):
        with self.assertRaises(ValueError):
            log_essay(self.user, self.essay, half_stars=11)

    def test_relog_restores_a_removed_shelving_without_resetting_the_first_stamp(self):
        shelf = default_shelf_for(self.user)
        original = stamp(self.user, self.essay, shelf, months_ago=40)
        first_stamped = original.created_at

        unshelve(self.user, self.essay)
        result = log_essay(self.user, self.essay)

        self.assertIsNone(result.shelving.removed_at)
        self.assertEqual(
            result.shelving.created_at,
            first_stamped,
            "the original stamp date is the durability signal and must survive a re-log",
        )


class UnshelveTests(TestCase):
    def setUp(self):
        self.user = make_user("keeper")
        self.essay = make_essay("Held", slug="held")

    def test_unshelve_is_a_soft_delete(self):
        log_essay(self.user, self.essay)
        unshelve(self.user, self.essay)
        shelving = Shelving.objects.get(user=self.user, essay=self.essay)
        self.assertIsNotNone(shelving.removed_at)
        self.assertFalse(shelving.is_active)

    def test_unshelve_never_removes_the_row(self):
        log_essay(self.user, self.essay)
        unshelve(self.user, self.essay)
        self.assertEqual(
            Shelving.objects.filter(user=self.user, essay=self.essay).count(),
            1,
            "the record that somebody held this is the thing the product is built on",
        )

    def test_unshelve_leaves_the_rating_in_place(self):
        log_essay(self.user, self.essay, half_stars=8)
        unshelve(self.user, self.essay)
        self.assertTrue(Rating.objects.filter(user=self.user, essay=self.essay).exists())


class AddEssayTests(TestCase):
    def setUp(self):
        self.user = make_user("submitter")

    def test_add_creates_the_essay_and_logs_it_for_the_submitter(self):
        result = add_essay(
            self.user,
            title="Something New",
            url="https://example.test/new",
            blurb="A line in my own words about it.",
        )
        self.assertTrue(result.created)
        self.assertEqual(result.essay.title, "Something New")
        self.assertTrue(
            Shelving.objects.filter(user=self.user, essay=result.essay).exists(),
            "adding is itself a log, so the submitter is first on the new page",
        )

    def test_url_is_normalised_on_the_way_in(self):
        result = add_essay(
            self.user,
            title="Tracked",
            url="https://WWW.example.test/tracked/?utm_source=x",
            blurb="A line in my own words about it.",
        )
        self.assertEqual(result.essay.url, "https://example.test/tracked")

    def test_a_duplicate_submission_logs_the_existing_essay_instead_of_erroring(self):
        existing = make_essay("Already Here", slug="already-here", url="https://example.test/dupe")
        other = make_user("someone-else")

        result = add_essay(
            other,
            title="Already Here, Retitled",
            url="http://www.example.test/dupe/?ref=hn",
            blurb="A duplicate submission is somebody telling you they rate it.",
        )

        self.assertEqual(result.essay, existing)
        self.assertEqual(Essay.objects.count(), 1)
        self.assertTrue(Shelving.objects.filter(user=other, essay=existing).exists())

    def test_collision_can_carry_a_rating(self):
        make_essay("Known", slug="known", url="https://example.test/known")
        result = add_essay(
            self.user,
            title="Known",
            url="https://example.test/known",
            blurb="Rating a piece that is already here.",
            half_stars=10,
        )
        self.assertEqual(result.rating.half_stars, 10)

    def test_slug_collisions_are_resolved(self):
        add_essay(
            self.user,
            title="Same Title",
            url="https://example.test/one",
            blurb="First of two with the same title.",
        )
        add_essay(
            self.user,
            title="Same Title",
            url="https://example.test/two",
            blurb="Second of two with the same title.",
        )
        self.assertEqual(Essay.objects.count(), 2)
        self.assertEqual(len(set(Essay.objects.values_list("slug", flat=True))), 2)

    def test_blank_url_is_rejected(self):
        with self.assertRaises(ValueError):
            add_essay(self.user, title="No URL", url="", blurb="Fifteen characters here.")


class ProfileTests(TestCase):
    def test_signup_creates_a_profile_and_a_default_shelf(self):
        user = make_user("newcomer")
        self.assertEqual(user.profile.handle, "newcomer")
        shelf = user.shelves.filter(is_default=True).first()
        self.assertIsNotNone(shelf, "shelve it must always have somewhere to go")
        self.assertTrue(shelf.is_public)

    def test_initials_come_from_the_handle_not_the_display_name(self):
        user = make_user("tom")
        user.profile.display_name = "Notes in Margin"
        user.profile.save()
        self.assertEqual(user.profile.initials, "TO")

    def test_initials_split_on_hyphens(self):
        user = make_user("jane-pike")
        self.assertEqual(user.profile.initials, "JP")
