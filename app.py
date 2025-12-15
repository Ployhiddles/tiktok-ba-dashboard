import re
import zipfile
from io import BytesIO
import html as html_escape

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# ---------- Parsers ----------
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
def load_data(zip_bytes: bytes, watch_path: str, likes_path: str):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        watch_txt = read_zip_txt(zf, watch_path)
        likes_txt = read_zip_txt(zf, likes_path)
    watch = parse_date_link_txt(watch_txt)
    likes = parse_date_link_txt(likes_txt)
    return watch, likes

def add_sessions(watch: pd.DataFrame, gap_minutes: int = 30) -> pd.DataFrame:
    if watch.empty:
        return watch
    w = watch.sort_values("ts_utc").copy()
    w["gap"] = w["ts_utc"].diff()
    w["new_session"] = (w["gap"].isna()) | (w["gap"] > pd.Timedelta(minutes=gap_minutes))
    w["session_id"] = w["new_session"].cumsum()
    return w

def apply_date(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if df.empty or start_date is None or end_date is None:
        return df
    mask = (df["ts_utc"].dt.date >= start_date) & (df["ts_utc"].dt.date <= end_date)
    return df.loc[mask].copy()

# ---------- TikTok Thumbnail via oEmbed ----------
@st.cache_data(show_spinner=False)
def get_tiktok_oembed(url: str) -> dict:
    """
    Uses TikTok oEmbed to get a thumbnail/title/author for a video URL.
    If TikTok blocks requests on your network, it returns {} and we show a gradient cover.
    """
    try:
        api = "https://www.tiktok.com/oembed"
        r = requests.get(
            api,
            params={"url": url},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            data = r.json()
            return {
                "thumbnail_url": data.get("thumbnail_url"),
                "title": data.get("title"),
                "author_name": data.get("author_name"),
            }
    except Exception:
        pass
    return {}

# ---------- Components-based Card Grid (always renders HTML) ----------
def render_clip_cards_components(df: pd.DataFrame, title: str, cards_per_row: int, n: int):
    st.markdown(f"**{title}**")
    if df.empty:
        st.info("No data in this date range.")
        return

    recent = (
        df.sort_values("ts_utc", ascending=False)
          .dropna(subset=["url"])
          .drop_duplicates(subset=["url"])
          .head(n)
          .copy()
    )
    recent["time_utc"] = recent["ts_utc"].dt.strftime("%Y-%m-%d %H:%M")

    cards = []
    for _, r in recent.iterrows():
        url = r["url"]
        vid = r.get("video_id") or ""
        time_utc = r["time_utc"]

        meta = get_tiktok_oembed(url)
        thumb = meta.get("thumbnail_url")
        title_txt = meta.get("title") or "TikTok clip"
        author = meta.get("author_name") or ""

        # HTML escape text fields
        safe_title = html_escape.escape(title_txt)
        safe_author = html_escape.escape(author)
        safe_vid = html_escape.escape(vid)
        safe_time = html_escape.escape(time_utc)
        safe_url = html_escape.escape(url)

        # thumbnail or gradient background
        if thumb:
            cover = f"""
              <div class="cover">
                <img src="{html_escape.escape(thumb)}" alt="thumb" loading="lazy" />
              </div>
            """
        else:
            seed = sum(ord(c) for c in str(vid)) % 360
            cover = f"""
              <div class="cover" style="
                background: linear-gradient(135deg,
                  hsla({seed},90%,60%,0.85),
                  hsla({(seed+60)%360},90%,55%,0.70));
              "></div>
            """

        cards.append(f"""
          <div class="card">
            {cover}
            <div class="meta">
              <div class="title">{safe_title}</div>
              <div class="sub">{safe_time} UTC{(" • " + safe_author) if author else ""}</div>
              <div class="id">Video ID: {safe_vid if vid else "—"}</div>
              <a class="btn" href="{safe_url}" target="_blank" rel="noopener noreferrer">Open clip</a>
            </div>
          </div>
        """)

    grid_html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <style>
        :root {{
          color-scheme: dark;
        }}
        body {{
          margin: 0;
          padding: 0;
          font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
          background: transparent;
          color: white;
        }}
        .grid {{
          display: grid;
          grid-template-columns: repeat({cards_per_row}, 1fr);
          gap: 16px;
        }}
        .card {{
          border-radius: 18px;
          padding: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          box-shadow: 0 10px 30px rgba(0,0,0,0.25);
          height: 270px;
          display:flex;
          flex-direction:column;
          justify-content:space-between;
          overflow:hidden;
        }}
        .cover {{
          border-radius: 14px;
          height: 150px;
          width: 100%;
          border: 1px solid rgba(255,255,255,0.10);
          overflow:hidden;
          background: rgba(255,255,255,0.06);
        }}
        .cover img {{
          width: 100%;
          height: 150px;
          object-fit: cover;
          display: block;
        }}
        .meta {{
          margin-top: 10px;
          line-height: 1.2;
        }}
        .title {{
          font-size: 13px;
          font-weight: 650;
          opacity: 0.95;
          max-height: 34px;
          overflow: hidden;
        }}
        .sub {{
          font-size: 12px;
          opacity: 0.75;
          margin-top: 4px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }}
        .id {{
          font-size: 11px;
          opacity: 0.65;
          margin-top: 4px;
          word-break: break-all;
        }}
        .btn {{
          margin-top: 10px;
          display: inline-block;
          text-decoration: none;
          padding: 8px 12px;
          border-radius: 12px;
          background: rgba(255,255,255,0.10);
          border: 1px solid rgba(255,255,255,0.15);
          color: white;
          font-size: 13px;
          text-align: center;
        }}
        .btn:hover {{
          background: rgba(255,255,255,0.16);
        }}
      </style>
    </head>
    <body>
      <div class="grid">
        {''.join(cards)}
      </div>
    </body>
    </html>
    """

    # Height: roughly 270px per row + gaps; keep it comfy
    rows = (len(recent) + cards_per_row - 1) // cards_per_row
    height = min(1200, rows * 290 + 10)

    components.html(grid_html, height=height, scrolling=False)

# ---------- App ----------
st.set_page_config(page_title="Engagement & Retention Dashboard", layout="wide")
st.title("Engagement & Retention Dashboard")
st.caption("Business Analyst case study using anonymized interaction logs from a short-form video platform export.")

# Upload ZIP
st.sidebar.header("1) Upload your TikTok export")
uploaded = st.sidebar.file_uploader("Upload ZIP", type=["zip"])
if not uploaded:
    st.warning("Upload your TikTok export ZIP file to start.")
    st.stop()

zip_bytes = uploaded.getvalue()

# Choose files inside ZIP
all_paths = list_zip_paths(zip_bytes)

st.sidebar.header("2) Select files inside the ZIP")
watch_candidates = [p for p in all_paths if p.lower().endswith("watch history.txt")]
likes_candidates = [p for p in all_paths if p.lower().endswith("like list.txt")]

watch_path = st.sidebar.selectbox("Watch History file", watch_candidates if watch_candidates else all_paths)
likes_path = st.sidebar.selectbox("Like List file", likes_candidates if likes_candidates else all_paths)

watch, likes = load_data(zip_bytes, watch_path, likes_path)

# Date filters
min_dt = min([df["ts_utc"].min() for df in [watch, likes] if not df.empty], default=None)
max_dt = max([df["ts_utc"].max() for df in [watch, likes] if not df.empty], default=None)

c1, c2 = st.columns(2)
with c1:
    start = st.date_input("Start date", value=min_dt.date() if min_dt is not None else None)
with c2:
    end = st.date_input("End date", value=max_dt.date() if max_dt is not None else None)

watch_f = apply_date(watch, start, end)
likes_f = apply_date(likes, start, end)

# KPIs
watch_days = watch_f["ts_utc"].dt.date.nunique() if not watch_f.empty else 0
total_watches = len(watch_f)
total_likes = len(likes_f)

watch_video_ids = set(watch_f["video_id"].dropna())
like_video_ids = set(likes_f["video_id"].dropna())
watch_to_like = (len(watch_video_ids & like_video_ids) / len(watch_video_ids)) if watch_video_ids else 0.0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total watches", f"{total_watches:,}")
k2.metric("Total likes", f"{total_likes:,}")
k3.metric("Active days (watch)", f"{watch_days:,}")
k4.metric("Watch → Like conversion", f"{watch_to_like:.1%}")

st.divider()

# Trends
st.subheader("Trends")
t1, t2 = st.columns(2)

if not watch_f.empty:
    watch_daily = (
        watch_f.assign(day=watch_f["ts_utc"].dt.date)
        .groupby("day")
        .size()
        .reset_index(name="watch_events")
    )
    t1.line_chart(watch_daily.set_index("day"))
else:
    t1.info("No watch history in this date range.")

if not likes_f.empty:
    likes_daily = (
        likes_f.assign(day=likes_f["ts_utc"].dt.date)
        .groupby("day")
        .size()
        .reset_index(name="like_events")
    )
    t2.line_chart(likes_daily.set_index("day"))
else:
    t2.info("No likes in this date range.")

st.divider()

# Sessions
st.subheader("Session behavior (based on watch history)")
gap_minutes = st.slider("Session gap (minutes)", min_value=5, max_value=120, value=30, step=5)

w_s = add_sessions(watch_f, gap_minutes=gap_minutes)
if not w_s.empty:
    session_stats = (
        w_s.groupby("session_id")
        .agg(
            session_start=("ts_utc", "min"),
            session_end=("ts_utc", "max"),
            events=("ts_utc", "size"),
        )
        .reset_index()
    )
    session_stats["duration_min"] = (
        (session_stats["session_end"] - session_stats["session_start"]).dt.total_seconds() / 60.0
    )
    st.dataframe(
        session_stats.sort_values("session_start", ascending=False).head(30),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No sessions found in this date range.")

st.divider()

# Clip cards with thumbnails (NO raw HTML text)
st.subheader("TikTok clip links")
cards_per_row = st.slider("Cards per row", min_value=2, max_value=5, value=4, step=1)
num_cards = st.slider("How many clips to show", min_value=4, max_value=40, value=12, step=4)

tab1, tab2 = st.tabs(["Most recent watched", "Most recent liked"])
with tab1:
    render_clip_cards_components(watch_f, "Watched clips", cards_per_row=cards_per_row, n=num_cards)
with tab2:
    render_clip_cards_components(likes_f, "Liked clips", cards_per_row=cards_per_row, n=num_cards)


