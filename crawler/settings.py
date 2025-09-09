BOT_NAME = "seo"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

ROBOTSTXT_OBEY = True
LOG_LEVEL = "INFO"
CLOSESPIDER_PAGECOUNT=100
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
