import json

from django.test import TestCase
from django.urls import reverse

from shelf.models import Essay, Log, Rating, Shelving
from shelf.ranking import ranked, score, with_stats
from shelf.services import log_essay
from shelf.tests import PASSWORD, make_essay, make_shelf, make_user, stamp
from shelf.views import _discovery_example, _featured_shelves, _newly_logged


class RouteTests(TestCase):
    def setUp(self):
        self.user = make_user("router")
        self.essay = make_essay("Routed", slug="routed")
        self.shelf = make_shelf(self.user, "Named Shelf", slug="named-shelf")
        stamp(self.user, self.essay, self.shelf, months_ago=5)

    def test_public_pages_render(self):
        for url in [
            reverse("landing"),
            reverse("discover"),
            reverse("essay", args=["routed"]),
            reverse("profile", args=["router"]),
            reverse("shelf", args=["router", "named-shelf"]),
            reverse("signup"),
            reverse("login"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_settings_and_logout_require_a_login(self):
        for name in ("settings", "logout"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                if name == "logout":
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response["Location"], reverse("landing"))
                else:
                    self.assertEqual(response.status_code, 302)
                    self.assertIn(reverse("login"), response["Location"])

    def test_add_requires_a_login(self):
        response = self.client.get(reverse("add"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_unknown_essay_is_a_404(self):
        self.assertEqual(
            self.client.get(reverse("essay", args=["nope"])).status_code, 404
        )

    def test_private_shelf_is_not_public(self):
        make_shelf(self.user, "Private", slug="private", is_public=False)
        self.assertEqual(
            self.client.get(reverse("shelf", args=["router", "private"])).status_code,
            404,
        )

    def test_a_strangers_shelf_is_two_clicks_from_the_landing_page(self):
        """Landing lists a shelf; the shelf lists essays. Two hops, no search."""
        landing = self.client.get(reverse("landing"))
        shelf_url = reverse("shelf", args=["router", "named-shelf"])
        self.assertContains(landing, shelf_url)

        shelf_page = self.client.get(shelf_url)
        self.assertContains(shelf_page, reverse("essay", args=["routed"]))


class ErrorPageTests(TestCase):
    def setUp(self):
        self.user = make_user("errpage")
        self.essay = make_essay("On the shelf", slug="on-the-shelf")
        self.shelf = make_shelf(self.user, "Public picks", slug="public-picks")
        stamp(self.user, self.essay, self.shelf, months_ago=2)

    def test_404_uses_the_styled_error_page_and_logs(self):
        response = self.client.get("/this-path-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "shelf/error.html")
        self.assertContains(response, "This page isn’t on the shelf.", status_code=404)
        self.assertContains(response, "Public shelves", status_code=404)
        self.assertContains(response, "Public picks", status_code=404)
        entry = Log.objects.get(kind="error.404")
        self.assertEqual(entry.status_code, 404)
        self.assertEqual(entry.path, "/this-path-does-not-exist/")

    def test_object_404_is_logged_automatically(self):
        response = self.client.get(reverse("essay", args=["nope"]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            Log.objects.filter(kind="error.404", path=response.wsgi_request.path).exists()
        )


class AccountSettingsTests(TestCase):
    def setUp(self):
        self.user = make_user("setter")
        self.client.login(username="setter", password=PASSWORD)

    def test_settings_page_renders(self):
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account")
        self.assertContains(response, "setter")

    def test_settings_update_handle_and_bio(self):
        response = self.client.post(
            reverse("settings"),
            {
                "handle": "new-setter",
                "display_name": "New Setter",
                "email": "setter@example.com",
                "bio": "Keeps the good ones.",
                "new_password1": "",
                "new_password2": "",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.username, "new-setter")
        self.assertEqual(self.user.profile.handle, "new-setter")
        self.assertEqual(self.user.profile.bio, "Keeps the good ones.")

    def test_logout_page_and_post(self):
        page = self.client.get(reverse("logout"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Log out of")
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("landing"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class LogEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user("tapper")
        self.essay = make_essay("Tappable", slug="tappable")
        self.url = reverse("log", args=["tappable"])

    def _login(self):
        self.client.login(username="tapper", password=PASSWORD)

    def test_anonymous_log_is_sent_to_the_login_page(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(Shelving.objects.exists())

    def test_get_is_not_allowed(self):
        self._login()
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_htmx_log_swaps_the_control_in_place(self):
        self._login()
        response = self.client.post(self.url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Shelving.objects.filter(essay=self.essay).exists())
        # The response is the button partial, not a whole page: no navigation.
        self.assertNotContains(response, "<html")
        self.assertContains(response, 'id="log-tappable"')
        self.assertContains(response, "Logged")

    def test_toast_header_is_valid_json(self):
        self._login()
        response = self.client.post(self.url, HTTP_HX_REQUEST="true")
        self.assertIn("toast", json.loads(response["HX-Trigger"]))

    def test_star_tap_logs_and_rates_together(self):
        self._login()
        self.client.post(self.url, {"half_stars": "7"}, HTTP_HX_REQUEST="true")
        self.assertTrue(Shelving.objects.filter(essay=self.essay).exists())
        self.assertEqual(Rating.objects.get(essay=self.essay).half_stars, 7)

    def test_clearing_a_rating_deletes_it_and_keeps_the_log(self):
        """The star control posts an explicit 0 to clear. Regression test: an empty
        string means 'leave it alone', so clearing used to be unreachable."""
        self._login()
        self.client.post(self.url, {"half_stars": "8"}, HTTP_HX_REQUEST="true")
        response = self.client.post(self.url, {"half_stars": "0"}, HTTP_HX_REQUEST="true")

        self.assertFalse(Rating.objects.filter(essay=self.essay).exists())
        self.assertTrue(
            Shelving.objects.filter(essay=self.essay, removed_at__isnull=True).exists()
        )
        self.assertEqual(json.loads(response["HX-Trigger"])["toast"], "Rating cleared")

    def test_empty_rating_field_leaves_an_existing_rating_alone(self):
        self._login()
        self.client.post(self.url, {"half_stars": "9"}, HTTP_HX_REQUEST="true")
        self.client.post(self.url, {"half_stars": ""}, HTTP_HX_REQUEST="true")
        self.assertEqual(Rating.objects.get(essay=self.essay).half_stars, 9)

    def test_garbage_rating_does_not_500(self):
        self._login()
        response = self.client.post(
            self.url, {"half_stars": "banana"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Rating.objects.filter(essay=self.essay).exists())

    def test_non_htmx_post_falls_back_to_a_redirect(self):
        self._login()
        response = self.client.post(self.url)
        self.assertRedirects(response, self.essay.get_absolute_url())

    def test_logging_is_available_wherever_the_essay_appears(self):
        """Same endpoint from the essay page, a shelf listing and discover."""
        self._login()
        shelf = make_shelf(self.user, "Listing", slug="listing")
        stamp(self.user, self.essay, shelf, months_ago=1)
        for url in [
            self.essay.get_absolute_url(),
            reverse("shelf", args=["tapper", "listing"]),
            reverse("discover"),
        ]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), self.url)


class AddEssayViewTests(TestCase):
    def setUp(self):
        self.user = make_user("adder")
        self.client.login(username="adder", password=PASSWORD)

    def test_add_creates_and_redirects_to_the_new_page(self):
        response = self.client.post(
            reverse("add"),
            {
                "title": "Fresh Thinking",
                "url": "https://example.test/fresh",
                "blurb": "A line of my own about why this matters.",
            },
        )
        essay = Essay.objects.get(url="https://example.test/fresh")
        self.assertRedirects(response, essay.get_absolute_url())
        self.assertTrue(Shelving.objects.filter(user=self.user, essay=essay).exists())

    def test_add_accepts_an_empty_optional_blurb(self):
        response = self.client.post(
            reverse("add_htmx"),
            {
                "title": "No Blurb Needed",
                "url": "https://example.test/no-blurb",
                "blurb": "",
                "form_prefix": "mod",
            },
            HTTP_HX_REQUEST="true",
        )
        essay = Essay.objects.get(url="https://example.test/no-blurb")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], essay.get_absolute_url())
        self.assertEqual(essay.blurb, "")
        self.assertTrue(Shelving.objects.filter(user=self.user, essay=essay).exists())

    def test_htmx_add_reports_the_new_page_and_escapes_the_title(self):
        """A quote in the title must not break the HX-Trigger JSON header."""
        response = self.client.post(
            reverse("add_htmx"),
            {
                "title": 'The "Quoted" Essay',
                "url": "https://example.test/quoted",
                "blurb": "Titles contain quotes and headers are JSON.",
                "form_prefix": "mod",
                "in_modal": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["toast"], 'Added The "Quoted" Essay')
        self.assertTrue(trigger["closeModal"])

    def test_invalid_add_returns_the_form_with_errors(self):
        response = self.client.post(
            reverse("add_htmx"),
            {"title": "", "url": "not-a-url", "blurb": "short"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Essay.objects.exists())
        # The 422 body must carry the re-rendered form, since that is what the
        # client swaps back in. An empty body is a submit button that does nothing.
        self.assertContains(response, 'name="title"', status_code=422)
        self.assertContains(response, "errorlist", status_code=422)

    def test_invalid_add_with_a_star_rating_re_renders_instead_of_erroring(self):
        """A bound form hands the star partial a string, which used to blow up on /."""
        response = self.client.post(
            reverse("add_htmx"),
            {
                "title": "Rated But Wrong",
                "url": "https://example.test/rated-but-wrong",
                "blurb": "too short",
                "half_stars": "7",
                "form_prefix": "sec",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        # The rating the user picked survives the round trip.
        self.assertContains(response, 'value="7"', status_code=422)
        self.assertContains(response, "3.5", status_code=422)
        self.assertFalse(Essay.objects.exists())

    def test_a_short_blurb_alone_still_returns_the_form(self):
        """The commonest near-miss: everything filled in but the blurb is too short."""
        response = self.client.post(
            reverse("add_htmx"),
            {
                "title": "Nearly There",
                "url": "https://example.test/nearly",
                "blurb": "too short",
                "form_prefix": "sec",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Nearly There", status_code=422)
        self.assertFalse(Essay.objects.exists())

    def test_logged_out_htmx_add_is_told_to_navigate_to_the_login_page(self):
        self.client.logout()
        response = self.client.post(
            reverse("add_htmx"),
            {
                "title": "Anonymous",
                "url": "https://example.test/anon",
                "blurb": "A blurb long enough to be valid.",
            },
            HTTP_HX_REQUEST="true",
        )
        # Not a 302: XHR would follow it and swap the login page into the form.
        self.assertEqual(response.status_code, 204)
        self.assertIn(reverse("login"), response["HX-Redirect"])
        self.assertFalse(Essay.objects.exists())

    def test_the_form_partial_is_rendered_into_both_places(self):
        landing = self.client.get(reverse("landing"))
        modal = self.client.get(reverse("add_modal"))
        # Same partial, different id prefix, so the two instances do not collide.
        self.assertContains(landing, 'id="sec-name"')
        self.assertContains(landing, 'id="sec-half"')
        self.assertContains(modal, 'id="mod-name"')
        self.assertContains(modal, 'id="mod-half"')
        self.assertNotContains(modal, 'id="sec-name"')


class DiscoverySurfaceTests(TestCase):
    def setUp(self):
        self.curator = make_user("curator")
        self.named = make_shelf(self.curator, "Institutions", slug="institutions")
        self.bulk = make_user("bulk")
        self.bulk_default = make_shelf(self.bulk, "Your shelf", slug="shelf", is_default=True)

        self.essays = [make_essay(f"Essay {i}", slug=f"essay-{i}") for i in range(12)]
        for i, essay in enumerate(self.essays[:4]):
            stamp(self.curator, essay, self.named, months_ago=i + 1)
        # The default shelf is much bigger, and must still lose to a named one.
        for i, essay in enumerate(self.essays):
            stamp(self.bulk, essay, self.bulk_default, months_ago=i + 1)

    def test_named_shelves_beat_bigger_default_shelves(self):
        featured = _featured_shelves()
        self.assertEqual(featured[0], self.named)

    def test_default_shelves_still_fill_the_grid_when_nothing_is_named(self):
        self.named.delete()
        self.assertIn(self.bulk_default, _featured_shelves())

    def test_the_feed_caps_how_much_one_person_can_take(self):
        feed = _newly_logged(limit=6, per_user=2)
        counts = {}
        for shelving in feed:
            counts[shelving.user_id] = counts.get(shelving.user_id, 0) + 1
        self.assertTrue(all(n <= 2 for n in counts.values()))
        self.assertGreater(len(set(counts)), 1, "one burst must not own the feed")

    def test_the_feed_caps_repeats_of_one_essay(self):
        popular = make_essay("Popular", slug="popular")
        for i in range(6):
            reader = make_user(f"fan{i}")
            stamp(reader, popular, make_shelf(reader, "Your shelf", is_default=True))
        feed = _newly_logged(limit=8, per_essay=2)
        repeats = [s for s in feed if s.essay_id == popular.pk]
        self.assertLessEqual(len(repeats), 2)

    def test_essay_page_lists_named_shelves_only(self):
        response = self.client.get(self.essays[0].get_absolute_url())
        self.assertContains(response, "Institutions")
        self.assertNotContains(response, "Your shelf")

    def test_discovery_example_uses_real_rows(self):
        example = _discovery_example()
        self.assertIsNotNone(example)
        self.assertEqual(example["shelf"], self.named)
        self.assertEqual(len(example["picks"]), 3)
        self.assertNotIn(
            example["found"].pk,
            [e.pk for e in example["picks"]],
            "the suggestion must be something the curator has not already logged",
        )


class NoScoreOnScreenTests(TestCase):
    """Section 9: nothing on the site displays a score."""

    def setUp(self):
        self.user = make_user("viewer")
        self.shelf = make_shelf(self.user, "Kept", slug="kept")
        self.essay = make_essay("Scored", slug="scored", tags=["systems"])
        stamp(self.user, self.essay, self.shelf, months_ago=30)
        log_essay(self.user, self.essay, half_stars=9)

    def test_the_score_value_never_reaches_the_page(self):
        annotated = with_stats(Essay.objects.filter(pk=self.essay.pk)).get()
        value = score(annotated)
        self.assertGreater(value, 0, "guard is meaningless if the score is zero")

        renderings = {f"{value:.2f}", f"{value:.3f}", f"{value:.4f}", str(round(value, 2))}
        for url in [
            reverse("landing"),
            reverse("discover"),
            self.essay.get_absolute_url(),
            reverse("shelf", args=["viewer", "kept"]),
        ]:
            body = self.client.get(url).content.decode()
            for rendering in renderings:
                with self.subTest(url=url, rendering=rendering):
                    self.assertNotIn(rendering, body)

    def test_pages_show_the_record_instead(self):
        response = self.client.get(self.essay.get_absolute_url())
        self.assertContains(response, "logs since")

    def test_discover_shows_a_circulation_range(self):
        response = self.client.get(reverse("discover"))
        self.assertContains(response, "on shelves since")

    def test_ranking_still_orders_by_score(self):
        quiet = make_essay("Quiet", slug="quiet")
        order = ranked(Essay.objects.all())
        self.assertEqual(order[0], self.essay)
        self.assertIn(quiet, order)
