"""Markdown to Telegram HTML Formatter.

Converts standard Markdown into Telegram-supported HTML tags,
preventing raw backtick boxes and unparsed asterisks while redacting secrets.
"""

import html
import re
from typing import List

# Patterns matching sensitive tokens and secrets
TELEGRAM_TOKEN_RE = re.compile(r"([0-9]{8,12}:[a-zA-Z0-9_-]{20,50})")
API_KEY_PATTERNS = [
    (re.compile(r"\bsk-(?:[a-zA-Z0-9_-]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:gh[pousr]_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]{20,}"), r"\1[REDACTED_API_KEY]"),
]


def sanitize_secrets(text: str) -> str:
    """Masks sensitive credentials, Telegram bot tokens, and API keys."""
    if not text:
        return ""
    sanitized = TELEGRAM_TOKEN_RE.sub("[REDACTED_TELEGRAM_TOKEN]", text)
    for pat, repl in API_KEY_PATTERNS:
        sanitized = pat.sub(repl, sanitized)
    return sanitized


def markdown_to_telegram_html(text: str) -> str:
    """Safely converts markdown to Telegram HTML with automatic secret redaction."""
    if not text:
        return ""

    text = sanitize_secrets(text)
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

    # Convert *italic* or _italic_ to <i>...</i> (avoid mangling path segments or snake_case)
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w/\\])_([^_\n]+?)_(?![\w/\\])", r"<i>\1</i>", text)

    # Restore placeholders
    for idx, cb in enumerate(code_blocks):
        text = text.replace(f"\x00CB{idx}\x00", cb)

    for idx, ic in enumerate(inline_codes):
        text = text.replace(f"\x00IC{idx}\x00", ic)

    return text
