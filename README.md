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


## V2.1 — riepilogo WIN / LOSS / Win Rate

A fianco delle metriche principali vengono mostrati:
- WIN
- LOSS
- Win Rate

Win Rate = WIN / (WIN + LOSS)

Sono esclusi dal calcolo:
- NO HIT
- PENDING
- AMBIGUO
- N/D


## V2.2 — posizione pulsante

Il pulsante `Analizza settimana` è stato spostato subito sotto il controllo
`ATR periodi per forza movimento`, prima della sezione Universo.


## V3.0 — Backtest manuale

Nuova sezione indipendente per testare la strategia giorno per giorno.

Parametri:
- data inizio / fine
- filtro stagionale minimo
- ATR period
- forza minima: TUTTI / MEDIO+ / BUONO+ / SOLO FORTE
- stop in multipli ATR
- LONG + SHORT / solo LONG / solo SHORT
- filtro opzionale coerenza Bias / rendimento medio
- copertura minima del campione

Regole:
- entry = Open della seduta
- target = target stagionale in punti
- stop = multiplo ATR selezionato
- se target e stop non vengono toccati -> uscita al Close
- se target e stop risultano entrambi toccati e non è ricostruibile l'ordine -> NO DATI

Metriche:
- Segnali
- Valutabili
- NO DATI
- WIN / LOSS
- Win Rate
- Profit Factor
- Expectancy in R
- Totale R
- Max Drawdown in R
- equity cumulata
- risultati per Forza
- risultati per Asset
- trade log completo

`NO DATI` è escluso dalle statistiche di performance.

La V3.0 è volutamente manuale. L'ottimizzatore automatico dei parametri va aggiunto
solo dopo aver verificato che questo motore di backtest produca risultati coerenti.


## V3.1 — filtro regime S&P 500

Sia LONG sia SHORT possono essere ammessi solo quando SPX Close(T-1) è sopra EMA(T-1). Periodo EMA modificabile, default 21. La diagnostica confronta SOPRA EMA / SOTTO EMA / NO DATI.


## V3.2 — Max trade per giorno

Nuovo parametro:
- 1
- 2
- 3
- TUTTI

Default: 1.

Se in una stessa giornata ci sono più candidati, la selezione viene effettuata
PRIMA di calcolare l'esito del trade, quindi senza look-ahead.

Ordine di priorità:
1. Target/ATR più alto
2. Score stagionale più alto
3. Asset in ordine alfabetico come tie-break deterministico

Nel Trade Log vengono mostrate:
- `Candidati giorno`
- `Rank giorno`

In questo modo è possibile verificare perché uno specifico trade è stato scelto.


## V3.3 — Regime SPX e analisi annuale

Modifiche:
- massimo 1 trade al giorno fissato come regola strutturale;
- rimosso il selettore 1/2/3/TUTTI;
- nuovo filtro regime SP500:
  - OFF
  - SOLO SOPRA EMA
  - SOLO SOTTO EMA
- periodo EMA modificabile, default 21;
- regime sempre calcolato su T-1, senza look-ahead;
- nuova tabella `Risultati per anno` con:
  - Segnali
  - Valutabili
  - NO DATI
  - WIN / LOSS
  - Win Rate
  - Profit Factor
  - Expectancy R
  - Totale R
  - Max DD R

La priorità del trade giornaliero resta:
1. Target/ATR più alto
2. Score stagionale più alto
3. nome asset come tie-break.


## V3.4 — filtro SOLO BUONO

Nuova opzione nella selezione `Forza minima`:

- TUTTI
- MEDIO+
- BUONO+
- SOLO BUONO
- SOLO FORTE

Definizioni:
- DEBOLE: Target/ATR < 0,30
- MEDIO: 0,30 <= Target/ATR < 0,50
- BUONO: 0,50 <= Target/ATR < 0,75
- FORTE: Target/ATR >= 0,75

`SOLO BUONO` seleziona esclusivamente i segnali compresi tra 0,50 e 0,75 ATR,
quindi esclude sia MEDIO/DEBOLE sia FORTE.

La regola di 1 trade massimo al giorno resta fissa.


## V3.5 — motore backtest ottimizzato

La logica della strategia non cambia.

Ottimizzazioni:
- ogni storico asset viene scaricato una sola volta per esecuzione;
- ATR(T-1) viene precalcolato una sola volta per asset;
- i rendimenti stagionali vengono indicizzati per mese/giorno;
- le finestre 10Y/15Y/20Y non ricostruiscono più DataFrame ad ogni seduta;
- EMA S&P 500 viene calcolata una sola volta;
- il regime SPX usa lookup sulla seduta precedente;
- dopo il ranking giornaliero l'esito viene calcolato solo sul trade realmente selezionato;
- massimo 1 trade al giorno resta fisso;
- nessun cambiamento alle regole di filtro, target, stop o NO DATI.

La V3.5 è pensata per backtest pluriennali e prepara il motore per il futuro
ottimizzatore automatico.


## V4.0 — Ottimizzatore automatico + Walk-Forward

### Griglia automatica

- filtro stagionale: 65 / 70 / 75 / 80
- ATR: 3 / 5 / 7 / 10 / 14 / 20
- Forza: MEDIO+ / BUONO+ / SOLO BUONO / SOLO FORTE
- Stop ATR: 0,30 / 0,40 / 0,50 / 0,60 / 0,75 / 1,00

Totale: 576 configurazioni.

### Regole fisse nell'optimizer

- massimo 1 trade al giorno
- copertura minima campione 60%
- LONG + SHORT
- regime S&P 500 OFF
- ranking giornaliero: Target/ATR, poi Score
- casi target+stop entrambi toccati sul daily = NO DATI nell'optimizer
  (la configurazione finale va validata col backtest manuale)

### Walk-Forward

Default:
- training rolling 3 anni
- test sull'anno successivo
- min 30 trade nel training
- min Profit Factor training 1,05
- min 50% anni positivi nel training

La configurazione viene scelta ESCLUSIVAMENTE sul training.
Il test successivo non influenza la scelta.

Ranking training:
1. Expectancy R più alta
2. Profit Factor più alto
3. Max Drawdown più basso
4. maggior numero di trade

### Output

- Top configurazioni full-period (solo esplorativo / in-sample)
- tabella fold Walk-Forward
- aggregato OUT-OF-SAMPLE
- equity OOS in R
- stabilità dei parametri scelti tra i fold

### Correzione Max Drawdown

Dalla V4 il Max Drawdown include correttamente l'equity iniziale pari a 0R,
quindi una partenza negativa viene conteggiata come drawdown.


## V4.1 — Export Excel completo

Dopo l'ottimizzazione compare il pulsante `Scarica report ottimizzazione Excel`.

Il file `.xlsx` contiene:
- `Riepilogo_OOS`
- `Impostazioni`
- `Full_576` con tutte le configurazioni testate
- `Walk_Forward`
- `Parametri_Scelti`
- `Stabilita`
- `Trade_OOS`

È il file da allegare in chat per analizzare il risultato completo senza
dipendere da screenshot parziali.


## V4.2 — fix export Excel

Corretto il TypeError durante la creazione del file Excel:
- i valori usati per calcolare la larghezza delle colonne vengono ora sempre convertiti in stringa;
- gestione più robusta dei tipi pandas/numpy;
- gestione esplicita dei valori infiniti nel riepilogo OOS.

La logica di scanner, backtest, ottimizzatore e Walk-Forward è invariata.


## V4.3 — Robust / Plateau Optimizer

La griglia resta invariata a 576 configurazioni. Cambia il criterio di scelta.

Nuove metriche per ogni configurazione:
- mediana R annuale
- peggior anno
- miglior anno
- dispersione dei risultati annuali
- numero di configurazioni vicine
- % configurazioni vicine positive
- expectancy mediana dei vicini
- Profit Factor mediano dei vicini
- Robust Score 0–100

Un "vicino" è una configurazione distante un solo passo in una sola dimensione
(filtro, ATR, Forza o Stop).

Pesi Robust Score:
- 20% quota anni positivi
- 15% mediana annuale
- 15% peggior anno
- 15% quota vicini positivi
- 10% expectancy mediana dei vicini
- 10% Profit Factor
- 5% numero trade
- 5% drawdown basso
- 5% dispersione annuale bassa

Il Walk-Forward non seleziona più la massima expectancy del training:
ordina prima per Robust Score e stabilità annuale/plateau.

Il giudizio finale resta esclusivamente OUT-OF-SAMPLE.


## V4.4 — Cost Stress Test

La logica di entry resta fissata sull'OPEN e il motore Robust/Plateau è invariato.

Nuovo stress test sui soli trade OUT-OF-SAMPLE:
- 0,00 R per trade
- 0,01 R
- 0,02 R
- 0,03 R
- 0,05 R
- 0,10 R

Per ogni livello vengono ricalcolati:
- Win Rate netto
- Profit Factor netto
- Expectancy netta
- Totale R netto
- Max Drawdown netto
- anni positivi
- % anni positivi

Viene inoltre calcolato il `Costo break-even per trade (R)`, cioè il costo
round-trip uniforme che porta l'Expectancy OOS a circa zero.

Il report Excel aggiunge il foglio `Cost_Stress` e il costo break-even nel
foglio `Riepilogo_OOS`.

Nota: lo stress test usa un costo uniforme espresso in R. Non sostituisce
ancora il futuro modulo CFD/Turbo con costi specifici per strumento.


## V4.5 — EDGE SEARCH (ultimo tentativo strutturale)

Obiettivo: trovare un vantaggio statistico OOS chiaramente forte oppure fermare
la strategia. Non vengono aggiunti indicatori casuali.

### Ricerca strutturale

Alla griglia base 576 vengono aggiunti soltanto:

- Trend `OFF`
- Trend `EMA21 ALIGN`
  - LONG ammesso solo se Close(T-1) > EMA21(T-1)
  - SHORT ammesso solo se Close(T-1) < EMA21(T-1)

e:

- `LONG+SHORT`
- `SOLO LONG`

Totale: 2304 configurazioni.

### Asset Gate ex-ante

Dopo che ogni fold sceglie la configurazione robusta sul training, l'app valuta
gli asset separatamente sempre e solo sul training.

Asset eleggibile:
- almeno 6 trade valutabili
- Profit Factor >= 1,05
- Expectancy > 0

Il gate viene usato solo se:
- restano almeno 3 asset
- i trade non scendono sotto il 50% del baseline
- PF ed expectancy training migliorano
- Total R training resta positivo

La whitelist viene poi congelata e applicata all'anno OOS PRIMA del ranking
giornaliero. Nessun asset viene escluso perché ha perso nell'OOS.

### Criteri finali EDGE FORTE

Per considerare il progetto valido devono essere superati TUTTI:
- almeno 80 trade OOS
- Profit Factor OOS >= 1,25
- Expectancy OOS >= +0,08R
- almeno 70% anni OOS positivi
- Totale R / Max Drawdown >= 1,50

Se la V4.5 non supera questi criteri, la raccomandazione è fermare o
ridisegnare la strategia, non continuare ad aggiungere filtri.


## V4.6 — Candela T-1 Align

Aggiunta una terza modalità strutturale, alternativa alle precedenti:

- `OFF`
- `EMA21 ALIGN`
- `CANDELA T-1 ALIGN`

Regola `CANDELA T-1 ALIGN`:
- LONG: Close(T-1) > Open(T-1)
- SHORT: Close(T-1) < Open(T-1)
- Doji: nessun trade

L'entry resta sempre all'Open di T.

La modalità candela NON viene combinata con EMA21: l'optimizer sceglie tra le
tre alternative strutturali, evitando di impilare filtri.

La griglia diventa:
4 threshold × 6 ATR × 4 Forza × 6 Stop × 3 regimi × 2 direzioni
= 3456 configurazioni.

Asset Gate e criteri finali EDGE FORTE restano invariati.


## V4.7 — Edge Search Slim + Candela T-1 nello screener

Per ridurre carico e rischio di overfitting:
- rimosso `EMA21 ALIGN`
- rimossa la variabile `SOLO LONG`
- direzione fissata `LONG+SHORT`
- restano solo `OFF` e `CANDELA T-1 ALIGN`

Griglia:
4 threshold × 6 ATR × 4 Forza × 6 Stop × 2 modalità
= 1152 configurazioni.

L'Asset Gate training-only resta attivo.

### Screener settimanale

Aggiunta colonna `Candela T-1`:
- `VERDE` se Close(T-1) > Open(T-1)
- `ROSSA` se Close(T-1) < Open(T-1)
- `DOJI` se Close(T-1) = Open(T-1)
- `N/D` se non disponibile

T-1 significa ultima vera seduta precedente alla data analizzata, non
semplicemente il giorno di calendario precedente.


## V4.7.1 — Fix Cost Stress

Corretto il `NameError: build_cost_stress_table is not defined`.

Sono state ripristinate/verificate:
- `apply_cost_r_to_oos`
- `build_cost_stress_table`
- `cost_break_even_r`
- livelli Cost Stress: 0 / 0,01 / 0,02 / 0,03 / 0,05 / 0,10 R

Nessuna modifica alla logica:
- optimizer 1152 configurazioni
- OFF vs CANDELA T-1 ALIGN
- LONG+SHORT fisso
- Asset Gate training-only
- Candela T-1 nello screener settimanale


## V4.8 — A/B Test

Aggiunto selettore `Test strutturale`:
- AUTO
- SOLO OFF
- SOLO CANDELA T-1

Per il confronto richiesto eseguire due run con identici parametri:
1. SOLO OFF
2. SOLO CANDELA T-1

Ogni run forzato testa 576 configurazioni. AUTO continua a testarne 1152.
Il nome del file Excel esportato include la modalità.


## V4.9 — Asset Robustness: COMPLETO vs SENZA DAX

Aggiunto il selettore `Robustezza universo`:
- `COMPLETO`
- `SENZA DAX`

`SENZA DAX` rimuove esclusivamente il DAX cash proxy (`^GDAXI`) prima che
inizi il Walk-Forward. Il ranking giornaliero viene quindi rifatto correttamente
sugli asset rimanenti: non si limita a sottrarre i trade DAX dal risultato.

Questo NON è un nuovo parametro ottimizzato e NON serve a cercare il miglior
sottoinsieme di asset. È un test controllato di dipendenza da un singolo mercato.

Per il test richiesto:
- periodo: 2010-01-01 → 2018-12-31
- Test strutturale: SOLO CANDELA T-1
- Min PF training: 1,05
- stessi altri parametri del test precedente
- eseguire `SENZA DAX`

Le classi Forza restano tutte attive nell'optimizer:
- MEDIO+
- BUONO+
- SOLO BUONO
- SOLO FORTE

L'optimizer le seleziona sul training; non è fissato a SOLO FORTE.
