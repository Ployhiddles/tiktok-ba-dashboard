import re
import zipfile
from io import BytesIO
import html
import textwrap

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

# -------------------- WRAPPED (Spotify-style story) --------------------
def render_wrapped(watch_f: pd.DataFrame, likes_f: pd.DataFrame):
    total_watches = len(watch_f)
    total_likes = len(likes_f)
    active_days = watch_f["ts_utc"].dt.date.nunique() if not watch_f.empty else 0

    watch_video_ids = set(watch_f["video_id"].dropna()) if ("video_id" in watch_f.columns and not watch_f.empty) else set()
    like_video_ids = set(likes_f["video_id"].dropna()) if ("video_id" in likes_f.columns and not likes_f.empty) else set()
    conversion = (len(watch_video_ids & like_video_ids) / len(watch_video_ids)) if watch_video_ids else 0.0

    if not watch_f.empty:
        peak_day = (
            watch_f.assign(day=watch_f["ts_utc"].dt.date)
                  .groupby("day").size()
                  .sort_values(ascending=False)
                  .head(1)
        )
        peak_day_str = str(peak_day.index[0])
        peak_day_count = int(peak_day.iloc[0])
        peak_hour = int(watch_f["ts_utc"].dt.hour.value_counts().idxmax())
        peak_hour_txt = f"{peak_hour:02d}:00"
    else:
        peak_day_str, peak_day_count, peak_hour_txt = "—", 0, "—"

    # Sessions (fixed 30m)
    if not watch_f.empty:
        w = watch_f.sort_values("ts_utc").copy()
        gap = w["ts_utc"].diff()
        w["new_session"] = gap.isna() | (gap > pd.Timedelta(minutes=30))
        sessions = int(w["new_session"].sum())
        avg_per_session = float(len(w) / sessions) if sessions else 0.0
    else:
        sessions, avg_per_session = 0, 0.0

    vibe = "Binge mode 🌀" if total_watches > 800 else ("Chill scroller 🌙" if total_watches > 250 else "Selective watcher 🎯")

    # IMPORTANT: dedent fixes the “HTML shows as code block” bug
    st.markdown(
        textwrap.dedent("""
        <style>
          .wrapped-hero{
            border-radius: 28px;
            padding: 28px;
            background: linear-gradient(135deg, rgba(125,50,255,.55), rgba(255,60,160,.35));
            border: 1px solid rgba(255,255,255,.15);
            box-shadow: 0 18px 60px rgba(0,0,0,.45);
          }
          .wrapped-title{
            font-size: 42px;
            font-weight: 800;
            line-height: 1.05;
            margin: 0;
          }
          .wrapped-sub{
            margin-top: 8px;
            opacity: .85;
            font-size: 16px;
          }
          .kpi-grid{
            display: grid;
            grid-template-columns: repeat(4, minmax(0,1fr));
            gap: 14px;
            margin-top: 18px;
          }
          .kpi-card{
            border-radius: 20px;
            padding: 16px;
            background: rgba(0,0,0,.22);
            border: 1px solid rgba(255,255,255,.10);
          }
          .kpi-label{ font-size: 12px; opacity: .8; }
          .kpi-value{ font-size: 26px; font-weight: 800; margin-top: 4px; }
          .kpi-note{ font-size: 12px; opacity: .7; margin-top: 6px; }

          .story-row{
            margin-top: 18px;
            display: grid;
            grid-template-columns: 1.2fr .8fr;
            gap: 14px;
          }
          .story-card{
            border-radius: 24px;
            padding: 18px;
            background: rgba(255,255,255,.04);
            border: 1px solid rgba(255,255,255,.10);
          }
          .story-h{ font-size: 18px; font-weight: 750; margin: 0; }
          .story-p{ margin-top: 8px; opacity: .85; line-height: 1.4; }
          .pill{
            display:inline-block; padding:6px 10px; border-radius: 999px;
            background: rgba(255,255,255,.10); border: 1px solid rgba(255,255,255,.12);
            font-size: 12px; opacity:.9; margin-right:8px; margin-top:8px;
          }
          @media (max-width: 1100px){
            .kpi-grid{ grid-template-columns: repeat(2, minmax(0,1fr)); }
            .story-row{ grid-template-columns: 1fr; }
          }
        </style>
        """),
        unsafe_allow_html=True,
    )

    st.markdown(
        textwrap.dedent(f"""
        <div class="wrapped-hero">
          <p class="wrapped-title">Your TikTok Wrapped</p>
          <div class="wrapped-sub">A quick story of your watching & liking behavior (from your TikTok export).</div>

          <div class="kpi-grid">
            <div class="kpi-card">
              <div class="kpi-label">Total watches</div>
              <div class="kpi-value">{total_watches:,}</div>
              <div class="kpi-note">{vibe}</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Total likes</div>
              <div class="kpi-value">{total_likes:,}</div>
              <div class="kpi-note">Your “I approve” button</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Watch → Like</div>
              <div class="kpi-value">{conversion:.1%}</div>
              <div class="kpi-note">Watches that become likes</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">Active days</div>
              <div class="kpi-value">{active_days:,}</div>
              <div class="kpi-note">Days with at least one watch</div>
            </div>
          </div>

          <div class="story-row">
            <div class="story-card">
              <p class="story-h">Your peak day</p>
              <p class="story-p">
                You were most active on <b>{peak_day_str}</b> with <b>{peak_day_count}</b> watched clips.
              </p>
              <span class="pill">Peak hour: <b>{peak_hour_txt}</b></span>
              <span class="pill">Sessions: <b>{sessions}</b></span>
              <span class="pill">Avg clips/session: <b>{avg_per_session:.1f}</b></span>
            </div>

            <div class="story-card">
              <p class="story-h">Your “like energy”</p>
              <p class="story-p">
                A watch turns into a like about <b>{conversion:.1%}</b> of the time.
                Higher conversion usually means your feed is very “on point”.
              </p>
              <p class="story-p" style="opacity:.75; font-size:13px;">
                BA angle: use this as a proxy for content relevance & satisfaction.
              </p>
            </div>
          </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

# -------------------- CLIP CARDS (client-side oEmbed) --------------------
def render_cards_client_oembed(df: pd.DataFrame, cards_per_row: int = 4, n: int = 12):
    required = {"ts_utc", "url"}
    if df is None or df.empty:
        st.info("No rows to show (empty in this date range).")
        return
    if not required.issubset(set(df.columns)):
        st.error("Selected file didn’t parse correctly. Please select Watch History / Like List files.")
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
        margin:0; background:transparent; color:white;
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
        width:100%; height:100%; object-fit:cover;
        transition:transform .35s; display:block;
      }}
      .card:hover .cover img {{ transform:scale(1.08); }}
      .meta {{ margin-top:8px; }}
      .title {{ font-size:13px; font-weight:650; max-height:34px; overflow:hidden; }}
      .sub {{ font-size:12px; opacity:.75; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
      .btn {{
        margin-top:8px; display:block; padding:8px; text-align:center;
        border-radius:12px; background:rgba(255,255,255,.10);
        border:1px solid rgba(255,255,255,.15); color:white; text-decoration:none;
      }}
      .btn:hover {{ background:rgba(255,255,255,.18); }}
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
          let i = 0;
          const workers = new Array(limit).fill(0).map(async () => {{
            while (i < tasks.length) {{
              const idx = i++;
              try {{ await tasks[idx](); }} catch(e) {{}}
            }}
          }});
          await Promise.all(workers);
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

# -------------------- APP --------------------
st.set_page_config(layout="wide")
st.title("Engagement & Retention Dashboard")
st.caption("Upload your TikTok export ZIP → Wrapped story → trends → sessions → clickable clip previews.")

uploaded = st.sidebar.file_uploader("Upload TikTok ZIP", type=["zip"])
if not uploaded:
    st.stop()

zip_bytes = uploaded.getvalue()
paths = list_zip_paths(zip_bytes)

watch_candidates = [p for p in paths if p.lower().endswith("watch history.txt")]
likes_candidates = [p for p in paths if p.lower().endswith("like list.txt")]

watch_default = watch_candidates[0] if watch_candidates else paths[0]
likes_default = likes_candidates[0] if likes_candidates else paths[0]

watch_path = st.sidebar.selectbox("Watch History file", paths, index=paths.index(watch_default))
likes_path = st.sidebar.selectbox("Like List file", paths, index=paths.index(likes_default))

watch = load_parsed_df(zip_bytes, watch_path)
likes = load_parsed_df(zip_bytes, likes_path)

# Date inputs (not sliders)
min_dt = min([df["ts_utc"].min() for df in [watch, likes] if not df.empty], default=None)
max_dt = max([df["ts_utc"].max() for df in [watch, likes] if not df.empty], default=None)

c1, c2 = st.columns(2)
with c1:
    start = st.date_input("Start date", value=min_dt.date() if min_dt is not None else None)
with c2:
    end = st.date_input("End date", value=max_dt.date() if max_dt is not None else None)

watch_f = apply_date(watch, start, end) if not watch.empty else watch
likes_f = apply_date(likes, start, end) if not likes.empty else likes

# Wrapped story section (FIXED)
render_wrapped(watch_f, likes_f)

st.divider()

# Trends
st.subheader("Trends")
t1, t2 = st.columns(2)

with t1:
    if not watch_f.empty:
        watch_daily = (
            watch_f.assign(day=watch_f["ts_utc"].dt.date)
                  .groupby("day").size()
                  .reset_index(name="watch_events")
        )
        st.line_chart(watch_daily.set_index("day"))
    else:
        st.info("No watch data to chart.")

with t2:
    if not likes_f.empty:
        likes_daily = (
            likes_f.assign(day=likes_f["ts_utc"].dt.date)
                  .groupby("day").size()
                  .reset_index(name="like_events")
        )
        st.line_chart(likes_daily.set_index("day"))
    else:
        st.info("No likes data to chart.")

st.divider()

# Sessions (gap fixed = 30)
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
    st.info("No sessions found in this date range.")

st.divider()

# Clip cards (fixed layout)
st.subheader("TikTok clips")
tab1, tab2 = st.tabs(["Most recent watched", "Most recent liked"])
with tab1:
    render_cards_client_oembed(watch_f, cards_per_row=4, n=12)
with tab2:
    render_cards_client_oembed(likes_f, cards_per_row=4, n=12)



