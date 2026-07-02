from price_monitor.domains.fetching.extraction import extract_product_data


def test_extract_product_data_from_json_ld_product() -> None:
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Phone","image":"https://example.com/p.jpg","aggregateRating":{"ratingValue":"4.8"},"offers":{"price":"123.45","priceCurrency":"RUB"}}
    </script>
    </head><body></body></html>
    """

    data = extract_product_data(html, fallback_currency="RUB")

    assert data.title == "Phone"
    assert data.image_url == "https://example.com/p.jpg"
    assert data.price_minor == 12345
    assert data.currency == "RUB"
    assert data.rating_value == "4.8"


def test_extract_product_data_from_json_ld_graph_with_low_price() -> None:
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@graph":[{"@type":"BreadcrumbList"},{"@type":"Product","name":"Graph Phone","image":["https://example.com/a.jpg","https://example.com/b.jpg"],"aggregateRating":{"ratingValue":"4.6"},"offers":{"lowPrice":"999.90"}}]}
    </script>
    </head><body></body></html>
    """

    data = extract_product_data(html, fallback_currency="RUB")

    assert data.title == "Graph Phone"
    assert data.image_url == "https://example.com/a.jpg"
    assert data.price_minor == 99990
    assert data.currency == "RUB"
    assert data.rating_value == "4.6"


def test_extract_product_data_returns_none_when_price_or_title_missing() -> None:
    assert (
        extract_product_data("<html><title>No price</title></html>", fallback_currency="RUB")
        is None
    )


def test_extract_product_data_returns_none_for_zero_price() -> None:
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Sold out phone","offers":{"price":"0","priceCurrency":"RUB"}}
    </script>
    </head><body></body></html>
    """

    assert extract_product_data(html, fallback_currency="RUB") is None
