import scrapy
import tldextract
from urllib.parse import urljoin
from scrapy.http import Request
import csv
import pathlib
import warnings

# Suppress deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

OUT_DIR = pathlib.Path("out")
PROGRESS_FILE = OUT_DIR / "progress.signal"

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
        self.items_scraped = 0  # track scraped items

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text("0")  # initialize progress

    def _update_progress(self):
        self.items_scraped += 1
        PROGRESS_FILE.write_text(str(self.items_scraped))

    def start_requests(self):
        yield Request(self.start_url, callback=self.parse_page, dont_filter=True)
        yield Request(urljoin(self.start_url, "/robots.txt"), callback=self.parse_robots, dont_filter=True)
        yield Request(urljoin(self.start_url, "/sitemap.xml"), callback=self.parse_sitemap, dont_filter=True)

    def parse_robots(self, response):
        self._update_progress()
        yield {
            "url": response.url,
            "status": response.status,
            "robots_txt": response.text[:5000],
        }

    def parse_sitemap(self, response):
        for loc in response.css("loc::text").getall():
            yield response.follow(loc, callback=self.parse_page)
            self._update_progress()

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

        self._update_progress()
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

        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            if self.allowed_domain in abs_url and abs_url.startswith("http"):
                yield response.follow(abs_url, callback=self.parse_page)

    def close(self, reason):
        """
        Ensure results.csv always exists, even if crawl found nothing.
        """
        results_file = OUT_DIR / "results.csv"
        if not results_file.exists() or self.items_scraped == 0:
            results_file.parent.mkdir(parents=True, exist_ok=True)
            with results_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Empty: run was not completed"])
