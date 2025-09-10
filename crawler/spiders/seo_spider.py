import scrapy
import tldextract
from urllib.parse import urljoin
from scrapy.http import Request
import csv
import pathlib
import warnings
import time
import logging

# Suppress deprecation & user warnings globally (still logged by Streamlit if desired)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger("seo_spider")


class SeoSpider(scrapy.Spider):
    """
    Usage:
      scrapy crawl seo -a start_url=https://example.com -O out/results.csv
    """
    name = "seo"

    custom_settings = {
        "DOWNLOAD_TIMEOUT": 15,
        "RETRY_TIMES": 1,
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
    """
    # --- Check Content-Type ---
    content_type = response.headers.get("Content-Type", b"").decode("utf-8").lower()

    if not content_type.startswith("text/html"):
        # Non-HTML resource → log and return basic info only
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

    # --- Safe to parse HTML ---
    title = (response.css("title::text").get(default="") or "").strip()
    h1 = (response.css("h1::text").get(default="") or "").strip()
    canonical = response.css('link[rel="canonical"]::attr(href)').get(default="")
    robots_meta = response.css('meta[name="robots"]::attr(content)').get(default="")

    # hreflang count
    hreflangs = response.css('link[rel="alternate"][hreflang]')
    hreflang_count = len(hreflangs)

    # Yield structured results
    yield {
        "url": response.url,
        "status": response.status,
        "title": title,
        "h1": h1,
        "canonical": canonical,
        "robots_meta": robots_meta,
        "hreflang_count": hreflang_count,
        "duplicate_title": False,  # will be flagged later in deduplication step
        "duplicate_h1": False,
        "note": None,
    }

        # Follow internal links (with explicit decision logging)
        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            if abs_url.startswith("http") and self.allowed_domain in abs_url:
                logger.debug(f"Following link (same domain): {abs_url}")
                yield response.follow(abs_url, callback=self.parse_page, errback=self.handle_error)
            else:
                logger.debug(f"Skipping external or disallowed link: {abs_url}")

    def handle_error(self, failure):
        """Log failed requests (e.g. timeout)."""
        request = failure.request
        logger.warning(f"Request failed: {request.url} -> {failure.value}")
        self.items_scraped += 1
        yield {
            "url": request.url,
            "status": "failed",
            "wait_time": "Page could not be opened (timeout or error).",
            "title": "",
            "h1": "",
            "canonical": "",
            "robots_meta": "",
            "hreflang_count": 0,
            "duplicate_title": False,
            "duplicate_h1": False,
            "decision_reason": f"error: {failure.value}",
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
