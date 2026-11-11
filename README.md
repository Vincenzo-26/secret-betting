# 🎅 Secret Betting

Web app per il Secret Santa con scommessa: l'app fa l'estrazione, ognuno vede solo a chi
fa il regalo e prova a indovinare tutte le altre coppie. Alla serata si svelano le coppie
e si stila la classifica.

## Regole attuali

- La propria coppia è già nota, quindi non si pronostica e non conta per il punteggio.
- Nei pronostici ognuno riceve da una sola persona e nessuno regala a se stesso.
- **1 punto** per ogni coppia indovinata. Se indovini chi fa il regalo **a te**, quella coppia
  vale **3 punti** (1 + bonus di 2, configurabile dall'admin).
- I pronostici degli altri restano nascosti; si possono modificare fino alla scadenza.
- **Spareggio:** a pari punti è più in alto chi ha salvato i pronostici prima. Conta l'ultimo
  salvataggio, quindi ogni modifica aggiorna l'orario.

## Indizi

- L'admin definisce 5-6 **caratteristiche** uguali per tutti, ognuna con almeno 2 valori
  (es. Altezza: bassa / media / alta), e compila la **scheda** di ogni partecipante.
  Le schede sono visibili a tutti i giocatori (pagina `/schede`, con filtro per valore).
- All'estrazione l'app genera **2 indizi a testa**, senza che nessuno li veda (admin compreso):
  - **uno vero e uno falso**, in ordine casuale (i giocatori lo sanno, ma non sanno quale);
  - mai sulla propria coppia né su quella del bonus (chi regala a te);
  - su due coppie diverse, e nessuna frase è uguale a quella di un altro giocatore;
  - ogni indizio lascia, dal punto di vista di chi lo riceve, 2-3 candidati possibili.
- Due tipi: "Chi fa il regalo a **X** ha *Capelli: neri*" e
  "**X** fa il regalo a qualcuno con *Altezza: alta*".
- Si sbloccano da soli alle date impostate dall'admin (indizio 1 e indizio 2). Il contenuto
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
| `/admin`    | admin           | partecipanti, vincoli, scadenza, estrazione, chiusura, rivelazione        |
| `/reveal`   | tutti (TV)      | rivelazione coppia per coppia e classifica in diretta                    |
| `/schede`   | giocatori       | tabella delle caratteristiche di tutti, per decifrare gli indizi          |

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
