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
    peak = equity.cummax()
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
        "Motore V3.5 ottimizzato: storici, ATR, stagionalità ed EMA SPX "
        "vengono precalcolati e riutilizzati durante il backtest."
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
