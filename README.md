# Seasonality Weekly Scanner — V1

App Streamlit per individuare le opportunità settimanali secondo il metodo:

- stagionalità 10 anni
- stagionalità 15 anni
- stagionalità 20 anni
- LONG solo se la percentuale positiva è >= 70% in tutte e tre le finestre
- SHORT solo se la percentuale negativa è >= 70% in tutte e tre le finestre
- target originale = valore assoluto della mediana (valore centrale) dei tre rendimenti medi 10Y, 15Y e 20Y
- stop originale = metà del target

## Punto metodologico

La V1 replica il comportamento osservato in Forecaster:
confronta lo **stesso giorno di calendario** nei precedenti 10, 15 e 20 anni.

Esempio:
- target = 11 agosto 2026
- storico = 11 agosto 2025, 2024, 2023, ecc.
- se l'11 agosto di un anno cade nel weekend o non è una seduta, quell'anno viene escluso.

Di conseguenza il denominatore reale può essere inferiore a 10/15/20.
Per esempio, l'11 agosto nei 10 anni precedenti al 2026 è una seduta in 7 anni:
6 casi SHORT su 7 producono 85,7%, visualizzato come 86%.

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


## Universo V1.3

### Top 10 titoli
- NVDA
- GOOGL
- GOOG
- AAPL
- MSFT
- AMZN
- AVGO
- META
- BRK-B
- TSLA

### Indici / futures
- E-mini S&P 500: ES=F
- Nasdaq 100 Future: NQ=F
- Mini Dow: YM=F
- E-mini Russell 2000: RTY=F
- DAX: ^GDAXI (cash proxy)
- Euro Stoxx 50: ^STOXX50E (cash proxy)

### Commodity futures
- Gold: GC=F
- WTI Crude Oil: CL=F
- Copper: HG=F

DAX ed Euro Stoxx 50 vengono volutamente analizzati tramite il cash index:
i continuous futures Eurex disponibili gratuitamente via Yahoo non sono
sufficientemente affidabili/coerenti per costruire una stagionalità 20Y.
