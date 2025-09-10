import streamlit as st
import pandas as pd
import pathlib
import time
from urllib.parse import urlparse
import sys
import subprocess
import json

st.set_page_config(page_title="SEO Crawl & Indexability Auditor", layout="wide")

st.title("SEO Crawl & Indexability Auditor")

domain = st.text_input("Domain (https://example.com)")
run_clicked = st.button("Run")

out_dir = pathlib.Path("out")
out_dir.mkdir(parents=True, exist_ok=True)

results_path = out_dir / "results.csv"
log_path = out_dir / "runner.log"
error_path = out_dir / "error.log"

preview_cols = [
    "url", "status", "wait_time", "title", "h1", "canonical",
    "robots_meta", "hreflang_count", "duplicate_title", "duplicate_h1",
]

def highlight_issues(val, colname):
    if colname == "status" and val != 200 and val != "failed":
        return "background-color: rgba(255, 0, 0, 0.1)"
    if colname == "status" and val == "failed":
        return "background-color: rgba(255, 0, 0, 0.2)"
    if colname == "duplicate_title" and val:
        return "background-color: rgba(255, 165, 0, 0.1)"
    if colname == "duplicate_h1" and val:
        return "background-color: rgba(255, 165, 0, 0.1)"
    if colname in ("canonical", "robots_meta") and (pd.isna(val) or val == ""):
        return "background-color: rgba(255, 255, 0, 0.1)"
    return ""

def styled_dataframe(df):
    style = df.style
    for col in ["status", "duplicate_title", "duplicate_h1", "canonical", "robots_meta"]:
        if col in df.columns:
            style = style.applymap(lambda v, c=col: highlight_issues(v, c), subset=[col])
    return style

# Show latest results
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
    except Exception as e:
        st.error(f"Could not read results.csv: {e}")

if run_clicked:
    with st.status("Preparing to crawl…", expanded=True) as status:
        try:
            log_path.write_text("")
            error_path.write_text("")
            if results_path.exists():
                results_path.unlink()

            status.write("Validating input…")
            parsed = urlparse(domain.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                status.update(label="Invalid URL. Please include https://", state="error")
                st.stop()

            status.write("Launching crawler…")
            try:
                subprocess.run(
                    [
                        sys.executable, "-m", "scrapy", "crawl", "seo",
                        "-a", f"start_url={domain}",
                        "-O", str(results_path),
                        "-L", "WARNING",
                    ],
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=open(error_path, "a", encoding="utf-8"),
                    check=False,
                )
            except FileNotFoundError:
                status.update(label="Cannot start crawler", state="error")
                st.error("Scrapy is not available in this environment.")
                st.stop()

            progress = st.progress(100)
            status.write("Crawl finished. Loading results…")

            try:
                df = pd.read_csv(results_path)

                if "Empty: run was not completed" in df.columns[0]:
                    st.warning("Crawl did not complete. Empty results file created.")
                elif df.empty:
                    st.warning("Crawl completed but no results were parsed.")
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

                status.update(label="Crawl complete", state="complete")

            except Exception as e:
                st.error(f"Crawl completed but results file could not be parsed: {e}")

        except Exception as e:
            status.update(label="Unexpected error", state="error")
            st.exception(e)
