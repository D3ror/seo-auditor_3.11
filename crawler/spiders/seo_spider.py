import scrapy
import tldextract
from urllib.parse import urljoin
from scrapy.http import Request
import csv
import pathlib
import warnings
import time

# Suppress deprecation & user warnings globally
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)


class SeoSpider(scrapy.Spider):
    """
    Usage:
      scrapy crawl seo -a start_url=https://example.com -O out/results.csv
    """
    name = "seo"

    custom_settings = {
        "DOWNLOAD_TIMEOUT": 15,  # fail fast on long waits
        "RETRY_TIMES": 1,        # fewer retries for speed
    }

    def __init__(self, start_url=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not start_url:
            raise ValueError("You must pass -a start_url=...")
        self.start_url = start_url
        self.allowed_domain = tldextract.extract(start_url).registered_domain
        self.visited_titles = set()
        self.visited_h1s = set()
        self.items_scraped = 0
        self.start_time = None

    def start_requests(self):
        self.start_time = time.time()
        # Crawl homepage
        yield Request(self.start_url, callback=self.parse_page, dont_filter=True, errback=self.handle_error)

        # Crawl sitemap.xml
        sitemap_url = urljoin(self.start_url, "/sitemap.xml")
        yield Request(sitemap_url, callback=self.parse_sitemap, dont_filter=True, errback=self.handle_error)

    def parse_sitemap(self, response):
        for loc in response.css("loc::text").getall():
            yield response.follow(loc, callback=self.parse_page, errback=self.handle_error)

    def parse_page(self, response):
        latency = round(response.meta.get("download_latency", 0), 2)

        # Extract SEO signals
        title = (response.css("title::text").get(default="") or "").strip()
        h1 = " ".join(response.css("h1 *::text").getall()).strip()
        canonical = response.css("link[rel=canonical]::attr(href)").get()
        robots_meta = ",".join(response.css("meta[name=robots]::attr(content)").getall())
        hreflangs = response.css("link[rel=alternate][hreflang]::attr(hreflang)").getall()

        # Track duplicates
        duplicate_title = title in self.visited_titles
        duplicate_h1 = h1 in self.visited_h1s
        self.visited_titles.add(title)
        self.visited_h1s.add(h1)

        self.items_scraped += 1
        yield {
            "url": response.url,
            "status": response.status,
            "wait_time": latency,
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
                yield response.follow(abs_url, callback=self.parse_page, errback=self.handle_error)

    def handle_error(self, failure):
        """Log failed requests (e.g. timeout)"""
        request = failure.request
        self.items_scraped += 1
        yield {
            "url": request.url,
            "status": "failed",
            "wait_time": "Page could not be opened due to long wait time. See CWV scores.",
            "title": "",
            "h1": "",
            "canonical": "",
            "robots_meta": "",
            "hreflang_count": 0,
            "duplicate_title": False,
            "duplicate_h1": False,
        }

    def close(self, reason):
        """
        Ensure results.csv always exists, even if crawl found nothing.
        """
        results_file = pathlib.Path("out") / "results.csv"
        if not results_file.exists() or self.items_scraped == 0:
            results_file.parent.mkdir(parents=True, exist_ok=True)
            with results_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Empty: run was not completed"])
