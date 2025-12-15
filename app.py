import re
import zipfile
import pandas as pd
import streamlit as st

# --------- Parsers ---------
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
            {
                "ts_utc": dates[i],
                "url": links[i],
                "video_id": extract_video_id(links[i]),
            }
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
    with zipfile.ZipFile(pd.io.common.BytesIO(zip_bytes)) as zf:
        return zf.namelist()

@st.cache_data
def load_data(zip_bytes: bytes, watch_path: str, likes_path: str):
    bio = pd.io.common.BytesIO(zip_bytes)
    with zipfile.ZipFile(bio) as zf:
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

def make_links_table(df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    if df.empty:
        return df
    out = (
        df.sort_values("ts_utc", ascending=False)
        .dropna(subset=["url"])
        .drop_duplicates(subset=["url"])
        .head(n)
        .copy()
    )
    out["time_utc"] = out["ts_utc"].dt.strftime("%Y-%m-%d %H:%M")
    return out[["time_utc", "url", "video_id"]]

# --------- UI ---------
st.set_page_config(page_title="Engagement & Retention Dashboard", layout="wide")
st.title("Engagement & Retention Dashboard")
st.caption("Business Analyst case study using anonymized interaction logs from a short-form video platform export.")

st.sidebar.header("1) Upload your TikTok export")
uploaded = st.sidebar.file_uploader("Upload ZIP", type=["zip"])
if not uploaded:
    st.warning("Upload your TikTok export ZIP file to start.")
    st.stop()

zip_bytes = uploaded.getvalue()

# List internal ZIP paths
all_paths = list_zip_paths(zip_bytes)

st.sidebar.header("2) Select files inside the ZIP")
watch_candidates = [p for p in all_paths if p.lower().endswith("watch history.txt")]
likes_candidates = [p for p in all_paths if p.lower().endswith("like list.txt")]

watch_path = st.sidebar.selectbox(
    "Watch History file",
    watch_candidates if watch_candidates else all_paths,
)
likes_path = st.sidebar.selectbox(
    "Like List file",
    likes_candidates if likes_candidates else all_paths,
)

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

# TikTok clip links
st.subheader("TikTok clip links")
tab1, tab2 = st.tabs(["Most recent watched", "Most recent liked"])

with tab1:
    if watch_f.empty:
        st.info("No watch history in this date range.")
    else:
        recent_watch = make_links_table(watch_f, n=30)
        try:
            st.data_editor(
                recent_watch,
                use_container_width=True,
                hide_index=True,
                disabled=True,
                column_config={
                    "url": st.column_config.LinkColumn(
                        "TikTok link",
                        help="Click to open the clip",
                        display_text="Open clip",
                    ),
                    "time_utc": st.column_config.TextColumn("Time (UTC)"),
                    "video_id": st.column_config.TextColumn("Video ID"),
                },
            )
        except Exception:
            for _, r in recent_watch.iterrows():
                st.markdown(f"- {r['time_utc']} — [Open clip]({r['url']})")

with tab2:
    if likes_f.empty:
        st.info("No likes in this date range.")
    else:
        recent_likes = make_links_table(likes_f, n=30)
        try:
            st.data_editor(
                recent_likes,
                use_container_width=True,
                hide_index=True,
                disabled=True,
                column_config={
                    "url": st.column_config.LinkColumn(
                        "TikTok link",
                        help="Click to open the clip",
                        display_text="Open clip",
                    ),
                    "time_utc": st.column_config.TextColumn("Time (UTC)"),
                    "video_id": st.column_config.TextColumn("Video ID"),
                },
            )
        except Exception:
            for _, r in recent_likes.iterrows():
                st.markdown(f"- {r['time_utc']} — [Open clip]({r['url']})")
