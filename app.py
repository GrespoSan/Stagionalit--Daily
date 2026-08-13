from __future__ import annotations

from datetime import date, timedelta
import io
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
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Amazon": "AMZN",
    "Broadcom": "AVGO",
    "Meta Platforms": "META",
    "Berkshire Hathaway B": "BRK-B",
    "Tesla": "TSLA",
    "Eli Lilly": "LLY",

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


@st.cache_data(ttl=60 * 60, show_spinner=False)
def download_intraday_5m(ticker: str, target_date: date) -> pd.DataFrame:
    """Barre 5m della singola data, usate solo per risolvere l'ordine target/stop."""
    try:
        df = yf.download(ticker,start=target_date.isoformat(),end=(target_date+timedelta(days=1)).isoformat(),interval="5m",auto_adjust=False,actions=False,progress=False,threads=False,prepost=True)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns,pd.MultiIndex):
        if ticker in df.columns.get_level_values(-1): df=df.xs(ticker,axis=1,level=-1)
        else: df.columns=df.columns.get_level_values(0)
    if any(c not in df.columns for c in ["Open","High","Low","Close"]):
        return pd.DataFrame()
    df=df[["Open","High","Low","Close"]].copy()
    idx=pd.to_datetime(df.index)
    try: idx=idx.tz_localize(None) if idx.tz is None else idx.tz_convert(None)
    except Exception: pass
    df.index=idx
    return df.dropna(subset=["High","Low"]).sort_index()

def resolve_intraday_order(bars: pd.DataFrame,bias: str,target_level: float,stop_level: float) -> str:
    if bars is None or bars.empty: return "NO DATI"
    for _,bar in bars.iterrows():
        hi=float(bar["High"]); lo=float(bar["Low"])
        if bias=="LONG": hit_target=hi>=target_level; hit_stop=lo<=stop_level
        else: hit_target=lo<=target_level; hit_stop=hi>=stop_level
        if hit_target and hit_stop: return "NO DATI"
        if hit_target: return "WIN"
        if hit_stop: return "LOSS"
    return "NO HIT"

def evaluate_trade_outcome(ticker: str,df: pd.DataFrame,target_date: date,bias: str,target_pts: float,atr_pts: float) -> dict:
    result={"Open trade":np.nan,"Target level":np.nan,"Stop level":np.nan,"SL 50% ATR pts":np.nan,"Esito":"PENDING"}
    if bias not in ("LONG","SHORT"):
        result["Esito"]="—"; return result
    if pd.isna(target_pts) or pd.isna(atr_pts):
        result["Esito"]="N/D"; return result
    # La colonna WIN/LOSS valuta solo giornate completamente trascorse.
    if target_date >= date.today():
        return result
    dt=pd.Timestamp(target_date)
    if dt not in df.index: return result
    op=df.at[dt,"Open"]; hi=df.at[dt,"High"]; lo=df.at[dt,"Low"]
    if pd.isna(op) or pd.isna(hi) or pd.isna(lo):
        result["Esito"]="N/D"; return result
    op=float(op); hi=float(hi); lo=float(lo); sl_pts=.5*float(atr_pts)
    if bias=="LONG":
        target_level=op+float(target_pts); stop_level=op-sl_pts; hit_target=hi>=target_level; hit_stop=lo<=stop_level
    else:
        target_level=op-float(target_pts); stop_level=op+sl_pts; hit_target=lo<=target_level; hit_stop=hi>=stop_level
    result.update({"Open trade":op,"Target level":target_level,"Stop level":stop_level,"SL 50% ATR pts":sl_pts})
    if hit_target and not hit_stop: result["Esito"]="WIN"
    elif hit_stop and not hit_target: result["Esito"]="LOSS"
    elif not hit_target and not hit_stop: result["Esito"]="NO HIT"
    else: result["Esito"]=resolve_intraday_order(download_intraday_5m(ticker,target_date),bias,target_level,stop_level)
    return result

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


def atr_pct_before_date(df: pd.DataFrame, target_date: date, period: int) -> tuple[float, float]:
    """
    ATR semplice sulle ultime N sedute COMPLETATE prima della data target.
    Restituisce (ATR in prezzo, ATR in % del close più recente).
    Nessun look-ahead: la seduta target non viene mai utilizzata.
    """
    hist = df.loc[df.index < pd.Timestamp(target_date)].copy()
    if len(hist) < period + 1:
        return np.nan, np.nan

    prev_close = hist["Close"].shift(1)
    tr = pd.concat(
        [
            hist["High"] - hist["Low"],
            (hist["High"] - prev_close).abs(),
            (hist["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean().iloc[-1]
    last_close = hist["Close"].iloc[-1]

    if pd.isna(atr) or pd.isna(last_close) or last_close == 0:
        return np.nan, np.nan

    return float(atr), float(atr / last_close)


def movement_class(ratio: float) -> str:
    if pd.isna(ratio):
        return "n/d"
    if ratio < 0.30:
        return "DEBOLE"
    if ratio < 0.50:
        return "MEDIO"
    if ratio < 0.75:
        return "BUONO"
    return "FORTE"


def analyze_target(
    name: str,
    ticker: str,
    df: pd.DataFrame,
    target: pd.Series,
    threshold: float,
    schedule: pd.DataFrame,
    atr_period: int,
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

    atr_value, atr_pct = atr_pct_before_date(df, target["date"], atr_period)
    target_atr = (
        original_target / atr_pct
        if not pd.isna(original_target) and not pd.isna(atr_pct) and atr_pct > 0
        else np.nan
    )
    move_quality = movement_class(target_atr)

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
        "10Y LONG raw": stats[10]["long_prob"],
        "15Y LONG raw": stats[15]["long_prob"],
        "20Y LONG raw": stats[20]["long_prob"],
        "10Y SHORT raw": stats[10]["short_prob"],
        "15Y SHORT raw": stats[15]["short_prob"],
        "20Y SHORT raw": stats[20]["short_prob"],
        "Avg 10Y": avg10,
        "Avg 15Y": avg15,
        "Avg 20Y": avg20,
        "Mediana 3 rend.": target_median_3,
        "Median 15Y": stats[15]["median"],
        "Target orig.": original_target,
        "Stop orig.": original_stop,
        "ATR pts": atr_value,
        "ATR%": atr_pct,
        "Target/ATR": target_atr,
        "Target pts": (atr_value * target_atr) if not pd.isna(atr_value) and not pd.isna(target_atr) else np.nan,
        "Forza mov.": move_quality,
        "Score": score,
        "N10": stats[10]["n"],
        "N15": stats[15]["n"],
        "N20": stats[20]["n"],
        "_samples": samples,
    }
    return result



@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def download_spx_history() -> pd.DataFrame:
    return download_history("^GSPC")


def spx_regime_before_date(spx_df: pd.DataFrame, target_date: date, ema_period: int) -> dict:
    out = {"SPX Regime": "NO DATI", "SPX Prev Close": np.nan, "SPX EMA": np.nan, "SPX Above EMA": False}
    if spx_df is None or spx_df.empty:
        return out
    hist = spx_df.loc[spx_df.index < pd.Timestamp(target_date)].copy()
    if len(hist) < ema_period:
        return out
    ema = hist["Close"].ewm(span=ema_period, adjust=False).mean()
    prev_close = hist["Close"].iloc[-1]
    prev_ema = ema.iloc[-1]
    if pd.isna(prev_close) or pd.isna(prev_ema):
        return out
    prev_close = float(prev_close)
    prev_ema = float(prev_ema)
    above = prev_close > prev_ema
    return {"SPX Regime": "SOPRA EMA" if above else "SOTTO EMA", "SPX Prev Close": prev_close, "SPX EMA": prev_ema, "SPX Above EMA": above}


def strength_min_ratio(label: str) -> float:
    mapping = {
        "TUTTI": 0.0,
        "MEDIO+": 0.30,
        "BUONO+": 0.50,
        "SOLO BUONO": 0.50,
        "SOLO FORTE": 0.75,
    }
    return mapping.get(label, 0.0)


def strength_passes(label: str, target_atr: float) -> bool:
    """
    Applica il filtro forza sul rapporto Target/ATR.
    Classi:
    DEBOLE < 0.30
    MEDIO  0.30 <= x < 0.50
    BUONO  0.50 <= x < 0.75
    FORTE  x >= 0.75
    """
    if pd.isna(target_atr):
        return False

    x = float(target_atr)

    if label == "TUTTI":
        return True
    if label == "MEDIO+":
        return x >= 0.30
    if label == "BUONO+":
        return x >= 0.50
    if label == "SOLO BUONO":
        return 0.50 <= x < 0.75
    if label == "SOLO FORTE":
        return x >= 0.75

    return True


def signal_return_coherent(row: dict) -> bool:
    """
    Coerenza opzionale:
    LONG -> mediana dei 3 rendimenti > 0
    SHORT -> mediana dei 3 rendimenti < 0
    """
    m = row.get("Mediana 3 rend.", np.nan)
    if pd.isna(m):
        return False
    if row.get("Bias") == "LONG":
        return m > 0
    if row.get("Bias") == "SHORT":
        return m < 0
    return False


def evaluate_backtest_trade(
    ticker: str,
    df: pd.DataFrame,
    target_date: date,
    bias: str,
    target_pts: float,
    atr_pts: float,
    stop_atr_mult: float,
) -> dict:
    """
    Entry: Open della seduta.
    Target: +/- target_pts.
    Stop: stop_atr_mult * ATR.
    Se nessuno dei due viene raggiunto: uscita al Close.
    Se target e stop sono entrambi toccati e l'ordine non è ricostruibile: NO DATI.
    """
    result = {
        "Open": np.nan,
        "Close": np.nan,
        "Target level": np.nan,
        "Stop level": np.nan,
        "SL pts": np.nan,
        "Exit price": np.nan,
        "Exit reason": "NO DATI",
        "Outcome": "NO DATI",
        "PnL pts": np.nan,
        "R": np.nan,
    }

    if bias not in ("LONG", "SHORT"):
        return result

    if pd.isna(target_pts) or pd.isna(atr_pts) or atr_pts <= 0 or target_pts < 0:
        return result

    dt = pd.Timestamp(target_date)
    if dt not in df.index:
        return result

    row = df.loc[dt]
    op, hi, lo, cl = row["Open"], row["High"], row["Low"], row["Close"]
    if any(pd.isna(x) for x in (op, hi, lo, cl)):
        return result

    op, hi, lo, cl = map(float, (op, hi, lo, cl))
    sl_pts = float(stop_atr_mult) * float(atr_pts)
    if sl_pts <= 0:
        return result

    if bias == "LONG":
        target_level = op + float(target_pts)
        stop_level = op - sl_pts
        hit_target = hi >= target_level
        hit_stop = lo <= stop_level
    else:
        target_level = op - float(target_pts)
        stop_level = op + sl_pts
        hit_target = lo <= target_level
        hit_stop = hi >= stop_level

    result.update({
        "Open": op,
        "Close": cl,
        "Target level": target_level,
        "Stop level": stop_level,
        "SL pts": sl_pts,
    })

    # Caso univoco dal daily
    if hit_target and not hit_stop:
        result.update({
            "Exit price": target_level,
            "Exit reason": "TARGET",
            "Outcome": "WIN",
            "PnL pts": float(target_pts),
            "R": float(target_pts) / sl_pts,
        })
        return result

    if hit_stop and not hit_target:
        result.update({
            "Exit price": stop_level,
            "Exit reason": "STOP",
            "Outcome": "LOSS",
            "PnL pts": -sl_pts,
            "R": -1.0,
        })
        return result

    # Entrambi toccati: prova intraday solo se plausibilmente disponibile.
    if hit_target and hit_stop:
        if target_date < (date.today() - timedelta(days=60)):
            return result

        bars = download_intraday_5m(ticker, target_date)
        order = resolve_intraday_order(bars, bias, target_level, stop_level)

        if order == "WIN":
            result.update({
                "Exit price": target_level,
                "Exit reason": "TARGET",
                "Outcome": "WIN",
                "PnL pts": float(target_pts),
                "R": float(target_pts) / sl_pts,
            })
        elif order == "LOSS":
            result.update({
                "Exit price": stop_level,
                "Exit reason": "STOP",
                "Outcome": "LOSS",
                "PnL pts": -sl_pts,
                "R": -1.0,
            })
        # altrimenti resta NO DATI
        return result

    # Nessuno dei due: chiusura a fine seduta.
    if bias == "LONG":
        pnl_pts = cl - op
    else:
        pnl_pts = op - cl

    if pnl_pts > 0:
        outcome = "WIN"
    elif pnl_pts < 0:
        outcome = "LOSS"
    else:
        outcome = "FLAT"

    result.update({
        "Exit price": cl,
        "Exit reason": "CLOSE",
        "Outcome": outcome,
        "PnL pts": pnl_pts,
        "R": pnl_pts / sl_pts,
    })
    return result


def backtest_metrics(trades: pd.DataFrame) -> dict:
    """
    Metriche calcolate solo sui trade con R disponibile.
    NO DATI è escluso automaticamente.
    """
    valid = trades.dropna(subset=["R"]).copy() if not trades.empty else pd.DataFrame()
    if valid.empty:
        return {
            "signals": len(trades),
            "valid": 0,
            "no_data": int((trades["Outcome"] == "NO DATI").sum()) if "Outcome" in trades.columns else 0,
            "wins": 0,
            "losses": 0,
            "win_rate": np.nan,
            "profit_factor": np.nan,
            "expectancy_r": np.nan,
            "total_r": np.nan,
            "max_dd_r": np.nan,
        }

    wins = int((valid["R"] > 0).sum())
    losses = int((valid["R"] < 0).sum())
    decisive = wins + losses
    gross_profit = float(valid.loc[valid["R"] > 0, "R"].sum())
    gross_loss = abs(float(valid.loc[valid["R"] < 0, "R"].sum()))
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf if gross_profit > 0 else np.nan

    ordered = valid.sort_values(["Date", "Asset"]).copy()
    equity = ordered["R"].cumsum()
    # Il capitale parte da 0R: il drawdown deve includere anche una partenza negativa.
    peak = equity.cummax().clip(lower=0)
    drawdown = equity - peak
    max_dd = abs(float(drawdown.min())) if len(drawdown) else np.nan

    return {
        "signals": len(trades),
        "valid": len(valid),
        "no_data": int((trades["Outcome"] == "NO DATI").sum()),
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / decisive) if decisive > 0 else np.nan,
        "profit_factor": pf,
        "expectancy_r": float(valid["R"].mean()),
        "total_r": float(valid["R"].sum()),
        "max_dd_r": max_dd,
    }



def prepare_asset_for_fast_backtest(df: pd.DataFrame, atr_period: int) -> tuple[pd.DataFrame, dict]:
    """
    Precalcola una sola volta ATR(T-1), Close(T-1) e gli indici stagionali
    mese/giorno per un asset. Evita di ricostruire gli stessi dati per ogni seduta.
    """
    work = df.copy()

    prev_close = work["Close"].shift(1)
    tr = pd.concat(
        [
            work["High"] - work["Low"],
            (work["High"] - prev_close).abs(),
            (work["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # L'ATR usato sul giorno T deve essere noto PRIMA dell'Open di T:
    # rolling ATR fino a T-1, quindi shift(1).
    work["_ATR_PREV"] = tr.rolling(int(atr_period), min_periods=int(atr_period)).mean().shift(1)
    work["_CLOSE_PREV"] = work["Close"].shift(1)

    seasonal_lookup = {}
    valid = work.dropna(subset=["Return"])
    for (month, day), grp in valid.groupby([valid.index.month, valid.index.day]):
        seasonal_lookup[(int(month), int(day))] = (
            grp.index.year.to_numpy(dtype=int),
            grp["Return"].to_numpy(dtype=float),
        )

    return work, seasonal_lookup


def fast_window_stats(
    seasonal_lookup: dict,
    target_date: date,
    years: int,
) -> dict:
    """
    Statistiche Forecaster sullo stesso giorno di calendario nei precedenti N anni.
    Usa array preindicizzati: nessuna scansione ripetuta del DataFrame completo.
    """
    pair = seasonal_lookup.get((target_date.month, target_date.day))
    if pair is None:
        return {
            "n": 0,
            "long_prob": np.nan,
            "short_prob": np.nan,
            "avg": np.nan,
            "median": np.nan,
        }

    hist_years, hist_returns = pair
    y = target_date.year
    mask = (hist_years >= y - int(years)) & (hist_years < y)
    vals = hist_returns[mask]
    vals = vals[~np.isnan(vals)]
    n = int(vals.size)

    if n == 0:
        return {
            "n": 0,
            "long_prob": np.nan,
            "short_prob": np.nan,
            "avg": np.nan,
            "median": np.nan,
        }

    return {
        "n": n,
        "long_prob": float(np.mean(vals > 0)),
        "short_prob": float(np.mean(vals < 0)),
        "avg": float(np.mean(vals)),
        "median": float(np.median(vals)),
    }


def fast_analyze_target(
    name: str,
    ticker: str,
    prepared_df: pd.DataFrame,
    seasonal_lookup: dict,
    target_date: date,
    threshold: float,
) -> dict:
    """
    Versione ottimizzata di analyze_target usata SOLO dal backtest.
    Mantiene la stessa logica statistica, ma riutilizza i dati precalcolati.
    """
    stats = {w: fast_window_stats(seasonal_lookup, target_date, w) for w in WINDOWS}

    long_ok = all(
        not pd.isna(stats[w]["long_prob"]) and stats[w]["long_prob"] >= threshold
        for w in WINDOWS
    )
    short_ok = all(
        not pd.isna(stats[w]["short_prob"]) and stats[w]["short_prob"] >= threshold
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
    avg_returns = [avg10, avg15, avg20]

    if bias != "—" and all(not pd.isna(x) for x in avg_returns):
        target_median_3 = float(np.median(avg_returns))
        original_target = abs(target_median_3)
    else:
        target_median_3 = np.nan
        original_target = np.nan

    dt = pd.Timestamp(target_date)
    if dt in prepared_df.index:
        atr_value = prepared_df.at[dt, "_ATR_PREV"]
        last_close = prepared_df.at[dt, "_CLOSE_PREV"]
    else:
        atr_value = np.nan
        last_close = np.nan

    if pd.isna(atr_value) or pd.isna(last_close) or float(last_close) == 0:
        atr_value = np.nan
        atr_pct = np.nan
    else:
        atr_value = float(atr_value)
        last_close = float(last_close)
        atr_pct = atr_value / last_close

    target_atr = (
        original_target / atr_pct
        if not pd.isna(original_target) and not pd.isna(atr_pct) and atr_pct > 0
        else np.nan
    )

    target_pts = (
        atr_value * target_atr
        if not pd.isna(atr_value) and not pd.isna(target_atr)
        else np.nan
    )

    if bias == "LONG":
        directional_probs = [stats[w]["long_prob"] for w in WINDOWS]
    elif bias == "SHORT":
        directional_probs = [stats[w]["short_prob"] for w in WINDOWS]
    else:
        directional_probs = []

    score = float(np.mean(directional_probs)) if directional_probs else np.nan

    return {
        "Date": target_date,
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
        "Target orig.": original_target,
        "ATR pts": atr_value,
        "ATR%": atr_pct,
        "Target/ATR": target_atr,
        "Target pts": target_pts,
        "Forza mov.": movement_class(target_atr),
        "Score": score,
        "N10": stats[10]["n"],
        "N15": stats[15]["n"],
        "N20": stats[20]["n"],
    }


def prepare_spx_for_fast_backtest(spx_df: pd.DataFrame, ema_period: int) -> pd.DataFrame:
    """
    Precalcola l'EMA SPX una sola volta. La ricerca del regime per ogni trade
    diventa una semplice lookup della seduta precedente.
    """
    if spx_df is None or spx_df.empty:
        return pd.DataFrame()

    out = spx_df[["Close"]].copy()
    out["_EMA"] = out["Close"].ewm(span=int(ema_period), adjust=False).mean()
    return out


def fast_spx_regime_before_date(
    spx_prepared: pd.DataFrame,
    target_date: date,
) -> dict:
    out = {
        "SPX Regime": "NO DATI",
        "SPX Prev Close": np.nan,
        "SPX EMA": np.nan,
        "SPX Above EMA": False,
    }

    if spx_prepared is None or spx_prepared.empty:
        return out

    target_ts = pd.Timestamp(target_date)
    pos = int(spx_prepared.index.searchsorted(target_ts, side="left")) - 1
    if pos < 0:
        return out

    prev_close = spx_prepared["Close"].iloc[pos]
    prev_ema = spx_prepared["_EMA"].iloc[pos]
    if pd.isna(prev_close) or pd.isna(prev_ema):
        return out

    prev_close = float(prev_close)
    prev_ema = float(prev_ema)
    above = prev_close > prev_ema

    return {
        "SPX Regime": "SOPRA EMA" if above else "SOTTO EMA",
        "SPX Prev Close": prev_close,
        "SPX EMA": prev_ema,
        "SPX Above EMA": above,
    }


def run_manual_backtest(
    universe: dict,
    start_date: date,
    end_date: date,
    threshold: float,
    atr_period: int,
    strength_filter: str,
    stop_atr_mult: float,
    direction_filter: str,
    require_return_coherence: bool,
    min_sample_coverage: float,
    spx_filter_mode: str,
    spx_ema_period: int,
) -> tuple[pd.DataFrame, list]:
    """
    Backtest ottimizzato:
    - ogni storico viene scaricato una sola volta;
    - ATR viene precalcolato una sola volta per asset;
    - lo storico stagionale viene indicizzato una sola volta per mese/giorno;
    - EMA SPX viene precalcolata una sola volta;
    - massimo 1 trade/giorno, selezionato PRIMA di conoscere l'esito.
    """
    candidates_list = []
    errors = []
    data_cache = {}

    spx_df = download_spx_history()
    spx_prepared = prepare_spx_for_fast_backtest(spx_df, int(spx_ema_period))
    if spx_prepared.empty:
        errors.append("S&P 500 (^GSPC): dati regime non disponibili")

    progress = st.progress(0)
    status = st.empty()

    items = list(universe.items())
    total_assets = max(len(items), 1)

    for i, (name, ticker) in enumerate(items, start=1):
        status.write(f"Backtest {name} ({ticker}) — preparazione dati…")
        df = download_history(ticker)

        if df.empty:
            errors.append(f"{name} ({ticker}): dati daily non disponibili")
            progress.progress(i / total_assets)
            continue

        data_cache[ticker] = df
        prepared_df, seasonal_lookup = prepare_asset_for_fast_backtest(
            df=df,
            atr_period=int(atr_period),
        )

        # Solo sedute realmente presenti e già concluse.
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        today_ts = pd.Timestamp(date.today())
        trade_index = prepared_df.index[
            (prepared_df.index >= start_ts)
            & (prepared_df.index <= end_ts)
            & (prepared_df.index < today_ts)
        ]

        status.write(
            f"Backtest {name} ({ticker}) — {len(trade_index)} sedute…"
        )

        for dt in trade_index:
            d = dt.date()

            sig = fast_analyze_target(
                name=name,
                ticker=ticker,
                prepared_df=prepared_df,
                seasonal_lookup=seasonal_lookup,
                target_date=d,
                threshold=threshold,
            )

            if sig["Bias"] not in ("LONG", "SHORT"):
                continue

            regime = fast_spx_regime_before_date(spx_prepared, d)

            if spx_filter_mode == "SOLO SOPRA EMA" and not regime["SPX Above EMA"]:
                continue
            if spx_filter_mode == "SOLO SOTTO EMA" and regime["SPX Regime"] != "SOTTO EMA":
                continue

            if direction_filter == "SOLO LONG" and sig["Bias"] != "LONG":
                continue
            if direction_filter == "SOLO SHORT" and sig["Bias"] != "SHORT":
                continue

            coverages = [
                sig["N10"] / 10,
                sig["N15"] / 15,
                sig["N20"] / 20,
            ]
            if min(coverages) < min_sample_coverage:
                continue

            if not strength_passes(strength_filter, sig["Target/ATR"]):
                continue

            if require_return_coherence and not signal_return_coherent(sig):
                continue

            candidates_list.append({
                "Date": d,
                "Asset": name,
                "Ticker": ticker,
                "Bias": sig["Bias"],
                "Forza": sig["Forza mov."],
                "Score": sig["Score"],
                "10Y": sig["10Y"],
                "15Y": sig["15Y"],
                "20Y": sig["20Y"],
                "N10": sig["N10"],
                "N15": sig["N15"],
                "N20": sig["N20"],
                "Target %": sig["Target orig."],
                "ATR pts": sig["ATR pts"],
                "Target pts": sig["Target pts"],
                "Target/ATR": sig["Target/ATR"],
                "Coerente": signal_return_coherent(sig),
                "SPX Regime": regime["SPX Regime"],
                "SPX Prev Close": regime["SPX Prev Close"],
                "SPX EMA": regime["SPX EMA"],
            })

        progress.progress(i / total_assets)

    status.write("Selezione del miglior trade di ogni giornata…")

    candidates = pd.DataFrame(candidates_list)
    if candidates.empty:
        status.empty()
        progress.empty()
        return candidates, errors

    # Conteggio candidati PRIMA del limite giornaliero.
    daily_counts = candidates.groupby("Date").size()
    candidates["Candidati giorno"] = candidates["Date"].map(daily_counts)

    # Ranking disponibile ex-ante:
    # 1) Target/ATR più alto
    # 2) Score più alto
    # 3) Asset alfabetico come tie-break
    candidates = candidates.sort_values(
        ["Date", "Target/ATR", "Score", "Asset"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)
    candidates["Rank giorno"] = candidates.groupby("Date").cumcount() + 1

    # Regola fissa: massimo 1 trade al giorno.
    selected = candidates[candidates["Rank giorno"] == 1].copy()

    status.write(f"Valutazione esito di {len(selected)} trade selezionati…")

    evaluated = []
    for _, row in selected.iterrows():
        df_eval = data_cache.get(row["Ticker"], pd.DataFrame())

        trade = evaluate_backtest_trade(
            ticker=row["Ticker"],
            df=df_eval,
            target_date=row["Date"],
            bias=row["Bias"],
            target_pts=row["Target pts"],
            atr_pts=row["ATR pts"],
            stop_atr_mult=stop_atr_mult,
        )

        record = row.to_dict()
        record.update(trade)
        evaluated.append(record)

    status.empty()
    progress.empty()

    bt = pd.DataFrame(evaluated)
    if not bt.empty:
        bt = bt.sort_values(["Date", "Rank giorno", "Asset"]).reset_index(drop=True)

    return bt, errors


def format_metric(v, fmt=".2f"):
    if pd.isna(v):
        return "n/d"
    if np.isinf(v):
        return "∞"
    return format(v, fmt)


def render_backtest_results(
    bt: pd.DataFrame,
    errors: list,
    atr_period: int,
    stop_atr_mult: float,
    spx_ema_period: int,
    spx_filter_mode: str,
):
    st.header("🧪 Backtest manuale")

    if bt.empty:
        st.warning("Nessun trade soddisfa i filtri selezionati nel periodo.")
        if errors:
            st.warning("\\n".join(errors))
        return

    m = backtest_metrics(bt)

    cols = st.columns(9)
    cols[0].metric("Segnali", m["signals"])
    cols[1].metric("Valutabili", m["valid"])
    cols[2].metric("NO DATI", m["no_data"])
    cols[3].metric("WIN", m["wins"])
    cols[4].metric("LOSS", m["losses"])
    cols[5].metric("Win Rate", "n/d" if pd.isna(m["win_rate"]) else f"{m['win_rate']:.1%}")
    cols[6].metric("Profit Factor", format_metric(m["profit_factor"]))
    cols[7].metric("Expectancy", "n/d" if pd.isna(m["expectancy_r"]) else f"{m['expectancy_r']:+.3f} R")
    cols[8].metric("Max DD", "n/d" if pd.isna(m["max_dd_r"]) else f"{m['max_dd_r']:.2f} R")

    st.caption(
        f"Totale: **{format_metric(m['total_r'], '+.2f')} R** · "
        f"Stop: **{stop_atr_mult:.2f} × ATR{atr_period}**. "
        "NO DATI è escluso da tutte le metriche di performance."
    )

    valid = bt.dropna(subset=["R"]).copy()
    if not valid.empty:
        equity = valid.sort_values(["Date", "Asset"])[["Date", "R"]].copy()
        equity["Equity R"] = equity["R"].cumsum()
        daily_equity = equity.groupby("Date", as_index=False)["R"].sum()
        daily_equity["Equity R"] = daily_equity["R"].cumsum()
        st.subheader("Equity cumulata in R")
        st.line_chart(daily_equity.set_index("Date")["Equity R"])

    st.subheader(f"Risultati per regime S&P 500 / EMA{int(spx_ema_period)}")
    regime_rows = []
    for regime_name in ["SOPRA EMA", "SOTTO EMA", "NO DATI"]:
        part = bt[bt["SPX Regime"] == regime_name] if "SPX Regime" in bt.columns else pd.DataFrame()
        if part.empty:
            continue
        mm = backtest_metrics(part)
        regime_rows.append({
            "Regime SPX": regime_name,
            "Segnali": mm["signals"],
            "Valutabili": mm["valid"],
            "NO DATI": mm["no_data"],
            "Win Rate": mm["win_rate"],
            "Profit Factor": mm["profit_factor"],
            "Expectancy R": mm["expectancy_r"],
            "Totale R": mm["total_r"],
            "Max DD R": mm["max_dd_r"],
        })
    if regime_rows:
        rf = pd.DataFrame(regime_rows)
        rf["Win Rate"] = rf["Win Rate"].map(lambda x: "n/d" if pd.isna(x) else f"{x:.1%}")
        for c in ["Profit Factor", "Expectancy R", "Totale R", "Max DD R"]:
            rf[c] = rf[c].map(lambda x: "n/d" if pd.isna(x) else ("∞" if np.isinf(x) else f"{x:.2f}"))
        st.dataframe(rf, width="stretch", hide_index=True)
    st.caption(
        f"Regime calcolato con Close SPX e EMA della seduta precedente (T−1). "
        f"Filtro attivo: {spx_filter_mode}. La stessa regola vale sia per LONG sia per SHORT."
    )

    st.subheader("Risultati per anno")
    yearly_rows = []
    bt_year = bt.copy()
    bt_year["Anno"] = pd.to_datetime(bt_year["Date"]).dt.year
    for year, part in bt_year.groupby("Anno"):
        mm = backtest_metrics(part)
        yearly_rows.append({
            "Anno": int(year),
            "Segnali": mm["signals"],
            "Valutabili": mm["valid"],
            "NO DATI": mm["no_data"],
            "WIN": mm["wins"],
            "LOSS": mm["losses"],
            "Win Rate": mm["win_rate"],
            "Profit Factor": mm["profit_factor"],
            "Expectancy R": mm["expectancy_r"],
            "Totale R": mm["total_r"],
            "Max DD R": mm["max_dd_r"],
        })

    if yearly_rows:
        yf = pd.DataFrame(yearly_rows).sort_values("Anno")
        yf["Win Rate"] = yf["Win Rate"].map(lambda x: "n/d" if pd.isna(x) else f"{x:.1%}")
        for c in ["Profit Factor", "Expectancy R", "Totale R", "Max DD R"]:
            yf[c] = yf[c].map(
                lambda x: "n/d" if pd.isna(x) else ("∞" if np.isinf(x) else f"{x:.2f}")
            )
        st.dataframe(yf, width="stretch", hide_index=True)

    st.subheader("Risultati per forza movimento")
    strength_order = ["DEBOLE", "MEDIO", "BUONO", "FORTE"]
    strength_rows = []
    for strength in strength_order:
        part = bt[bt["Forza"] == strength]
        if part.empty:
            continue
        mm = backtest_metrics(part)
        strength_rows.append({
            "Forza": strength,
            "Segnali": mm["signals"],
            "Valutabili": mm["valid"],
            "NO DATI": mm["no_data"],
            "Win Rate": mm["win_rate"],
            "Profit Factor": mm["profit_factor"],
            "Expectancy R": mm["expectancy_r"],
            "Totale R": mm["total_r"],
        })
    if strength_rows:
        sf = pd.DataFrame(strength_rows)
        for c in ["Win Rate"]:
            sf[c] = sf[c].map(lambda x: "n/d" if pd.isna(x) else f"{x:.1%}")
        for c in ["Profit Factor", "Expectancy R", "Totale R"]:
            sf[c] = sf[c].map(lambda x: "n/d" if pd.isna(x) else ("∞" if np.isinf(x) else f"{x:.2f}"))
        st.dataframe(sf, width="stretch", hide_index=True)

    st.subheader("Risultati per asset")
    asset_rows = []
    for asset, part in bt.groupby("Asset"):
        mm = backtest_metrics(part)
        asset_rows.append({
            "Asset": asset,
            "Segnali": mm["signals"],
            "Valutabili": mm["valid"],
            "NO DATI": mm["no_data"],
            "Win Rate": mm["win_rate"],
            "Profit Factor": mm["profit_factor"],
            "Expectancy R": mm["expectancy_r"],
            "Totale R": mm["total_r"],
        })
    af = pd.DataFrame(asset_rows).sort_values("Totale R", ascending=False)
    af["Win Rate"] = af["Win Rate"].map(lambda x: "n/d" if pd.isna(x) else f"{x:.1%}")
    for c in ["Profit Factor", "Expectancy R", "Totale R"]:
        af[c] = af[c].map(lambda x: "n/d" if pd.isna(x) else ("∞" if np.isinf(x) else f"{x:.2f}"))
    st.dataframe(af, width="stretch", hide_index=True)

    st.subheader("Trade log")
    disp = bt.copy()
    for c in ["Score", "10Y", "15Y", "20Y", "Target %"]:
        disp[c] = disp[c].map(lambda x: "n/d" if pd.isna(x) else f"{x:.1%}")
    disp["Target/ATR"] = disp["Target/ATR"].map(lambda x: "n/d" if pd.isna(x) else f"{x:.0%}")
    for c in ["ATR pts", "Target pts", "SL pts", "SPX Prev Close", "SPX EMA", "Open", "Close", "Exit price", "PnL pts", "R"]:
        if c in disp.columns:
            disp[c] = disp[c].map(lambda x: "n/d" if pd.isna(x) else f"{x:,.2f}")

    show_cols = [
        "Date", "Asset", "Ticker", "Bias", "Forza", "Score",
        "10Y", "15Y", "20Y", "N10", "N15", "N20",
        "Target %", "ATR pts", "Target pts", "SL pts",
        "Candidati giorno", "Rank giorno",
        "SPX Regime", "SPX Prev Close", "SPX EMA",
        "Open", "Exit reason", "Outcome", "PnL pts", "R", "Coerente"
    ]
    st.dataframe(disp[show_cols], width="stretch", hide_index=True)

    with st.expander("Note sul backtest"):
        st.write(
            "• La stagionalità di ogni data usa esclusivamente anni precedenti alla data testata.\\n"
            "• L'ATR usa esclusivamente sedute precedenti.\\n"
            f"• Il regime SPX usa Close e EMA{int(spx_ema_period)} della seduta precedente (T−1).\\n"
            "• Se il filtro SPX è attivo, sia LONG sia SHORT richiedono SPX sopra EMA.\\n"
            "• Se né target né stop vengono raggiunti, il trade viene chiuso al Close.\\n"
            "• Se target e stop sono entrambi toccati nella stessa seduta e non possiamo "
            "stabilire l'ordine con dati intraday, l'esito è NO DATI e il trade non entra nelle metriche.\\n"
            "• La strategia usa sempre massimo 1 trade al giorno. La selezione viene applicata prima "
            "di conoscere l'esito, ordinando i candidati per Target/ATR e poi Score.\n"
            "• La versione non applica ancora un limite di rischio complessivo tra giornate o correlazioni tra asset."
        )

    if errors:
        st.warning("\\n".join(errors))



# ============================================================
# V4 — OTTIMIZZATORE AUTOMATICO + WALK-FORWARD
# ============================================================

OPT_THRESHOLDS = [65, 70, 75, 80]
OPT_ATR_PERIODS = [3, 5, 7, 10, 14, 20]
OPT_STRENGTHS = ["MEDIO+", "BUONO+", "SOLO BUONO", "SOLO FORTE"]
OPT_STOPS = [0.30, 0.40, 0.50, 0.60, 0.75, 1.00]
OPT_COVERAGE = 0.60


def optimizer_strength_mask(values: pd.Series, label: str) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce")
    if label == "MEDIO+":
        return x >= 0.30
    if label == "BUONO+":
        return x >= 0.50
    if label == "SOLO BUONO":
        return (x >= 0.50) & (x < 0.75)
    if label == "SOLO FORTE":
        return x >= 0.75
    return pd.Series(True, index=values.index)


def build_optimizer_base(
    universe: dict,
    start_date: date,
    end_date: date,
    atr_periods: list[int],
) -> tuple[pd.DataFrame, list]:
    """
    Costruisce una matrice base una sola volta.
    La stagionalità è indipendente da threshold/ATR/stop e viene quindi
    precalcolata per ogni asset/data una sola volta.
    """
    rows = []
    errors = []
    progress = st.progress(0)
    status = st.empty()

    items = list(universe.items())
    total_assets = max(len(items), 1)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    today_ts = pd.Timestamp(date.today())

    for i, (name, ticker) in enumerate(items, start=1):
        status.write(f"Ottimizzatore — preparo {name} ({ticker})…")
        df = download_history(ticker)

        if df.empty:
            errors.append(f"{name} ({ticker}): dati daily non disponibili")
            progress.progress(i / total_assets)
            continue

        # Lookup stagionale mese/giorno.
        seasonal_lookup = {}
        valid_ret = df.dropna(subset=["Return"])
        for (month, day), grp in valid_ret.groupby(
            [valid_ret.index.month, valid_ret.index.day]
        ):
            seasonal_lookup[(int(month), int(day))] = (
                grp.index.year.to_numpy(dtype=int),
                grp["Return"].to_numpy(dtype=float),
            )

        # ATR(T-1) per tutti i periodi della griglia.
        prev_close = df["Close"].shift(1)
        tr = pd.concat(
            [
                df["High"] - df["Low"],
                (df["High"] - prev_close).abs(),
                (df["Low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr_maps = {}
        for p in atr_periods:
            atr_maps[int(p)] = tr.rolling(
                int(p), min_periods=int(p)
            ).mean().shift(1)

        trade_index = df.index[
            (df.index >= start_ts)
            & (df.index <= end_ts)
            & (df.index < today_ts)
        ]

        for dt in trade_index:
            d = dt.date()
            stats = {
                w: fast_window_stats(seasonal_lookup, d, w)
                for w in WINDOWS
            }

            avg_returns = [
                stats[10]["avg"],
                stats[15]["avg"],
                stats[20]["avg"],
            ]
            if all(not pd.isna(x) for x in avg_returns):
                target_pct = abs(float(np.median(avg_returns)))
            else:
                target_pct = np.nan

            row = {
                "Date": d,
                "Asset": name,
                "Ticker": ticker,
                "Open": float(df.at[dt, "Open"]) if not pd.isna(df.at[dt, "Open"]) else np.nan,
                "High": float(df.at[dt, "High"]) if not pd.isna(df.at[dt, "High"]) else np.nan,
                "Low": float(df.at[dt, "Low"]) if not pd.isna(df.at[dt, "Low"]) else np.nan,
                "Close": float(df.at[dt, "Close"]) if not pd.isna(df.at[dt, "Close"]) else np.nan,
                "Prev Close": float(prev_close.loc[dt]) if not pd.isna(prev_close.loc[dt]) else np.nan,
                "Target %": target_pct,
                "L10": stats[10]["long_prob"],
                "L15": stats[15]["long_prob"],
                "L20": stats[20]["long_prob"],
                "S10": stats[10]["short_prob"],
                "S15": stats[15]["short_prob"],
                "S20": stats[20]["short_prob"],
                "N10": stats[10]["n"],
                "N15": stats[15]["n"],
                "N20": stats[20]["n"],
            }

            for p in atr_periods:
                v = atr_maps[int(p)].loc[dt]
                row[f"ATR_{int(p)}"] = float(v) if not pd.isna(v) else np.nan

            rows.append(row)

        progress.progress(i / total_assets)

    status.empty()
    progress.empty()

    base = pd.DataFrame(rows)
    if not base.empty:
        base = base.sort_values(["Date", "Asset"]).reset_index(drop=True)
    return base, errors


def optimizer_select_daily_trades(
    base: pd.DataFrame,
    threshold_pct: int,
    atr_period: int,
    strength: str,
) -> pd.DataFrame:
    """
    Applica:
    - copertura minima 60% fissa
    - threshold stagionale
    - forza movimento
    - ranking ex-ante
    - massimo 1 trade al giorno
    """
    if base.empty:
        return pd.DataFrame()

    x = base.copy()

    # Copertura fissa 60% sulle tre finestre.
    coverage_mask = (
        (x["N10"] / 10 >= OPT_COVERAGE)
        & (x["N15"] / 15 >= OPT_COVERAGE)
        & (x["N20"] / 20 >= OPT_COVERAGE)
    )
    x = x[coverage_mask].copy()
    if x.empty:
        return x

    th = float(threshold_pct) / 100.0

    long_ok = (
        (x["L10"] >= th)
        & (x["L15"] >= th)
        & (x["L20"] >= th)
    )
    short_ok = (
        (x["S10"] >= th)
        & (x["S15"] >= th)
        & (x["S20"] >= th)
    )

    x["Bias"] = np.where(
        long_ok & ~short_ok,
        "LONG",
        np.where(short_ok & ~long_ok, "SHORT", "—"),
    )
    x = x[x["Bias"].isin(["LONG", "SHORT"])].copy()
    if x.empty:
        return x

    x["Score"] = np.where(
        x["Bias"] == "LONG",
        x[["L10", "L15", "L20"]].mean(axis=1),
        x[["S10", "S15", "S20"]].mean(axis=1),
    )

    atr_col = f"ATR_{int(atr_period)}"
    x["ATR pts"] = pd.to_numeric(x[atr_col], errors="coerce")
    x["ATR %"] = x["ATR pts"] / x["Prev Close"]
    x["Target/ATR"] = x["Target %"] / x["ATR %"]
    x["Target pts"] = x["Target %"] * x["Prev Close"]

    x = x[
        optimizer_strength_mask(x["Target/ATR"], strength)
        & x["ATR pts"].notna()
        & (x["ATR pts"] > 0)
        & x["Target pts"].notna()
    ].copy()
    if x.empty:
        return x

    # Ranking noto prima dell'entry.
    daily_counts = x.groupby("Date").size()
    x["Candidati giorno"] = x["Date"].map(daily_counts)

    x = x.sort_values(
        ["Date", "Target/ATR", "Score", "Asset"],
        ascending=[True, False, False, True],
    )
    x["Rank giorno"] = x.groupby("Date").cumcount() + 1
    x = x[x["Rank giorno"] == 1].copy()

    x["Threshold"] = int(threshold_pct)
    x["ATR period"] = int(atr_period)
    x["Forza"] = strength

    return x.reset_index(drop=True)


def optimizer_evaluate_stop(
    selected: pd.DataFrame,
    stop_atr: float,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """
    Valuta il trade su OHLC daily.

    Per l'ottimizzatore i casi in cui Target e Stop risultano entrambi
    toccati nella stessa seduta sono sempre NO DATI. Questo evita migliaia
    di download intraday e, soprattutto, non inventa l'ordine degli eventi.
    La configurazione finale va poi verificata col backtest manuale.
    """
    if selected is None or selected.empty:
        return pd.DataFrame()

    x = selected.copy()

    if start_date is not None:
        x = x[x["Date"] >= start_date].copy()
    if end_date is not None:
        x = x[x["Date"] <= end_date].copy()
    if x.empty:
        return x

    sl = float(stop_atr) * x["ATR pts"]
    long_mask = x["Bias"] == "LONG"

    target_level = np.where(
        long_mask,
        x["Open"] + x["Target pts"],
        x["Open"] - x["Target pts"],
    )
    stop_level = np.where(
        long_mask,
        x["Open"] - sl,
        x["Open"] + sl,
    )

    hit_target = np.where(
        long_mask,
        x["High"] >= target_level,
        x["Low"] <= target_level,
    )
    hit_stop = np.where(
        long_mask,
        x["Low"] <= stop_level,
        x["High"] >= stop_level,
    )

    both = hit_target & hit_stop
    target_only = hit_target & ~hit_stop
    stop_only = hit_stop & ~hit_target
    neither = ~hit_target & ~hit_stop

    r = np.full(len(x), np.nan, dtype=float)
    r[target_only] = (
        x.loc[target_only, "Target pts"].to_numpy(dtype=float)
        / sl.loc[target_only].to_numpy(dtype=float)
    )
    r[stop_only] = -1.0

    close_r = np.where(
        long_mask,
        (x["Close"] - x["Open"]) / sl,
        (x["Open"] - x["Close"]) / sl,
    )
    r[neither] = close_r[neither]

    outcome = np.full(len(x), "NO DATI", dtype=object)
    outcome[target_only] = "WIN"
    outcome[stop_only] = "LOSS"
    outcome[neither & (r > 0)] = "WIN"
    outcome[neither & (r < 0)] = "LOSS"
    outcome[neither & (r == 0)] = "FLAT"
    outcome[both] = "NO DATI"

    exit_reason = np.full(len(x), "NO DATI", dtype=object)
    exit_reason[target_only] = "TARGET"
    exit_reason[stop_only] = "STOP"
    exit_reason[neither] = "CLOSE"

    x["SL pts"] = sl
    x["R"] = r
    x["Outcome"] = outcome
    x["Exit reason"] = exit_reason
    x["Stop ATR"] = float(stop_atr)

    return x


def optimizer_metrics(trades: pd.DataFrame) -> dict:
    empty = {
        "signals": 0,
        "valid": 0,
        "no_data": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": np.nan,
        "profit_factor": np.nan,
        "expectancy_r": np.nan,
        "total_r": np.nan,
        "max_dd_r": np.nan,
        "positive_year_ratio": np.nan,
        "positive_years": 0,
        "years": 0,
        "median_year_r": np.nan,
        "worst_year_r": np.nan,
        "best_year_r": np.nan,
        "year_std_r": np.nan,
    }

    if trades is None or trades.empty:
        return empty.copy()

    valid = trades.dropna(subset=["R"]).copy()
    no_data = int(trades["R"].isna().sum())

    if valid.empty:
        out = empty.copy()
        out["signals"] = len(trades)
        out["no_data"] = no_data
        return out

    valid = valid.sort_values(["Date", "Asset"]).copy()
    wins = int((valid["R"] > 0).sum())
    losses = int((valid["R"] < 0).sum())
    decisive = wins + losses

    gross_profit = float(valid.loc[valid["R"] > 0, "R"].sum())
    gross_loss = abs(float(valid.loc[valid["R"] < 0, "R"].sum()))
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf if gross_profit > 0 else np.nan

    equity = valid["R"].cumsum()
    peak = equity.cummax().clip(lower=0)
    dd = equity - peak
    max_dd = abs(float(dd.min())) if len(dd) else np.nan

    yearly = valid.copy()
    yearly["Year"] = pd.to_datetime(yearly["Date"]).dt.year
    yearly_r = yearly.groupby("Year")["R"].sum()
    years = int(len(yearly_r))
    positive_years = int((yearly_r > 0).sum())

    return {
        "signals": len(trades),
        "valid": len(valid),
        "no_data": no_data,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / decisive if decisive > 0 else np.nan,
        "profit_factor": pf,
        "expectancy_r": float(valid["R"].mean()),
        "total_r": float(valid["R"].sum()),
        "max_dd_r": max_dd,
        "positive_year_ratio": positive_years / years if years > 0 else np.nan,
        "positive_years": positive_years,
        "years": years,
        "median_year_r": float(yearly_r.median()) if years > 0 else np.nan,
        "worst_year_r": float(yearly_r.min()) if years > 0 else np.nan,
        "best_year_r": float(yearly_r.max()) if years > 0 else np.nan,
        "year_std_r": float(yearly_r.std(ddof=0)) if years > 0 else np.nan,
    }



def optimizer_metric_row(
    selected: pd.DataFrame,
    stop_atr: float,
    threshold: int,
    atr_period: int,
    strength: str,
    start_date: date,
    end_date: date,
) -> tuple[dict, pd.DataFrame]:
    trades = optimizer_evaluate_stop(
        selected=selected,
        stop_atr=stop_atr,
        start_date=start_date,
        end_date=end_date,
    )
    m = optimizer_metrics(trades)

    row = {
        "Filtro %": int(threshold),
        "ATR": int(atr_period),
        "Forza": strength,
        "Stop ATR": float(stop_atr),
        "Trade": m["valid"],
        "NO DATI": m["no_data"],
        "Win Rate": m["win_rate"],
        "Profit Factor": m["profit_factor"],
        "Expectancy R": m["expectancy_r"],
        "Totale R": m["total_r"],
        "Max DD R": m["max_dd_r"],
        "Anni +": m["positive_years"],
        "Anni": m["years"],
        "% anni +": m["positive_year_ratio"],
        "Mediana anno R": m["median_year_r"],
        "Peggior anno R": m["worst_year_r"],
        "Miglior anno R": m["best_year_r"],
        "Dispersione anni R": m["year_std_r"],
        "R/DD": (
            m["total_r"] / m["max_dd_r"]
            if not pd.isna(m["total_r"])
            and not pd.isna(m["max_dd_r"])
            and m["max_dd_r"] > 0
            else np.nan
        ),
    }
    return row, trades



def add_plateau_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Misura quanto una configurazione è circondata da configurazioni vicine
    che restano profittevoli.

    Vicino = un solo passo di griglia in UNA sola dimensione:
    filtro, ATR, Forza oppure Stop.
    """
    if df is None or df.empty:
        return df.copy()

    out = df.copy().reset_index(drop=True)

    th_vals = list(OPT_THRESHOLDS)
    atr_vals = list(OPT_ATR_PERIODS)
    strength_vals = list(OPT_STRENGTHS)
    stop_vals = [round(float(v), 2) for v in OPT_STOPS]

    key_to_idx = {}
    for i, row in out.iterrows():
        key = (
            int(row["Filtro %"]),
            int(row["ATR"]),
            str(row["Forza"]),
            round(float(row["Stop ATR"]), 2),
        )
        key_to_idx[key] = i

    n_list = []
    pos_list = []
    med_exp_list = []
    med_pf_list = []
    med_worst_list = []

    for _, row in out.iterrows():
        key = (
            int(row["Filtro %"]),
            int(row["ATR"]),
            str(row["Forza"]),
            round(float(row["Stop ATR"]), 2),
        )

        positions = [
            th_vals.index(key[0]),
            atr_vals.index(key[1]),
            strength_vals.index(key[2]),
            stop_vals.index(key[3]),
        ]
        grids = [th_vals, atr_vals, strength_vals, stop_vals]

        neighbor_indices = []
        for dim in range(4):
            for delta in (-1, 1):
                p = positions[dim] + delta
                if 0 <= p < len(grids[dim]):
                    nk = list(key)
                    nk[dim] = grids[dim][p]
                    nk = tuple(nk)
                    if nk in key_to_idx:
                        neighbor_indices.append(key_to_idx[nk])

        if not neighbor_indices:
            n_list.append(0)
            pos_list.append(np.nan)
            med_exp_list.append(np.nan)
            med_pf_list.append(np.nan)
            med_worst_list.append(np.nan)
            continue

        ndf = out.loc[neighbor_indices]
        positive = (
            (pd.to_numeric(ndf["Expectancy R"], errors="coerce") > 0)
            & (pd.to_numeric(ndf["Profit Factor"], errors="coerce") > 1)
        )

        n_list.append(len(ndf))
        pos_list.append(float(positive.mean()))
        med_exp_list.append(
            float(pd.to_numeric(ndf["Expectancy R"], errors="coerce").median())
        )
        med_pf_list.append(
            float(pd.to_numeric(ndf["Profit Factor"], errors="coerce").replace([np.inf, -np.inf], np.nan).median())
        )
        med_worst_list.append(
            float(pd.to_numeric(ndf["Peggior anno R"], errors="coerce").median())
        )

    out["Vicini"] = n_list
    out["% vicini positivi"] = pos_list
    out["Exp vicini mediana"] = med_exp_list
    out["PF vicini mediana"] = med_pf_list
    out["Peggior anno vicini mediana"] = med_worst_list
    return out


def add_robust_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score 0-100 orientato alla robustezza, non al massimo rendimento.

    Pesi:
    20% anni positivi
    15% mediana annuale
    15% peggior anno
    15% quota vicini positivi
    10% expectancy mediana dei vicini
    10% Profit Factor
     5% numero trade
     5% drawdown basso
     5% dispersione annuale bassa
    """
    if df is None or df.empty:
        return df.copy()

    out = df.copy()

    def pct_rank(series, higher_is_better=True, cap=None):
        s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if cap is not None:
            s = s.clip(lower=cap[0], upper=cap[1])
        if s.notna().sum() == 0:
            return pd.Series(0.0, index=s.index)
        ranked = s.rank(
            pct=True,
            method="average",
            ascending=True if higher_is_better else False,
        )
        return ranked.fillna(0.0)

    components = {
        "years_pos": pct_rank(out["% anni +"], True),
        "median_year": pct_rank(out["Mediana anno R"], True),
        "worst_year": pct_rank(out["Peggior anno R"], True),
        "neighbor_pos": pct_rank(out["% vicini positivi"], True),
        "neighbor_exp": pct_rank(out["Exp vicini mediana"], True),
        "pf": pct_rank(out["Profit Factor"], True, cap=(0, 3)),
        "trades": pct_rank(out["Trade"], True),
        "dd": pct_rank(out["Max DD R"], False),
        "dispersion": pct_rank(out["Dispersione anni R"], False),
    }

    out["Robust Score"] = 100.0 * (
        0.20 * components["years_pos"]
        + 0.15 * components["median_year"]
        + 0.15 * components["worst_year"]
        + 0.15 * components["neighbor_pos"]
        + 0.10 * components["neighbor_exp"]
        + 0.10 * components["pf"]
        + 0.05 * components["trades"]
        + 0.05 * components["dd"]
        + 0.05 * components["dispersion"]
    )

    return out


def run_optimizer_walkforward(
    universe: dict,
    start_date: date,
    end_date: date,
    train_years: int,
    min_train_trades: int,
    min_train_pf: float,
    min_positive_year_ratio: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list]:
    """
    1) Precalcola i candidati per 96 combinazioni:
       threshold × ATR × forza.
    2) Applica i 6 stop => 576 configurazioni.
    3) Mostra classifica full-period SOLO esplorativa.
    4) Walk-forward rolling: N anni train -> anno successivo OOS.
    """
    base, errors = build_optimizer_base(
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        atr_periods=OPT_ATR_PERIODS,
    )
    if base.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), errors

    status = st.empty()
    progress = st.progress(0)

    # 96 selezioni giornaliere, riusate per tutti gli stop e tutti i fold.
    selected_cache = {}
    signal_configs = [
        (th, atr, strength)
        for th in OPT_THRESHOLDS
        for atr in OPT_ATR_PERIODS
        for strength in OPT_STRENGTHS
    ]

    for i, (th, atr, strength) in enumerate(signal_configs, start=1):
        status.write(
            f"Ottimizzatore — segnali {i}/{len(signal_configs)} "
            f"(Filtro {th} · ATR{atr} · {strength})"
        )
        selected_cache[(th, atr, strength)] = optimizer_select_daily_trades(
            base=base,
            threshold_pct=th,
            atr_period=atr,
            strength=strength,
        )
        progress.progress(0.25 * i / len(signal_configs))

    # Classifica full-period.
    full_rows = []
    total_full = len(signal_configs) * len(OPT_STOPS)
    count = 0
    for th, atr, strength in signal_configs:
        selected = selected_cache[(th, atr, strength)]
        for stop in OPT_STOPS:
            count += 1
            row, _ = optimizer_metric_row(
                selected=selected,
                stop_atr=stop,
                threshold=th,
                atr_period=atr,
                strength=strength,
                start_date=start_date,
                end_date=end_date,
            )
            full_rows.append(row)
            if count % 20 == 0 or count == total_full:
                status.write(
                    f"Ottimizzatore — classifica full-period {count}/{total_full}"
                )
                progress.progress(0.25 + 0.25 * count / total_full)

    full_df = pd.DataFrame(full_rows)
    full_df = add_plateau_metrics(full_df)
    full_df = add_robust_score(full_df)

    # Walk-forward rolling per anno.
    start_year = start_date.year
    end_year = end_date.year
    test_years = list(range(start_year + int(train_years), end_year + 1))

    fold_rows = []
    oos_trade_frames = []
    chosen_rows = []

    total_folds = max(len(test_years), 1)

    for fold_i, test_year in enumerate(test_years, start=1):
        train_start_year = test_year - int(train_years)
        train_start = max(start_date, date(train_start_year, 1, 1))
        train_end = min(end_date, date(test_year - 1, 12, 31))
        test_start = max(start_date, date(test_year, 1, 1))
        test_end = min(end_date, date(test_year, 12, 31))

        if train_start > train_end or test_start > test_end:
            continue

        status.write(
            f"Walk-forward {fold_i}/{total_folds}: "
            f"train {train_start.year}-{train_end.year} → test {test_year}"
        )

        train_candidates = []

        for th, atr, strength in signal_configs:
            selected = selected_cache[(th, atr, strength)]
            for stop in OPT_STOPS:
                row, _ = optimizer_metric_row(
                    selected=selected,
                    stop_atr=stop,
                    threshold=th,
                    atr_period=atr,
                    strength=strength,
                    start_date=train_start,
                    end_date=train_end,
                )
                train_candidates.append(row)

        train_df = pd.DataFrame(train_candidates)
        train_df = add_plateau_metrics(train_df)
        train_df = add_robust_score(train_df)

        eligible = train_df[
            (train_df["Trade"] >= int(min_train_trades))
            & (train_df["Profit Factor"] >= float(min_train_pf))
            & (train_df["Expectancy R"] > 0)
            & (train_df["% anni +"] >= float(min_positive_year_ratio))
            & (train_df["Vicini"] >= 3)
        ].copy()

        selection_rule = "ROBUST: criteri completi + plateau"

        # Fallback trasparente: resta robust-oriented, ma allenta i filtri.
        if eligible.empty:
            eligible = train_df[
                (train_df["Trade"] >= int(min_train_trades))
                & (train_df["Expectancy R"] > 0)
                & (train_df["Vicini"] >= 3)
            ].copy()
            selection_rule = "ROBUST fallback: trade minimi + expectancy positiva"

        if eligible.empty:
            eligible = train_df[
                (train_df["Trade"] >= max(10, int(min_train_trades // 2)))
                & (train_df["Vicini"] >= 2)
            ].copy()
            selection_rule = "ROBUST fallback: campione minimo ridotto"

        if eligible.empty:
            continue

        # La scelta NON è più il massimo di expectancy.
        # Prima Robust Score, poi stabilità annuale e solo dopo performance.
        eligible = eligible.sort_values(
            [
                "Robust Score",
                "% anni +",
                "Peggior anno R",
                "Mediana anno R",
                "% vicini positivi",
                "Profit Factor",
                "Max DD R",
                "Trade",
            ],
            ascending=[False, False, False, False, False, False, True, False],
        )

        best = eligible.iloc[0]
        key = (
            int(best["Filtro %"]),
            int(best["ATR"]),
            str(best["Forza"]),
        )
        stop = float(best["Stop ATR"])
        selected = selected_cache[key]

        test_row, test_trades = optimizer_metric_row(
            selected=selected,
            stop_atr=stop,
            threshold=key[0],
            atr_period=key[1],
            strength=key[2],
            start_date=test_start,
            end_date=test_end,
        )

        if not test_trades.empty:
            test_trades = test_trades.copy()
            test_trades["Test Year"] = test_year
            oos_trade_frames.append(test_trades)

        fold_rows.append({
            "Train": f"{train_start.year}-{train_end.year}",
            "Test": int(test_year),
            "Filtro %": key[0],
            "ATR": key[1],
            "Forza": key[2],
            "Stop ATR": stop,
            "Regola selezione": selection_rule,
            "Robust Score": best["Robust Score"],
            "Train Trade": int(best["Trade"]),
            "Train PF": best["Profit Factor"],
            "Train Exp R": best["Expectancy R"],
            "Train DD R": best["Max DD R"],
            "Train % anni +": best["% anni +"],
            "Train Mediana anno R": best["Mediana anno R"],
            "Train Peggior anno R": best["Peggior anno R"],
            "Train Dispersione anni R": best["Dispersione anni R"],
            "Train % vicini positivi": best["% vicini positivi"],
            "Train Exp vicini mediana": best["Exp vicini mediana"],
            "Test Trade": int(test_row["Trade"]),
            "Test NO DATI": int(test_row["NO DATI"]),
            "Test Win Rate": test_row["Win Rate"],
            "Test PF": test_row["Profit Factor"],
            "Test Exp R": test_row["Expectancy R"],
            "Test Tot R": test_row["Totale R"],
            "Test DD R": test_row["Max DD R"],
        })

        chosen_rows.append({
            "Filtro %": key[0],
            "ATR": key[1],
            "Forza": key[2],
            "Stop ATR": stop,
            "Robust Score": best["Robust Score"],
            "% vicini positivi": best["% vicini positivi"],
            "Mediana anno R": best["Mediana anno R"],
            "Peggior anno R": best["Peggior anno R"],
        })

        progress.progress(0.50 + 0.50 * fold_i / total_folds)

    status.empty()
    progress.empty()

    folds_df = pd.DataFrame(fold_rows)
    chosen_df = pd.DataFrame(chosen_rows)

    if oos_trade_frames:
        oos_trades = pd.concat(oos_trade_frames, ignore_index=True)
        oos_trades = oos_trades.sort_values(["Date", "Asset"]).reset_index(drop=True)
    else:
        oos_trades = pd.DataFrame()

    return full_df, folds_df, chosen_df, oos_trades, errors



def build_optimizer_excel_report(
    full_df: pd.DataFrame,
    folds_df: pd.DataFrame,
    chosen_df: pd.DataFrame,
    oos_trades: pd.DataFrame,
    settings: dict,
) -> bytes:
    """Crea un unico report Excel con tutti i dati dell'ottimizzazione."""
    output = io.BytesIO()
    oos = optimizer_metrics(oos_trades)

    summary_df = pd.DataFrame(
        [
            ["Trade OOS", oos["valid"]],
            ["NO DATI OOS", oos["no_data"]],
            ["WIN OOS", oos["wins"]],
            ["LOSS OOS", oos["losses"]],
            ["Win Rate OOS", oos["win_rate"]],
            ["Profit Factor OOS", oos["profit_factor"]],
            ["Expectancy OOS (R)", oos["expectancy_r"]],
            ["Totale OOS (R)", oos["total_r"]],
            ["Max Drawdown OOS (R)", oos["max_dd_r"]],
            ["Anni OOS positivi", oos["positive_years"]],
            ["Anni OOS totali", oos["years"]],
            ["% anni OOS positivi", oos["positive_year_ratio"]],
        ],
        columns=["Metrica", "Valore"],
    )

    settings_df = pd.DataFrame(
        [{"Parametro": str(k), "Valore": str(v)} for k, v in settings.items()]
    )

    if not chosen_df.empty:
        stability_rows = []
        for col in ["Filtro %", "ATR", "Forza", "Stop ATR"]:
            counts = chosen_df[col].value_counts(dropna=False)
            for value, count in counts.items():
                stability_rows.append(
                    {
                        "Parametro": col,
                        "Valore": value,
                        "Fold": int(count),
                        "% fold": count / len(chosen_df),
                    }
                )
        stability_df = pd.DataFrame(stability_rows)
    else:
        stability_df = pd.DataFrame(
            columns=["Parametro", "Valore", "Fold", "% fold"]
        )

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        datasets = [
            ("Riepilogo_OOS", summary_df),
            ("Impostazioni", settings_df),
            ("Full_576", full_df),
            ("Walk_Forward", folds_df),
            ("Parametri_Scelti", chosen_df),
            ("Stabilita", stability_df),
            ("Trade_OOS", oos_trades),
        ]

        for sheet_name, df_sheet in datasets:
            df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)

        workbook = writer.book
        header_fmt = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#1F4E78",
                "border": 1,
                "align": "center",
                "valign": "vcenter",
            }
        )
        pct_fmt = workbook.add_format({"num_format": "0.0%"})
        num2_fmt = workbook.add_format({"num_format": "0.00"})
        num3_fmt = workbook.add_format({"num_format": "0.000"})
        date_fmt = workbook.add_format({"num_format": "yyyy-mm-dd"})

        for sheet_name, df_sheet in datasets:
            ws = writer.sheets[sheet_name]
            ws.freeze_panes(1, 0)

            if len(df_sheet.columns) > 0:
                ws.autofilter(
                    0,
                    0,
                    max(len(df_sheet), 1),
                    len(df_sheet.columns) - 1,
                )

            for c, col in enumerate(df_sheet.columns):
                ws.write(0, c, col, header_fmt)
                sample = (
                    [str(v) for v in df_sheet[col].head(250).tolist()]
                    if len(df_sheet)
                    else []
                )
                max_len = max([len(str(col))] + [len(str(v)) for v in sample])
                width = min(max(max_len + 2, 11), 28)

                col_name = str(col)
                cell_fmt = None
                if (
                    "Win Rate" in col_name
                    or "% anni" in col_name
                    or "% fold" in col_name
                    or "% vicini" in col_name
                ):
                    cell_fmt = pct_fmt
                    width = max(width, 14)
                elif col_name in {
                    "Expectancy R",
                    "Train Exp R",
                    "Test Exp R",
                }:
                    cell_fmt = num3_fmt
                    width = max(width, 14)
                elif any(
                    key in col_name
                    for key in [
                        "Profit Factor",
                        "Totale R",
                        "Max DD",
                        "R/DD",
                        "Stop ATR",
                        "Train PF",
                        "Test PF",
                        "Train DD",
                        "Test DD",
                        "Mediana anno",
                        "Peggior anno",
                        "Miglior anno",
                        "Dispersione anni",
                        "Exp vicini",
                        "PF vicini",
                        "Robust Score",
                    ]
                ):
                    cell_fmt = num2_fmt
                    width = max(width, 14)
                elif col_name == "Date":
                    cell_fmt = date_fmt
                    width = max(width, 12)

                ws.set_column(c, c, width, cell_fmt)

        # Formattazione specifica del riepilogo.
        ws = writer.sheets["Riepilogo_OOS"]
        for row_idx, metric in enumerate(summary_df["Metrica"], start=1):
            if metric in {"Win Rate OOS", "% anni OOS positivi"}:
                ws.write_number(row_idx, 1, float(summary_df.iloc[row_idx - 1, 1]), pct_fmt)
            elif metric == "Expectancy OOS (R)" and pd.notna(summary_df.iloc[row_idx - 1, 1]):
                ws.write_number(row_idx, 1, float(summary_df.iloc[row_idx - 1, 1]), num3_fmt)
            elif metric in {
                "Profit Factor OOS",
                "Totale OOS (R)",
                "Max Drawdown OOS (R)",
            } and pd.notna(summary_df.iloc[row_idx - 1, 1]):
                value = summary_df.iloc[row_idx - 1, 1]
                if np.isinf(value):
                    ws.write(row_idx, 1, "∞")
                else:
                    ws.write_number(row_idx, 1, float(value), num2_fmt)

    output.seek(0)
    return output.getvalue()


def render_optimizer_results(
    full_df: pd.DataFrame,
    folds_df: pd.DataFrame,
    chosen_df: pd.DataFrame,
    oos_trades: pd.DataFrame,
    errors: list,
    settings: dict,
):
    st.header("⚙️ Ottimizzatore automatico + Walk-Forward")

    st.caption(
        "Griglia fissa: 4 filtri stagionali × 6 ATR × 4 classi Forza × "
        "6 Stop = **576 configurazioni**. Regole fisse: 1 trade/giorno, "
        "copertura campione 60%, LONG+SHORT, regime SPX OFF."
    )

    if full_df.empty:
        st.warning("L'ottimizzatore non ha prodotto risultati.")
        if errors:
            st.warning("\\n".join(errors))
        return

    # ---------------- Full period, solo esplorativo ----------------
    st.subheader("Top configurazioni full-period — esplorativo")
    st.warning(
        "Questa tabella usa tutto il periodo ed è IN-SAMPLE. "
        "Ora è ordinata per Robust Score/plateau, non per expectancy massima, "
        "ma non va comunque usata da sola per scegliere la strategia."
    )

    top = full_df[
        (full_df["Trade"] >= 50)
        & full_df["Expectancy R"].notna()
    ].copy()

    if top.empty:
        top = full_df.copy()

    top = top.sort_values(
        [
            "Robust Score",
            "% anni +",
            "Peggior anno R",
            "% vicini positivi",
            "Profit Factor",
            "Max DD R",
            "Trade",
        ],
        ascending=[False, False, False, False, False, True, False],
    ).head(20)

    top_disp = top.copy()
    top_disp["Win Rate"] = top_disp["Win Rate"].map(
        lambda x: "n/d" if pd.isna(x) else f"{x:.1%}"
    )
    top_disp["% anni +"] = top_disp["% anni +"].map(
        lambda x: "n/d" if pd.isna(x) else f"{x:.0%}"
    )
    if "% vicini positivi" in top_disp.columns:
        top_disp["% vicini positivi"] = top_disp["% vicini positivi"].map(
            lambda x: "n/d" if pd.isna(x) else f"{x:.0%}"
        )
    for c in [
        "Profit Factor", "Expectancy R", "Totale R", "Max DD R", "R/DD",
        "Mediana anno R", "Peggior anno R", "Miglior anno R",
        "Dispersione anni R", "Exp vicini mediana", "PF vicini mediana",
        "Peggior anno vicini mediana", "Robust Score"
    ]:
        if c not in top_disp.columns:
            continue
        top_disp[c] = top_disp[c].map(
            lambda x: "n/d" if pd.isna(x) else ("∞" if np.isinf(x) else f"{x:.2f}")
        )
    top_disp["Stop ATR"] = top_disp["Stop ATR"].map(lambda x: f"{x:.2f}")
    st.dataframe(top_disp, width="stretch", hide_index=True)

    # ---------------- Walk-forward ----------------
    st.subheader("Walk-Forward — risultati fuori campione")

    if folds_df.empty:
        st.warning("Nessun fold Walk-Forward disponibile con il periodo selezionato.")
        return

    fold_disp = folds_df.copy()
    for c in [
        "Robust Score", "Train PF", "Train Exp R", "Train DD R",
        "Train Mediana anno R", "Train Peggior anno R",
        "Train Dispersione anni R", "Train Exp vicini mediana",
        "Test PF", "Test Exp R", "Test Tot R", "Test DD R"
    ]:
        if c in fold_disp.columns:
            fold_disp[c] = fold_disp[c].map(
                lambda x: "n/d" if pd.isna(x) else ("∞" if np.isinf(x) else f"{x:.2f}")
            )
    for c in ["Train % anni +", "Train % vicini positivi", "Test Win Rate"]:
        fold_disp[c] = fold_disp[c].map(
            lambda x: "n/d" if pd.isna(x) else f"{x:.1%}"
        )
    fold_disp["Stop ATR"] = fold_disp["Stop ATR"].map(lambda x: f"{x:.2f}")
    st.dataframe(fold_disp, width="stretch", hide_index=True)

    # ---------------- OOS aggregate ----------------
    oos = optimizer_metrics(oos_trades)
    positive_test_years = 0
    total_test_years = 0
    if not oos_trades.empty:
        tmp = oos_trades.dropna(subset=["R"]).copy()
        if not tmp.empty:
            tmp["Year"] = pd.to_datetime(tmp["Date"]).dt.year
            yr = tmp.groupby("Year")["R"].sum()
            positive_test_years = int((yr > 0).sum())
            total_test_years = int(len(yr))

    st.subheader("Aggregato OUT-OF-SAMPLE")
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Trade OOS", oos["valid"])
    c2.metric("NO DATI", oos["no_data"])
    c3.metric("Win Rate", "n/d" if pd.isna(oos["win_rate"]) else f"{oos['win_rate']:.1%}")
    c4.metric("Profit Factor", format_metric(oos["profit_factor"]))
    c5.metric("Expectancy", "n/d" if pd.isna(oos["expectancy_r"]) else f"{oos['expectancy_r']:+.3f} R")
    c6.metric("Totale", "n/d" if pd.isna(oos["total_r"]) else f"{oos['total_r']:+.2f} R")
    c7.metric("Max DD", "n/d" if pd.isna(oos["max_dd_r"]) else f"{oos['max_dd_r']:.2f} R")

    if total_test_years > 0:
        st.caption(
            f"Anni OOS positivi: **{positive_test_years}/{total_test_years} "
            f"({positive_test_years / total_test_years:.0%})**."
        )

    # Equity OOS
    valid_oos = oos_trades.dropna(subset=["R"]).copy() if not oos_trades.empty else pd.DataFrame()
    if not valid_oos.empty:
        valid_oos = valid_oos.sort_values(["Date", "Asset"])
        daily = valid_oos.groupby("Date", as_index=False)["R"].sum()
        daily["Equity OOS R"] = daily["R"].cumsum()
        st.subheader("Equity OUT-OF-SAMPLE in R")
        st.line_chart(daily.set_index("Date")["Equity OOS R"])

    # Stabilità parametri scelti
    if not chosen_df.empty:
        st.subheader("Stabilità dei parametri scelti nei fold")
        stability = []
        for col in ["Filtro %", "ATR", "Forza", "Stop ATR"]:
            counts = chosen_df[col].value_counts(dropna=False)
            for value, count in counts.items():
                stability.append({
                    "Parametro": col,
                    "Valore": value,
                    "Fold": int(count),
                    "% fold": count / len(chosen_df),
                })
        stab = pd.DataFrame(stability)
        stab["% fold"] = stab["% fold"].map(lambda x: f"{x:.0%}")
        st.dataframe(stab, width="stretch", hide_index=True)

    st.info(
        "Interpretazione V4.3: il ranking privilegia robustezza annuale e plateau "
        "di configurazioni vicine, non il massimo di expectancy. La tabella full-period "
        "resta IN-SAMPLE; il dato decisivo continua a essere l'OUT-OF-SAMPLE Walk-Forward. "
        "Se l'OOS non resta positivo, la strategia non è robusta anche se il Robust Score è alto."
    )

    st.subheader("Esporta risultati")
    excel_bytes = build_optimizer_excel_report(
        full_df=full_df,
        folds_df=folds_df,
        chosen_df=chosen_df,
        oos_trades=oos_trades,
        settings=settings,
    )

    start_tag = str(settings.get("Data inizio", "start")).replace("/", "-")
    end_tag = str(settings.get("Data fine", "end")).replace("/", "-")

    st.download_button(
        "📥 Scarica report ottimizzazione Excel",
        data=excel_bytes,
        file_name=f"seasonality_optimizer_{start_tag}_{end_tag}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
        help=(
            "Contiene tutte le 576 configurazioni, i fold Walk-Forward, "
            "i parametri scelti, la stabilità e tutti i trade OUT-OF-SAMPLE."
        ),
    )
    st.caption(
        "Scarica questo file e allegalo in chat: contiene tutti i dati necessari "
        "per analizzare l'ottimizzazione senza screenshot."
    )

    if errors:
        st.warning("\\n".join(errors))


def parse_universe_text(text: str) -> tuple[dict, list]:
    """
    Formati accettati:
    - Nome,Ticker
    - Ticker

    Ignora righe vuote e commenti che iniziano con #.
    Se è presente solo il ticker, il nome visualizzato coincide con il ticker.
    """
    universe = {}
    bad_rows = []

    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue

        if "," in raw:
            parts = [p.strip() for p in raw.split(",", 1)]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                bad_rows.append(raw)
                continue
            name, ticker = parts
        else:
            ticker = raw.strip()
            name = ticker

        # Evita duplicati di ticker mantenendo la prima occorrenza.
        if ticker not in universe.values():
            universe[name] = ticker

    return universe, bad_rows


def decode_uploaded_txt(uploaded_file) -> str:
    raw = uploaded_file.getvalue()
    # UTF-8 con BOM, poi fallback latin-1 per file Windows/legacy.
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


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

    atr_period = st.number_input(
        "ATR periodi per forza movimento",
        min_value=2,
        max_value=50,
        value=5,
        step=1,
        help="Default 5: più coerente con una strategia su singola seduta. "
             "Serve solo per valutare la dimensione del target rispetto alla volatilità recente."
    )

    run = st.button("Analizza settimana", type="primary", width="stretch")

    st.divider()
    st.subheader("Backtest manuale")

    bt_start = st.date_input(
        "Data inizio backtest",
        value=date(date.today().year, 1, 1),
        key="bt_start",
    )
    bt_end = st.date_input(
        "Data fine backtest",
        value=date.today(),
        key="bt_end",
        help="La seduta odierna viene esclusa finché non è completa."
    )
    bt_threshold_pct = st.slider(
        "Filtro stagionale backtest",
        min_value=50,
        max_value=95,
        value=70,
        step=1,
        key="bt_threshold",
    )
    bt_atr_period = st.number_input(
        "ATR periodi backtest",
        min_value=2,
        max_value=50,
        value=5,
        step=1,
        key="bt_atr_period",
    )
    bt_strength = st.selectbox(
        "Forza minima",
        ["TUTTI", "MEDIO+", "BUONO+", "SOLO BUONO", "SOLO FORTE"],
        index=0,
        help=(
            "SOLO BUONO = Target/ATR >= 0,50 e < 0,75. "
            "SOLO FORTE = Target/ATR >= 0,75."
        ),
    )
    st.caption(
        "Classi Forza: DEBOLE <30% ATR · MEDIO 30–50% · "
        "BUONO 50–75% · FORTE ≥75%."
    )

    bt_stop_atr = st.slider(
        "Stop Loss in multipli ATR",
        min_value=0.25,
        max_value=1.50,
        value=0.50,
        step=0.05,
        help="0,50 = stop pari al 50% dell'ATR selezionato."
    )
    bt_direction = st.selectbox(
        "Direzione",
        ["LONG + SHORT", "SOLO LONG", "SOLO SHORT"],
        index=0,
    )
    bt_coherence = st.checkbox(
        "Richiedi coerenza Bias / rendimento medio",
        value=False,
        help="LONG richiede Mediana 3 rendimenti > 0; SHORT richiede < 0."
    )
    bt_sample_coverage_pct = st.slider(
        "Copertura minima campione",
        min_value=0,
        max_value=70,
        value=0,
        step=5,
        help="Filtro opzionale sulla quota di osservazioni realmente disponibili nelle finestre 10/15/20 anni."
    )

    st.markdown("**Regime S&P 500**")
    bt_spx_mode = st.selectbox(
        "Filtro regime SP500",
        ["OFF", "SOLO SOPRA EMA", "SOLO SOTTO EMA"],
        index=0,
        help=(
            "Vale sia per LONG sia per SHORT. Il regime usa Close SP500 ed EMA "
            "della seduta precedente (T-1), quindi senza look-ahead."
        ),
    )
    bt_spx_ema_period = st.number_input(
        "Periodo EMA SP500", min_value=5, max_value=200, value=21, step=1, key="bt_spx_ema_period"
    )

    run_backtest = st.button("Esegui backtest", type="secondary", width="stretch")
    st.caption(
        "Motore V4.3 robust/plateau: storici, ATR, stagionalità ed EMA SPX "
        "vengono precalcolati e riutilizzati durante il backtest."
    )

    st.divider()
    st.subheader("Ottimizzatore automatico")

    opt_start = st.date_input(
        "Data inizio ottimizzazione",
        value=date(2019, 1, 1),
        key="opt_start",
    )
    opt_end = st.date_input(
        "Data fine ottimizzazione",
        value=date.today(),
        key="opt_end",
        help="La seduta odierna incompleta viene esclusa automaticamente.",
    )
    opt_train_years = st.number_input(
        "Anni training Walk-Forward",
        min_value=2,
        max_value=5,
        value=3,
        step=1,
    )
    opt_min_train_trades = st.number_input(
        "Min trade nel training",
        min_value=10,
        max_value=200,
        value=30,
        step=5,
    )
    opt_min_train_pf = st.number_input(
        "Min Profit Factor training",
        min_value=0.90,
        max_value=2.00,
        value=1.05,
        step=0.05,
        format="%.2f",
    )
    opt_min_positive_years_pct = st.slider(
        "Min % anni positivi training",
        min_value=0,
        max_value=100,
        value=50,
        step=10,
    )

    run_optimizer = st.button(
        "Ottimizza + Walk-Forward",
        type="secondary",
        width="stretch",
    )
    st.caption(
        "Griglia invariata: filtro 65/70/75/80 · ATR 3/5/7/10/14/20 · "
        "MEDIO+/BUONO+/SOLO BUONO/SOLO FORTE · Stop 0.30/0.40/0.50/0.60/0.75/1.00. "
        "La V4.3 seleziona per robustezza annuale + plateau. "
        "Fissi: 1 trade/giorno, copertura 60%, SPX OFF."
    )

    st.divider()
    st.subheader("Universo")

    uploaded_universe = st.file_uploader(
        "Lista asset esterna (.txt) — opzionale",
        type=["txt"],
        help=(
            "Se carichi un file .txt, l'app usa quella lista al posto "
            "dell'universo predefinito. Formati accettati: Nome,Ticker oppure solo Ticker."
        ),
    )

    if uploaded_universe is None:
        st.caption(f"Universo attivo: **predefinito ({len(DEFAULT_UNIVERSE)} asset)**")
        st.text_area(
            "Asset predefiniti",
            value="\n".join(f"{k},{v}" for k, v in DEFAULT_UNIVERSE.items()),
            height=210,
            disabled=True,
        )
    else:
        uploaded_text = decode_uploaded_txt(uploaded_universe)
        uploaded_preview, uploaded_bad_rows = parse_universe_text(uploaded_text)
        st.caption(
            f"Universo attivo: **file {uploaded_universe.name} "
            f"({len(uploaded_preview)} asset validi)**"
        )
        st.text_area(
            "Anteprima file caricato",
            value=uploaded_text,
            height=210,
            disabled=True,
        )
        if uploaded_bad_rows:
            st.warning(
                "Righe non valide nel file: " + " | ".join(uploaded_bad_rows)
            )

    st.caption(
        "DAX e Euro Stoxx 50 sono analizzati sul cash index come proxy "
        "stagionale; gli altri strumenti indicati come Future usano i "
        "continuous futures Yahoo."
    )


st.info(
    "**Metodo Forecaster:** per ogni giornata futura viene usato lo stesso "
    "giorno di calendario nei 10, 15 e 20 anni precedenti. "
    "Se in un determinato anno quella data cade nel weekend o non è una seduta, "
    "quell'anno viene escluso dal campione. Esempio: l'11 agosto viene confrontato "
    "solo con gli 11 agosto che sono stati effettive sedute di borsa."
)

# Se è stato richiesto l'ottimizzatore, usa lo stesso universo selezionato.
if run_optimizer:
    if opt_start > opt_end:
        st.error("La data iniziale dell'ottimizzazione deve precedere la data finale.")
        st.stop()

    if uploaded_universe is None:
        opt_universe = DEFAULT_UNIVERSE.copy()
        opt_bad_rows = []
        opt_universe_source = "predefinito"
    else:
        uploaded_text = decode_uploaded_txt(uploaded_universe)
        opt_universe, opt_bad_rows = parse_universe_text(uploaded_text)
        opt_universe_source = uploaded_universe.name

    if opt_bad_rows:
        st.error("Righe universo non valide: " + " | ".join(opt_bad_rows))
        st.stop()

    if not opt_universe:
        st.error("Nessun asset valido nell'universo selezionato.")
        st.stop()

    st.info(
        f"Ottimizzazione: **{opt_start} → {opt_end}** · "
        f"Training rolling **{int(opt_train_years)} anni** · "
        f"Min trade train **{int(opt_min_train_trades)}** · "
        f"Min PF train **{opt_min_train_pf:.2f}** · "
        f"Min anni positivi **{opt_min_positive_years_pct}%** · "
        f"Universo **{opt_universe_source}**"
    )

    opt_full, opt_folds, opt_chosen, opt_oos, opt_errors = run_optimizer_walkforward(
        universe=opt_universe,
        start_date=opt_start,
        end_date=opt_end,
        train_years=int(opt_train_years),
        min_train_trades=int(opt_min_train_trades),
        min_train_pf=float(opt_min_train_pf),
        min_positive_year_ratio=opt_min_positive_years_pct / 100,
    )

    opt_export_settings = {
        "Data inizio": opt_start,
        "Data fine": opt_end,
        "Training rolling anni": int(opt_train_years),
        "Min trade training": int(opt_min_train_trades),
        "Min Profit Factor training": float(opt_min_train_pf),
        "Min % anni positivi training": f"{opt_min_positive_years_pct}%",
        "Universo": opt_universe_source,
        "Numero asset": len(opt_universe),
        "Max trade/giorno": 1,
        "Copertura minima campione": "60%",
        "Direzione": "LONG + SHORT",
        "Regime SPX": "OFF",
        "Filtri stagionali testati": "65, 70, 75, 80",
        "ATR testati": "3, 5, 7, 10, 14, 20",
        "Forza testate": "MEDIO+, BUONO+, SOLO BUONO, SOLO FORTE",
        "Stop ATR testati": "0.30, 0.40, 0.50, 0.60, 0.75, 1.00",
        "Numero configurazioni": 576,
    }

    render_optimizer_results(
        full_df=opt_full,
        folds_df=opt_folds,
        chosen_df=opt_chosen,
        oos_trades=opt_oos,
        errors=opt_errors,
        settings=opt_export_settings,
    )
    st.stop()

# Se è stato richiesto il backtest, usa lo stesso universo selezionato.
if run_backtest:
    if bt_start > bt_end:
        st.error("La data iniziale del backtest deve essere precedente alla data finale.")
        st.stop()

    if uploaded_universe is None:
        bt_universe = DEFAULT_UNIVERSE.copy()
        bt_bad_rows = []
        bt_universe_source = "predefinito"
    else:
        uploaded_text = decode_uploaded_txt(uploaded_universe)
        bt_universe, bt_bad_rows = parse_universe_text(uploaded_text)
        bt_universe_source = uploaded_universe.name

    if bt_bad_rows:
        st.error("Righe universo non valide: " + " | ".join(bt_bad_rows))
        st.stop()

    if not bt_universe:
        st.error("Nessun asset valido nell'universo selezionato.")
        st.stop()

    st.info(
        f"Backtest: **{bt_start} → {bt_end}** · "
        f"Filtro ≥ **{bt_threshold_pct}%** · ATR **{int(bt_atr_period)}** · "
        f"Forza **{bt_strength}** · Stop **{bt_stop_atr:.2f} ATR** · "
        f"Max trade/giorno **1** · "
        f"Regime SPX **{bt_spx_mode} EMA{int(bt_spx_ema_period) if bt_spx_mode != 'OFF' else ''}** · "
        f"Universo **{bt_universe_source}**"
    )

    bt_df, bt_errors = run_manual_backtest(
        universe=bt_universe,
        start_date=bt_start,
        end_date=bt_end,
        threshold=bt_threshold_pct / 100,
        atr_period=int(bt_atr_period),
        strength_filter=bt_strength,
        stop_atr_mult=float(bt_stop_atr),
        direction_filter=bt_direction,
        require_return_coherence=bool(bt_coherence),
        min_sample_coverage=bt_sample_coverage_pct / 100,
        spx_filter_mode=bt_spx_mode,
        spx_ema_period=int(bt_spx_ema_period),
    )

    render_backtest_results(
        bt=bt_df,
        errors=bt_errors,
        atr_period=int(bt_atr_period),
        stop_atr_mult=float(bt_stop_atr),
        spx_ema_period=int(bt_spx_ema_period),
        spx_filter_mode=bt_spx_mode,
    )
    st.stop()

if not run:
    st.stop()

# Risoluzione universo:
# - nessun file -> universo predefinito
# - file presente -> usa esclusivamente il contenuto del file
if uploaded_universe is None:
    universe = DEFAULT_UNIVERSE.copy()
    bad_rows = []
    universe_source = "predefinito"
else:
    uploaded_text = decode_uploaded_txt(uploaded_universe)
    universe, bad_rows = parse_universe_text(uploaded_text)
    universe_source = uploaded_universe.name

if bad_rows:
    st.error("Righe universo non valide: " + " | ".join(bad_rows))
    st.stop()

if not universe:
    st.error(
        "Il file caricato non contiene asset validi. "
        "Usa una riga per asset nel formato Nome,Ticker oppure Ticker."
    )
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
                atr_period=int(atr_period),
            )
        )

    progress.progress(i / len(universe))

status.empty()
progress.empty()

if not results:
    st.error("Non è stato possibile calcolare alcun risultato.")
    st.stop()

history_cache = {ticker: download_history(ticker) for ticker in universe.values()}
for r in results:
    if r["Bias"] not in ("LONG", "SHORT"):
        r.update({"Open trade":np.nan,"Target level":np.nan,"Stop level":np.nan,"SL 50% ATR pts":np.nan,"Esito":"—"})
        continue
    r.update(evaluate_trade_outcome(ticker=r["Ticker"],df=history_cache.get(r["Ticker"],pd.DataFrame()),target_date=r["Date"],bias=r["Bias"],target_pts=r["Target pts"],atr_pts=r["ATR pts"]))

res = pd.DataFrame([{k: v for k, v in r.items() if k != "_samples"} for r in results])
opps = res[res["Bias"] != "—"].copy()
opps = opps.sort_values(["Date", "Score"], ascending=[True, False])

# Metriche riepilogative
win_count = int((opps["Esito"] == "WIN").sum()) if "Esito" in opps.columns else 0
loss_count = int((opps["Esito"] == "LOSS").sum()) if "Esito" in opps.columns else 0
closed_count = win_count + loss_count
win_rate = (win_count / closed_count) if closed_count > 0 else np.nan

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Sedute analizzate", len(targets))
c2.metric("Asset analizzati", len(universe), help=f"Fonte universo: {universe_source}")
c3.metric("Opportunità valide", len(opps))
c4.metric("WIN", win_count)
c5.metric("LOSS", loss_count)
c6.metric("Win Rate", "n/d" if pd.isna(win_rate) else f"{win_rate:.1%}",
          help="WIN / (WIN + LOSS). NO HIT, PENDING e NO DATI sono esclusi.")

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
            "Forza mov.", "Score",
            "10Y", "15Y", "20Y",
            "Avg 10Y", "Avg 15Y", "Avg 20Y", "Mediana 3 rend.",
            "Target orig.",
            "ATR pts", "Target pts",
            "SL 50% ATR pts", "Esito"
        ]
    ].copy()

    for col in ["10Y", "15Y", "20Y", "Avg 10Y", "Avg 15Y", "Avg 20Y", "Mediana 3 rend.", "Target orig.", "Score"]:
        display[col] = display[col].map(pct)

    display["ATR pts"] = display["ATR pts"].map(
        lambda x: "n/d" if pd.isna(x) else f"{x:,.2f}"
    )
    display["Target pts"] = display["Target pts"].map(
        lambda x: "n/d" if pd.isna(x) else f"{x:,.2f}"
    )
    display["SL 50% ATR pts"] = display["SL 50% ATR pts"].map(
        lambda x: "n/d" if pd.isna(x) else f"{x:,.2f}"
    )

    display = display.rename(
        columns={
            "ATR pts": f"ATR{int(atr_period)} pts",
            "Target pts": "Target pts",
            "SL 50% ATR pts": f"SL 50% ATR{int(atr_period)} pts"
        }
    )

    def color_bias(val):
        if val == "SHORT":
            return "color: #ff4b4b; font-weight: 700;"
        if val == "LONG":
            return "color: #21c55d; font-weight: 700;"
        return ""

    def color_strength(val):
        styles = {
            "DEBOLE": "color: #ff4b4b; font-weight: 700;",
            "MEDIO": "color: #f0a000; font-weight: 700;",
            "BUONO": "color: #21c55d; font-weight: 700;",
            "FORTE": "color: #21c55d; font-weight: 800;",
        }
        return styles.get(val, "")

    def color_outcome(val):
        if val == "WIN": return "color: #21c55d; font-weight: 800;"
        if val == "LOSS": return "color: #ff4b4b; font-weight: 800;"
        if val == "NO DATI": return "color: #f0a000; font-weight: 800;"
        return ""

    styled_display = (
        display.style
        .map(color_bias, subset=["Bias"])
        .map(color_strength, subset=["Forza mov."])
        .map(color_outcome, subset=["Esito"])
    )
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
        f"**Mediana dei 3 rendimenti:** {pct(original['Mediana 3 rend.'])}  ·  "
        f"**Mediana storica 15Y:** {pct(original['Median 15Y'])}"
    )
    atr_pts_txt = "n/d" if pd.isna(original["ATR pts"]) else f"{original['ATR pts']:,.2f}"
    target_pts_txt = "n/d" if pd.isna(original["Target pts"]) else f"{original['Target pts']:,.2f}"
    target_atr_txt = "n/d" if pd.isna(original["Target/ATR"]) else f"{original['Target/ATR']:.0%}"

    sl_pts_txt = "n/d" if pd.isna(original["SL 50% ATR pts"]) else f"{original['SL 50% ATR pts']:,.2f}"
    open_txt = "n/d" if pd.isna(original["Open trade"]) else f"{original['Open trade']:,.2f}"
    target_level_txt = "n/d" if pd.isna(original["Target level"]) else f"{original['Target level']:,.2f}"
    stop_level_txt = "n/d" if pd.isna(original["Stop level"]) else f"{original['Stop level']:,.2f}"

    st.write(
        f"**TP stagionale:** {pct(original['Target orig.'])}  ·  "
        f"**ATR{int(atr_period)}:** {atr_pts_txt} punti  ·  "
        f"**Target:** {target_pts_txt} punti  ·  "
        f"**SL 50% ATR:** {sl_pts_txt} punti  ·  "
        f"**Target/ATR{int(atr_period)}:** {target_atr_txt}  ·  "
        f"**Forza movimento:** {original['Forza mov.']}"
    )
    st.write(
        f"**Open:** {open_txt}  ·  **Livello Target:** {target_level_txt}  ·  "
        f"**Livello Stop:** {stop_level_txt}  ·  **Esito:** {original['Esito']}"
    )

    hist = original["_samples"][20].copy()
    hist["Return"] = hist["Return"].map(lambda x: f"{x:.2%}")
    st.dataframe(hist, width="stretch", hide_index=True)

    st.caption(
        "Il target stagionale deriva dalla mediana dei rendimenti medi 10Y, 15Y e 20Y. "
        "La regola operativa corrente usa uno stop pari al 50% dell'ATR in punti. "
        "L'esito viene verificato a partire dall'Open della giornata."
    )
else:
    st.caption("Nessun dettaglio disponibile perché non ci sono opportunità valide.")

with st.expander("Diagnostica dati / campione"):
    diag = res[
        [
            "Date", "Asset", "Ticker", "Bias",
            "10Y LONG raw", "10Y SHORT raw",
            "15Y LONG raw", "15Y SHORT raw",
            "20Y LONG raw", "20Y SHORT raw",
            "N10", "N15", "N20"
        ]
    ].copy()

    # Mostra sempre le statistiche disponibili, anche quando non passa il filtro 70/70/70.
    rename_map = {
        "10Y LONG raw": "10Y LONG",
        "10Y SHORT raw": "10Y SHORT",
        "15Y LONG raw": "15Y LONG",
        "15Y SHORT raw": "15Y SHORT",
        "20Y LONG raw": "20Y LONG",
        "20Y SHORT raw": "20Y SHORT",
    }
    diag = diag.rename(columns=rename_map)

    for col in ["10Y LONG", "10Y SHORT", "15Y LONG", "15Y SHORT", "20Y LONG", "20Y SHORT"]:
        diag[col] = diag[col].map(lambda x: "N/D" if pd.isna(x) else f"{x:.1%}")

    st.dataframe(diag, width="stretch", hide_index=True)

    st.caption(
        "Bias = — significa che i dati esistono ma la giornata non supera il filtro "
        "70/70/70 né LONG né SHORT. N/D viene usato solo quando il dato storico "
        "non è realmente disponibile."
    )

    if data_errors:
        st.warning("\n".join(data_errors))

st.divider()
st.info(
    f"**Esito trade:** entry sull'Open. Target = Open ± Target pts; "
    f"Stop = Open ∓ 50% dell'ATR{int(atr_period)} in punti. "
    "WIN = target prima dello stop · LOSS = stop prima del target · "
    "NO HIT = nessun livello raggiunto · PENDING = giornata non ancora conclusa · "
    "NO DATI = entrambi i livelli toccati senza ordine determinabile. "
    "Forza: <30% ATR = DEBOLE · 30–50% = MEDIO · 50–75% = BUONO · ≥75% = FORTE."
)

st.caption(
    "Uso di ricerca/statistica, non consiglio finanziario. "
    "La disponibilità e qualità dei dati Yahoo Finance va controllata "
    "prima di impiegare il risultato in operatività reale."
)
