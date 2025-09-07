import re
import scrapy
from scrapy.http import Request
from scrapy_playwright.page import PageMethod


class OptionsSpider(scrapy.Spider):
    """
    Usage:
      scrapy crawl options -a start_url=https://example.com/products -O out/results.csv
    """
    name = "options"

    def __init__(self, start_url=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not start_url:
            raise ValueError("You must pass -a start_url=...")
        self.start_url = start_url

    def start_requests(self):
        yield Request(
            self.start_url,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_load_state", "load"),
                    PageMethod("wait_for_selector", "div.product, .product-card, [data-product]"),
                ],
            },
        )

    def parse(self, response):
        # Example product parsing (adapt selectors to your site)
        cards = response.css("div.product, .product-card, [data-product]")
        for card in cards:
            name = (card.css(".name::text, .product-title::text, h2::text").get() or "").strip()
            price_text = (card.css(".price::text, .product-price::text").get() or "").strip().replace(",", ".")
            href = card.css("a::attr(href)").get()
            url = response.urljoin(href) if href else response.url

            m = re.search(r"([0-9]+(?:[.,][0-9]+)?)", price_text)
            price = float(m.group(1).replace(",", ".")) if m else None

            features = {
                "rating": float((card.css("[data-rating]::attr(data-rating)").get() or "3").strip()),
                "popularity": float(len(card.css("a, button"))),
            }

            if name and price is not None:
                yield {
                    "name": name,
                    "price": price,
                    "url": url,
                    **features,
                }

        next_href = response.css("a.next::attr(href), a[rel=next]::attr(href)").get()
        if next_href:
            yield response.follow(
                next_href,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [PageMethod("wait_for_load_state", "load")],
                }
            )
