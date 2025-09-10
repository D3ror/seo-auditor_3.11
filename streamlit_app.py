import streamlit as st
import pandas as pd
import pathlib
import time
from urllib.parse import urlparse
import sys
import subprocess
import json
import uuid
import tempfile
import logging, warnings, io

st.set_page_config(page_title="SEO Crawl & Indexability Auditor", layout="wide")

st.title("SEO Crawl & Indexability Auditor")

# --- Session state setup (isolates users & avoids cross-session leakage) ---
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
if "running" not in st.session_state:
    st.session_state.running = False
if "last_results" not in st.session_state:
    st.session_state.last_results = None

# --- Directories and file paths (use tmp per session to avoid leaks) ---
out_dir = pathlib.Path(tempfile.gettempdir()) / f"seo_auditor_{st.session_state.session_id}"
out_dir.mkdir(parents=True, exist_ok=True)

results_path = out_dir / "results.csv"
log_path = out_dir / "runner.log"
error_path = out_dir / "error.log"

preview_cols = [
    "url", "status", "title", "h1", "canonical", "robots_meta",
    "hreflang_count", "duplicate_title", "duplicate_h1",
]

# --- Logging + warnings capture (non-fatal) ---
log_buf = io.StringIO()
handler = logging.StreamHandler(log_buf)
logger = logging.getLogger("seo_auditor")
logger.setLevel(logging.INFO)
logger.handlers = []
logger.addHandler(handler)
logging.captureWarnings(True)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def highlight_issues(val, colname):
    """UI highlight for common SEO issues."""
    import pandas as pd
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


# --- Form ensures deterministic "Run" button behaviour ---
with st.form("crawl_form"):
    domain = st.text_input("Domain (https://example.com)")
    submitted = st.form_submit_button("Run crawl", disabled=st.session_state.running)

# --- Only run if form submitted ---
if submitted:
    with st.status("Preparing to crawl…", expanded=True) as status:
        st.session_state.running = True
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
                st.session_state.running = False
                st.stop()

            # 2) Launch crawler (blocking is safer for portfolio demo)
            status.write("Launching crawler…")
            try:
                process = subprocess.Popen(
                    [
                        sys.executable, "-m", "scrapy", "crawl", "seo",
                        "-a", f"start_url={domain}",
                        "-O", str(results_path),
                        "-L", "WARNING",
                    ],
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=open(error_path, "a", encoding="utf-8"),
                )
            except FileNotFoundError:
                status.update(label="Cannot start crawler", state="error")
                st.error("Scrapy is not available in this environment.")
                st.code("pip install scrapy scrapy-playwright")
                st.session_state.running = False
                st.stop()

            # 3) Monitor progress
            progress = st.progress(0)
            log_box = st.empty()
            row_count, stable_ticks = 0, 0
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

                # Only treat *real* errors as fatal
                if error_path.exists() and error_path.stat().st_size > 0:
                    err_txt = error_path.read_text(encoding="utf-8", errors="ignore")

                    # Define non-fatal patterns to ignore
                    non_fatal = ("DeprecationWarning", "UserWarning", "Retrying", "Ignoring")
                    if any(w in err_txt for w in non_fatal):
                        # Just show warning in log panel, don’t stop crawl
                        log_box.code(err_txt.strip(), language="text")
                        # Reset error.log so it doesn’t trip again
                        error_path.write_text("")
                    else:
                        # Fatal error: stop crawl
                        status.update(label="Crawler reported a fatal error", state="error")
                        st.error(err_txt.strip() or "Unknown error. See error log.")
                        st.session_state.running = False
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
                        progress.progress(min(100, max(5, row_count)))
                    except Exception:
                        pass
                    if stable_ticks >= 3:
                        break
                time.sleep(1)
            else:
                status.update(label="Timed out waiting for results.", state="error")
                st.error("Timed out waiting for results.csv. Check logs.")
                st.session_state.running = False
                st.stop()

            # 4) Load and show results
            status.write("Loading results…")
            try:
                df = pd.read_csv(results_path)
                st.session_state.last_results = df  # per-session only

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
                            key=f"download_csv_{st.session_state.session_id}",
                        )
                        st.download_button(
                            "Download JSON",
                            data=df.to_json(orient="records", indent=2).encode("utf-8"),
                            file_name="seo_audit_results.json",
                            mime="application/json",
                            key=f"download_json_{st.session_state.session_id}",
                        )

                progress.progress(100)
                status.update(label="Crawl complete", state="complete")
            except Exception as e:
                st.error(f"Crawl completed but results file could not be parsed: {e}")
        except Exception as e:
            status.update(label="An unexpected error occurred", state="error")
            st.exception(e)
        finally:
            st.session_state.running = False



# --- Show logs & warnings (non-fatal) ---
with st.expander("Crawler logs & warnings (non-fatal)"):
    st.text(log_buf.getvalue())
    if log_path.exists():
        st.text("--- crawler stdout ---")
        st.text(log_path.read_text(encoding="utf-8", errors="ignore"))


