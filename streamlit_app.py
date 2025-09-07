import streamlit as st
import pandas as pd
import pathlib
import time
from urllib.parse import urlparse

st.title("SEO Crawl & Indexability Auditor")

domain = st.text_input("Domain (https://example.com)")
run_clicked = st.button("Run")

out_dir = pathlib.Path("out")
out_dir.mkdir(parents=True, exist_ok=True)

results_path = out_dir / "results.csv"
log_path = out_dir / "runner.log" # optional: have your crawler write logs here
error_path = out_dir / "error.log" # optional: have your crawler write errors here
# Show latest results if available
if results_path.exists():
    st.subheader("Latest results")
    try:
        st.dataframe(pd.read_csv(results_path))
    except Exception as e:
        st.error(f"Could not read results.csv: {e}")    
if run_clicked:
    with st.status("Preparing to crawl…", expanded=True) as status:
        try:
            # 1) Validate input
            status.write("Validating input…")
            parsed = urlparse(domain.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                status.update(label="Invalid URL. Please include https://", state="error")
                st.stop()

            # 2) Launch your crawler here
            import sys
            import subprocess
            status.write("Launching crawler…")

            try:
                subprocess.Popen(
                    [
                        sys.executable, "-m", "scrapy", "crawl", "options",
                        "-a", f"start_url={domain}",
                        "-O", str(results_path),
                    ],
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=open(error_path, "a", encoding="utf-8"),
                )
            except FileNotFoundError:
                status.update(label="Cannot start crawler", state="error")
                st.error(
                    "Scrapy is not available in this Python environment.\n"
                    "Install it into the same env and restart Streamlit, or run Streamlit from the env."
                )
                st.code("pip install scrapy scrapy-playwright")
                st.stop()
            # 3) Monitor progress
            progress = st.progress(0)
            log_box = st.empty()
            wait_seconds = 600
            last_size = -1
            stable_ticks = 0

            status.write("Crawling… this may take a while.")
            for i in range(wait_seconds):
                if log_path.exists():
                    try:
                        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                            tail = f.readlines()[-12:]
                        log_box.code("".join(tail), language="text")
                    except Exception:
                        pass

                if error_path.exists() and error_path.stat().st_size > 0:
                    try:
                        err_txt = error_path.read_text(encoding="utf-8", errors="ignore")
                        status.update(label="Crawler reported an error", state="error")
                        st.error(err_txt.strip() or "Unknown error. See error log.")
                        st.stop()
                    except Exception:
                        status.update(label="Crawler reported an error", state="error")
                        st.error("An error occurred. See out/error.log.")
                        st.stop()

                if results_path.exists():
                    size = results_path.stat().st_size
                    if size == last_size:
                        stable_ticks += 1
                    else:
                        stable_ticks = 0
                    last_size = size

                    if stable_ticks >= 2:
                        break

                pct = min(100, int((i / wait_seconds) * 100))
                progress.progress(pct)
                time.sleep(1)
            else:
                status.update(label="Timed out waiting for results.", state="error")
                st.error("Timed out waiting for out/results.csv. Check logs.")
                st.stop()

            # 4) Load and show results  ✅ moved INSIDE the with-block
            status.write("Loading results…")
            df = pd.read_csv(results_path)
            st.subheader("Crawl results")
            st.dataframe(df)
            progress.progress(100)
            status.update(label="Crawl complete", state="complete")
        except Exception as e:
            status.update(label="An unexpected error occurred", state="error")
            st.exception(e)
