import scrapy
import tldextract
from urllib.parse import urljoin
from scrapy.http import Request
import csv
import pathlib
import warnings
import time
import logging
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.internet.error import DNSLookupError, TimeoutError, TCPTimedOutError

# Suppress deprecation & user warnings globally (still logged by Streamlit if desired)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger("seo_spider")


class SeoSpider(scrapy.Spider):
    name = "seo"

    custom_settings = {
        "DOWNLOAD_TIMEOUT": 15,
        "RETRY_TIMES": 1,
        "ROBOTSTXT_OBEY": True,  # Respect robots.txt
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
        yield Request(
            self.start_url,
            callback=self.parse_page,
            dont_filter=True,
            errback=self.handle_error,
        )

        sitemap_url = urljoin(self.start_url, "/sitemap.xml")
        yield Request(
            sitemap_url,
            callback=self.parse_sitemap,
            dont_filter=True,
            errback=self.handle_error,
        )

    def parse_sitemap(self, response):
        for loc in response.css("loc::text").getall():
            logger.info(f"Found sitemap entry: {loc}")
            yield response.follow(loc, callback=self.parse_page, errback=self.handle_error)

    def parse_page(self, response):
        """
        Parse a single page for SEO signals.
        Skip non-HTML resources (images, PDFs, etc.) but log them.
        Also skip external or disallowed links, but record them in results.
        """
        content_type = response.headers.get("Content-Type", b"").decode("utf-8").lower()

        if not content_type.startswith("text/html"):
            yield {
                "url": response.url,
                "status": response.status,
                "title": None,
                "h1": None,
                "canonical": None,
                "robots_meta": None,
                "hreflang_count": 0,
                "duplicate_title": False,
                "duplicate_h1": False,
                "note": f"Skipped non-HTML resource ({content_type})"
            }
            return

        title = (response.css("title::text").get(default="") or "").strip()
        h1 = (response.css("h1::text").get(default="") or "").strip()
        canonical = response.css('link[rel="canonical"]::attr(href)').get(default="")
        robots_meta = response.css('meta[name="robots"]::attr(content)').get(default="")
        hreflangs = response.css('link[rel="alternate"][hreflang]')
        hreflang_count = len(hreflangs)

        yield {
            "url": response.url,
            "status": response.status,
            "title": title,
            "h1": h1,
            "canonical": canonical,
            "robots_meta": robots_meta,
            "hreflang_count": hreflang_count,
            "duplicate_title": False,
            "duplicate_h1": False,
            "note": None,
            "skipped_by_robots": False,
        }

        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            if abs_url.startswith("http") and self.allowed_domain in abs_url:
                yield response.follow(abs_url, callback=self.parse_page, errback=self.handle_error)
            else:
                yield {
                    "url": abs_url,
                    "status": "skipped",
                    "title": "",
                    "h1": "",
                    "canonical": "",
                    "robots_meta": "",
                    "hreflang_count": 0,
                    "duplicate_title": False,
                    "duplicate_h1": False,
                    "note": "Skipped external or disallowed link",
                    "skipped_by_robots": False,
                }

    def handle_error(self, failure):
        """Log failed requests without crashing crawl."""
        request = failure.request
        self.items_scraped += 1

        # Check if the failure is due to robots.txt
        robots_skipped = "Forbidden by robots.txt" in str(failure.value)

        yield {
            "url": request.url,
            "status": "failed" if not robots_skipped else "skipped",
            "title": "",
            "h1": "",
            "canonical": "",
            "robots_meta": "",
            "hreflang_count": 0,
            "duplicate_title": False,
            "duplicate_h1": False,
            "note": f"{failure.value}" if not robots_skipped else "Skipped due to robots.txt",
            "skipped_by_robots": robots_skipped,
        }

    def close(self, reason):
        """Ensure results.csv always exists, even if crawl found nothing."""
        results_file = pathlib.Path("out") / "results.csv"
        if not results_file.exists() or self.items_scraped == 0:
            results_file.parent.mkdir(parents=True, exist_ok=True)
            with results_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Empty: run was not completed"])
        logger.info(f"Crawl finished. Reason: {reason}. Items scraped: {self.items_scraped}")
