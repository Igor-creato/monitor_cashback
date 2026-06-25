WILDBERRIES_BASKET_RANGES = (
    (143, 1),
    (287, 2),
    (431, 3),
    (719, 4),
    (1007, 5),
    (1061, 6),
    (1115, 7),
    (1169, 8),
    (1313, 9),
    (1601, 10),
    (1655, 11),
    (1919, 12),
    (2045, 13),
    (2189, 14),
    (2405, 15),
    (2621, 16),
    (2837, 17),
    (3053, 18),
    (3269, 19),
    (3485, 20),
    (3701, 21),
    (3917, 22),
    (4133, 23),
    (4349, 24),
    (4565, 25),
    (4877, 26),
    (5189, 27),
    (5501, 28),
    (5813, 29),
    (6125, 30),
    (6437, 31),
    (6749, 32),
    (7061, 33),
    (7373, 34),
    (7685, 35),
    (7997, 36),
)
WILDBERRIES_BASKET_STEP = 312


def wildberries_image_url(product_id: int) -> str:
    volume = product_id // 100000
    part = product_id // 1000
    basket = wildberries_basket(volume)
    return (
        f"https://basket-{basket:02d}.wbbasket.ru/"
        f"vol{volume}/part{part}/{product_id}/images/big/1.webp"
    )


def wildberries_basket(volume: int) -> int:
    for upper_bound, basket in WILDBERRIES_BASKET_RANGES:
        if volume <= upper_bound:
            return basket
    last_upper_bound, last_basket = WILDBERRIES_BASKET_RANGES[-1]
    return last_basket + (
        (volume - last_upper_bound + WILDBERRIES_BASKET_STEP - 1)
        // WILDBERRIES_BASKET_STEP
    )
