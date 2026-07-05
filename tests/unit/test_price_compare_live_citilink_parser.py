from decimal import Decimal

from price_monitor.price_compare.live.adapters.parsers import parse_items


def test_citilink_parser_maps_captured_graphql_products() -> None:
    content = """
    <html><body>
    <script type="application/json" data-monitor-cashback-live-json="citilink_graphql">
    {
      "data": {
        "fullSearchFilter": {
          "record": {
            "products": [
              {
                "id": "2012345",
                "name": "Смартфон Xiaomi Redmi Note 13 8/256GB, черный",
                "slug": "smartfon-xiaomi-redmi-note-13-8-256gb-chernyi",
                "isAvailable": true,
                "price": {"current": "17990", "old": ""},
                "brand": {"name": "Xiaomi"},
                "category": {"name": "Смартфоны"},
                "images": {
                  "citilink": [
                    {
                      "sources": [
                        {"size": "SM", "url": "https://cdn.citilink.ru/sm.jpg"},
                        {"size": "MD", "url": "https://cdn.citilink.ru/md.jpg"}
                      ]
                    }
                  ]
                }
              }
            ]
          }
        }
      }
    }
    </script>
    </body></html>
    """

    items = parse_items("citilink_search_v1", content, "citilink.ru", 5)

    assert len(items) == 1
    assert items[0].title == "Смартфон Xiaomi Redmi Note 13 8/256GB, черный"
    assert items[0].price == Decimal("17990")
    assert items[0].url == (
        "https://www.citilink.ru/product/smartfon-xiaomi-redmi-note-13-8-256gb-chernyi-2012345/"
    )
    assert items[0].availability == "in_stock"
    assert items[0].brand == "Xiaomi"
    assert items[0].category == "Смартфоны"
    assert items[0].image_url == "https://cdn.citilink.ru/md.jpg"
    assert items[0].external_id == "2012345"
