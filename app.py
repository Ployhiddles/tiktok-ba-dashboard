import re
import zipfile
from io import BytesIO
import html

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# -------------------- GLOBAL APP SETTINGS --------------------
st.set_page_config(page_title="TikTok BA Dashboard", layout="wide")

# TikTok-like theme + font (Inter feels close; safe for deployment)
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

      :root{
        --tt-black:#010101;
        --tt-white:#FFFFFF;
        --tt-cyan:#69C9D0;
        --tt-pink:#EE1D52;
        --tt-card: rgba(255,255,255,0.06);
        --tt-card-border: rgba(255,255,255,0.10);
      }

      html, body, [class*="css"]  {
        font-family: "Inter", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif !important;
      }

      .stApp{
        background:
          radial-gradient(1200px 800px at 18% 0%,
            rgba(105,201,208,0.12) 0%,
            rgba(1,1,1,1) 55%),
          radial-gradient(900px 700px at 82% 0%,
            rgba(238,29,82,0.14) 0%,
            rgba(1,1,1,1) 55%),
          #010101;
        color: var(--tt-white);
      }

      section[data-testid="stSidebar"]{
        background: rgba(1,1,1,0.92) !important;
        border-right: 1px solid rgba(255,255,255,0.08);
      }

      h1,h2,h3,h4{
        color: var(--tt-white) !important;
        letter-spacing: .2px;
      }

      /* Make Streamlit metric cards feel like TikTok UI */
      div[data-testid="stMetric"]{
        background: var(--tt-card);
        border: 1px solid var(--tt-card-border);
        border-radius: 18px;
        padding: 12px 14px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.35);
      }
      div[data-testid="stMetric"] label{
        color: rgba(255,255,255,0.72) !important;
      }

      /* Tabs highlight gradient */
      div[data-baseweb="tab-highlight"]{
        background: linear-gradient(90deg, var(--tt-cyan), var(--tt-pink)) !important;
      }
      button[data-baseweb="tab"]{
        color: rgba(255,255,255,0.75) !important;
        font-weight: 700 !important;
      }
      button[data-baseweb="tab"][aria-selected="true"]{
        color: white !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------- PARSERS --------------------
DATE_RE = re.compile(r"Date:\s*(.+?)\s*UTC")
LINK_RE = re.compile(r"Link:\s*(https?://\S+)")

def extract_video_id(url: str):
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else None

def parse_date_link_txt(text: str) -> pd.DataFrame:
    dates = DATE_RE.findall(text)
    links = LINK_RE.findall(text)
    n = min(len(dates), len(links))
    rows = []
    for i in range(n):
        rows.append({"ts_utc": dates[i], "url": links[i], "video_id": extract_video_id(links[i])})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], errors="coerce", utc=True)
    return df.dropna(subset=["ts_utc"])

def read_zip_txt(zf: zipfile.ZipFile, path: str) -> str:
    with zf.open(path) as f:
        return f.read().decode("utf-8", errors="replace")

@st.cache_data
def list_zip_paths(zip_bytes: bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        return zf.namelist()

@st.cache_data
def load_parsed_df(zip_bytes: bytes, path: str) -> pd.DataFrame:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        txt = read_zip_txt(zf, path)
    return parse_date_link_txt(txt)

def apply_date(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if df.empty or start_date is None or end_date is None:
        return df
    mask = (df["ts_utc"].dt.date >= start_date) & (df["ts_utc"].dt.date <= end_date)
    return df.loc[mask].copy()

def add_sessions(watch: pd.DataFrame, gap_minutes: int = 30) -> pd.DataFrame:
    if watch.empty:
        return watch
    w = watch.sort_values("ts_utc").copy()
    w["gap"] = w["ts_utc"].diff()
    w["new_session"] = (w["gap"].isna()) | (w["gap"] > pd.Timedelta(minutes=gap_minutes))
    w["session_id"] = w["new_session"].cumsum()
    return w

# -------------------- CARD GRID (CLIENT-SIDE oEmbed) --------------------
def render_cards_client_oembed(df: pd.DataFrame, cards_per_row: int, n: int, load_thumbs: bool):
    required = {"ts_utc", "url"}
    if df is None or df.empty:
        st.info("No rows to show. Try widening the date range or selecting the correct file.")
        return
    if not required.issubset(set(df.columns)):
        st.error(f"Selected file didn’t parse correctly. Found columns: {list(df.columns)}")
        return

    recent = (
        df.sort_values("ts_utc", ascending=False)
          .dropna(subset=["url"])
          .drop_duplicates(subset=["url"])
          .head(n)
          .copy()
    )

    card_divs = []
    for _, r in recent.iterrows():
        url = html.escape(str(r["url"]))
        time = pd.to_datetime(r["ts_utc"], utc=True).strftime("%Y-%m-%d %H:%M")

        card_divs.append(f"""
          <div class="card" data-url="{url}">
            <div class="cover placeholder"></div>
            <div class="meta">
              <div class="title">{("Loading…" if load_thumbs else "TikTok clip")}</div>
              <div class="sub">{time} UTC</div>
              <a class="btn" href="{url}" target="_blank" rel="noopener noreferrer">Open clip</a>
            </div>
          </div>
        """)

    js_block = ""
    if load_thumbs:
        js_block = r"""
        <script>
          async function fetchOembed(url) {
            const api = "https://www.tiktok.com/oembed?url=" + encodeURIComponent(url);
            const res = await fetch(api);
            if (!res.ok) throw new Error("oEmbed failed: " + res.status);
            return await res.json();
          }

          async function runLimited(tasks, limit=4) {
            let i = 0;
            const workers = new Array(limit).fill(0).map(async () => {
              while (i < tasks.length) {
                const idx = i++;
                try { await tasks[idx](); } catch(e) {}
              }
            });
            await Promise.all(workers);
          }

          const cards = Array.from(document.querySelectorAll(".card"));
          const tasks = cards.map(card => async () => {
            const url = card.dataset.url;
            const data = await fetchOembed(url);

            const thumb = data.thumbnail_url;
            const title = data.title || "TikTok clip";
            const author = data.author_name || "";

            card.querySelector(".title").textContent = title;

            const subEl = card.querySelector(".sub");
            if (author) subEl.textContent = subEl.textContent + " • " + author;

            if (thumb) {
              const cover = card.querySelector(".cover");
              cover.classList.remove("placeholder");
              cover.innerHTML = "";
              const img = document.createElement("img");
              img.src = thumb;
              img.loading = "lazy";
              cover.appendChild(img);
            }
          });

          runLimited(tasks, 4);
        </script>
        """

    html_doc = f"""
    <html>
    <head>
      <meta charset="utf-8"/>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    </head>

    <style>
      :root{{
        --tt-black:#010101;
        --tt-white:#FFFFFF;
        --tt-cyan:#69C9D0;
        --tt-pink:#EE1D52;
      }}

      body{{
        margin:0;
        background:transparent;
        color:var(--tt-white);
        font-family: "Inter", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      }}

      .grid{{
        display:grid;
        grid-template-columns:repeat({cards_per_row},1fr);
        gap:18px;
      }}

      .card{{
        aspect-ratio: 1 / 1;
        padding:12px;
        border-radius:22px;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.10);
        box-shadow: 0 12px 40px rgba(0,0,0,0.45);
        display:flex;
        flex-direction:column;
        justify-content:space-between;
        overflow:hidden;
        transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
      }}

      .card:hover{{
        transform: translateY(-4px) scale(1.02);
        border-color: rgba(255,255,255,0.18);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.12),
          0 18px 55px rgba(0,0,0,0.55),
          -10px 0 30px rgba(105,201,208,0.22),
          10px 0 30px rgba(238,29,82,0.20);
      }}

      .cover{{
        aspect-ratio:1/1;
        border-radius:18px;
        overflow:hidden;
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(255,255,255,0.06);
      }}

      .placeholder{{
        background:
          radial-gradient(600px 300px at 20% 0%, rgba(105,201,208,0.35), rgba(1,1,1,0) 60%),
          radial-gradient(600px 300px at 80% 0%, rgba(238,29,82,0.30), rgba(1,1,1,0) 60%),
          rgba(255,255,255,0.06);
      }}

      .cover img{{
        width:100%;
        height:100%;
        object-fit:cover;
        display:block;
        transition: transform .25s ease;
      }}

      .card:hover .cover img{{
        transform: scale(1.05);
      }}

      .meta{{ margin-top:10px; }}

      .title{{
        font-size:13px;
        font-weight:800;
        max-height:34px;
        overflow:hidden;
      }}

      .sub{{
        margin-top:4px;
        font-size:12px;
        opacity:0.75;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }}

      .btn{{
        margin-top:10px;
        display:block;
        padding:10px 12px;
        text-align:center;
        border-radius:14px;
        color: white;
        text-decoration:none;
        background: linear-gradient(90deg, rgba(105,201,208,0.18), rgba(238,29,82,0.18));
        border: 1px solid rgba(255,255,255,0.14);
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
        transition: transform .15s ease, border-color .15s ease, background .15s ease;
      }}

      .btn:hover{{
        transform: translateY(-1px);
        border-color: rgba(255,255,255,0.22);
        background: linear-gradient(90deg, rgba(105,201,208,0.26), rgba(238,29,82,0.26));
      }}
    </style>

    <body>
      <div class="grid">
        {''.join(card_divs)}
      </div>
      {js_block}
    </body>
    </html>
    """

    rows = (len(recent) + cards_per_row - 1) // cards_per_row
    height = min(1400, rows * 330 + 20)
    components.html(html_doc, height=height, scrolling=False)

# -------------------- APP UI --------------------
st.title("TikTok Engagement Dashboard")
st.caption("Upload your TikTok export ZIP to explore watch/like behavior, trends, sessions, and clips.")

uploaded = st.sidebar.file_uploader("Upload TikTok ZIP", type=["zip"])
if not uploaded:
    st.stop()

zip_bytes = uploaded.getvalue()
paths = list_zip_paths(zip_bytes)

# Auto-select correct file paths
watch_candidates = [p for p in paths if p.lower().endswith("watch history.txt")]
likes_candidates = [p for p in paths if p.lower().endswith("like list.txt")]

watch_default = watch_candidates[0] if watch_candidates else paths[0]
likes_default = likes_candidates[0] if likes_candidates else paths[0]

watch_path = st.sidebar.selectbox("Watch History file", paths, index=paths.index(watch_default))
likes_path = st.sidebar.selectbox("Like List file", paths, index=paths.index(likes_default))

watch = load_parsed_df(zip_bytes, watch_path)
likes = load_parsed_df(zip_bytes, likes_path)

st.sidebar.header("Display")
load_thumbs = st.sidebar.checkbox("Load thumbnails/titles", value=True)

# Date filters
min_dt = min([df["ts_utc"].min() for df in [watch, likes] if not df.empty], default=None)
max_dt = max([df["ts_utc"].max() for df in [watch, likes] if not df.empty], default=None)

c1, c2 = st.columns(2)
with c1:
    start = st.date_input("Start date", value=min_dt.date() if min_dt is not None else None)
with c2:
    end = st.date_input("End date", value=max_dt.date() if max_dt is not None else None)

watch_f = apply_date(watch, start, end) if (not watch.empty and "ts_utc" in watch.columns) else watch
likes_f = apply_date(likes, start, end) if (not likes.empty and "ts_utc" in likes.columns) else likes

# KPIs
st.subheader("KPIs")
watch_days = watch_f["ts_utc"].dt.date.nunique() if not watch_f.empty else 0
total_watches = len(watch_f)
total_likes = len(likes_f)

watch_video_ids = set(watch_f["video_id"].dropna()) if ("video_id" in watch_f.columns and not watch_f.empty) else set()
like_video_ids = set(likes_f["video_id"].dropna()) if ("video_id" in likes_f.columns and not likes_f.empty) else set()
watch_to_like = (len(watch_video_ids & like_video_ids) / len(watch_video_ids)) if watch_video_ids else 0.0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total watches", f"{total_watches:,}")
k2.metric("Total likes", f"{total_likes:,}")
k3.metric("Active days", f"{watch_days:,}")
k4.metric("Watch → Like conversion", f"{watch_to_like:.1%}")

st.divider()

# Trends graphs
st.subheader("Trends")
t1, t2 = st.columns(2)

if not watch_f.empty:
    watch_daily = (
        watch_f.assign(day=watch_f["ts_utc"].dt.date)
        .groupby("day").size()
        .reset_index(name="watch_events")
    )
    t1.line_chart(watch_daily.set_index("day"))
else:
    t1.info("No watch data in this date range.")

if not likes_f.empty:
    likes_daily = (
        likes_f.assign(day=likes_f["ts_utc"].dt.date)
        .groupby("day").size()
        .reset_index(name="like_events")
    )
    t2.line_chart(likes_daily.set_index("day"))
else:
    t2.info("No likes data in this date range.")

st.divider()

# Sessions
st.subheader("Session behavior (from Watch History)")
gap_minutes = st.slider("Session gap (minutes)", 5, 120, 30, step=5)

w_s = add_sessions(watch_f, gap_minutes=gap_minutes) if not watch_f.empty else pd.DataFrame()
if not w_s.empty:
    session_stats = (
        w_s.groupby("session_id")
        .agg(session_start=("ts_utc", "min"),
             session_end=("ts_utc", "max"),
             events=("ts_utc", "size"))
        .reset_index()
    )
    session_stats["duration_min"] = (
        (session_stats["session_end"] - session_stats["session_start"]).dt.total_seconds() / 60.0
    )
    st.dataframe(session_stats.sort_values("session_start", ascending=False).head(30),
                 use_container_width=True, hide_index=True)
else:
    st.info("No sessions found for the selected range.")

st.divider()

# Clip cards
st.subheader("Clips")
cards_per_row = st.slider("Cards per row", 2, 5, 4)
num_cards = st.slider("Number of clips", 4, 40, 12, step=4)

tab1, tab2 = st.tabs(["Watched", "Liked"])
with tab1:
    render_cards_client_oembed(watch_f, cards_per_row, num_cards, load_thumbs)
with tab2:
    render_cards_client_oembed(likes_f, cards_per_row, num_cards, load_thumbs)
