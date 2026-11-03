"""
app.py — Satelitní sledování koupacích vod (demo pro SZÚ)
=========================================================
Streamlit appka, jen čte data připravená collectorem:
    lokality.csv, vyrezy.csv, snimky.csv, snimky/<vyrez>/<RRRRMMDD>.png
Žádné API, žádný klíč.

Spuštění lokálně:  streamlit run app.py
"""

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent
NODATA_BG = (208, 208, 208)          # podklad pod průhledné (no-data) pixely
MAIN_W = 900                         # šířka hlavního snímku [px]
THUMB_W = 320                        # šířka náhledu v mřížce [px]
ATTRIBUTION = "Contains modified Copernicus Sentinel data 2026, zpracováno Sentinel Hub (CDSE)."

st.set_page_config(page_title="Satelitní sledování koupacích vod", page_icon="🛰️", layout="wide")


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


@st.cache_data
def animation(paths: tuple[str, ...], labels: tuple[str, ...], width: int = 700) -> bytes:
    frames = [Image.open(io.BytesIO(render(p, width, l))).convert("P", palette=Image.ADAPTIVE)
              for p, l in zip(paths, labels)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=700, loop=0)
    return buf.getvalue()


def fmt_date(dt) -> str:
    return f"{dt.day}. {dt.month}. {dt.year}"


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
        kraje = st.multiselect("Kraj", sorted(lok["kraj"].unique()))
        povodi = st.multiselect("Povodí", sorted(lok["povodi"].unique()))
        hledat = st.text_input("Název nebo kód obsahuje")
        f = lok[lok["typ"].isin(typy)]
        if kraje:
            f = f[f["kraj"].isin(kraje)]
        if povodi:
            f = f[f["povodi"].isin(povodi)]
        if hledat:
            q = hledat.strip().lower()
            f = f[f["nazev"].str.lower().str.contains(q, regex=False) | f["kod"].str.lower().str.contains(q, regex=False)]
        f = f.sort_values("nazev")
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
    st.image(render(path, MAIN_W))
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
    den_sn = den_sn.sort_values("nazev")

    st.header(f"Snímky z {fmt_date(den)}")
    st.caption(f"{len(den_sn)} z {len(zobrazit)} výřezů má v tento den použitelný snímek.")
    cols = st.columns(4)
    for i, r in enumerate(den_sn.itertuples()):
        with cols[i % 4]:
            st.image(render(r.soubor, THUMB_W))
            st.markdown(f"**{r.nazev}**  \n<small>oblačnost/bez dat {r.nepouzitelne_pct:.0f} %</small>",
                        unsafe_allow_html=True)
            if st.button("Zvětšit", key=f"z_{r.vyrez}"):
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

    st.header(v["nazev"])
    st.caption(f"{kod} · {l['kraj']} kraj · {l['khs']} · povodí {l['povodi']}"
               + (" · celkový pohled" if celek else ""))
    if rada.empty:
        st.info("V této sezóně není pro výřez žádný použitelný snímek.")
        st.stop()

    datumy = list(rada["datum"])
    key = f"slider_{v['vyrez']}_{sezona}"
    if key not in st.session_state or st.session_state[key] not in datumy:
        st.session_state[key] = datumy[-1]

    def nastav(d, k=key):
        st.session_state[k] = d

    c1, c2 = st.columns([5, 1])
    with c1:
        vybrane = st.select_slider("Datum snímku", options=datumy, key=key,
                                   format_func=lambda d: fmt_date(datetime.strptime(d, "%Y%m%d")))
    with c2:
        st.write("")
        anim = st.button("▶ Animace", use_container_width=True)

    r = rada[rada["datum"] == vybrane].iloc[0]
    if anim:
        st.image(animation(tuple(rada["soubor"]),
                           tuple(fmt_date(d) for d in rada["dt"])))
        st.caption(f"Animace {len(rada)} snímků sezóny {sezona}.")
    else:
        st.image(render(r["soubor"], MAIN_W))
        st.caption(f"{fmt_date(r['dt'])} · oblačnost/bez dat ve výřezu {r['nepouzitelne_pct']:.0f} %")
        st.download_button("Stáhnout PNG", (BASE / r["soubor"]).read_bytes(),
                           file_name=f"{v['vyrez']}_{vybrane}.png", mime="image/png")

    st.subheader(f"Snímky sezóny {sezona}")
    cols = st.columns(6)
    for i, x in enumerate(rada.itertuples()):
        with cols[i % 6]:
            st.image(render(x.soubor, 200))
            st.button(fmt_date(x.dt), key=f"t_{x.datum}", on_click=nastav, args=(x.datum,),
                      type="primary" if x.datum == vybrane else "secondary",
                      use_container_width=True)
