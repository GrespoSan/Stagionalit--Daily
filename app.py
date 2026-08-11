from __future__ import annotations

from datetime import date, timedelta
import math

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import pandas_market_calendars as mcal


APP_TITLE = "Seasonality Weekly Scanner"

DEFAULT_UNIVERSE = {
    # Top 10 mostrati nella classifica fornita
    "Nvidia": "NVDA",
    "Alphabet A": "GOOGL",
    "Alphabet C": "GOOG",
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Amazon": "AMZN",
    "Broadcom": "AVGO",
    "Meta Platforms": "META",
    "Berkshire Hathaway B": "BRK-B",
    "Tesla": "TSLA",

    # Principali futures su indici USA
    "E-mini S&P 500 Future": "ES=F",
    "Nasdaq 100 Future": "NQ=F",
    "Mini Dow Future": "YM=F",
    "E-mini Russell 2000 Future": "RTY=F",

    # Europa: proxy cash per avere una serie Yahoo coerente e lunga
    "DAX (proxy cash)": "^GDAXI",
    "Euro Stoxx 50 (proxy cash)": "^STOXX50E",

    # Commodity futures
    "Gold Future": "GC=F",
    "WTI Crude Oil Future": "CL=F",
    "Copper Future": "HG=F",
}

WINDOWS = (10, 15, 20)


st.set_page_config(page_title=APP_TITLE, page_icon="📅", layout="wide")


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def download_history(ticker: str, start: str = "1990-01-01") -> pd.DataFrame:
    """
    Scarica OHLC daily da Yahoo Finance.

    auto_adjust=False è intenzionale:
    - per questa strategia vogliamo il movimento di PREZZO della seduta;
    - usiamo Close, non Adj Close, così i dividendi non vengono trasformati
      in total return.
    """
    df = yf.download(
        ticker,
        start=start,
        end=(date.today() + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance può restituire MultiIndex anche con un solo ticker.
    if isinstance(df.columns, pd.MultiIndex):
        if ticker in df.columns.get_level_values(-1):
            df = df.xs(ticker, axis=1, level=-1)
        else:
            df.columns = df.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame()

    df = df[required].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["Close"])
    df["Return"] = df["Close"].pct_change()
    return df


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def nyse_schedule(start_year: int, end_year: int) -> pd.DataFrame:
    cal = mcal.get_calendar("NYSE")
    schedule = cal.schedule(
        start_date=f"{start_year}-01-01",
        end_date=f"{end_year}-12-31",
    )
    schedule = schedule.copy()
    schedule.index = pd.to_datetime(schedule.index).tz_localize(None)
    schedule["year"] = schedule.index.year
    schedule["month"] = schedule.index.month
    schedule["tdom"] = schedule.groupby(["year", "month"]).cumcount() + 1
    return schedule


def next_week_bounds(ref: date) -> tuple[date, date]:
    """Lunedì-venerdì della prossima settimana di calendario."""
    days_to_monday = (7 - ref.weekday()) % 7
    if days_to_monday == 0:
        days_to_monday = 7
    monday = ref + timedelta(days=days_to_monday)
    return monday, monday + timedelta(days=4)


def trading_targets(start_d: date, end_d: date, schedule: pd.DataFrame) -> pd.DataFrame:
    """
    Genera lunedì-venerdì senza imporre il calendario NYSE.
    Questo evita di perdere giornate europee/commodity quando Wall Street
    è chiusa. Le festività storiche vengono comunque escluse naturalmente
    perché la data non è presente nella serie dello strumento.
    """
    dates = pd.date_range(start=start_d, end=end_d, freq="D")
    dates = [d for d in dates if d.weekday() < 5]
    if not dates:
        return pd.DataFrame(columns=["date", "month", "tdom"])

    rows = []
    for d in dates:
        rows.append({
            "date": d.date(),
            "month": d.month,
            "tdom": 0,   # mantenuto solo per compatibilità; non usato dal metodo Forecaster
        })
    return pd.DataFrame(rows)


def seasonal_sample(
    df: pd.DataFrame,
    target_date: date,
    target_month: int,
    target_tdom: int,
    years: int,
    schedule: pd.DataFrame,
) -> pd.DataFrame:
    """
    Replica Forecaster: confronta lo STESSO GIORNO DI CALENDARIO
    (mese + giorno) nei precedenti N anni.

    Se quella data cade di sabato/domenica/festivo, l'anno viene escluso.
    Il rendimento è close-to-close della seduta selezionata.
    """
    target_year = target_date.year
    wanted_years = range(target_year - years, target_year)

    rows = []
    for y in wanted_years:
        try:
            dt = pd.Timestamp(date(y, target_date.month, target_date.day))
        except ValueError:
            continue

        # La data deve essere una vera seduta presente nei dati dello strumento.
        if dt not in df.index:
            continue

        r = df.at[dt, "Return"]
        if pd.isna(r):
            continue

        rows.append(
            {
                "Year": int(y),
                "Date": dt.date(),
                "Return": float(r),
            }
        )

    return pd.DataFrame(rows).sort_values("Year") if rows else pd.DataFrame()


def stats_for_window(sample: pd.DataFrame, expected_n: int) -> dict:
    # Forecaster usa le osservazioni realmente disponibili all'interno
    # dei N anni di calendario; weekend e festività non entrano nel denominatore.
    n = len(sample)
    if n == 0:
        return {
            "n": 0,
            "long_prob": np.nan,
            "short_prob": np.nan,
            "avg": np.nan,
            "median": np.nan,
        }

    r = sample["Return"]
    return {
        "n": n,
        "long_prob": float((r > 0).mean()),
        "short_prob": float((r < 0).mean()),
        "avg": float(r.mean()),
        "median": float(r.median()),
    }


def analyze_target(
    name: str,
    ticker: str,
    df: pd.DataFrame,
    target: pd.Series,
    threshold: float,
    schedule: pd.DataFrame,
) -> dict:
    stats = {}
    samples = {}

    for w in WINDOWS:
        sample = seasonal_sample(
            df=df,
            target_date=target["date"],
            target_month=int(target["month"]),
            target_tdom=int(target["tdom"]),
            years=w,
            schedule=schedule,
        )
        samples[w] = sample
        stats[w] = stats_for_window(sample, w)

    long_ok = all(
        not math.isnan(stats[w]["long_prob"]) and stats[w]["long_prob"] >= threshold
        for w in WINDOWS
    )
    short_ok = all(
        not math.isnan(stats[w]["short_prob"]) and stats[w]["short_prob"] >= threshold
        for w in WINDOWS
    )

    if long_ok and not short_ok:
        bias = "LONG"
    elif short_ok and not long_ok:
        bias = "SHORT"
    else:
        bias = "—"

    avg10 = stats[10]["avg"]
    avg15 = stats[15]["avg"]
    avg20 = stats[20]["avg"]

    # Strategia originale: target = valore CENTRALE (mediana)
    # dei tre rendimenti medi 10Y, 15Y e 20Y.
    avg_returns = [avg10, avg15, avg20]
    if bias != "—" and all(not math.isnan(x) for x in avg_returns):
        target_median_3 = float(np.median(avg_returns))
        original_target = abs(target_median_3)
        original_stop = original_target / 2
    else:
        target_median_3 = np.nan
        original_target = np.nan
        original_stop = np.nan

    # Punteggio solo per ordinare le opportunità; NON modifica il filtro.
    directional_probs = []
    if bias == "LONG":
        directional_probs = [stats[w]["long_prob"] for w in WINDOWS]
    elif bias == "SHORT":
        directional_probs = [stats[w]["short_prob"] for w in WINDOWS]

    score = float(np.mean(directional_probs)) if directional_probs else np.nan

    result = {
        "Date": target["date"],
        "Asset": name,
        "Ticker": ticker,
        "Bias": bias,
        "10Y": stats[10]["long_prob"] if bias == "LONG" else stats[10]["short_prob"] if bias == "SHORT" else np.nan,
        "15Y": stats[15]["long_prob"] if bias == "LONG" else stats[15]["short_prob"] if bias == "SHORT" else np.nan,
        "20Y": stats[20]["long_prob"] if bias == "LONG" else stats[20]["short_prob"] if bias == "SHORT" else np.nan,
        "Avg 10Y": avg10,
        "Avg 15Y": avg15,
        "Avg 20Y": avg20,
        "Mediana 3 rend.": target_median_3,
        "Median 15Y": stats[15]["median"],
        "Target orig.": original_target,
        "Stop orig.": original_stop,
        "Score": score,
        "N10": stats[10]["n"],
        "N15": stats[15]["n"],
        "N20": stats[20]["n"],
        "_samples": samples,
    }
    return result


def pct(v):
    if pd.isna(v):
        return "n/d"
    return f"{v:.1%}"


st.title("📅 Seasonality Weekly Scanner")
st.caption(
    "Replica operativa del filtro stagionale 10/15/20 anni. "
    "La V1 non aggiunge RSI, trend, COT o altri filtri."
)

with st.sidebar:
    st.header("Impostazioni")

    default_start, default_end = next_week_bounds(date.today())
    week_start = st.date_input(
        "Lunedì della settimana da analizzare",
        value=default_start,
    )
    week_end = week_start + timedelta(days=4)

    threshold_pct = st.slider(
        "Filtro minimo su 10Y / 15Y / 20Y",
        min_value=50,
        max_value=95,
        value=70,
        step=1,
    )
    threshold = threshold_pct / 100

    st.divider()
    st.subheader("Universo")

    universe_text = st.text_area(
        "Una riga per asset: Nome,Ticker Yahoo",
        value="\n".join(f"{k},{v}" for k, v in DEFAULT_UNIVERSE.items()),
        height=210,
    )

    st.caption(
        "DAX e Euro Stoxx 50 sono analizzati sul cash index come proxy "
        "stagionale; gli altri strumenti indicati come Future usano i "
        "continuous futures Yahoo."
    )

    run = st.button("Analizza settimana", type="primary", width="stretch")

st.info(
    "**Metodo Forecaster:** per ogni giornata futura viene usato lo stesso "
    "giorno di calendario nei 10, 15 e 20 anni precedenti. "
    "Se in un determinato anno quella data cade nel weekend o non è una seduta, "
    "quell'anno viene escluso dal campione. Esempio: l'11 agosto viene confrontato "
    "solo con gli 11 agosto che sono stati effettive sedute di borsa."
)

if not run:
    st.stop()

# Parse universo
universe = {}
bad_rows = []
for raw in universe_text.splitlines():
    raw = raw.strip()
    if not raw:
        continue
    parts = [p.strip() for p in raw.split(",", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        bad_rows.append(raw)
    else:
        universe[parts[0]] = parts[1]

if bad_rows:
    st.error("Righe universo non valide: " + " | ".join(bad_rows))
    st.stop()

if not universe:
    st.error("Inserisci almeno un asset.")
    st.stop()

# Calendario abbastanza ampio per la finestra 20Y.
schedule = nyse_schedule(week_start.year - 21, week_start.year)
targets = trading_targets(week_start, week_end, schedule)

if targets.empty:
    st.warning("Nessuna seduta NYSE nella settimana selezionata.")
    st.stop()

progress = st.progress(0)
status = st.empty()
results = []
data_errors = []

for i, (name, ticker) in enumerate(universe.items(), start=1):
    status.write(f"Analisi {name} ({ticker})…")
    df = download_history(ticker)

    if df.empty:
        data_errors.append(f"{name} ({ticker}): dati non disponibili")
        progress.progress(i / len(universe))
        continue

    for _, target in targets.iterrows():
        results.append(
            analyze_target(
                name=name,
                ticker=ticker,
                df=df,
                target=target,
                threshold=threshold,
                schedule=schedule,
            )
        )

    progress.progress(i / len(universe))

status.empty()
progress.empty()

if not results:
    st.error("Non è stato possibile calcolare alcun risultato.")
    st.stop()

res = pd.DataFrame([{k: v for k, v in r.items() if k != "_samples"} for r in results])
opps = res[res["Bias"] != "—"].copy()
opps = opps.sort_values(["Date", "Score"], ascending=[True, False])

c1, c2, c3 = st.columns(3)
c1.metric("Sedute analizzate", len(targets))
c2.metric("Asset analizzati", len(universe))
c3.metric("Opportunità valide", len(opps))

st.subheader("Opportunità della settimana")

if opps.empty:
    st.warning(
        f"Nessun asset soddisfa contemporaneamente il filtro ≥ {threshold_pct}% "
        "su 10, 15 e 20 anni."
    )
else:
    display = opps[
        [
            "Date", "Asset", "Ticker", "Bias",
            "10Y", "15Y", "20Y",
            "Avg 10Y", "Avg 15Y", "Avg 20Y", "Mediana 3 rend.",
            "Median 15Y", "Target orig.", "Stop orig.", "Score"
        ]
    ].copy()

    for col in ["10Y", "15Y", "20Y", "Avg 10Y", "Avg 15Y", "Avg 20Y", "Mediana 3 rend.", "Median 15Y", "Target orig.", "Stop orig.", "Score"]:
        display[col] = display[col].map(pct)

    def color_bias(val):
        if val == "SHORT":
            return "color: #ff4b4b; font-weight: 700;"
        if val == "LONG":
            return "color: #21c55d; font-weight: 700;"
        return ""

    styled_display = display.style.map(color_bias, subset=["Bias"])
    st.dataframe(styled_display, width="stretch", hide_index=True)

st.divider()
st.subheader("Dettaglio storico")

valid_keys = [
    (r["Date"], r["Asset"], r["Ticker"], r["Bias"])
    for r in results
    if r["Bias"] != "—"
]

if valid_keys:
    labels = [
        f"{d} · {asset} ({ticker}) · {bias}"
        for d, asset, ticker, bias in valid_keys
    ]
    selected_label = st.selectbox("Seleziona opportunità", labels)
    selected_idx = labels.index(selected_label)
    key = valid_keys[selected_idx]

    original = next(
        r for r in results
        if (r["Date"], r["Asset"], r["Ticker"], r["Bias"]) == key
    )

    d1, d2, d3 = st.columns(3)
    d1.metric("Prob. 10Y", pct(original["10Y"]))
    d2.metric("Prob. 15Y", pct(original["15Y"]))
    d3.metric("Prob. 20Y", pct(original["20Y"]))

    st.write(
        f"**Avg 10Y:** {pct(original['Avg 10Y'])}  ·  "
        f"**Avg 15Y:** {pct(original['Avg 15Y'])}  ·  "
        f"**Avg 20Y:** {pct(original['Avg 20Y'])}  ·  "
        f"**Mediana dei 3 rendimenti:** {pct(original['Mediana 3 rend.'])}"
    )
    st.write(
        f"**TP originale:** {pct(original['Target orig.'])}  ·  "
        f"**SL originale:** {pct(original['Stop orig.'])}"
    )

    hist = original["_samples"][20].copy()
    hist["Return"] = hist["Return"].map(lambda x: f"{x:.2%}")
    st.dataframe(hist, width="stretch", hide_index=True)

    st.caption(
        "Il TP e lo SL mostrati replicano la regola descritta: "
        "target = valore assoluto della mediana dei rendimenti medi 10Y, 15Y e 20Y; "
        "stop = metà del target. "
        "La V1 NON afferma ancora che questo TP/SL sia ottimale."
    )
else:
    st.caption("Nessun dettaglio disponibile perché non ci sono opportunità valide.")

with st.expander("Diagnostica dati / campione"):
    diag = res[["Date", "Asset", "Ticker", "Bias", "10Y", "15Y", "20Y", "N10", "N15", "N20"]].copy()
    for col in ["10Y", "15Y", "20Y"]:
        diag[col] = diag[col].map(pct)
    st.dataframe(diag, width="stretch", hide_index=True)
    if data_errors:
        st.warning("\n".join(data_errors))

st.divider()
st.caption(
    "Uso di ricerca/statistica, non consiglio finanziario. "
    "La disponibilità e qualità dei dati Yahoo Finance va controllata "
    "prima di impiegare il risultato in operatività reale."
)
