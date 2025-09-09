import scrapy
import tldextract
from urllib.parse import urljoin
from scrapy.http import Request
import csv
import pathlib


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
        self.items_scraped = 0  # track how many rows were actually scraped

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
        self.items_scraped += 1
        yield {
            "url": response.url,
            "status": response.status,
            "robots_txt": response.text[:5000],  # store first 5k chars
        }

    def parse_sitemap(self, response):
        for loc in response.css("loc::text").getall():
            # Following sitemap URLs may yield results later
            yield response.follow(loc, callback=self.parse_page)

    def parse_page(self, response):
        title = response.css("title::text").get(default="").strip()
        h1 = response.css("h1::text").get(default="").strip()
        canonical = response.css("link[rel=canonical]::attr(href)").get()
        robots_meta = ",".join(response.css("meta[name=robots]::attr(content)").getall())
        hreflangs = response.css("link[rel=alternate][hreflang]::attr(hreflang)").getall()

        duplicate_title = title in self.visited_titles
        duplicate_h1 = h1 in self.visited_h1s
        self.visited_titles.add(title)
        self.visited_h1s.add(h1)

        self.items_scraped += 1
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

        # Follow internal links
        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            if self.allowed_domain in abs_url and abs_url.startswith("http"):
                yield response.follow(abs_url, callback=self.parse_page)

    def close(self, reason):
        """
        Fail-safe: Ensure results.csv always exists.
        If no items were scraped, write a marker row.
        """
        results_file = pathlib.Path("out") / "results.csv"
        results_file.parent.mkdir(parents=True, exist_ok=True)

        if not results_file.exists() or self.items_scraped == 0:
            with results_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Empty: run was not completed"])
