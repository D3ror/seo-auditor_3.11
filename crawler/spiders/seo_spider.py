import scrapy
import tldextract
from urllib.parse import urljoin
from scrapy.http import Request
import csv
import pathlib
import json
import time
from scrapy import signals


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
        self.items_scraped = 0
        self.sitemap_total = 0
        self._progress_path = pathlib.Path("out") / "progress.json"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        # connect signals
        crawler.signals.connect(spider.item_scraped_signal, signal=signals.item_scraped)
        crawler.signals.connect(spider.spider_closed_signal, signal=signals.spider_closed)
        crawler.signals.connect(spider.spider_opened_signal, signal=signals.spider_opened)
        return spider

    def spider_opened_signal(self, spider):
        # initialize progress file
        self._write_progress(status="running", reason=None)

    def item_scraped_signal(self, item, response, spider):
        # increment and persist progress
        self.items_scraped += 1
        last_url = response.url if response is not None else ""
        self._write_progress(status="running", last_url=last_url)

    def spider_closed_signal(self, spider, reason):
        # mark finished
        self._write_progress(status="finished", reason=reason)

    def _write_progress(self, status="running", last_url="", reason=None):
        payload = {
            "items_scraped": int(self.items_scraped),
            "sitemap_total": int(self.sitemap_total or 0),
            "last_url": last_url,
            "status": status,
            "reason": reason,
            "ts": int(time.time()),
        }
        try:
            self._progress_path.parent.mkdir(parents=True, exist_ok=True)
            with self._progress_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except Exception:
            self.logger.debug("Could not write progress file", exc_info=True)

    async def start(self):
        # Crawl homepage
        yield Request(self.start_url, callback=self.parse_page, dont_filter=True)

        # Crawl robots.txt
        robots_url = urljoin(self.start_url, "/robots.txt")
        yield Request(robots_url, callback=self.parse_robots, dont_filter=True)

        # Crawl sitemap.xml
        sitemap_url = urljoin(self.start_url, "/sitemap.xml")
        yield Request(sitemap_url, callback=self.parse_sitemap, dont_filter=True)

    def parse_robots(self, response):
        return {
            "url": response.url,
            "status": response.status,
            "robots_txt": response.text[:5000],
        }

    def parse_sitemap(self, response):
        locs = response.css("loc::text").getall()
        if locs:
            self.sitemap_total = len(locs)
            self._write_progress()
        for loc in locs:
            if loc.startswith("http"):
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

        return {
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

        # Follow links
        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            if self.allowed_domain in abs_url and abs_url.startswith("http"):
                yield response.follow(abs_url, callback=self.parse_page)

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