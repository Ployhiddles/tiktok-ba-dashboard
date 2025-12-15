import re
import zipfile
import pandas as pd
import streamlit as st
from io import BytesIO

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
        rows.append(
            {"ts_utc": dates[i], "url": links[i], "video_id": extract_video_id(links[i])}
        )
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

# ---------- Card Grid UI ----------
st.markdown(
    """
    <style>
      .clip-grid-card{
        border-radius: 16px;
        padding: 14px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        height: 220px;
        display:flex;
        flex-direction:column;
        justify-content:space-between;
        overflow:hidden;
      }
      .clip-cover{
        border-radius: 14px;
        height: 120px;
        width: 100%;
        border: 1px solid rgba(255,255,255,0.10);
      }
      .clip-meta{
        margin-top: 10px;
        line-height: 1.25;
      }
      .clip-time{
        font-size: 12px;
        opacity: 0.8;
      }
      .clip-id{
        font-size: 12px;
        opacity: 0.7;
        margin-top: 4px;
        word-break: break-all;
      }
      .clip-btn{
        margin-top: 10px;
        display:inline-block;
        text-decoration:none;
        padding: 8px 12px;
        border-radius: 12px;
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.15);
        color: white !important;
        font-size: 13px;
        text-align:center;
      }
      .clip-btn:hover{
        background: rgba(255,255,255,0.16);
      }
    </style>
    """,
    unsafe_allow_html=True,
)

def render_clip_cards(df: pd.DataFrame, title: str, cards_per_row: int = 4, n: int = 12):
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

    rows = [recent.iloc[i:i+cards_per_row] for i in range(0, len(recent), cards_per_row)]
    for chunk in rows:
        cols = st.columns(cards_per_row, gap="large")
        for i, (_, r) in enumerate(chunk.iterrows()):
            vid = (r.get("video_id") or "")
            seed = sum(ord(c) for c in str(vid)) % 360
            cover_style = (
                f"background: linear-gradient(135deg, "
                f"hsla({seed},90%,60%,0.85), hsla({(seed+60)%360},90%,55%,0.70));"
            )
            card_html = f"""
              <div class="clip-grid-card">
                <div class="clip-cover" style="{cover_style}"></div>
                <div class="clip-meta">
                  <div class="clip-time">{r['time_utc']} UTC</div>
                  <div class="clip-id">Video ID: {vid if vid else "—"}</div>
                  <a class="clip-btn" href="{r['url']}" target="_blank" rel="noopener noreferrer">Open clip</a>
                </div>
              </div>
            """
            with cols[i]:
                st.markdown(card_html, unsafe_allow_html=True)

# ---------- Streamlit App ----------
st.set_page_config(page_title="Engagement & Retention Dashboard", layout="wide")
st.title("Engagement & Retention Dashboard")
st.caption("Business Analyst case study using anonymized interaction logs from a short-form video platform export.")

# 1) Upload ZIP (works for GitHub + Streamlit Cloud)
st.sidebar.header("1) Upload your TikTok export")
uploaded = st.sidebar.file_uploader("Upload ZIP", type=["zip"])
if not uploaded:
    st.warning("Upload your TikTok export ZIP file to start.")
    st.stop()

zip_bytes = uploaded.getvalue()

# 2) Choose files inside ZIP
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

# TikTok clip links (card grid like your screenshot)
st.subheader("TikTok clip links")
tab1, tab2 = st.tabs(["Most recent watched", "Most recent liked"])

with tab1:
    render_clip_cards(watch_f, "Watched clips", cards_per_row=4, n=12)

with tab2:
    render_clip_cards(likes_f, "Liked clips", cards_per_row=4, n=12)

