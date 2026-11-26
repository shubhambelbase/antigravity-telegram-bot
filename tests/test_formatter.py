from execution.formatter import markdown_to_telegram_html, sanitize_secrets


def test_markdown_to_telegram_html_basic():
    md = "**Hello** *world* and `print('hi')`"
    res = markdown_to_telegram_html(md)
    assert "<b>Hello</b>" in res
    assert "<i>world</i>" in res
    assert "<code>print(&#x27;hi&#x27;)</code>" in res


def test_markdown_to_telegram_html_code_block():
    md = "Code:\n```python\ndef test():\n    return True\n```"
    res = markdown_to_telegram_html(md)
    assert "<pre><code>def test():\n    return True</code></pre>" in res


def test_markdown_to_telegram_html_headers():
    md = "### Section Header\nSome details"
    res = markdown_to_telegram_html(md)
    assert "<b>Section Header</b>" in res


def test_sanitize_secrets():
    # Telegram Bot Token
    token_str = "Connecting to https://api.telegram.org/bot123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345678/sendMessage"
    redacted = sanitize_secrets(token_str)
    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345678" not in redacted
    assert "[REDACTED_TELEGRAM_TOKEN]" in redacted

    # OpenAI / Anthropic / GitHub keys
    secret_str = "Authorization: Bearer sk-abcdef1234567890abcdef123456 and token ghp_1234567890abcdefghijklmnopqrstuv"
    redacted2 = sanitize_secrets(secret_str)
    assert "sk-abcdef1234567890abcdef123456" not in redacted2
    assert "ghp_1234567890abcdefghijklmnopqrstuv" not in redacted2
    assert "[REDACTED_API_KEY]" in redacted2

    # Modern hyphenated OpenAI/Anthropic keys, fine-grained GitHub PATs, AWS keys, Bearer tokens
    modern = (
        "OPENAI=sk-proj-abcDEF123456_xyz78901234 "
        "ANTHROPIC=sk-ant-api03-abcdef123456_789012 "
        "GH=github_pat_11ABCDE_0123456789abcdef "
        "AWS=AKIAIOSFODNN7EXAMPLE "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload"
    )
    redacted3 = sanitize_secrets(modern)
    assert "sk-proj-" not in redacted3
    assert "sk-ant-" not in redacted3
    assert "github_pat_" not in redacted3
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted3
    assert "eyJhbGci" not in redacted3
