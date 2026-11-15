from execution.formatter import markdown_to_telegram_html


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
