from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from shelf.models import Essay, Rating
from shelf.ranking import circulation, ranked, score, with_stats
from shelf.tests import make_essay, make_shelf, make_user, stamp


class RankingTests(TestCase):
    def setUp(self):
        self.readers = [make_user(f"reader{i}") for i in range(6)]
        self.shelves = {u.id: make_shelf(u, "Shelf", is_default=True) for u in self.readers}

    def _shelve(self, essay, users, months_ago):
        for user in users:
            stamp(user, essay, self.shelves[user.id], months_ago=months_ago)

    def _stats(self, essay):
        return with_stats(Essay.objects.filter(pk=essay.pk)).get()

    def test_long_circulation_outranks_a_recent_spike(self):
        """The whole point of span and alive: a slow burner beats a flash in the pan."""
        enduring = make_essay("Enduring", slug="enduring")
        spike = make_essay("Spike", slug="spike")

        # Enduring: shelved steadily across nine years by six people, still moving.
        for reader, months in zip(self.readers, (108, 84, 60, 36, 12, 0)):
            self._shelve(enduring, [reader], months)
        # Spike: everyone at once, last week, and more of them.
        self._shelve(spike, self.readers, 0)

        order = ranked(Essay.objects.all())
        self.assertEqual(
            [e.slug for e in order][0],
            "enduring",
            "an essay in circulation since 2017 should outrank a one-week spike",
        )

    def test_score_rises_with_rating(self):
        essay = make_essay("Rated", slug="rated")
        self._shelve(essay, self.readers[:3], 2)
        before = score(self._stats(essay))
        for user in self.readers[:3]:
            Rating.objects.create(user=user, essay=essay, half_stars=10)
        after = score(self._stats(essay))
        self.assertGreater(after, before)

    def test_score_is_bounded(self):
        essay = make_essay("Bounded", slug="bounded")
        self._shelve(essay, self.readers, 0)
        Rating.objects.create(user=self.readers[0], essay=essay, half_stars=10)
        value = score(self._stats(essay))
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_unshelved_essay_scores_zero(self):
        essay = make_essay("Lonely", slug="lonely")
        self.assertEqual(score(self._stats(essay)), 0.0)

    def test_removed_shelvings_do_not_prop_up_the_ranking(self):
        essay = make_essay("Abandoned", slug="abandoned")
        self._shelve(essay, self.readers, 3)
        with_history = score(self._stats(essay))

        essay.shelvings.update(removed_at=timezone.now())
        after_removal = score(self._stats(essay))

        self.assertGreater(with_history, after_removal)
        self.assertEqual(after_removal, 0.0)
        self.assertEqual(
            essay.shelvings.count(), 6, "rows must survive removal; only the score drops"
        )

    def test_circulation_reports_facts_not_scores(self):
        essay = make_essay("Circulating", slug="circulating")
        self._shelve(essay, [self.readers[0]], 96)
        self._shelve(essay, [self.readers[1]], 0)
        circ = circulation(self._stats(essay))
        self.assertEqual(circ["first_year"], (timezone.now() - timedelta(days=96 * 30.4)).year)
        self.assertTrue(circ["still_going"])
        self.assertNotIn("score", circ)

    def test_circulation_is_none_before_anything_is_shelved(self):
        essay = make_essay("Fresh", slug="fresh")
        self.assertIsNone(circulation(self._stats(essay)))

    def test_ranked_respects_limit(self):
        for i in range(5):
            make_essay(f"Essay {i}", slug=f"essay-{i}")
        self.assertEqual(len(ranked(Essay.objects.all(), limit=3)), 3)
