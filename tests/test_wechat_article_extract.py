from src.wechat import (
    _extract_article_text,
    _extract_article_text_with_fallback_parser,
)


def test_article_extract_fallback_parser_works():
    html = """
    <html>
      <head><title>测试</title><script>var x = 1;</script></head>
      <body>
        <nav>导航栏</nav>
        <article>
          <p>这是一段用于测试的中文正文内容。它需要足够长，才能通过最小长度过滤。</p>
          <p>这里继续补充一些内容，用来模拟新闻正文中的第二段信息。</p>
          <p>这段文本用于验证 fallback HTMLParser 至少能够提取正文文本。</p>
          <p>再补充一些描述，使正文长度超过最低阈值，避免被清洗函数直接过滤为空。</p>
          <p>为了确保长度稳定超过当前项目中的正文清洗下限，这里继续补充一段较长的说明文字，用来模拟新闻页正文的延展叙述部分。</p>
          <p>这段补充文本没有特殊结构，只是为了让测试更稳，不会因为阈值微调或者分句方式变化而偶发返回空字符串。</p>
        </article>
      </body>
    </html>
    """
    text = _extract_article_text_with_fallback_parser(html)

    assert "中文正文内容" in text
    assert "导航栏" not in text


def test_extract_article_text_returns_method():
    html = """
    <html>
      <body>
        <article>
          <p>这是一段较长的测试文章正文，用于验证三层正文提取函数不会报错。</p>
          <p>如果安装了 trafilatura 或 readability，它们可能会优先提取。</p>
          <p>如果专业库没有成功，也应该回退到项目内置 HTMLParser。</p>
          <p>这里继续补足长度，使清洗函数不会因为文本太短而返回空字符串。</p>
        </article>
      </body>
    </html>
    """
    text, method = _extract_article_text(html, url="https://example.com")

    assert isinstance(text, str)
    assert isinstance(method, str)
