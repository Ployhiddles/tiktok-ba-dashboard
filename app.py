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
        rows.append({
            "ts_utc": dates[i],
            "url": links[i],
            "video_id": extract_video_id(links[i])
        })
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
    return parse_date_link_txt(watch_txt), parse_date_link_txt(likes_txt)

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
    recent = (
        df.sort_values("ts_utc", ascending=False)
        .dropna(subset=["url"])
        .drop_duplicates(subset=["url"])
        .head(n)
    )

    cards_html = ""
    for _, r in recent.iterrows():
        meta = get_tiktok_oembed(r["url"])
        thumb = meta.get("thumb")
        title = html.escape(meta.get("title") or "TikTok clip")
        author = html.escape(meta.get("author") or "")
        time = r["ts_utc"].strftime("%Y-%m-%d %H:%M")
        url = html.escape(r["url"])

        if thumb:
            cover = f'<img src="{thumb}" />'
        else:
            seed = sum(ord(c) for c in str(r["video_id"])) % 360
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
            <a class="btn" href="{url}" target="_blank">Open clip</a>
          </div>
        </div>
        """

    html_doc = f"""
    <html>
    <style>
      body {{ margin:0; background:transparent; color:white; font-family:sans-serif }}
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
        transition:transform .25s, box-shadow .25s;
      }}
      .card:hover {{
        transform:scale(1.05);
        box-shadow:
          0 0 0 1px rgba(255,255,255,.2),
          0 15px 45px rgba(0,0,0,.5),
          0 0 35px rgba(255,90,90,.35);
      }}
      .cover {{
        aspect-ratio:1/1;
        overflow:hidden;
        border-radius:14px;
      }}
      .cover img {{
        width:100%;
        height:100%;
        object-fit:cover;
        transition:transform .35s;
      }}
      .card:hover img {{ transform:scale(1.08); }}
      .title {{ font-size:13px; font-weight:600; margin-top:8px }}
      .sub {{ font-size:12px; opacity:.75 }}
      .btn {{
        margin-top:8px;
        display:block;
        padding:8px;
        text-align:center;
        border-radius:12px;
        background:rgba(255,255,255,.1);
        color:white;
        text-decoration:none;
      }}
    </style>
    <body>
      <div class="grid">{cards_html}</div>
    </body>
    </html>
    """

    height = ((len(recent)+cards_per_row-1)//cards_per_row)*300
    components.html(html_doc, height=min(height,1200), scrolling=False)

# -------------------- STREAMLIT APP --------------------
st.set_page_config(layout="wide")
st.title("Engagement & Retention Dashboard")

uploaded = st.sidebar.file_uploader("Upload TikTok ZIP", type=["zip"])
if not uploaded:
    st.stop()

paths = list_zip_paths(uploaded.getvalue())
watch_path = st.sidebar.selectbox("Watch History", paths)
likes_path = st.sidebar.selectbox("Like List", paths)

watch, likes = load_data(uploaded.getvalue(), watch_path, likes_path)

st.subheader("TikTok Clips")
cards_per_row = st.slider("Cards per row", 2, 5, 4)
num_cards = st.slider("Number of clips", 4, 40, 12, step=4)

tab1, tab2 = st.tabs(["Watched", "Liked"])
with tab1:
    render_cards(watch, cards_per_row, num_cards)
with tab2:
    render_cards(likes, cards_per_row, num_cards)


