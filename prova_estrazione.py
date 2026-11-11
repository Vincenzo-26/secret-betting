"""Prove su una COPIA del database (il database vero non viene mai toccato).

Uso:
  .venv\\Scripts\\python.exe prova_estrazione.py [Nome]                  (prova_estrazione.bat)
  .venv\\Scripts\\python.exe prova_estrazione.py --rivelazione [Nome]    (prova_rivelazione.bat)

Estrazione (default):
  1. copia instance/secret_santa.db in instance/prova/ (ogni volta da capo);
  2. sulla copia: date di prova per gli indizi + estrazione;
  3. server di prova su http://localhost:5056, apre il profilo di [Nome].

Rivelazione (--rivelazione): come sopra, in più
  - pronostici casuali per tutti i giocatori (così la classifica si muove);
  - il server è raggiungibile dagli altri dispositivi della stessa wifi;
  - apre /reveal sul PC e stampa l'indirizzo del telecomando per il cellulare.

La password admin della copia è quella solita (.env). Le coppie non vengono mai stampate.
"""
import os
import random
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
REAL_DB = BASE / "instance" / "secret_santa.db"
PROVA_DIR = BASE / "instance" / "prova"
PORT = 5056

args = [a for a in sys.argv[1:] if not a.startswith("--")]
REVEAL_MODE = "--rivelazione" in sys.argv
NOME = args[0] if args else "Vincenzo"


def die(msg):
    print(f"\n[ERRORE] {msg}")
    sys.exit(1)


def random_guesses(db, assignments, ids, p, accuracy):
    """Pronostici casuali ma validi per il giocatore p: alcune coppie giuste
    (circa `accuracy`), le altre a caso, nessun destinatario ripetuto."""
    givers = [g for g in ids if g != p]
    pool = [r for r in ids if r != assignments[p]]          # chi ho pescato io non riceve da altri
    for _ in range(2000):
        keep = {g for g in givers if random.random() < accuracy}
        fixed = {g: assignments[g] for g in keep}
        rest_g = [g for g in givers if g not in keep]
        rest_r = [r for r in pool if r not in fixed.values()]
        random.shuffle(rest_r)
        guess = {**fixed, **dict(zip(rest_g, rest_r))}
        if all(g != r for g, r in guess.items()):
            break
    else:
        return
    db.executemany("INSERT INTO guesses(player_id, giver_id, receiver_id) VALUES (?, ?, ?)",
                   [(p, g, r) for g, r in guess.items()])


if not REAL_DB.exists():
    die(f"Database vero non trovato: {REAL_DB}")

# 1. Copia pulita (backup API di SQLite: sicura anche col server vero acceso).
PROVA_DIR.mkdir(parents=True, exist_ok=True)
for f in PROVA_DIR.glob("secret_santa.db*"):
    f.unlink()
src = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
dst = sqlite3.connect(PROVA_DIR / "secret_santa.db")
src.backup(dst)
dst.close()
src.close()
print("Copia del database creata in instance\\prova (il database vero non viene toccato).")

# 2. Avvia l'app sulla copia.
os.environ["DATA_DIR"] = str(PROVA_DIR)
os.environ["FLASK_SKIP_DOTENV"] = "1"   # niente avviso "install python-dotenv"
sys.path.insert(0, str(BASE))
import app as sb  # noqa: E402  (va importato dopo aver impostato DATA_DIR; legge anche .env)

if not os.environ.get("ADMIN_PASSWORD"):
    os.environ["ADMIN_PASSWORD"] = secrets.token_urlsafe(16)
    print("(Nessuna ADMIN_PASSWORD nel file .env: l'admin della copia non sarà accessibile.)")

# Cookie con un nome diverso: così la prova non ti scollega dal server vero.
sb.app.config["SESSION_COOKIE_NAME"] = "sb_prova_session"

admin = sb.app.test_client()
r = admin.post("/api/admin/login", json={"password": os.environ["ADMIN_PASSWORD"]})
if r.status_code != 200:
    die("Login admin sulla copia non riuscito.")

state = admin.get("/api/admin/state").get_json()
if state["game"]["phase"] != "setup":
    die("Nel database vero l'estrazione risulta già fatta: la prova serve solo in fase di preparazione.")

now = time.time()
settings = {"hint1_at": now - 60, "hint2_at": now + 7 * 86400}
if not state["game"]["event_at"] or state["game"]["event_at"] <= settings["hint2_at"]:
    settings["event_at"] = now + 30 * 86400      # serata (= chiusura pronostici) dopo gli indizi
admin.put("/api/admin/settings", json=settings)

r = admin.post("/api/admin/draw", json={})
if r.status_code != 200:
    die("Estrazione non riuscita: " + (r.get_json() or {}).get("error", "errore sconosciuto"))
admin.post("/api/admin/logout", json={})
print("Estrazione di prova fatta (solo sulla copia).")

db = sqlite3.connect(PROVA_DIR / "secret_santa.db")
row = db.execute("SELECT code FROM participants WHERE name = ? COLLATE NOCASE", (NOME,)).fetchone()

if REVEAL_MODE:
    assignments = dict(db.execute("SELECT giver_id, receiver_id FROM assignments").fetchall())
    ids = list(assignments)
    db.execute("DELETE FROM guesses")
    for p in ids:
        random_guesses(db, assignments, ids, p, accuracy=random.uniform(0.05, 0.45))
        # orari di consegna diversi, per vedere anche lo spareggio
        db.execute("UPDATE participants SET guesses_updated_at = ? WHERE id = ?",
                   (now - random.uniform(3600, 10 * 86400), p))
    db.commit()
    print(f"Pronostici casuali compilati per tutti i {len(ids)} giocatori.")
else:
    print("  - indizi 1-2: già sbloccati   - indizi 3-4: tra 7 giorni"
          + ("   - serata (chiusura pronostici): tra 30 giorni" if "event_at" in settings else ""))
db.close()

host = "127.0.0.1"
if REVEAL_MODE:
    host = "0.0.0.0"   # raggiungibile dal cellulare sulla stessa wifi
    ip = sb.lan_ip()
    if ip:
        sb.app.config["REMOTE_URL"] = f"http://{ip}:{PORT}/telecomando"   # per il QR sul maxischermo
    open_url = f"http://localhost:{PORT}/reveal"
    print(f"\nServer di PROVA acceso. Sul PC si apre la pagina della rivelazione: {open_url}")
    print("Sul CELLULARE (stessa wifi del PC) inquadra il QR sullo schermo, oppure apri:")
    print(f"     http://{ip}:{PORT}/telecomando" if ip else "     (IP del PC non trovato: usa ipconfig)")
    print("ed entra con la solita password admin. Poi premi 'Inizia la rivelazione'.")
    print("Se Windows chiede di consentire Python sulla rete, consenti solo le reti PRIVATE.")
    print("Puoi anche usare la tastiera sul PC (spazio = avanti, freccia sinistra = indietro)")
    print(f"dopo aver fatto login admin su http://localhost:{PORT}/admin nello stesso browser.")
else:
    open_url = f"http://localhost:{PORT}/" + (f"p/{row[0]}" if row else "")
    if not row:
        print(f"(Nessun partecipante chiamato {NOME!r}: apro la home.)")
    print(f"\nServer di PROVA acceso su http://localhost:{PORT}")
    print("Entra con il tuo solito PIN.")
print("Chiudi questa finestra per spegnere la prova.\n")

threading.Timer(1.5, lambda: webbrowser.open(open_url)).start()
sb.app.run(host=host, port=PORT)
