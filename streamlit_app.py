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

# Columns we care about for SEO preview
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

# Helper: Highlight SEO issues with semi-transparent colors
def highlight_issues(val, colname):
    if colname == "status" and val != 200:
        return "background-color: rgba(255, 0, 0, 0.1)"  # faint red
    if colname == "duplicate_title" and val:
        return "background-color: rgba(255, 165, 0, 0.1)"  # faint orange
    if colname == "duplicate_h1" and val:
        return "background-color: rgba(255, 165, 0, 0.1)"  # faint orange
    if colname in ("canonical", "robots_meta") and (pd.isna(val) or val == ""):
        return "background-color: rgba(255, 255, 0, 0.1)"  # faint yellow
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

# Show latest results if available
if results_path.exists():
    st.subheader("Latest results")
    try:
        df = pd.read_csv(results_path)

        # Detect empty run marker
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
        	st.warning("Results file exists but doesn’t contain SEO columns.")
     else:
          if "Empty: run was not completed" in df.columns or "Empty: run was not completed" in df.iloc[0].to_string():
        	st.warning("Crawl finished with no results. (Empty run)")
    	  else:
        	st.warning("Results file exists but has no SEO data.")

                # Download buttons
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

                # Google Sheets export (if secrets available)
                if "gcp_service_account" in st.secrets:
                    try:
                        import gspread
                        from google.oauth2.service_account import Credentials

                        creds = Credentials.from_service_account_info(
                            st.secrets["gcp_service_account"],
                            scopes=["https://www.googleapis.com/auth/spreadsheets"]
                        )
                        client = gspread.authorize(creds)
                        sheet = client.create("SEO Audit Results")
                        worksheet = sheet.get_worksheet(0)
                        worksheet.update([df.columns.values.tolist()] + df.values.tolist())
                        st.success(f"Exported to Google Sheets: {sheet.url}")
                    except Exception as e:
                        st.error(f"Could not export to Google Sheets: {e}")
                else:
                    st.info("Google Sheets export not configured (set `gcp_service_account` in Streamlit secrets).")
    except Exception as e:
        st.error(f"Could not read results.csv: {e}")

if run_clicked:
    with st.status("Preparing to crawl…", expanded=True) as status:
        try:
            # Reset logs and results
            log_path.write_text("")
            error_path.write_text("")
            if results_path.exists():
                results_path.unlink()

            # 1) Validate input
            status.write("Validating input…")
            parsed = urlparse(domain.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                status.update(label="Invalid URL. Please include https://", state="error")
                st.stop()

            # 2) Launch crawler
            status.write("Launching crawler…")
            try:
                subprocess.Popen(
                    [
                        sys.executable, "-m", "scrapy", "crawl", "seo",
                        "-a", f"start_url={domain}",
                        "-O", str(results_path),
                        "-L", "WARNING",  # suppress startup chatter
                    ],
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=open(error_path, "a", encoding="utf-8"),
                )
            except FileNotFoundError:
                status.update(label="Cannot start crawler", state="error")
                st.error("Scrapy is not available in this environment.")
                st.code("pip install scrapy scrapy-playwright")
                st.stop()

            # 3) Monitor progress
            progress = st.progress(0)
            log_box = st.empty()
            row_count = 0
            stable_ticks = 0
            wait_seconds = 600

            status.write("Crawling… this may take a while.")
            for i in range(wait_seconds):
                # Show logs
                if log_path.exists():
                    try:
                        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                            tail = f.readlines()[-12:]
                        log_box.code("".join(tail), language="text")
                    except Exception:
                        pass

                # Show errors if crawl fails
                if error_path.exists() and error_path.stat().st_size > 0:
                    err_txt = error_path.read_text(encoding="utf-8", errors="ignore")
                    status.update(label="Crawler reported an error", state="error")
                    st.error(err_txt.strip() or "Unknown error. See error log.")
                    st.stop()

                # Track progress via results
                if results_path.exists():
                    try:
                        df = pd.read_csv(results_path)
                        new_rows = len(df)
                        if new_rows > row_count:
                            row_count = new_rows
                            stable_ticks = 0
                        else:
                            stable_ticks += 1

                        pct = min(100, max(5, row_count))
                        progress.progress(pct)
                    except Exception:
                        pass

                    if stable_ticks >= 3:
                        break

                time.sleep(1)
            else:
                status.update(label="Timed out waiting for results.", state="error")
                st.error("Timed out waiting for out/results.csv. Check logs.")
                st.stop()

            # 4) Load and show results
            status.write("Loading results…")
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

                        # Download buttons
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

            except Exception:
                st.error("Crawl completed but results file could not be parsed.")

        except Exception as e:
            status.update(label="An unexpected error occurred", state="error")
            st.exception(e)
