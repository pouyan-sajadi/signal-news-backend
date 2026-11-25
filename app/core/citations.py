from markdown_it import MarkdownIt


# Recognize raw HTML as a token so links inside it are ignored, as in the report renderer.
_MARKDOWN = MarkdownIt("commonmark", {"html": True, "linkify": True}).enable(
    ["table", "strikethrough", "linkify"],
)


def citation_urls(markdown: str) -> set[str]:
    """Read links from Markdown, including references and displayed autolinks."""
    links = set()
    for block in _MARKDOWN.parse(markdown):
        children = block.children or []
        for index, token in enumerate(children):
            if token.type != "link_open":
                continue
            href = token.attrGet("href")
            if href is None:
                continue
            if token.markup == "linkify" and not href.startswith("mailto:"):
                # GFM autolinks a URL with a scheme or www., but leaves lone domain names as text.
                label = children[index + 1].content.lower()
                if not label.startswith(("https://", "http://", "www.")):
                    continue
            links.add(href)
    return links


def validate_draft_citations(markdown: str, selected_articles: list[dict]) -> set[str]:
    allowed_urls = {_MARKDOWN.normalizeLink(article["url"]) for article in selected_articles}
    citations = citation_urls(markdown)
    if not citations:
        raise ValueError("Draft has no citation links.")
    if citations - allowed_urls:
        raise ValueError("Draft links to a URL outside the selected articles.")
    return citations


def validate_edited_citations(markdown: str, draft_citations: set[str]) -> None:
    edited_citations = citation_urls(markdown)
    if draft_citations - edited_citations:
        raise ValueError("Edited report removed a draft citation link.")
    if edited_citations - draft_citations:
        raise ValueError("Edited report added a link that was absent from the draft.")
