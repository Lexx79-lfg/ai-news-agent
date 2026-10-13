"""Offline tests for news_agent. No network and no Anthropic API calls.

Run with:  python -m unittest test_news_agent -v
"""
import json, unittest, urllib.error, urllib.request
from datetime import date
from email.message import Message
from unittest import mock

import news_agent as na


class FakeResponse:
    def __init__(self, url, body, content_type="text/html; charset=utf-8"):
        self.url = url
        self.body = body.encode("utf-8")
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, n=-1):
        self.read_sizes.append(n)
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def page(*metas):
    tags = "\n".join(f'<meta property="{k}" content="{v}">' for k, v in metas)
    return f"<html><head><title>t</title>{tags}</head><body>hi</body></html>"


GOOD = page(("og:image", "https://cdn.example.com/pic.jpg"),
            ("og:site_name", "Example News"),
            ("og:image:alt", "A robot reading a newspaper"))


class Offline(unittest.TestCase):
    """Fails any test that tries to reach the Anthropic API or the real network."""

    def setUp(self):
        guard = mock.patch.object(na, "ask_claude", side_effect=AssertionError("Anthropic API must not be called"))
        guard.start()
        self.addCleanup(guard.stop)
        net = mock.patch("urllib.request.urlopen", side_effect=AssertionError("real network must not be used"))
        net.start()
        self.addCleanup(net.stop)

    def serve(self, url, body, **kw):
        resp = FakeResponse(url, body, **kw)
        patcher = mock.patch.object(na._opener, "open", return_value=resp)
        self.opened = patcher.start()
        self.addCleanup(patcher.stop)
        return resp

    def story(self, url="https://example.com/article", **extra):
        s = {"title": "Big AI news", "summary": "Something happened.", "why": "It matters.",
             "source": "Example", "url": url, "category": "AI"}
        s.update(extra)
        return s

    def render(self, stories, one_idea=""):
        return na.build_page(one_idea, stories, today=date(2026, 10, 13))


class TestPreviews(Offline):
    def test_good_page_shows_credited_image(self):
        resp = self.serve("https://example.com/article", GOOD)
        stories = na.add_previews([self.story()])
        self.assertEqual(stories[0]["preview"], {"image": "https://cdn.example.com/pic.jpg",
                                                 "site_name": "Example News",
                                                 "alt": "A robot reading a newspaper"})
        req = self.opened.call_args.args[0]
        self.assertIn(na.REPO_URL, req.get_header("User-agent"))
        self.assertEqual(self.opened.call_args.kwargs["timeout"], 8)
        self.assertEqual(resp.read_sizes, [na.MAX_BYTES])

        out = self.render(stories)
        self.assertIn('src="https://cdn.example.com/pic.jpg"', out)
        self.assertIn('alt="A robot reading a newspaper"', out)
        self.assertIn('loading="lazy"', out)
        self.assertNotIn("referrerpolicy", out)  # publishers can still see the referrer and block hotlinking
        self.assertIn('<a href="https://example.com/article" target="_blank" rel="noopener">Image: Example News</a>', out)
        self.assertIn("onerror=\"this.closest('figure').remove()\"", out)

    def test_relative_image_resolves_against_https_page(self):
        self.serve("https://example.com/a/article", page(("og:image", "/img/p.png"), ("og:site_name", "Ex")))
        p = na.get_preview("https://example.com/a/article")
        self.assertEqual(p["image"], "https://example.com/img/p.png")

    def test_alt_falls_back_to_title(self):
        self.serve("https://example.com/article", page(("og:image", "https://x.com/p.jpg"), ("og:site_name", "Ex")))
        out = self.render(na.add_previews([self.story()]))
        self.assertIn('alt="Big AI news"', out)

    def test_missing_site_name_shows_no_image(self):
        self.serve("https://example.com/article", page(("og:image", "https://cdn.example.com/pic.jpg")))
        stories = na.add_previews([self.story()])
        self.assertIsNone(stories[0]["preview"])
        out = self.render(stories)
        self.assertNotIn("<img", out)
        self.assertNotIn("<figure", out)

    def test_missing_image_shows_no_image(self):
        self.serve("https://example.com/article", page(("og:site_name", "Example News")))
        stories = na.add_previews([self.story()])
        self.assertIsNone(stories[0]["preview"])
        self.assertNotIn("<img", self.render(stories))

    def test_http_image_is_rejected(self):
        self.serve("https://example.com/article", page(("og:image", "http://cdn.example.com/pic.jpg"),
                                                       ("og:site_name", "Example News")))
        stories = na.add_previews([self.story()])
        self.assertIsNone(stories[0]["preview"])
        self.assertNotIn("<img", self.render(stories))

    def test_http_article_is_never_fetched(self):
        self.serve("http://example.com/article", GOOD)
        stories = na.add_previews([self.story(url="http://example.com/article")])
        self.opened.assert_not_called()
        self.assertIsNone(stories[0]["preview"])
        out = self.render(stories)
        self.assertNotIn("<img", out)
        self.assertNotIn('href="http://example.com', out)

    def test_redirect_to_http_is_rejected(self):
        # The final URL after redirects is http, so the page is ignored.
        self.serve("http://example.com/article", GOOD)
        self.assertIsNone(na.get_preview("https://example.com/article"))

    def test_redirect_handler_refuses_http(self):
        handler = na.HttpsOnlyRedirect()
        req = urllib.request.Request("https://example.com/a")
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://example.com/b")
        self.assertIsNotNone(handler.redirect_request(req, None, 302, "Found", {}, "https://example.com/b"))

    def test_non_html_is_ignored(self):
        self.serve("https://example.com/file.pdf", GOOD, content_type="application/pdf")
        self.assertIsNone(na.get_preview("https://example.com/file.pdf"))

    def test_network_error_gives_no_preview(self):
        patcher = mock.patch.object(na._opener, "open", side_effect=urllib.error.URLError("timed out"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertIsNone(na.get_preview("https://example.com/article"))

    def test_injection_through_meta_tags_is_escaped(self):
        evil = ('<html><head>'
                '<meta property="og:image" content="https://cdn.example.com/p.jpg&quot; onload=&quot;alert(1)">'
                '<meta property="og:site_name" content="&lt;script&gt;alert(&#39;site&#39;)&lt;/script&gt;">'
                '<meta property="og:image:alt" content="&quot;&gt;&lt;img src=x onerror=alert(2)&gt;">'
                '</head></html>')
        self.serve("https://example.com/article", evil)
        stories = na.add_previews([self.story()])
        self.assertIsNotNone(stories[0]["preview"])
        out = self.render(stories)
        self.assertNotIn("<script>alert", out)
        self.assertNotIn('" onload="alert(1)', out)
        self.assertNotIn("<img src=x", out)
        self.assertIn("&lt;script&gt;alert(&#x27;site&#x27;)&lt;/script&gt;", out)
        self.assertIn("&quot; onload=&quot;alert(1)", out)
        self.assertEqual(out.count("<img "), 1)

    def test_javascript_image_url_is_rejected(self):
        self.serve("https://example.com/article", page(("og:image", "javascript:alert(1)"), ("og:site_name", "Ex")))
        self.assertIsNone(na.get_preview("https://example.com/article"))


class TestParsing(Offline):
    STORY = {"title": "T", "summary": "S", "why": "W", "source": "Src", "url": "https://e.com", "category": "AI"}

    def test_new_object_format(self):
        raw = "Here you go:\n" + json.dumps({"one_idea": "Everything connects.", "stories": [self.STORY]}) + "\nDone."
        idea, stories = na.parse_response(raw)
        self.assertEqual(idea, "Everything connects.")
        self.assertEqual(stories, [self.STORY])

    def test_old_list_format(self):
        raw = "Sure!\n" + json.dumps([self.STORY, self.STORY])
        idea, stories = na.parse_response(raw)
        self.assertEqual(idea, "")
        self.assertEqual(len(stories), 2)

    def test_garbage_returns_empty(self):
        self.assertEqual(na.parse_response("sorry, no news"), ("", []))
        self.assertEqual(na.parse_response("{not json} [also not]"), ("", []))

    def test_object_without_stories_list_is_rejected(self):
        self.assertEqual(na.parse_response('{"one_idea": "x"}'), ("", []))


class TestPage(Offline):
    def test_claude_text_is_escaped_and_one_idea_comes_first(self):
        s = self.story(title="<script>alert(1)</script>", url="https://e.com/?a=1&b=2")
        out = self.render([s], one_idea="<b>Ideas</b> __TOP__ & more")
        self.assertNotIn("<script>alert", out)
        self.assertNotIn("<b>Ideas</b>", out)
        self.assertIn("&lt;b&gt;Ideas&lt;/b&gt; __TOP__ &amp; more", out)
        self.assertIn('href="https://e.com/?a=1&amp;b=2"', out)
        self.assertLess(out.index("One Idea"), out.index("TOP STORY"))

    def test_figure_requires_site_name_even_if_preview_is_tampered(self):
        s = self.story(preview={"image": "https://x.com/p.jpg", "site_name": "", "alt": ""})
        self.assertNotIn("<img", self.render([s]))

    def test_page_keeps_look_and_adds_accessibility_and_meta(self):
        out = self.render([self.story()], one_idea="An idea.")
        for needle in ['<html lang="en">', "<title>AI Briefing 2026-10-13</title>",  # daily.yml's live check relies on this 'id="music"', 'class="pill"', "enter the matrix",
                       '<meta name="description"', '<meta property="og:title"', '<meta property="og:description"',
                       '<meta property="og:url"', "prefers-reduced-motion", ":focus-visible",
                       "footer { text-align: center; font-family: Menlo, Consolas, monospace; color: #1D9E75;"]:
            self.assertIn(needle, out)
        self.assertNotIn("__", out.split("<style>")[0])

    def test_no_stories(self):
        out = self.render([])
        self.assertIn("No stories today.", out)
        self.assertNotIn("One Idea", out)


if __name__ == "__main__":
    unittest.main()
