"""Markdown to Telegram HTML Formatter.

Converts standard Markdown into Telegram-supported HTML tags,
preventing raw backtick boxes and unparsed asterisks.
"""

import html
import re
from typing import List


def markdown_to_telegram_html(text: str) -> str:
    """Safely converts markdown to Telegram HTML."""
    if not text:
        return ""

    code_blocks: List[str] = []

    def replace_code_block(match: re.Match) -> str:
        code = match.group(1)
        idx = len(code_blocks)
        escaped_code = html.escape(code.strip("\r\n"))
        code_blocks.append(f"<pre><code>{escaped_code}</code></pre>")
        return f"\x00CB{idx}\x00"

    # Match ```optional_lang\n code ```
    text = re.sub(
        r"```(?:[a-zA-Z0-9_\-\+]*\n)?(.*?)```",
        replace_code_block,
        text,
        flags=re.DOTALL,
    )

    inline_codes: List[str] = []

    def replace_inline_code(match: re.Match) -> str:
        code = match.group(1)
        idx = len(inline_codes)
        escaped_code = html.escape(code)
        inline_codes.append(f"<code>{escaped_code}</code>")
        return f"\x00IC{idx}\x00"

    # Match `code`
    text = re.sub(r"`([^`\n]+)`", replace_inline_code, text)

    # HTML escape the remaining body text
    text = html.escape(text)

    # Convert Markdown headers (# Header) to bold
    text = re.sub(r"^(?:#{1,6})\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Convert **bold** or __bold__ to <b>...</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Convert *italic* or _italic_ to <i>...</i>
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # Restore placeholders
    for idx, cb in enumerate(code_blocks):
        text = text.replace(f"\x00CB{idx}\x00", cb)

    for idx, ic in enumerate(inline_codes):
        text = text.replace(f"\x00IC{idx}\x00", ic)

    return text
