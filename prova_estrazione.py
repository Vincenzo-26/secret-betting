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
  - alla votazione dei regali gli altri giocatori votano da soli, a caso (tu voti dal tuo profilo);
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


def fake_voters(my_id):
    """Solo nella prova: quando si apre la votazione dei regali, gli altri giocatori
    votano a caso uno alla volta (tu voti dal tuo profilo). Nessun voto viene stampato."""
    while True:
        time.sleep(2)
        try:
            db = sqlite3.connect(PROVA_DIR / "secret_santa.db")
            s = dict(db.execute("SELECT key, value FROM settings"))
            amap = dict(db.execute("SELECT giver_id, receiver_id FROM assignments"))
            if s.get("phase") != "reveal" or int(s.get("reveal_step", 0)) != len(amap) + 2:
                db.close()
                continue
            voted = {r[0] for r in db.execute("SELECT voter_id FROM gift_voters")}
            todo = [p for p in amap if p != my_id and p not in voted]
            if todo:
                p = random.choice(todo)
                best, worst = random.sample([g for g in amap if g != p], 2)
                db.execute("INSERT INTO gift_voters(voter_id) VALUES (?)", (p,))
                for giver, kind in ((best, "best"), (worst, "worst")):
                    db.execute("INSERT INTO gift_votes(giver_id, kind, votes) VALUES (?, ?, 1) "
                               "ON CONFLICT(giver_id, kind) DO UPDATE SET votes = votes + 1", (giver, kind))
                db.commit()
            db.close()
        except sqlite3.Error:
            pass


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
    settings["event_at"] = now + 30 * 86400      # serata dopo gli indizi
if state["game"]["deadline_custom"] and state["game"]["deadline_custom"] <= settings["hint2_at"]:
    settings["deadline"] = now + 29 * 86400      # chiusura pronostici dopo gli indizi e prima della serata
admin.put("/api/admin/settings", json=settings)

r = admin.post("/api/admin/draw", json={})
if r.status_code != 200:
    die("Estrazione non riuscita: " + (r.get_json() or {}).get("error", "errore sconosciuto"))
admin.post("/api/admin/logout", json={})
print("Estrazione di prova fatta (solo sulla copia).")

db = sqlite3.connect(PROVA_DIR / "secret_santa.db")
row = db.execute("SELECT code, id FROM participants WHERE name = ? COLLATE NOCASE", (NOME,)).fetchone()

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
    if row:
        print()
        print("VOTAZIONE DEI REGALI (dopo il podio): gli altri giocatori votano da soli, a caso;")
        print("il tuo voto lo dai dal tuo profilo di prova (entra con il tuo PIN):")
        print(f"     http://{ip or 'localhost'}:{PORT}/p/{row[0]}")
    threading.Thread(target=fake_voters, args=(row[1] if row else None,), daemon=True).start()
else:
    open_url = f"http://localhost:{PORT}/" + (f"p/{row[0]}" if row else "")
    if not row:
        print(f"(Nessun partecipante chiamato {NOME!r}: apro la home.)")
    print(f"\nServer di PROVA acceso su http://localhost:{PORT}")
    print("Entra con il tuo solito PIN.")
print("Chiudi questa finestra per spegnere la prova.\n")

threading.Timer(1.5, lambda: webbrowser.open(open_url)).start()
sb.app.run(host=host, port=PORT)
