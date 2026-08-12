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


## Forza del movimento

La V1.4 aggiunge un controllo della dimensione economica/statistica del movimento:

- ATR periodi default = 5
- ATR calcolato solo sulle sedute completate prima della giornata target
- ATR% = ATR / ultimo close
- Target/ATR = target stagionale % / ATR%
- classificazione:
  - < 0,30 = DEBOLE
  - 0,30–0,50 = MEDIO
  - 0,50–0,75 = BUONO
  - >= 0,75 = FORTE

La classificazione NON filtra ancora i segnali. Serve per raccogliere evidenza
e capire successivamente se una soglia minima migliora davvero i risultati.

Alphabet viene mantenuta una sola volta tramite GOOGL.


## Tabella principale V1.5

- `Median 15Y` rimossa dalla tabella principale perché non entra nel filtro né nel target.
- `Median 15Y` resta visibile nel Dettaglio storico.
- `Forza mov.` e `Score` spostate subito dopo `Bias` per rendere immediata la lettura operativa.


## V1.6 — Target/ATR più leggibile

Il rapporto Target/ATR viene ora mostrato come percentuale dell'ATR.

Esempio:
- Target = 0,8%
- ATR5 = 3,4%
- Target/ATR5 = 24%

Significa che il target stagionale equivale a circa il 24% dell'ATR5.


## V1.7 — valori operativi in punti

La tabella principale mostra ora:
- ATR5 pts (o il periodo ATR selezionato)
- Target pts

`Target pts` è il movimento di prezzo corrispondente al target stagionale.
È matematicamente equivalente a:

Target pts = ATR pts × Target/ATR

Esempio:
ATR5 = 6,80 punti
Target/ATR5 = 25%
Target = 1,70 punti

Per futures i "punti" sono punti del contratto/quotazione.
Per azioni sono unità di prezzo (es. dollari per azione).


## V1.8

- aggiunto Eli Lilly (`LLY`) all'universo
- la Diagnostica mostra sempre le probabilità LONG e SHORT reali su 10Y/15Y/20Y
- `Bias = —` significa "nessun segnale valido"
- `N/D` viene usato solo quando il dato storico non è realmente disponibile


## V1.9 — lista asset esterna .txt

Nella sidebar è disponibile un upload opzionale di un file `.txt`.

Comportamento:
- se NON viene caricato alcun file, l'app usa l'universo predefinito;
- se viene caricato un file, l'app usa esclusivamente gli asset presenti nel file;
- righe vuote e righe che iniziano con `#` vengono ignorate.

Formati accettati:

```text
Nvidia,NVDA
Apple,AAPL
Gold Future,GC=F
```

oppure, più semplicemente:

```text
NVDA
AAPL
GC=F
```

Nel secondo caso il ticker viene usato anche come nome visualizzato.

È incluso `asset_list_example.txt` con l'universo predefinito completo.


## V2.0 — Stop ATR e verifica WIN/LOSS

Regola operativa:
- Entry = Open della giornata
- Target LONG = Open + Target pts
- Target SHORT = Open - Target pts
- Stop LONG = Open - 50% ATR pts
- Stop SHORT = Open + 50% ATR pts

Nuove colonne:
- SL 50% ATR in punti
- Esito

Esiti:
- WIN = target raggiunto prima dello stop
- LOSS = stop raggiunto prima del target
- NO HIT = nessun livello raggiunto nella giornata conclusa
- PENDING = giornata corrente/futura, quindi non ancora valutata
- AMBIGUO = target e stop toccati nella stessa giornata senza ordine determinabile

Quando Daily High/Low toccano entrambi i livelli, l'app prova le barre 5 minuti per stabilire quale sia stato raggiunto prima. Se entrambi risultano toccati nella stessa barra 5m o l'intraday non è disponibile, l'esito resta AMBIGUO.

Nota: con Target = 25% ATR e Stop = 50% ATR, il break-even teorico è 66,7% prima di costi/slippage.
