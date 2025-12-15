import re
import zipfile
from io import BytesIO
import html

import pandas as pd
import requests
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
    df = df.dropna(subset=["ts_utc"])
    return df

def read_zip_txt(zf: zipfile.ZipFile, path: str) -> str:
    with zf.open(path) as f:
        return f.read().decode("utf-8", errors="replace")

@st.cache_data
def list_zip_paths(zip_bytes: bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        return zf.namelist()

@st.cache_data
def load_parsed_df(zip_bytes: bytes, path: str) -> pd.DataFrame:
    """Parse one txt file into a (ts_utc,url,video_id) dataframe if possible."""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        txt = read_zip_txt(zf, path)
    return parse_date_link_txt(txt)

# -------------------- THUMBNAILS --------------------
@st.cache_data(show_spinner=False)
def get_tiktok_oembed(url: str):
    try:
        r = requests.get(
            "https://www.tiktok.com/oembed",
            params={"url": url},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            j = r.json()
            return {
                "thumb": j.get("thumbnail_url"),
                "title": j.get("title"),
                "author": j.get("author_name"),
            }
    except Exception:
        pass
    return {}

# -------------------- CARD GRID (HTML COMPONENT) --------------------
def render_cards(df: pd.DataFrame, cards_per_row: int, n: int):
    # ✅ Guard: don’t crash if wrong file selected
    required = {"ts_utc", "url"}
    if df is None or df.empty:
        st.info("No rows to show (empty dataset). Try selecting the correct Watch/Like file.")
        return
    if not required.issubset(set(df.columns)):
        st.error(f"Selected file didn’t parse into expected columns. Found columns: {list(df.columns)}")
        st.stop()

    recent = (
        df.sort_values("ts_utc", ascending=False)
          .dropna(subset=["url"])
          .drop_duplicates(subset=["url"])
          .head(n)
          .copy()
    )

    cards_html = ""
    for _, r in recent.iterrows():
        url_raw = str(r["url"])
        meta = get_tiktok_oembed(url_raw)

        thumb = meta.get("thumb")
        title = html.escape(meta.get("title") or "TikTok clip")
        author = html.escape(meta.get("author") or "")
        time = pd.to_datetime(r["ts_utc"], utc=True).strftime("%Y-%m-%d %H:%M")
        url = html.escape(url_raw)

        if thumb:
            cover = f'<img src="{html.escape(thumb)}" />'
        else:
            vid = str(r.get("video_id") or "")
            seed = sum(ord(c) for c in vid) % 360
            cover = f'''
              <div style="width:100%;height:100%;
              background:linear-gradient(135deg,
              hsla({seed},90%,60%,.85),
              hsla({(seed+60)%360},90%,55%,.7));"></div>
            '''

        cards_html += f"""
        <div class="card">
          <div class="cover">{cover}</div>
          <div class="meta">
            <div class="title">{title}</div>
            <div class="sub">{time} UTC {("• " + author) if author else ""}</div>
            <a class="btn" href="{url}" target="_blank" rel="noopener noreferrer">Open clip</a>
          </div>
        </div>
        """

    html_doc = f"""
    <html>
    <head><meta charset="utf-8"/></head>
    <style>
      body {{ margin:0; background:transparent; color:white; font-family:sans-serif; }}
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
      .cover img {{
        width:100%;
        height:100%;
        object-fit:cover;
        transition:transform .35s;
        display:block;
      }}
      .card:hover .cover img {{ transform:scale(1.08); }}
      .meta {{ margin-top:8px; }}
      .title {{ font-size:13px; font-weight:600; }}
      .sub {{ font-size:12px; opacity:.75; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
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
      .btn:hover {{ background:rgba(255,255,255,.18); }}
    </style>
    <body>
      <div class="grid">{cards_html}</div>
    </body>
    </html>
    """

    rows = (len(recent) + cards_per_row - 1) // cards_per_row
    height = min(1400, rows * 330 + 20)
    components.html(html_doc, height=height, scrolling=False)

# -------------------- STREAMLIT APP --------------------
st.set_page_config(layout="wide")
st.title("Engagement & Retention Dashboard")

uploaded = st.sidebar.file_uploader("Upload TikTok ZIP", type=["zip"])
if not uploaded:
    st.stop()

zip_bytes = uploaded.getvalue()
paths = list_zip_paths(zip_bytes)

# ✅ Better defaults: try to auto-select correct files
def pick_default(candidates, fallback):
    return candidates[0] if candidates else fallback

watch_candidates = [p for p in paths if p.lower().endswith("watch history.txt")]
likes_candidates = [p for p in paths if p.lower().endswith("like list.txt")]

watch_default = pick_default(watch_candidates, paths[0])
likes_default = pick_default(likes_candidates, paths[0])

watch_path = st.sidebar.selectbox("Watch History file", paths, index=paths.index(watch_default))
likes_path = st.sidebar.selectbox("Like List file", paths, index=paths.index(likes_default))

watch = load_parsed_df(zip_bytes, watch_path)
likes = load_parsed_df(zip_bytes, likes_path)

# ✅ Debug panel (helps you pick correct files)
with st.expander("Debug (if something looks wrong)"):
    st.write("Watch rows:", len(watch), "Columns:", list(watch.columns))
    st.write("Like rows:", len(likes), "Columns:", list(likes.columns))
    st.write("Tip: choose files ending with 'Watch History.txt' and 'Like List.txt'")

st.subheader("TikTok Clips")
cards_per_row = st.slider("Cards per row", 2, 5, 4)
num_cards = st.slider("Number of clips", 4, 40, 12, step=4)

tab1, tab2 = st.tabs(["Watched", "Liked"])
with tab1:
    render_cards(watch, cards_per_row, num_cards)
with tab2:
    render_cards(likes, cards_per_row, num_cards)
