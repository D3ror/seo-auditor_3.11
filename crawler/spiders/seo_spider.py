import scrapy
import tldextract
from urllib.parse import urljoin, urlparse
from scrapy.http import Request


class OptionsSpider(scrapy.Spider):
    """
    Usage:
      scrapy crawl seo -a start_url=https://example.com -O out/results.csv
    """
    name = "seo"

    def __init__(self, start_url=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not start_url:
            raise ValueError("You must pass -a start_url=...")
        self.start_url = start_url
        self.allowed_domain = tldextract.extract(start_url).registered_domain
        self.visited_titles = set()
        self.visited_h1s = set()

    def start_requests(self):
        # Crawl homepage
        yield Request(self.start_url, callback=self.parse_page, dont_filter=True)

        # Crawl robots.txt
        robots_url = urljoin(self.start_url, "/robots.txt")
        yield Request(robots_url, callback=self.parse_robots, dont_filter=True)

        # Crawl sitemap.xml
        sitemap_url = urljoin(self.start_url, "/sitemap.xml")
        yield Request(sitemap_url, callback=self.parse_sitemap, dont_filter=True)

    def parse_robots(self, response):
        yield {
            "url": response.url,
            "status": response.status,
            "robots_txt": response.text[:5000],  # store first 5k chars
        }

    def parse_sitemap(self, response):
        for loc in response.css("loc::text").getall():
            if loc.startswith("http"):  # only follow valid URLs
                yield response.follow(loc, callback=self.parse_page)

    def parse_page(self, response):
        # Extract SEO signals
        title = response.css("title::text").get(default="").strip()
        h1 = response.css("h1::text").get(default="").strip()
        canonical = response.css("link[rel=canonical]::attr(href)").get()
        robots_meta = ",".join(response.css("meta[name=robots]::attr(content)").getall())
        hreflangs = response.css("link[rel=alternate][hreflang]::attr(hreflang)").getall()

        # Track duplicates
        duplicate_title = title in self.visited_titles
        duplicate_h1 = h1 in self.visited_h1s
        self.visited_titles.add(title)
        self.visited_h1s.add(h1)

        yield {
            "url": response.url,
            "status": response.status,
            "title": title,
            "h1": h1,
            "canonical": canonical,
            "robots_meta": robots_meta,
            "hreflang_count": len(hreflangs),
            "duplicate_title": duplicate_title,
            "duplicate_h1": duplicate_h1,
        }

        # Follow internal links safely
        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            parsed = urlparse(abs_url)

            # Only follow http/https and skip mailto:, tel:, javascript:, etc.
            if parsed.scheme in ("http", "https") and self.allowed_domain in abs_url:
                yield response.follow(abs_url, callback=self.parse_page)