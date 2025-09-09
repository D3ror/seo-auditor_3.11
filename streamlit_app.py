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

out_dir = pathlib.Path("out")
results_path = out_dir / "results.csv"
log_path = out_dir / "runner.log"
error_path = out_dir / "error.log"
progress_file = out_dir / "progress.signal"

preview_cols = ["url","status","title","h1","canonical","robots_meta","hreflang_count","duplicate_title","duplicate_h1"]

def highlight_issues(val, colname):
    if colname == "status" and val != 200:
        return "background-color: rgba(255, 0, 0, 0.1)"
    if colname in ("duplicate_title","duplicate_h1") and val:
        return "background-color: rgba(255, 165, 0, 0.1)"
    if colname in ("canonical","robots_meta") and (pd.isna(val) or val==""):
        return "background-color: rgba(255, 255, 0, 0.1)"
    return ""

def styled_dataframe(df):
    return df.style.applymap(lambda v: highlight_issues(v,"status"),subset=["status"])\
                   .applymap(lambda v: highlight_issues(v,"duplicate_title"),subset=["duplicate_title"])\
                   .applymap(lambda v: highlight_issues(v,"duplicate_h1"),subset=["duplicate_h1"])\
                   .applymap(lambda v: highlight_issues(v,"canonical"),subset=["canonical"])\
                   .applymap(lambda v: highlight_issues(v,"robots_meta"),subset=["robots_meta"])

if run_clicked:
    log_path.write_text("")
    error_path.write_text("")
    if results_path.exists(): results_path.unlink()
    if progress_file.exists(): progress_file.write_text("0")

    parsed = urlparse(domain.strip())
    if parsed.scheme not in ("http","https") or not parsed.netloc:
        st.error("Invalid URL. Include https://")
        st.stop()

    try:
        subprocess.Popen(
            [sys.executable,"-m","scrapy","crawl","seo","-a",f"start_url={domain}","-O",str(results_path),"-L","WARNING"],
            stdout=open(log_path,"a",encoding="utf-8"),
            stderr=open(error_path,"a",encoding="utf-8")
        )
    except FileNotFoundError:
        st.error("Scrapy not found in environment.")
        st.stop()

    st.write("Crawling…")
    progress_bar = st.progress(0)

    # Track progress from progress.signal
    prev_count = 0
    timeout_sec = 600
    for _ in range(timeout_sec):
        time.sleep(1)
        try:
            if progress_file.exists():
                count = int(progress_file.read_text().strip() or 0)
                if count != prev_count:
                    progress_bar.progress(min(count,100))  # approximate
                    prev_count = count
        except Exception:
            pass
        if results_path.exists() and prev_count>0: break
    progress_bar.progress(100)

    # Show results
    try:
        df = pd.read_csv(results_path)
        if df.empty or "Empty: run was not completed" in df.columns[0]:
            st.warning("Crawl did not complete. Empty results file created.")
        else:
            st.subheader("Crawl results")
            st.dataframe(df)
            existing_cols = [c for c in preview_cols if c in df.columns]
            if existing_cols:
                st.subheader("SEO Signals")
                st.dataframe(styled_dataframe(df[existing_cols].head(50)))
    except Exception as e:
        st.error(f"Could not read results.csv: {e}")
