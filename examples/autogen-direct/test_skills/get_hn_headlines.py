def run(count: int = 10) -> list[str]:
    """
    Fetch headlines from HackerNews front page.

    Args:
        count: Number of headlines to return (default: 10)

    Returns:
        List of headline strings
    """
    import html
    import re

    # Fetch the HackerNews front page with enough content to get all headlines
    html_content = tools.fetch(url="https://news.ycombinator.com/", raw=True, max_length=20000)

    # Extract the HTML content (remove any prefix text)
    html_start = html_content.find("<html")
    if html_start != -1:
        clean_html = html_content[html_start:]
    else:
        clean_html = html_content

    # Pattern to match the title structure in HackerNews
    pattern = r'<span class="titleline"><a href="[^"]*">([^<]+)</a>'
    matches = re.findall(pattern, clean_html)

    # Decode HTML entities (like &#x27; for apostrophes)
    decoded_matches = [html.unescape(match) for match in matches]

    # Return the requested number of headlines
    return decoded_matches[:count]
