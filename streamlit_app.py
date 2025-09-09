import streamlit as st
import pandas as pd
import pathlib
import time
from urllib.parse import urlparse
import sys
import subprocess
import json
import os

st.set_page_config(page_title="SEO Crawl & Indexability Auditor", layout="wide")

st.title("SEO Crawl & Indexability Auditor")

domain = st.text_input("Domain (https://example.com)")
run_clicked = st.button("Run")

out_dir = pathlib.Path("out")
out_dir.mkdir(parents=True, exist_ok=True)

results_path = out_dir / "results.csv"
progress_path = out_dir / "progress.json"
log_path = out_dir / "runner.log"
error_path = out_dir / "error.log"

# Columns we care about
preview_cols = [
    "url",
    "status",
    "title",
    "h1",
    "canonical",
    "robots_meta",
    "hreflang_count",
    "duplicate_title",
    "duplicate_h1",
]

# Highlighting
def highlight_issues(val, colname):
    if colname == "status" and val != 200:
        return "background-color: rgba(255, 0, 0, 0.05)"
    if colname == "duplicate_title" and val:
        return "background-color: rgba(255, 165, 0, 0.05)"
    if colname == "duplicate_h1" and val:
        return "background-color: rgba(255, 165, 0, 0.05)"
    if colname in ("canonical", "robots_meta") and (pd.isna(val) or val == ""):
        return "background-color: rgba(255, 255, 0, 0.05)"
    return ""

def styled_dataframe(df):
    return df.style.applymap(
        lambda v: highlight_issues(v, "status"), subset=["status"]
    ).applymap(
        lambda v: highlight_issues(v, "duplicate_title"), subset=["duplicate_title"]
    ).applymap(
        lambda v: highlight_issues(v, "duplicate_h1"), subset=["duplicate_h1"]
    ).applymap(
        lambda v: highlight_issues(v, "canonical"), subset=["canonical"]
    ).applymap(
        lambda v: highlight_issues(v, "robots_meta"), subset=["robots_meta"]
    )

# Show last results
if results_path.exists():
    st.subheader("Latest results")
    try:
        df = pd.read_csv(results_path)
        if "Empty: run was not completed" in df.columns[0]:
            st.warning("Last crawl did not complete. Empty results file created.")
        elif df.empty:
            st.warning("No results parsed from last crawl.")
        else:
            st.dataframe(df)
            existing_cols = [c for c in preview_cols if c in df.columns]
            if existing_cols:
                st.subheader("SEO Signals (Preview with highlights)")
                try:
                    st.dataframe(styled_dataframe(df[existing_cols].head(50)))
                except Exception:
                    st.warning("Results exist but don’t contain SEO columns.")

                # Downloads
                st.download_button(
                    "Download CSV",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name="seo_audit_results.csv",
                    mime="text/csv",
                )
                st.download_button(
                    "Download JSON",
                    data=df.to_json(orient="records", indent=2).encode("utf-8"),
                    file_name="seo_audit_results.json",
                    mime="application/json",
                )
    except Exception as e:
        st.error(f"Could not read results.csv: {e}")

if run_clicked:
    with st.status("Preparing to crawl…", expanded=True) as status:
        try:
            # Reset logs
            log_path.write_text("")
            error_path.write_text("")
            if results_path.exists():
                results_path.unlink()
            if progress_path.exists():
                progress_path.unlink()

            # Validate
            status.write("Validating input…")
            parsed = urlparse(domain.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                status.update(label="Invalid URL. Please include https://", state="error")
                st.stop()

            # Launch crawler
            status.write("Launching crawler…")
            try:
                env = os.environ.copy()
                env["PYTHONWARNINGS"] = "ignore::DeprecationWarning"

                subprocess.Popen(
                    [
                        sys.executable,
                        "-W", "ignore::DeprecationWarning",
                        "-m", "scrapy", "crawl", "seo",
                        "-a", f"start_url={domain}",
                        "-O", str(results_path),
                        "-L", "WARNING",
                    ],
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=open(error_path, "a", encoding="utf-8"),
                    env=env,
                )
            except FileNotFoundError:
                status.update(label="Cannot start crawler", state="error")
                st.error("Scrapy not available. Install with:")
                st.code("pip install scrapy scrapy-playwright")
                st.stop()

            # Monitor
            progress = st.progress(0)
            log_box = st.empty()
            wait_seconds = 600

            status.write("Crawling…")
            for i in range(wait_seconds):
                # Logs
                if log_path.exists():
                    try:
                        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                            tail = f.readlines()[-12:]
                        log_box.code("".join(tail), language="text")
                    except Exception:
                        pass

                # Errors
                if error_path.exists() and error_path.stat().st_size > 0:
                    err_txt = error_path.read_text(encoding="utf-8", errors="ignore")
                    status.update(label="Crawler error", state="error")
                    st.error(err_txt.strip() or "Unknown error.")
                    st.stop()

                # Progress.json
                if progress_path.exists():
                    try:
                        pj = json.loads(progress_path.read_text(encoding="utf-8"))
                        items = int(pj.get("items_scraped", 0))
                        total = int(pj.get("sitemap_total", 0))
                        status_str = pj.get("status", "running")

                        if total > 0:
                            pct = int((items / total) * 100)
                            pct = max(1, min(100, pct))
                        else:
                            pct = min(95, items)

                        progress.progress(pct)
                        if status_str == "finished":
                            break
                    except Exception:
                        pass

                time.sleep(1)
            else:
                status.update(label="Timed out", state="error")
                st.error("Timed out waiting for crawl results.")
                st.stop()

            # Load results
            status.write("Loading results…")
            try:
                df = pd.read_csv(results_path)
                if "Empty: run was not completed" in df.columns[0]:
                    st.warning("Crawl did not complete. Empty results created.")
                elif df.empty:
                    st.warning("Crawl completed but no results parsed.")
                else:
                    st.subheader("Crawl results")
                    st.dataframe(df)

                    existing_cols = [c for c in preview_cols if c in df.columns]
                    if existing_cols:
                        st.subheader("SEO Signals (Preview with highlights)")
                        st.dataframe(styled_dataframe(df[existing_cols].head(50)))

                        st.download_button(
                            "Download CSV",
                            data=df.to_csv(index=False).encode("utf-8"),
                            file_name="seo_audit_results.csv",
                            mime="text/csv",
                        )
                        st.download_button(
                            "Download JSON",
                            data=df.to_json(orient="records", indent=2).encode("utf-8"),
                            file_name="seo_audit_results.json",
                            mime="application/json",
                        )

                progress.progress(100)
                status.update(label="Crawl complete", state="complete")

            except Exception as e:
                st.error(f"Crawl completed but results could not be parsed: {e}")

        except Exception as e:
            status.update(label="Unexpected error", state="error")
            st.exception(e)
