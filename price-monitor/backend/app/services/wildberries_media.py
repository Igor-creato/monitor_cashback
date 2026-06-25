WILDBERRIES_IMAGE_CDN_HOST = "sam-basket-cdn-04.geobasket.ru"


def wildberries_image_url(product_id: int) -> str:
    volume = product_id // 100000
    part = product_id // 1000
    return (
        f"https://{WILDBERRIES_IMAGE_CDN_HOST}/"
        f"vol{volume}/part{part}/{product_id}/images/big/1.webp"
    )
