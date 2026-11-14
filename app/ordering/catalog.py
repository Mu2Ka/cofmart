"""Меню CaVa перенесено с фотографии. Неуказанный объём = «порция»."""

from dataclasses import dataclass

CAFES = {"1": "CaVa", "2": "Порт-Брю"}
CATEGORIES = {
    "coffee": "☕ Кофе",
    "signature": "✨ Авторские напитки",
    "tea": "🍵 Чай",
    "other": "🧊 Другие напитки",
}


@dataclass(frozen=True)
class Product:
    name: str
    category: str
    sizes: dict[str, int]
    alternative_milk: bool = False


PRODUCTS = {
    "1": {
        "1": Product("Американо", "coffee", {"350": 165}),
        "2": Product("Фильтр-кофе", "coffee", {"350": 165}),
        "3": Product("Флэт уайт", "coffee", {"250": 185}, True),
        "4": Product("Латте", "coffee", {"250": 240, "350": 260, "450": 280}, True),
        "5": Product("Капучино", "coffee", {"250": 240, "350": 260, "450": 280}, True),
        "6": Product("Раф", "coffee", {"350": 275, "450": 350}, True),
        "7": Product("Бамбл · вишня", "coffee", {"350": 285, "450": 385}),
        "8": Product("Бамбл · апельсин", "coffee", {"350": 285, "450": 385}),
        "9": Product("Бамбл · грейпфрут", "coffee", {"350": 285, "450": 385}),
        "10": Product("Эспрессо-тоник", "coffee", {"350": 260}),
        "11": Product("Айс латте", "coffee", {"350": 230, "450": 265}, True),
        "12": Product("Тоник малиновый", "other", {"350": 260}),
        "13": Product("Какао", "other", {"350": 220, "450": 285}, True),
        "14": Product("Латте апельсин", "signature", {"350": 275, "450": 350}, True),
        "15": Product("Латте ваниль–лаванда", "signature", {"350": 275, "450": 350}, True),
        "16": Product("Латте арахис", "signature", {"350": 275, "450": 350}, True),
        "17": Product("Латте солёная карамель", "signature", {"350": 275, "450": 350}, True),
        "18": Product("Латте фисташка–малина", "signature", {"350": 285, "450": 360}, True),
        "19": Product("Айс латте тирамису", "signature", {"450": 320}, True),
        "20": Product("Матча латте", "signature", {"350": 220}, True),
        "21": Product("Матча бамбл", "signature", {"350": 240}),
        "22": Product("Лимонад вишня–сакура", "other", {"450": 210}),
        "23": Product("Лимонад киви–виноград", "other", {"450": 210}),
        "24": Product("Матча тоник ананас–маракуйя", "signature", {"450": 450}),
        "25": Product("Маракуйя–апельсин", "tea", {"portion": 265}),
        "26": Product("Грейпфрут–клубника", "tea", {"portion": 265}),
        "27": Product("Медовая облепиха", "tea", {"portion": 265}),
        "28": Product("Имбирь–лимон", "tea", {"portion": 265}),
        "29": Product("Глинтвейн", "tea", {"portion": 200}),
        "30": Product("Чёрный чай · ассам", "tea", {"portion": 110}),
        "31": Product("Чёрный чай · эрл грей", "tea", {"portion": 110}),
        "32": Product("Зелёный чай · сенча", "tea", {"portion": 110}),
        "33": Product("Зелёный чай · жасмин", "tea", {"portion": 110}),
        "34": Product("Иван-чай", "tea", {"portion": 110}),
        "35": Product("Ромашка", "tea", {"portion": 110}),
        "36": Product("Молочный улун", "tea", {"portion": 110}),
        "37": Product("Смузи ягодный", "other", {"portion": 290}),
        "38": Product("Милкшейк", "other", {"portion": 285}),
    },
    # Существующее учебное меню второй кофейни.
    "2": {
        "1": Product("Американо", "coffee", {"portion": 100}),
        "2": Product("Раф", "coffee", {"portion": 250}),
    },
}


def size_label(size: str) -> str:
    return "порция" if size == "portion" else f"{size} мл"


@dataclass(frozen=True)
class Drink:
    """Выбранный напиток: объём и молоко уже учтены в названии и цене."""

    name: str
    price: int
    product: Product


def get_drink(cafe_id: str, sku: str) -> Drink | None:
    # Например, 4_350 — латте 350 мл, 4_350a — тот же напиток на альтернативном молоке.
    product_id, _, size = sku.partition("_")
    product = PRODUCTS.get(cafe_id, {}).get(product_id)
    alternative = size.endswith("a")
    if alternative:
        size = size[:-1]
    if product is None or size not in product.sizes:
        return None
    if alternative and not product.alternative_milk:
        return None

    name = f"{product.name} · {size_label(size)}"
    price = product.sizes[size]
    if alternative:
        name += " · альтернативное молоко"
        price += 70
    return Drink(name, price, product)
