import re
import zipfile
from io import BytesIO
import html

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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

# -------------------- CARDS (client-side oEmbed) --------------------
def render_cards_client_oembed(df: pd.DataFrame, cards_per_row: int = 4, n: int = 12):
    required = {"ts_utc", "url"}
    if df is None or df.empty:
        st.info("No rows to show. (Empty in this date range or wrong file selected.)")
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
              <div class="title">Loading…</div>
              <div class="sub">{time} UTC</div>
              <a class="btn" href="{url}" target="_blank" rel="noopener noreferrer">Open clip</a>
            </div>
          </div>
        """)

    html_doc = f"""
    <html>
    <head><meta charset="utf-8"/></head>
    <style>
      body {{
        margin:0;
        background:transparent;
        color:white;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      }}
      .grid {{
        display:grid;
        grid-template-columns:repeat({cards_per_row},1fr);
        gap:18px;
      }}
      .card {{
        aspect-ratio:1/1;
        padding:12px;
        border-radius:18px;
        background:rgba(255,255,255,.04);
        border:1px solid rgba(255,255,255,.08);
        display:flex;
        flex-direction:column;
        justify-content:space-between;
        overflow:hidden;
        transition:transform .25s, box-shadow .25s, border-color .25s;
      }}
      .card:hover {{
        transform:scale(1.05);
        box-shadow:
          0 0 0 1px rgba(255,255,255,.2),
          0 15px 45px rgba(0,0,0,.5),
          0 0 35px rgba(255,90,90,.35);
        border-color: rgba(255,255,255,.25);
      }}
      .cover {{
        aspect-ratio:1/1;
        overflow:hidden;
        border-radius:14px;
        border:1px solid rgba(255,255,255,.10);
        background:rgba(255,255,255,.06);
      }}
      .placeholder {{
        background:linear-gradient(135deg, rgba(170,70,255,.75), rgba(255,70,160,.55));
      }}
      .cover img {{
        width:100%;
        height:100%;
        object-fit:cover;
        transition:transform .35s;
        display:block;
      }}
      .card:hover .cover img {{
        transform:scale(1.08);
      }}
      .meta {{ margin-top:8px; }}
      .title {{
        font-size:13px;
        font-weight:650;
        max-height:34px;
        overflow:hidden;
      }}
      .sub {{
        font-size:12px;
        opacity:.75;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }}
      .btn {{
        margin-top:8px;
        display:block;
        padding:8px;
        text-align:center;
        border-radius:12px;
        background:rgba(255,255,255,.1);
        border:1px solid rgba(255,255,255,.15);
        color:white;
        text-decoration:none;
      }}
      .btn:hover {{
        background:rgba(255,255,255,.18);
      }}
    </style>
    <body>
      <div class="grid">{''.join(card_divs)}</div>

      <script>
        async function fetchOembed(url) {{
          const api = "https://www.tiktok.com/oembed?url=" + encodeURIComponent(url);
          const res = await fetch(api);
          if (!res.ok) throw new Error("oEmbed failed: " + res.status);
          return await res.json();
        }}

        async function runLimited(tasks, limit=4) {{
          const results = [];
          let i = 0;
          const workers = new Array(limit).fill(0).map(async () => {{
            while (i < tasks.length) {{
              const idx = i++;
              try {{ results[idx] = await tasks[idx](); }}
              catch(e) {{ results[idx] = null; }}
            }}
          }});
          await Promise.all(workers);
          return results;
        }}

        const cards = Array.from(document.querySelectorAll(".card"));
        const tasks = cards.map(card => async () => {{
          const url = card.dataset.url;
          const data = await fetchOembed(url);

          const thumb = data.thumbnail_url;
          const title = data.title || "TikTok clip";
          const author = data.author_name || "";

          card.querySelector(".title").textContent = title;
          const sub = card.querySelector(".sub");
          sub.textContent = sub.textContent + (author ? (" • " + author) : "");

          if (thumb) {{
            const cover = card.querySelector(".cover");
            cover.classList.remove("placeholder");
            cover.innerHTML = "";
            const img = document.createElement("img");
            img.src = thumb;
            img.loading = "lazy";
            cover.appendChild(img);
          }}
        }});

        runLimited(tasks, 4);
      </script>
    </body>
    </html>
    """

    rows = (len(recent) + cards_per_row - 1) // cards_per_row
    height = min(1400, rows * 330 + 20)
    components.html(html_doc, height=height, scrolling=False)

# -------------------- APP (one page) --------------------
st.set_page_config(layout="wide")
st.title("Engagement & Retention Dashboard")

st.markdown(
    "Upload your TikTok export ZIP → pick Watch History + Like List → see KPIs, trends, sessions, and clip previews."
)

uploaded = st.sidebar.file_uploader("Upload TikTok ZIP", type=["zip"])
if not uploaded:
    st.stop()

zip_bytes = uploaded.getvalue()
paths = list_zip_paths(zip_bytes)

# Auto-select correct files
watch_candidates = [p for p in paths if p.lower().endswith("watch history.txt")]
likes_candidates = [p for p in paths if p.lower().endswith("like list.txt")]

watch_default = watch_candidates[0] if watch_candidates else paths[0]
likes_default = likes_candidates[0] if likes_candidates else paths[0]

watch_path = st.sidebar.selectbox("Watch History file", paths, index=paths.index(watch_default))
likes_path = st.sidebar.selectbox("Like List file", paths, index=paths.index(likes_default))

watch = load_parsed_df(zip_bytes, watch_path)
likes = load_parsed_df(zip_bytes, likes_path)

# Date filter (no slider; simple inputs are OK)
min_dt = min([df["ts_utc"].min() for df in [watch, likes] if not df.empty], default=None)
max_dt = max([df["ts_utc"].max() for df in [watch, likes] if not df.empty], default=None)

c1, c2 = st.columns(2)
with c1:
    start = st.date_input("Start date", value=min_dt.date() if min_dt is not None else None)
with c2:
    end = st.date_input("End date", value=max_dt.date() if max_dt is not None else None)

watch_f = apply_date(watch, start, end) if not watch.empty else watch
likes_f = apply_date(likes, start, end) if not likes.empty else likes

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
k3.metric("Active days (watch)", f"{watch_days:,}")
k4.metric("Watch → Like conversion", f"{watch_to_like:.1%}")

st.divider()

# Trends graphs
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
    t1.info("No watch data to chart.")

if not likes_f.empty:
    likes_daily = (
        likes_f.assign(day=likes_f["ts_utc"].dt.date)
        .groupby("day")
        .size()
        .reset_index(name="like_events")
    )
    t2.line_chart(likes_daily.set_index("day"))
else:
    t2.info("No likes data to chart.")

st.divider()

# Sessions (fixed gap=30 min; no slider)
st.subheader("Session behavior (gap = 30 minutes)")
w_s = add_sessions(watch_f, gap_minutes=30) if not watch_f.empty else pd.DataFrame()
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
    st.info("No sessions found.")

st.divider()

# Clip cards (fixed layout: 4 per row, 12 clips)
st.subheader("TikTok clips")
tab1, tab2 = st.tabs(["Most recent watched", "Most recent liked"])
with tab1:
    render_cards_client_oembed(watch_f, cards_per_row=4, n=12)
with tab2:
    render_cards_client_oembed(likes_f, cards_per_row=4, n=12)






