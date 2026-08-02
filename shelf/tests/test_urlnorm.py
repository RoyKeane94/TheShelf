from django.test import SimpleTestCase

from shelf.urlnorm import host_of, normalise_url


class NormaliseUrlTests(SimpleTestCase):
    def test_lowercases_host_and_strips_www(self):
        self.assertEqual(
            normalise_url("https://WWW.Example.COM/essays/one"),
            "https://example.com/essays/one",
        )

    def test_drops_trailing_slash(self):
        self.assertEqual(
            normalise_url("https://example.com/essays/one/"),
            "https://example.com/essays/one",
        )

    def test_drops_tracking_parameters_but_keeps_real_ones(self):
        self.assertEqual(
            normalise_url(
                "https://example.com/p?utm_source=twitter&ref=hn&id=7&utm_campaign=x"
            ),
            "https://example.com/p?id=7",
        )

    def test_drops_fragment(self):
        self.assertEqual(
            normalise_url("https://example.com/p#section-3"),
            "https://example.com/p",
        )

    def test_upgrades_scheme_and_supplies_missing_one(self):
        self.assertEqual(normalise_url("example.com/p"), "https://example.com/p")
        self.assertEqual(normalise_url("http://example.com/p"), "https://example.com/p")

    def test_variants_of_the_same_page_converge(self):
        variants = [
            "http://www.example.com/essays/one/?utm_medium=email",
            "https://Example.com/essays/one",
            "example.com/essays/one/#top",
        ]
        self.assertEqual(len({normalise_url(v) for v in variants}), 1)

    def test_empty_input(self):
        self.assertEqual(normalise_url(""), "")
        self.assertEqual(normalise_url(None), "")

    def test_path_only_root_survives(self):
        self.assertEqual(normalise_url("https://example.com/"), "https://example.com/")

    def test_host_of(self):
        self.assertEqual(host_of("https://www.Example.com/a/b"), "example.com")
