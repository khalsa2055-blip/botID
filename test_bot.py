import base64
import unittest
from unittest.mock import patch
from urllib.parse import quote

import requests

import bot


class FakeResponse:
    def __init__(self, text: str, status_error: Exception | None = None):
        self.text = text
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise self.status_error


class PublicSearchTests(unittest.TestCase):
    @patch("bot.requests.get")
    def test_combines_public_results_from_multiple_providers(self, get):
        get.side_effect = [
            FakeResponse('<a class="result__a" href="https://t.me/public_one">One</a>'),
            FakeResponse('<a class="result-link" href="https://t.me/public_two">Two</a>'),
            FakeResponse('<li class="b_algo"><h2><a href="https://t.me/public_three">Three</a></h2></li>'),
        ]

        results = bot.search_public_telegram("example")

        self.assertEqual(
            results,
            [
                ("One", "https://t.me/public_one"),
                ("Two", "https://t.me/public_two"),
                ("Three", "https://t.me/public_three"),
            ],
        )
        self.assertEqual(get.call_count, 3)
        self.assertIn("site:t.me example", get.call_args_list[0].kwargs["params"]["q"])

    @patch("bot.requests.get")
    def test_uses_fallback_after_provider_failure(self, get):
        get.side_effect = [
            requests.Timeout("DuckDuckGo timed out"),
            FakeResponse('<a class="result-link" href="https://t.me/fallback_group">Fallback</a>'),
            requests.ConnectionError("Bing unavailable"),
        ]

        results = bot.search_public_telegram("123456789")

        self.assertEqual(results, [("Fallback", "https://t.me/fallback_group")])
        self.assertEqual(get.call_count, 3)

    @patch("bot.requests.get")
    def test_reports_failure_when_every_provider_fails(self, get):
        get.side_effect = [
            requests.Timeout("timeout"),
            requests.ConnectionError("connection"),
            requests.HTTPError("http"),
        ]

        with self.assertRaisesRegex(RuntimeError, "DuckDuckGo"):
            bot.search_public_telegram("term")

    @patch("bot.requests.get")
    def test_filters_non_telegram_result_urls(self, get):
        get.side_effect = [
            FakeResponse('<a class="result__a" href="https://example.com/page">External</a>'),
            FakeResponse('<a class="result-link" href="https://t.me.evil.example/page">Lookalike</a>'),
            FakeResponse('<li class="b_algo"><h2><a href="https://example.org">Other</a></h2></li>'),
        ]

        self.assertEqual(bot.search_public_telegram("term"), [])

    def test_validates_numeric_ids_and_usernames_for_where(self):
        self.assertTrue(bot.is_valid_identifier("8589682604"))
        self.assertTrue(bot.is_valid_identifier("@sample_name"))
        self.assertFalse(bot.is_valid_identifier("123"))
        self.assertFalse(bot.is_valid_identifier("https://t.me/sample_name"))

    def test_unwraps_search_provider_redirects(self):
        destination = "https://t.me/example_group"
        wrapped = "https://duckduckgo.com/l/?uddg=" + quote(destination, safe="")
        self.assertEqual(bot.unwrap_search_result_url(wrapped, "DuckDuckGo"), destination)

        encoded = "a1" + base64.urlsafe_b64encode(destination.encode()).decode().rstrip("=")
        bing_wrapped = "https://www.bing.com/ck/a?u=" + encoded
        self.assertEqual(bot.unwrap_search_result_url(bing_wrapped, "Bing"), destination)


if __name__ == "__main__":
    unittest.main()
