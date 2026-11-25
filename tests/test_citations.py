import unittest

from app.core.citations import citation_urls, validate_draft_citations, validate_edited_citations


class CitationTests(unittest.TestCase):
    def test_reads_markdown_links_references_tables_and_autolinks(self):
        text = (
            "[Inline](https://one.test) and [reference][two].\n\n"
            "| Source |\n| --- |\n| [table](https://three.test) |\n\n"
            "<https://four.test> and https://five.test/story and www.example.com.\n\n"
            '[two]: https://two.test "Article title"\n'
        )
        self.assertEqual(citation_urls(text), {
            "https://one.test", "https://two.test", "https://three.test",
            "https://four.test", "https://five.test/story", "http://www.example.com",
        })

    def test_ignores_unused_references_code_images_and_raw_html(self):
        text = (
            '`[inline code](https://inline.test)` and plain example.com\n\n'
            '![Image](https://image.test/cover.png)\n\n'
            '[unused]: https://unused.test\n\n'
            '```md\n[code block](https://code.test)\n```\n\n'
            '<a href="https://html.test">Raw HTML</a>\n'
        )
        self.assertEqual(citation_urls(text), set())

    def test_can_reposition_and_relabel_inline_citations(self):
        urls = ["https://one.test/story?a=1&b=2", "https://two.test"]
        draft = "[One](https://one.test/story?a=1&amp;b=2) and [Two](https://two.test)."
        citations = validate_draft_citations(draft, [{"url": url} for url in urls])
        self.assertEqual(citations, set(urls))
        validate_edited_citations(
            "[Second first][two] and [renamed][one], plus [repeat][one].\n\n"
            "[two]: https://two.test\n[one]: https://one.test/story?a=1&b=2",
            citations,
        )
        with self.assertRaisesRegex(ValueError, "outside the selected articles"):
            validate_draft_citations("[Altered](https://one.test/story?a=1)", [{"url": urls[0]}])
