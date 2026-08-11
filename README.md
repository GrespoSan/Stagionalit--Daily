# Seasonality Weekly Scanner — V1

App Streamlit per individuare le opportunità settimanali secondo il metodo:

- stagionalità 10 anni
- stagionalità 15 anni
- stagionalità 20 anni
- LONG solo se la percentuale positiva è >= 70% in tutte e tre le finestre
- SHORT solo se la percentuale negativa è >= 70% in tutte e tre le finestre
- target originale = valore assoluto della media dei tre rendimenti medi 10Y, 15Y e 20Y
- stop originale = metà del target

## Punto metodologico

Una data di calendario non è una seduta in tutti gli anni (weekend/festività).
La V1 confronta quindi la **stessa N-esima seduta dello stesso mese**.

Esempio:
- target = 12ª seduta di agosto 2026
- storico = 12ª seduta di agosto 2025, 2024, 2023, ecc.

Questo permette di avere fino a una osservazione per anno e rende possibili
campioni reali di 10/15/20 anni.

## Prezzi

La V1 usa `yfinance` con `auto_adjust=False` e la colonna `Close`.
L'obiettivo è studiare il movimento del prezzo, non il total return da dividendi.

## Avvio locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

Caricare almeno:

- `app.py`
- `requirements.txt`

in un repository GitHub e scegliere `app.py` come entry point.

## Cosa NON fa ancora la V1

Non aggiunge:
- RSI
- trend filter
- COT
- correlazioni
- fondamentali

e non considera il TP/SL originale come già validato.

Il passo successivo, solo se lo scanner produce opportunità interessanti,
è costruire un backtest specifico delle regole di ingresso/uscita descritte
nella strategia originale.
