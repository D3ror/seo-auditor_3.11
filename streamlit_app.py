import streamlit as st
import pandas as pd
import pathlib
import time
from urllib.parse import urlparse
import sys
import subprocess

st.set_page_config(page_title="SEO Crawl & Indexability Auditor", layout="wide")
st.title("SEO Crawl & Indexability Auditor")

domain = st.text_input("Domain (https://example.com)")
run_clicked = st.button("Run")

OUT_DIR = pathlib.Path("out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

results_path = OUT_DIR / "results.csv"
log_path = OUT_DIR / "runner.log"
error_path = OUT_DIR / "error.log"

preview_cols = [
    "url", "status", "title", "h1", "canonical",
    "robots_meta", "hreflang_count", "duplicate_title", "duplicate_h1"
]

def highlight_issues(val, colname):
    if colname == "status" and val != 200:
        return "background-color: rgba(255, 0, 0, 0.1)"
    if colname in ("duplicate_title", "duplicate_h1") and val:
        return "background-color: rgba(255, 165, 0, 0.1)"
    if colname in ("canonical", "robots_meta") and (pd.isna(val) or val == ""):
        return "background-color: rgba(255, 255, 0, 0.1)"
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

# Show latest results
if results_path.exists():
    st.subheader("Latest results")
    try:
        df = pd.read_csv(results_path)
        if df.empty or df.iloc[0]["status"] == "Empty: run was not completed":
            st.warning("Last crawl did not complete. Empty results file created.")
        else:
            st.dataframe(df)
            existing_cols = [c for c in preview_cols if c in df.columns]
            if existing_cols:
                try:
                    st.subheader("SEO Signals (Preview with highlights)")
                    st.dataframe(styled_dataframe(df[existing_cols].head(50)))
                except Exception:
                    st.warning("Results file exists but doesn’t contain SEO columns.")
    except Exception as e:
        st.error(f"Could not read results.csv: {e}")

# Run crawl
if run_clicked:
    log_path.write_text("")
    error_path.write_text("")
    if results_path.exists():
        results_path.unlink()

    parsed = urlparse(domain.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        st.error("Invalid URL. Please include https://")
        st.stop()

    progress = st.progress(0)
    log_box = st.empty()

    try:
        subprocess.Popen(
            [sys.executable, "-m", "scrapy", "crawl", "seo", "-a", f"start_url={domain}", "-O", str(results_path), "-L", "WARNING"],
            stdout=open(log_path, "a", encoding="utf-8"),
            stderr=open(error_path, "a", encoding="utf-8")
        )
    except FileNotFoundError:
        st.error("Scrapy is not installed. pip install scrapy scrapy-playwright")
        st.stop()

    # Monitor progress by log lines (option A)
    status = st.empty()
    row_count = 0
    stable_ticks = 0
    wait_seconds = 600
    for _ in range(wait_seconds):
        if log_path.exists():
            try:
                lines = log_path.read_text(errors="ignore").splitlines()
                log_box.code("\n".join(lines[-12:]), language="text")
                pct = min(100, int(len(lines) / 50 * 100))  # approximate progress
                progress.progress(pct)
            except Exception:
                pass
        if error_path.exists() and error_path.stat().st_size > 0:
            err_txt = error_path.read_text(errors="ignore")
            st.error(err_txt)
            st.stop()
        time.sleep(1)

    progress.progress(100)
    status.text("Crawl finished. Check results below.")

    # Reload results after crawl
    if results_path.exists():
        try:
            df = pd.read_csv(results_path)
            if df.empty or df.iloc[0]["status"] == "Empty: run was not completed":
                st.warning("Crawl did not complete. Empty results file created.")
            else:
                st.subheader("Crawl results")
                st.dataframe(df)
                existing_cols = [c for c in preview_cols if c in df.columns]
                if existing_cols:
                    st.subheader("SEO Signals (Preview with highlights)")
                    st.dataframe(styled_dataframe(df[existing_cols].head(50)))
        except Exception:
            st.warning("Could not parse results.csv after crawl.")
