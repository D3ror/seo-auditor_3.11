import typer
from app.crawl import run_crawl

app = typer.Typer()

@app.command()
def audit(domain: str, outdir: str = "out"):
    """
    Crawl domain, parse robots/sitemaps, collect indexability signals, write CSV/JSON/HTML.
    """
    run_crawl(domain, outdir)

if __name__ == "__main__":
    app()
