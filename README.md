# 🎅 Secret Betting

Web app per il Secret Santa con scommessa: l'app fa l'estrazione, ognuno vede solo a chi
fa il regalo e prova a indovinare tutte le altre coppie. Alla serata si svelano le coppie
e si stila la classifica.

## Regole attuali

- La propria coppia è già nota, quindi non si pronostica e non conta per il punteggio.
- Nei pronostici ognuno riceve da una sola persona e nessuno regala a se stesso.
- **1 punto** per ogni coppia indovinata. Se indovini chi fa il regalo **a te**, quella coppia
  vale **3 punti** (1 + bonus di 2, configurabile dall'admin).
- **Dopo la rivelazione** i pronostici diventano visibili, a piccole dosi:
  - sul maxischermo, per ogni coppia svelata: chi l'aveva indovinata, se il destinatario aveva
    capito chi gli fa il regalo, e l'errore più comune ("in 5 pensavano che…");
  - a rivelazione completa, nella pagina personale: i propri pronostici con ✅/❌ e la risposta
    giusta, più "👀 I pronostici degli altri", una persona alla volta.
- I pronostici degli altri restano nascosti fino ad allora; si possono modificare fino all'**inizio della serata**
  (la data dell'evento è anche la scadenza, così non ci si mette d'accordo parlandone).
  Gli sblocchi degli indizi devono essere prima della serata.
- Non è obbligatorio pronosticare tutte le coppie: conta solo quello che si indovina.
- **Spareggio:** a pari punti è più in alto chi ha salvato i pronostici prima. Conta l'ultimo
  salvataggio, quindi ogni modifica aggiorna l'orario.

## Indizi

- L'admin definisce 5-6 **caratteristiche** uguali per tutti, ognuna con almeno 2 valori
  (es. Altezza: bassa / media / alta), e compila la **scheda** di ogni partecipante.
  Le schede le vede solo l'admin: i giocatori hanno solo i propri indizi e devono capire da soli a chi si riferiscono.
- All'estrazione l'app genera **4 indizi a testa**, senza che nessuno li veda (admin compreso):
  - **2 veri e 2 falsi**, in ordine casuale (i giocatori lo sanno, ma non sanno quali);
  - mai sulla propria coppia né su quella del bonus (chi regala a te);
  - su quattro coppie diverse, e nessuna frase è uguale a quella di un altro giocatore;
  - ogni "fatto" (es. *l'altezza di chi regala a X*) compare una sola volta in tutto il gioco,
    così confrontando gli indizi tra giocatori non si trovano contraddizioni;
  - ogni indizio lascia, dal punto di vista di chi lo riceve, 2-3 candidati possibili.
- Due tipi: "Chi fa il regalo a **X** ha *Capelli: neri*" e
  "**X** fa il regalo a qualcuno con *Altezza: alta*".
- Si sbloccano da soli, 2 alla volta, alle due date impostate dall'admin (indizi 1-2 e 3-4). Il contenuto
  di un indizio bloccato non lascia mai il server.
- A rivelazione completata, `/reveal` mostra tutti gli indizi distribuiti con ✅ vero / ❌ falso.
- Caratteristiche e schede si possono modificare solo prima dell'estrazione.
- **Caratteristiche automatiche dalla data di nascita** (📅): stagione, elemento zodiacale, segno,
  semestre, metà più grande/giovane del gruppo. L'admin inserisce solo la data, che non viene
  mai mostrata ai giocatori: vedono solo i valori calcolati.

## Pagine

| URL         | Chi             | Cosa                                                                      |
|-------------|-----------------|---------------------------------------------------------------------------|
| `/p/<link>` | ogni giocatore  | primo accesso: si sceglie un PIN; poi si entra con il PIN                 |
| `/me`       | giocatore       | il proprio abbinamento (tocca per scoprirlo) e i pronostici              |
| `/admin`    | admin           | partecipanti, vincoli, date, estrazione, chiusura, rivelazione        |
| `/reveal`   | tutti (TV)      | rivelazione coppia per coppia e classifica in diretta                    |
| `/telecomando` | admin (cellulare) | pulsanti grandi per svelare le coppie una alla volta (non mostra le coppie). Prima dello show `/reveal` mostra un QR per aprirlo: serve comunque la password admin |

## Sicurezza / privacy

- Il database SQLite sta in `instance/` sul server e **non viene mai servito** al browser.
  I giocatori passano solo dalle API, che restituiscono esclusivamente i loro dati.
- Ogni giocatore sceglie il proprio PIN al primo accesso: l'admin distribuisce i link ma
  non conosce i PIN. Dopo 5 PIN sbagliati il profilo si blocca per 10 minuti.
- L'admin **non vede mai l'esito dell'estrazione**: le coppie compaiono solo durante la
  rivelazione. L'estrazione si può rifare solo finché nessuno ha visto il proprio abbinamento.
- Se l'admin resetta un PIN, il giocatore se ne accorge (al prossimo accesso deve sceglierne
  uno nuovo) e le sue sessioni aperte vengono chiuse.
- Limite: chi ha accesso ai file del server potrebbe leggere il database a mano.
  L'app protegge dagli altri giocatori, non da chi gestisce il server.

## Avvio in locale (Windows)

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copia `.env.example` in `.env` e imposta `ADMIN_PASSWORD`, poi:

```bash
.venv\Scripts\python.exe app.py
```

Apri http://localhost:5000/admin.

Scorciatoie (doppio clic):

| File | Cosa fa |
|------|---------|
| `apri_admin.bat` | accende il server (se spento) e apre l'admin |
| `apri_profilo.bat` | accende il server e apre il proprio profilo (nome in cima al file) |
| `prova_estrazione.bat` | estrazione di prova su una **copia** del database (porta 5056) e apre il profilo |
| `prova_rivelazione.bat` | come sopra + pronostici casuali per tutti; apre `/reveal` sul PC con il QR del telecomando da inquadrare col cellulare (stessa wifi) |

Le prove non toccano mai `instance/secret_santa.db`.

Test:

```bash
.venv\Scripts\python.exe -m unittest discover tests
```

## Messa online gratis (PythonAnywhere)

PythonAnywhere ha un piano gratuito con disco persistente (il database non si perde) e
HTTPS incluso. Il sito sarà `https://<tuo-utente>.pythonanywhere.com`.

1. Crea un account gratuito su pythonanywhere.com.
2. Nella scheda **Files** carica la cartella del progetto (senza `.venv` e `instance`),
   per esempio in `/home/<utente>/secret_santa_26`.
3. Apri una **Bash console** e lancia:
   `cd ~/secret_santa_26 && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. Crea `~/secret_santa_26/.env` con:
   ```
   ADMIN_PASSWORD=<una password lunga>
   COOKIE_SECURE=1
   ```
5. Scheda **Web**: *Add a new web app*, poi *Manual configuration* e Python 3.11.
   - *Virtualenv*: `/home/<utente>/secret_santa_26/.venv`
   - Nel file *WSGI configuration* sostituisci tutto con:
     ```python
     import sys
     sys.path.insert(0, "/home/<utente>/secret_santa_26")
     from app import app as application
     ```
   - In *Security* attiva **Force HTTPS**, poi premi **Reload**.
6. Vai su `/admin`, aggiungi i partecipanti e manda a ciascuno il suo link (pulsante WhatsApp).

Nota: sul piano gratuito bisogna cliccare "Run until 3 months from today" nella scheda Web
almeno una volta ogni 3 mesi, quindi ampiamente sufficiente per un Secret Santa.

## Struttura

```
app.py          server Flask: DB, autenticazione, API
logic.py        logica pura: estrazione, validazione pronostici, punteggi
web/            pagine HTML (index, login, me, admin, reveal) + static/ (CSS, JS)
tests/          test di logica e API (incluse le verifiche di privacy)
instance/       database e chiave di sessione (creata in automatico, non va condivisa)
```
