"""
app.py — Satelitní sledování koupacích vod (demo pro SZÚ)
=========================================================
Streamlit appka, jen čte data připravená collectorem:
    lokality.csv, vyrezy.csv, snimky.csv, snimky/<vyrez>/<RRRRMMDD>.png
Žádné API, žádný klíč.

Spuštění lokálně:  streamlit run app.py
"""

import base64
import unicodedata
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent
NODATA_BG = (208, 208, 208)          # podklad pod průhledné (no-data) pixely
IMG_H = 420                          # výška okna hlavního snímku v prohlížeči [px]
FULL_W = 1400                        # šířka snímku v dialogu „plná velikost“ [px]
THUMB_BOX = (320, 240)               # rámeček náhledu v mřížce „podle data“ [px]
THUMB_BOX_S = (240, 180)             # rámeček náhledu v mřížce sezóny [px]
ATTRIBUTION = "Contains modified Copernicus Sentinel data 2026, zpracováno Sentinel Hub (CDSE)."

ANIM_DELAY_MS = 800                  # prodleva mezi snímky animace [ms]

st.set_page_config(page_title="Satelitní sledování koupacích vod", page_icon="🛰️", layout="wide")

# menší horní mezery (výchozí Streamlit má nad obsahem ~6 rem)
st.markdown("""<style>
[data-testid="stHeader"] { height: 2.5rem; background: transparent; }
[data-testid="stMainBlockContainer"] { padding-top: 2.75rem; }
[data-testid="stSidebarHeader"] { padding-top: 0.5rem; padding-bottom: 0; height: 2.25rem; }
[data-testid="stSidebarUserContent"] { padding-top: 0; }
[data-testid="stSidebarUserContent"] h1 { padding-top: 0; }
</style>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
#  Data
# ══════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_data():
    lok = pd.read_csv(BASE / "lokality.csv", dtype=str)
    lok["typ"] = lok["kod"].str[:2]                       # KO / PK
    vyr = pd.read_csv(BASE / "vyrezy.csv", dtype=str)
    vyr["kody_list"] = vyr["kody"].str.split(";")
    sn = pd.read_csv(BASE / "snimky.csv", dtype=str)
    sn = sn[sn["stav"] == "ok"].copy()
    sn["dt"] = pd.to_datetime(sn["datum"], format="%Y%m%d")
    sn["sezona"] = sn["dt"].dt.year
    sn["nepouzitelne_pct"] = pd.to_numeric(sn["nepouzitelne_pct"], errors="coerce")
    return lok, vyr, sn


def vyrez_for(kod: str, celek: bool, vyr: pd.DataFrame) -> pd.Series | None:
    typ = "celek" if celek else "lokalni"
    m = vyr[(vyr["typ"] == typ) & vyr["kody_list"].apply(lambda k: kod in k)]
    return m.iloc[0] if len(m) else None


@st.cache_data(max_entries=400)
def render(path: str, width: int, label: str | None = None) -> bytes:
    """PNG -> RGB na šedém podkladu (no-data), zvětšené na danou šířku."""
    img = Image.open(BASE / path).convert("RGBA")
    bg = Image.new("RGBA", img.size, NODATA_BG + (255,))
    bg.alpha_composite(img)
    img = bg.convert("RGB")
    h = round(img.height * width / img.width)
    img = img.resize((width, h), Image.NEAREST if width >= img.width else Image.LANCZOS)
    if label:
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 8 * len(label) + 12, 22], fill=(0, 0, 0))
        d.text((6, 5), label, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@st.cache_data(max_entries=3000)
def thumb(path: str, box_w: int, box_h: int) -> bytes:
    """Náhled vepsaný do pevného rámečku box_w × box_h (okraje průhledné),
    aby měly všechny náhledy v mřížce stejnou velikost."""
    img = Image.open(BASE / path).convert("RGBA")
    bg = Image.new("RGBA", img.size, NODATA_BG + (255,))
    bg.alpha_composite(img)
    scale = min(box_w / bg.width, box_h / bg.height)
    w, h = max(1, round(bg.width * scale)), max(1, round(bg.height * scale))
    bg = bg.resize((w, h), Image.LANCZOS if scale < 1 else Image.NEAREST)
    canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    canvas.paste(bg, ((box_w - w) // 2, (box_h - h) // 2))
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()


def grid_rows(seq, n):
    """Po řádcích: každý řádek má vlastní st.columns -> řádky začínají zarovnaně."""
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield zip(st.columns(n), seq[i:i + n])


def cz_key(text: str) -> str:
    """Řadicí klíč bez diakritiky (jinak by Č, Š, Ž skončily až za Z)."""
    t = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def fmt_date(dt) -> str:
    # pevné mezery: „30. 7. 2026“ by Markdown (popisky tlačítek, caption)
    # vyhodnotil jako číslovaný seznam a zobrazil jen „2026“
    return f"{dt.day}. {dt.month}. {dt.year}"


@st.cache_data(max_entries=2000)
def webp_uri(path: str) -> str:
    """Snímek v nativním rozlišení, no-data na šedé, jako WebP data URI."""
    img = Image.open(BASE / path).convert("RGBA")
    bg = Image.new("RGBA", img.size, NODATA_BG + (255,))
    bg.alpha_composite(img)
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "WEBP", quality=90)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


THEMES = {
    "light": dict(FG="#31333F", MUTED="#808495", BG="#f0f2f6", LINE="#d5d7de"),
    "dark":  dict(FG="#fafafa", MUTED="#a3a8b8", BG="#262730", LINE="#4a4c58"),
}


@st.cache_data(max_entries=60)
def viewer_html(vyrez: str, title: str, popis: str,
                items: tuple[tuple[str, str, int], ...], theme: str) -> str:
    """Prohlížeč detailu (viewer.html): items = (soubor, RRRRMMDD, % nepoužitelných)."""
    data = {
        "title": title, "popis": popis, "vyrez": vyrez, "delay": ANIM_DELAY_MS,
        "items": [{"d": fmt_date(datetime.strptime(f, "%Y%m%d")), "f": f, "p": p,
                   "src": webp_uri(soubor)} for soubor, f, p in items],
    }
    html = (BASE / "viewer.html").read_text(encoding="utf-8")
    for k, v in THEMES.get(theme, THEMES["light"]).items():
        html = html.replace(f"__{k}__", v)
    w, h = Image.open(BASE / items[0][0]).size          # všechny snímky výřezu mají stejný rozměr
    html = html.replace("__IMG_H__", str(IMG_H)).replace("__ASPECT__", f"{w} / {h}")
    return html.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


lok, vyr, sn = load_data()


# ══════════════════════════════════════════════════════════════════════════
#  Sidebar
# ══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("Satelitní sledování koupacích vod")
    sezony = sorted(sn["sezona"].unique(), reverse=True)
    sezona = st.selectbox("Sezóna", sezony)
    sn_s = sn[sn["sezona"] == sezona]
    rezim = st.radio("Výběr", ["Podle data", "Podle lokality"], horizontal=True)

    if rezim == "Podle lokality":
        typy = st.multiselect("Typ", ["KO", "PK"], default=["KO", "PK"],
                              help="KO = koupací oblast, PK = přírodní koupaliště")
        kraje = st.multiselect("Kraj", sorted(lok["kraj"].unique()), placeholder="všechny")
        povodi = st.multiselect("Povodí", sorted(lok["povodi"].unique()), placeholder="všechna")
        hledat = st.text_input("Název nebo kód obsahuje")
        f = lok[lok["typ"].isin(typy)]
        if kraje:
            f = f[f["kraj"].isin(kraje)]
        if povodi:
            f = f[f["povodi"].isin(povodi)]
        if hledat:
            q = hledat.strip().lower()
            f = f[f["nazev"].str.lower().str.contains(q, regex=False) | f["kod"].str.lower().str.contains(q, regex=False)]
        f = f.sort_values("nazev", key=lambda c: c.map(cz_key))
        if f.empty:
            st.warning("Filtru neodpovídá žádná lokalita.")
            st.stop()
        kod = st.selectbox("Lokalita", f["kod"],
                           format_func=lambda k: f"{f.set_index('kod').at[k, 'nazev']} ({k})")
        ma_celek = vyrez_for(kod, True, vyr) is not None
        celek = st.toggle("Celkový pohled nádrže", value=False, disabled=not ma_celek,
                          help=None if ma_celek else "Pro tuto lokalitu není celkový výřez nádrže.")
    else:
        celek = st.toggle("U nádrží celkový pohled", value=False,
                          help="Nádrže s celkovým výřezem (Brno, Dalešice, Vranov, Letovice) "
                               "zobrazit celé místo lokálních oblastí.")

    st.divider()
    st.markdown("**Legenda (APA filtr)**  \n"
                "🔵 čistá voda · 🟢 biomasa řas/sinic · 🔴 zákal (bahno)  \n"
                "přirozené barvy = pevnina, mraky · šedá = bez dat")
    st.caption(ATTRIBUTION)


# ══════════════════════════════════════════════════════════════════════════
#  Dialog se zvětšeným snímkem
# ══════════════════════════════════════════════════════════════════════════

@st.dialog("Snímek", width="large")
def zoom(path: str, title: str, subtitle: str):
    st.subheader(title)
    st.caption(subtitle)
    st.image(render(path, FULL_W), width="stretch")
    st.download_button("Stáhnout PNG", (BASE / path).read_bytes(),
                       file_name=Path(path).parent.name + "_" + Path(path).name, mime="image/png")


# ══════════════════════════════════════════════════════════════════════════
#  Režim: podle data
# ══════════════════════════════════════════════════════════════════════════

if rezim == "Podle data":
    data = sorted(sn_s["dt"].unique(), reverse=True)
    if not data:
        st.info("Pro tuto sezónu nejsou žádné snímky.")
        st.stop()
    den = st.selectbox("Datum snímku", data, format_func=lambda d: fmt_date(pd.Timestamp(d)))
    den = pd.Timestamp(den)

    # výřezy k zobrazení: každá lokalita -> lokální výřez, příp. celek; bez duplicit
    zobrazit = {}
    for k in lok["kod"]:
        v = vyrez_for(k, True, vyr) if celek else None
        if v is None:
            v = vyrez_for(k, False, vyr)
        if v is not None:
            zobrazit[v["vyrez"]] = v["nazev"]
    den_sn = sn_s[(sn_s["dt"] == den) & sn_s["vyrez"].isin(zobrazit)].copy()
    den_sn["nazev"] = den_sn["vyrez"].map(zobrazit)
    den_sn = den_sn.sort_values("nazev", key=lambda c: c.map(cz_key))

    st.header(f"Snímky z {fmt_date(den)}")
    st.caption(f"{len(den_sn)} z {len(zobrazit)} výřezů má v tento den použitelný snímek.")
    for row in grid_rows(den_sn.itertuples(), 4):
        for col, r in row:
            with col:
                st.image(thumb(r.soubor, *THUMB_BOX), width="stretch")
                # pevná výška popisku (2 řádky názvu + oblačnost) -> tlačítka v jedné linii
                st.markdown(f"<div style='height:4.4em;overflow:hidden;line-height:1.35'>"
                            f"<b>{r.nazev}</b><br><small>oblačnost/bez dat "
                            f"{r.nepouzitelne_pct:.0f} %</small></div>", unsafe_allow_html=True)
                if st.button("🔍 Plná velikost", key=f"z_{r.vyrez}", width="stretch"):
                    zoom(r.soubor, r.nazev, fmt_date(den))


# ══════════════════════════════════════════════════════════════════════════
#  Režim: podle lokality
# ══════════════════════════════════════════════════════════════════════════

else:
    v = vyrez_for(kod, celek, vyr)
    if v is None:
        st.error("Lokalita nemá definovaný výřez.")
        st.stop()
    l = lok.set_index("kod").loc[kod]
    rada = sn_s[sn_s["vyrez"] == v["vyrez"]].sort_values("dt")

    popis = (f"{kod} · {l['kraj']} kraj · {l['khs']} · povodí {l['povodi']}"
             + (" · celkový pohled" if celek else ""))
    if rada.empty:
        st.header(v["nazev"])
        st.caption(popis)
        st.info("V této sezóně není pro výřez žádný použitelný snímek.")
        st.stop()

    theme = getattr(getattr(st.context, "theme", None), "type", None) or "light"
    items = tuple((x.soubor, x.datum, int(round(x.nepouzitelne_pct))) for x in rada.itertuples())
    st.iframe(viewer_html(v["vyrez"], v["nazev"], popis, items, theme), height="content")

    st.subheader(f"Snímky sezóny {sezona}")
    st.caption("Kliknutím na datum se snímek otevře v plné velikosti.")
    for row in grid_rows(rada.itertuples(), 6):
        for col, x in row:
            with col:
                st.image(thumb(x.soubor, *THUMB_BOX_S), width="stretch")
                if st.button(fmt_date(x.dt), key=f"t_{x.datum}", width="stretch"):
                    zoom(x.soubor, v["nazev"], fmt_date(x.dt))
