"""Secret Betting — server Flask.

Il database SQLite vive solo sul server (cartella `instance/`, mai servita al
browser). I giocatori comunicano solo tramite le API qui sotto, che restituiscono
esclusivamente i loro dati: il proprio abbinamento e i propri pronostici.
L'admin gestisce il gioco ma non riceve mai l'esito dell'estrazione prima
della rivelazione.
"""
import hmac
import json
import os
import secrets
import socket
import sqlite3
import time
from collections import defaultdict
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import segno
from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import logic
from logic import GameError

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"


def _load_dotenv(path):
    """Mini-lettore di .env (KEY=VALUE), senza dipendenze esterne."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "instance"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "secret_santa.db"

PIN_MAX_ATTEMPTS = 5
PIN_LOCK_SECONDS = 10 * 60
ADMIN_MAX_ATTEMPTS = 10
ADMIN_LOCK_SECONDS = 10 * 60

DEFAULT_SETTINGS = {
    "game_name": "Secret Betting 2026",
    "phase": "setup",        # setup -> playing -> reveal
    "guesses_closed": "0",   # chiusura manuale dei pronostici
    "reveal_step": "0",
    "bonus_points": "2",     # extra per chi indovina il proprio Santa (totale 1 + 2 = 3)
    "hint1_at": "",          # sblocco indizi 1-2 (epoch) o vuoto
    "hint2_at": "",          # sblocco indizi 3-4 (epoch) o vuoto
    "event_at": "",          # data/ora della serata dello scambio (epoch) o vuoto
    "extra_timer_label": "Concepimento figlio Rocco",  # timer extra (goliardico)
    "extra_timer_at": "",
}

MAX_TRAITS = 8


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    key_file = DATA_DIR / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


app = Flask(__name__, static_folder=str(WEB_DIR / "static"), static_url_path="/static")
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=60),
    JSON_AS_ASCII=False,
)


# ======================================================================= DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS participants (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    code               TEXT NOT NULL UNIQUE,
    pin_hash           TEXT,
    pin_version        INTEGER NOT NULL DEFAULT 0,
    failed_attempts    INTEGER NOT NULL DEFAULT 0,
    locked_until       REAL NOT NULL DEFAULT 0,
    viewed_at          REAL,
    guesses_updated_at REAL,
    created_at         REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exclusions (
    giver_id    INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    receiver_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    PRIMARY KEY (giver_id, receiver_id)
);
CREATE TABLE IF NOT EXISTS assignments (
    giver_id     INTEGER PRIMARY KEY REFERENCES participants(id),
    receiver_id  INTEGER NOT NULL REFERENCES participants(id),
    reveal_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS guesses (
    player_id   INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    giver_id    INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    receiver_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    PRIMARY KEY (player_id, giver_id)
);
-- Caratteristiche per gli indizi (es. Altezza: bassa/media/alta)
CREATE TABLE IF NOT EXISTS traits (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    options  TEXT NOT NULL,          -- JSON: lista di valori
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trait_values (
    participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    trait_id       INTEGER NOT NULL REFERENCES traits(id) ON DELETE CASCADE,
    value          TEXT NOT NULL,
    PRIMARY KEY (participant_id, trait_id)
);
-- Indizi generati all'estrazione (2 a testa: uno vero, uno falso)
CREATE TABLE IF NOT EXISTS hints (
    player_id  INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    slot       INTEGER NOT NULL,
    kind       TEXT NOT NULL,         -- santa_of | gives_to
    subject_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    trait_id   INTEGER NOT NULL REFERENCES traits(id) ON DELETE CASCADE,
    value      TEXT NOT NULL,
    is_true    INTEGER NOT NULL,
    PRIMARY KEY (player_id, slot)
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def migrate(db):
    """Aggiunge le colonne nuove ai database creati con versioni precedenti,
    senza toccare i dati esistenti."""
    def columns(table):
        return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    if "birthdate" not in columns("participants"):
        db.execute("ALTER TABLE participants ADD COLUMN birthdate TEXT")      # YYYY-MM-DD, solo admin
    if "derived" not in columns("traits"):
        db.execute("ALTER TABLE traits ADD COLUMN derived TEXT")              # es. "stagione"; NULL = manuale


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    migrate(db)
    for key, value in DEFAULT_SETTINGS.items():
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    db.commit()
    db.close()


init_db()


def get_settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return s


def set_setting(key, value):
    get_db().execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def participants():
    return get_db().execute("SELECT * FROM participants ORDER BY name COLLATE NOCASE").fetchall()


def assignments_map():
    rows = get_db().execute("SELECT giver_id, receiver_id FROM assignments").fetchall()
    return {r["giver_id"]: r["receiver_id"] for r in rows}


def guesses_of(player_id):
    rows = get_db().execute(
        "SELECT giver_id, receiver_id FROM guesses WHERE player_id = ?", (player_id,)
    ).fetchall()
    return {r["giver_id"]: r["receiver_id"] for r in rows}


def guesses_open(s=None):
    s = s or get_settings()
    if s["phase"] != "playing" or s["guesses_closed"] == "1":
        return False
    # I pronostici si chiudono all'inizio della serata (così non ci si mette d'accordo parlandone).
    event_at = _epoch_or_none(s["event_at"])
    if event_at is not None and time.time() >= event_at:
        return False
    return True


def game_public(s=None):
    s = s or get_settings()
    return {
        "name": s["game_name"],
        "deadline": _epoch_or_none(s["event_at"]),   # la scadenza dei pronostici è la serata
        "phase": s["phase"],
        "guesses_open": guesses_open(s),
        "bonus_points": int(s["bonus_points"]),
        "hint_dates": [_epoch_or_none(s["hint1_at"]), _epoch_or_none(s["hint2_at"])],
        "event_at": _epoch_or_none(s["event_at"]),
        "extra_timer": {"label": s["extra_timer_label"], "at": _epoch_or_none(s["extra_timer_at"])},
    }


def traits_list():
    rows = get_db().execute("SELECT * FROM traits ORDER BY position, id").fetchall()
    return [
        {"id": r["id"], "name": r["name"], "options": json.loads(r["options"]), "derived": r["derived"]}
        for r in rows
    ]


def _parse_birthdate(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def recompute_derived(db):
    """Ricalcola le caratteristiche automatiche (da data di nascita) di tutti.
    Va chiamata dopo ogni modifica a date, partecipanti o caratteristiche automatiche:
    "Età nel gruppo" dipende da tutto il gruppo."""
    derived = db.execute("SELECT id, derived FROM traits WHERE derived IS NOT NULL").fetchall()
    if not derived:
        return
    people = db.execute("SELECT id, birthdate FROM participants").fetchall()
    dates = {p["id"]: _parse_birthdate(p["birthdate"]) for p in people}
    known = [d for d in dates.values() if d]
    for t in derived:
        db.execute("DELETE FROM trait_values WHERE trait_id = ?", (t["id"],))
        db.executemany(
            "INSERT INTO trait_values(participant_id, trait_id, value) VALUES (?, ?, ?)",
            [(pid, t["id"], logic.derive_trait(t["derived"], d, known)) for pid, d in dates.items() if d],
        )


def trait_values_map():
    """{participant_id: {trait_id: value}}"""
    out = defaultdict(dict)
    for r in get_db().execute("SELECT participant_id, trait_id, value FROM trait_values"):
        out[r["participant_id"]][r["trait_id"]] = r["value"]
    return out


def reveal_complete(s=None):
    s = s or get_settings()
    if s["phase"] != "reveal":
        return False
    total = get_db().execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
    return int(s["reveal_step"]) >= total


def _epoch_or_none(value):
    return float(value) if value not in (None, "") else None


def revealed_givers(s=None):
    s = s or get_settings()
    if s["phase"] != "reveal":
        return set()
    step = int(s["reveal_step"])
    rows = get_db().execute(
        "SELECT giver_id FROM assignments ORDER BY reveal_order LIMIT ?", (step,)
    ).fetchall()
    return {r["giver_id"] for r in rows}


# ================================================================= helpers

def ok(**data):
    return jsonify({"ok": True, **data})


def fail(message, status=400, **extra):
    return jsonify({"ok": False, "error": message, **extra}), status


@app.errorhandler(GameError)
def handle_game_error(err):
    return fail(str(err))


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@app.before_request
def require_json_for_writes():
    # Difesa CSRF: le richieste che modificano dati devono essere JSON
    # (un form di un altro sito non può inviarle senza preflight CORS).
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        if not request.is_json:
            return fail("Richiesta non valida.", 415)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def current_player():
    pid = session.get("pid")
    if pid is None:
        return None
    row = get_db().execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
    if row is None or row["pin_hash"] is None or row["pin_version"] != session.get("pin_ver"):
        return None
    return row


def player_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        player = current_player()
        if player is None:
            return fail("Accesso richiesto.", 401)
        g.player = player
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return fail("Accesso admin richiesto.", 401)
        return fn(*args, **kwargs)
    return wrapper


def require_phase(*phases):
    phase = get_settings()["phase"]
    if phase not in phases:
        raise GameError({
            "setup": "Operazione non possibile: l'estrazione non è ancora stata fatta.",
            "playing": "Operazione non possibile: l'estrazione è già stata fatta.",
            "reveal": "Operazione non possibile: la rivelazione è in corso.",
        }[phase])


# =================================================================== pagine

def page(name):
    return send_from_directory(WEB_DIR, name)


@app.get("/")
def index_page():
    return page("index.html")


@app.get("/p/<code>")
def login_page(code):
    return page("login.html")


@app.get("/me")
def me_page():
    return page("me.html")


@app.get("/admin")
def admin_page():
    return page("admin.html")


@app.get("/reveal")
def reveal_page():
    return page("reveal.html")


@app.get("/telecomando")
def remote_page():
    return page("telecomando.html")


# ============================================================ auth giocatore

@app.get("/api/auth/link/<code>")
def link_info(code):
    row = get_db().execute("SELECT name, pin_hash FROM participants WHERE code = ?", (code,)).fetchone()
    if row is None:
        return fail("Link non valido. Chiedi all'admin un nuovo link.", 404)
    return ok(name=row["name"], pin_set=row["pin_hash"] is not None)


@app.post("/api/auth/pin")
def login_pin():
    data = body()
    code = str(data.get("code", ""))
    pin = str(data.get("pin", ""))
    db = get_db()
    row = db.execute("SELECT * FROM participants WHERE code = ?", (code,)).fetchone()
    if row is None:
        return fail("Link non valido.", 404)

    now = time.time()
    if row["pin_hash"] is None:
        # Primo accesso: il giocatore sceglie il proprio PIN.
        if not (pin.isdigit() and 4 <= len(pin) <= 8):
            return fail("Il PIN deve avere da 4 a 8 cifre.")
        version = row["pin_version"] + 1
        db.execute(
            "UPDATE participants SET pin_hash = ?, pin_version = ?, failed_attempts = 0, locked_until = 0 "
            "WHERE id = ?",
            (generate_password_hash(pin), version, row["id"]),
        )
        db.commit()
    else:
        if row["locked_until"] > now:
            minutes = int((row["locked_until"] - now) // 60) + 1
            return fail(f"Troppi tentativi. Riprova tra {minutes} minuti.", 429)
        if not check_password_hash(row["pin_hash"], pin):
            failed = row["failed_attempts"] + 1
            if failed >= PIN_MAX_ATTEMPTS:
                db.execute(
                    "UPDATE participants SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                    (now + PIN_LOCK_SECONDS, row["id"]),
                )
                db.commit()
                return fail("PIN errato. Troppi tentativi: accesso bloccato per 10 minuti.", 429)
            db.execute("UPDATE participants SET failed_attempts = ? WHERE id = ?", (failed, row["id"]))
            db.commit()
            return fail(f"PIN errato. Tentativi rimasti: {PIN_MAX_ATTEMPTS - failed}.", 401)
        version = row["pin_version"]
        db.execute("UPDATE participants SET failed_attempts = 0 WHERE id = ?", (row["id"],))
        db.commit()

    session.permanent = True
    session["pid"] = row["id"]
    session["pin_ver"] = version
    return ok(name=row["name"])


@app.post("/api/auth/logout")
def logout():
    session.pop("pid", None)
    session.pop("pin_ver", None)
    return ok()


# ========================================================= area giocatore

@app.get("/api/me")
@player_required
def me():
    db = get_db()
    s = get_settings()
    me_row = g.player
    people = participants()
    names = {p["id"]: p["name"] for p in people}

    assignment = None
    if s["phase"] in ("playing", "reveal"):
        a = db.execute("SELECT receiver_id FROM assignments WHERE giver_id = ?", (me_row["id"],)).fetchone()
        if a is not None:
            assignment = {"id": a["receiver_id"], "name": names.get(a["receiver_id"])}
            if me_row["viewed_at"] is None:
                db.execute("UPDATE participants SET viewed_at = ? WHERE id = ?", (time.time(), me_row["id"]))
                db.commit()

    my_guesses = guesses_of(me_row["id"])
    results = None
    if s["phase"] == "reveal":
        amap = assignments_map()
        shown = revealed_givers(s)
        board = logic.compute_scores(
            [(p["id"], p["name"]) for p in people],
            amap,
            {pid: guesses_of(pid) for pid in names},
            shown,
            int(s["bonus_points"]),
            {p["id"]: p["guesses_updated_at"] for p in people},
        )
        mine = next(r for r in board if r["id"] == me_row["id"])
        results = {
            "rank": mine["rank"],
            "points": mine["points"],
            "correct": mine["correct"],
            "bonus": mine["bonus"],
            "total_players": len(board),
            # Solo le coppie già svelate: {giver_id: receiver_id}
            "revealed": {str(gid): amap[gid] for gid in shown},
        }
        if len(shown) == len(amap):
            # A rivelazione completa ognuno può guardare i pronostici degli altri (uno alla volta, nella pagina).
            results["others"] = [
                {"id": r["id"], "name": r["name"], "rank": r["rank"], "points": r["points"],
                 "correct": r["correct"], "bonus": r["bonus"],
                 "guesses": {str(k): v for k, v in guesses_of(r["id"]).items()}}
                for r in board if r["id"] != me_row["id"]
            ]

    return ok(
        me={"id": me_row["id"], "name": me_row["name"]},
        game=game_public(s),
        participants=[{"id": p["id"], "name": p["name"]} for p in people],
        assignment=assignment,
        guesses={str(k): v for k, v in my_guesses.items()},
        guesses_updated_at=me_row["guesses_updated_at"],
        results=results,
        hints=player_hints(me_row["id"], s, names),
        has_traits=bool(traits_list()),
    )


def _hint_payload(row, names, show_truth):
    item = {
        "kind": row["kind"],
        "subject": names.get(row["subject_id"], "?"),
        "trait": row["trait_name"],
        "value": row["value"],
    }
    if show_truth:
        item["is_true"] = bool(row["is_true"])
    return item


def player_hints(player_id, s, names):
    """Indizi del giocatore. Il contenuto di un indizio ancora bloccato non
    lascia mai il server; vero/falso si scopre solo a rivelazione completata."""
    if s["phase"] not in ("playing", "reveal"):
        return []
    rows = get_db().execute(
        "SELECT h.*, t.name AS trait_name FROM hints h JOIN traits t ON t.id = h.trait_id "
        "WHERE h.player_id = ? ORDER BY h.slot",
        (player_id,),
    ).fetchall()
    now = time.time()
    complete = reveal_complete(s)
    out = []
    for row in rows:
        unlock_at = _epoch_or_none(s.get(f"hint{logic.hint_group(row['slot'])}_at"))
        unlocked = s["phase"] == "reveal" or (unlock_at is not None and now >= unlock_at)
        item = {"slot": row["slot"], "unlock_at": unlock_at, "unlocked": unlocked}
        if unlocked:
            item.update(_hint_payload(row, names, complete))
        out.append(item)
    return out


@app.put("/api/me/guesses")
@player_required
def save_guesses():
    s = get_settings()
    if not guesses_open(s):
        return fail("I pronostici sono chiusi.", 403)
    db = get_db()
    me_row = g.player
    a = db.execute("SELECT receiver_id FROM assignments WHERE giver_id = ?", (me_row["id"],)).fetchone()
    if a is None:
        return fail("Estrazione non trovata.", 409)
    raw = body().get("guesses", {})
    if not isinstance(raw, dict):
        return fail("Formato non valido.")
    ids = [p["id"] for p in participants()]
    clean = logic.validate_guesses(me_row["id"], a["receiver_id"], ids, raw)

    now = time.time()
    db.execute("DELETE FROM guesses WHERE player_id = ?", (me_row["id"],))
    db.executemany(
        "INSERT INTO guesses(player_id, giver_id, receiver_id) VALUES (?, ?, ?)",
        [(me_row["id"], gid, rid) for gid, rid in clean.items()],
    )
    db.execute("UPDATE participants SET guesses_updated_at = ? WHERE id = ?", (now, me_row["id"]))
    db.commit()
    return ok(saved=len(clean), total=len(ids) - 1, updated_at=now)


# ============================================================ admin: auth

_admin_failures = defaultdict(list)  # ip -> [timestamp, ...]


@app.post("/api/admin/login")
def admin_login():
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        return fail("ADMIN_PASSWORD non configurata sul server.", 500)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    now = time.time()
    recent = [t for t in _admin_failures[ip] if now - t < ADMIN_LOCK_SECONDS]
    _admin_failures[ip] = recent
    if len(recent) >= ADMIN_MAX_ATTEMPTS:
        return fail("Troppi tentativi. Riprova più tardi.", 429)
    password = str(body().get("password", ""))
    if not hmac.compare_digest(password.encode(), expected.encode()):
        recent.append(now)
        return fail("Password errata.", 401)
    _admin_failures.pop(ip, None)
    session.permanent = True
    session["admin"] = True
    return ok()


@app.post("/api/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return ok()


# ============================================================ admin: stato

@app.get("/api/admin/state")
@admin_required
def admin_state():
    db = get_db()
    s = get_settings()
    people = participants()
    total = len(people)
    counts = {
        r["player_id"]: r["n"]
        for r in db.execute("SELECT player_id, COUNT(*) AS n FROM guesses GROUP BY player_id")
    }
    exclusions = db.execute("SELECT giver_id, receiver_id FROM exclusions").fetchall()
    drawn = db.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] > 0
    now = time.time()
    # NB: l'esito dell'estrazione NON viene mai restituito all'admin.
    return ok(
        game=game_public(s),
        reveal_step=int(s["reveal_step"]),
        drawn=drawn,
        anyone_viewed=any(p["viewed_at"] for p in people),
        participants=[
            {
                "id": p["id"],
                "name": p["name"],
                "code": p["code"],
                "pin_set": p["pin_hash"] is not None,
                "birthdate": p["birthdate"],   # solo per l'admin, mai inviata ai giocatori
                "locked": p["locked_until"] > now,
                "viewed": p["viewed_at"] is not None,
                "guesses": counts.get(p["id"], 0),
                "guesses_total": max(total - 1, 0),
                "guesses_updated_at": p["guesses_updated_at"],
            }
            for p in people
        ],
        exclusions=[{"giver_id": e["giver_id"], "receiver_id": e["receiver_id"]} for e in exclusions],
        traits=traits_list(),
        trait_values={str(pid): {str(t): v for t, v in vals.items()} for pid, vals in trait_values_map().items()},
        # Solo quanti indizi esistono, mai il loro contenuto.
        hints_count=db.execute("SELECT COUNT(*) FROM hints").fetchone()[0],
    )


@app.put("/api/admin/settings")
@admin_required
def admin_settings():
    data = body()
    if "game_name" in data:
        name = str(data["game_name"]).strip()[:80]
        if not name:
            return fail("Il nome del gioco non può essere vuoto.")
        set_setting("game_name", name)
    for key, label in (("hint1_at", "Data indizi 1-2"), ("hint2_at", "Data indizi 3-4"), ("event_at", "Data dell'evento"), ("extra_timer_at", "Data del timer extra")):
        if key in data:
            value = data[key]
            if value in (None, ""):
                set_setting(key, "")
            else:
                try:
                    set_setting(key, float(value))
                except (TypeError, ValueError):
                    return fail(f"{label} non valida.")
    s = get_settings()
    ev = _epoch_or_none(s["event_at"])
    for key, label in (("hint1_at", "indizi 1-2"), ("hint2_at", "indizi 3-4")):
        at = _epoch_or_none(s[key])
        if ev is not None and at is not None and at >= ev:
            return fail(f"Lo sblocco degli {label} deve essere prima della serata "
                        "(alla serata i pronostici si chiudono).")
    if "extra_timer_label" in data:
        label = str(data["extra_timer_label"] or "").strip()[:60]
        if not label:
            return fail("Il nome del timer extra non può essere vuoto.")
        set_setting("extra_timer_label", label)
    if "bonus_points" in data:
        try:
            bp = int(data["bonus_points"])
        except (TypeError, ValueError):
            return fail("Bonus non valido.")
        if not 0 <= bp <= 10:
            return fail("Il bonus deve essere tra 0 e 10.")
        set_setting("bonus_points", bp)
    get_db().commit()
    return ok()


# ====================================================== admin: partecipanti

def _clean_name(raw):
    name = " ".join(str(raw or "").split())[:40]
    if not name:
        raise GameError("Il nome non può essere vuoto.")
    return name


@app.post("/api/admin/participants")
@admin_required
def add_participant():
    require_phase("setup")
    name = _clean_name(body().get("name"))
    db = get_db()
    try:
        db.execute(
            "INSERT INTO participants(name, code, created_at) VALUES (?, ?, ?)",
            (name, secrets.token_urlsafe(12), time.time()),
        )
    except sqlite3.IntegrityError:
        return fail(f"Esiste già un partecipante chiamato «{name}».")
    db.commit()
    return ok()


@app.patch("/api/admin/participants/<int:pid>")
@admin_required
def rename_participant(pid):
    name = _clean_name(body().get("name"))
    db = get_db()
    try:
        cur = db.execute("UPDATE participants SET name = ? WHERE id = ?", (name, pid))
    except sqlite3.IntegrityError:
        return fail(f"Esiste già un partecipante chiamato «{name}».")
    if cur.rowcount == 0:
        return fail("Partecipante non trovato.", 404)
    db.commit()
    return ok()


@app.delete("/api/admin/participants/<int:pid>")
@admin_required
def delete_participant(pid):
    require_phase("setup")
    db = get_db()
    db.execute("DELETE FROM participants WHERE id = ?", (pid,))
    recompute_derived(db)
    db.commit()
    return ok()


@app.put("/api/admin/participants/<int:pid>/birthdate")
@admin_required
def set_birthdate(pid):
    """La data di nascita la vede solo l'admin: ai giocatori arrivano solo
    le caratteristiche calcolate (stagione, segno, ...)."""
    require_phase("setup")
    raw = str(body().get("birthdate") or "").strip()
    value = None
    if raw:
        d = _parse_birthdate(raw)
        if d is None or not (date(1900, 1, 1) <= d <= date.today()):
            return fail("Data di nascita non valida.")
        value = d.isoformat()
    db = get_db()
    cur = db.execute("UPDATE participants SET birthdate = ? WHERE id = ?", (value, pid))
    if cur.rowcount == 0:
        return fail("Partecipante non trovato.", 404)
    recompute_derived(db)
    db.commit()
    return ok()


@app.post("/api/admin/participants/<int:pid>/reset-pin")
@admin_required
def reset_pin(pid):
    db = get_db()
    cur = db.execute(
        "UPDATE participants SET pin_hash = NULL, pin_version = pin_version + 1, "
        "failed_attempts = 0, locked_until = 0 WHERE id = ?",
        (pid,),
    )
    if cur.rowcount == 0:
        return fail("Partecipante non trovato.", 404)
    db.commit()
    return ok()


@app.post("/api/admin/participants/<int:pid>/new-link")
@admin_required
def new_link(pid):
    db = get_db()
    cur = db.execute("UPDATE participants SET code = ? WHERE id = ?", (secrets.token_urlsafe(12), pid))
    if cur.rowcount == 0:
        return fail("Partecipante non trovato.", 404)
    db.commit()
    return ok()


# ========================================================== admin: vincoli

@app.post("/api/admin/exclusions")
@admin_required
def add_exclusion():
    require_phase("setup")
    data = body()
    try:
        giver, receiver = int(data.get("giver_id")), int(data.get("receiver_id"))
    except (TypeError, ValueError):
        return fail("Seleziona due partecipanti.")
    if giver == receiver:
        return fail("Seleziona due partecipanti diversi.")
    ids = {p["id"] for p in participants()}
    if giver not in ids or receiver not in ids:
        return fail("Partecipante non trovato.", 404)
    pairs = [(giver, receiver)]
    if data.get("both"):
        pairs.append((receiver, giver))
    db = get_db()
    db.executemany("INSERT OR IGNORE INTO exclusions(giver_id, receiver_id) VALUES (?, ?)", pairs)
    db.commit()
    return ok()


@app.delete("/api/admin/exclusions")
@admin_required
def delete_exclusion():
    require_phase("setup")
    data = body()
    db = get_db()
    db.execute(
        "DELETE FROM exclusions WHERE giver_id = ? AND receiver_id = ?",
        (data.get("giver_id"), data.get("receiver_id")),
    )
    db.commit()
    return ok()


# ================================================ admin: caratteristiche

def _clean_trait(data):
    name = " ".join(str(data.get("name") or "").split())[:30]
    if not name:
        raise GameError("Dai un nome alla caratteristica.")
    raw = data.get("options")
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        raise GameError("Valori non validi.")
    options, seen = [], set()
    for opt in raw:
        opt = " ".join(str(opt).split())[:30]
        if opt and opt.lower() not in seen:
            seen.add(opt.lower())
            options.append(opt)
    if not 2 <= len(options) <= 10:
        raise GameError("Ogni caratteristica deve avere da 2 a 10 valori diversi.")
    return name, options


@app.post("/api/admin/traits")
@admin_required
def add_trait():
    require_phase("setup")
    data = body()
    derived = data.get("derived")
    if derived:
        # Caratteristica automatica: nome e valori sono fissi.
        spec = logic.DERIVED_TRAITS.get(str(derived))
        if spec is None:
            return fail("Caratteristica automatica sconosciuta.")
        name, options = spec["name"], spec["options"]
    else:
        derived = None
        name, options = _clean_trait(data)
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM traits").fetchone()[0] >= MAX_TRAITS:
        return fail(f"Massimo {MAX_TRAITS} caratteristiche.")
    if derived and db.execute("SELECT 1 FROM traits WHERE derived = ?", (derived,)).fetchone():
        return fail(f"«{name}» è già presente.")
    pos = db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM traits").fetchone()[0]
    try:
        db.execute("INSERT INTO traits(name, options, position, derived) VALUES (?, ?, ?, ?)",
                   (name, json.dumps(options, ensure_ascii=False), pos, derived))
    except sqlite3.IntegrityError:
        return fail(f"Esiste già una caratteristica «{name}».")
    recompute_derived(db)
    db.commit()
    return ok()


def _is_derived(db, tid):
    row = db.execute("SELECT derived FROM traits WHERE id = ?", (tid,)).fetchone()
    return row is not None and row["derived"] is not None


@app.put("/api/admin/traits/<int:tid>")
@admin_required
def edit_trait(tid):
    require_phase("setup")
    name, options = _clean_trait(body())
    db = get_db()
    if _is_derived(db, tid):
        return fail("Le caratteristiche calcolate dalla data di nascita non si modificano: puoi solo eliminarle.")
    try:
        cur = db.execute("UPDATE traits SET name = ?, options = ? WHERE id = ?",
                         (name, json.dumps(options, ensure_ascii=False), tid))
    except sqlite3.IntegrityError:
        return fail(f"Esiste già una caratteristica «{name}».")
    if cur.rowcount == 0:
        return fail("Caratteristica non trovata.", 404)
    # I valori non più previsti vanno ricompilati.
    placeholders = ",".join("?" * len(options))
    db.execute(f"DELETE FROM trait_values WHERE trait_id = ? AND value NOT IN ({placeholders})", (tid, *options))
    db.commit()
    return ok()


@app.delete("/api/admin/traits/<int:tid>")
@admin_required
def delete_trait(tid):
    require_phase("setup")
    db = get_db()
    db.execute("DELETE FROM traits WHERE id = ?", (tid,))
    db.commit()
    return ok()


@app.put("/api/admin/trait-values")
@admin_required
def set_trait_value():
    require_phase("setup")
    data = body()
    try:
        pid, tid = int(data.get("participant_id")), int(data.get("trait_id"))
    except (TypeError, ValueError):
        return fail("Richiesta non valida.")
    value = str(data.get("value") or "")
    db = get_db()
    trait = db.execute("SELECT options FROM traits WHERE id = ?", (tid,)).fetchone()
    if trait is None or db.execute("SELECT 1 FROM participants WHERE id = ?", (pid,)).fetchone() is None:
        return fail("Non trovato.", 404)
    if _is_derived(db, tid):
        return fail("Questo valore si calcola dalla data di nascita.")
    if not value:
        db.execute("DELETE FROM trait_values WHERE participant_id = ? AND trait_id = ?", (pid, tid))
    else:
        if value not in json.loads(trait["options"]):
            return fail("Valore non previsto per questa caratteristica.")
        db.execute(
            "INSERT INTO trait_values(participant_id, trait_id, value) VALUES (?, ?, ?) "
            "ON CONFLICT(participant_id, trait_id) DO UPDATE SET value = excluded.value",
            (pid, tid, value),
        )
    db.commit()
    return ok()


# ======================================================= admin: estrazione

@app.post("/api/admin/draw")
@admin_required
def do_draw():
    require_phase("setup")
    db = get_db()
    ids = [p["id"] for p in participants()]
    forbidden = [(r["giver_id"], r["receiver_id"]) for r in db.execute("SELECT * FROM exclusions")]
    traits = {t["id"]: t["options"] for t in traits_list()}
    attrs = trait_values_map()
    if traits:
        missing = [p["name"] for p in participants() if len(attrs.get(p["id"], {})) < len(traits)]
        if missing:
            raise GameError("Completa le schede prima dell'estrazione. Mancano dati per: " + ", ".join(missing))
    result = logic.draw(ids, forbidden)
    hints = logic.generate_hints(result, traits, attrs)
    order = {gid: i for i, gid in enumerate(logic.reveal_order(ids))}
    db.execute("DELETE FROM assignments")
    db.execute("DELETE FROM guesses")
    db.execute("DELETE FROM hints")
    db.executemany(
        "INSERT INTO assignments(giver_id, receiver_id, reveal_order) VALUES (?, ?, ?)",
        [(gid, rid, order[gid]) for gid, rid in result.items()],
    )
    db.executemany(
        "INSERT INTO hints(player_id, slot, kind, subject_id, trait_id, value, is_true) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (pid, slot, h["kind"], h["subject"], h["trait"], h["value"], int(h["is_true"]))
            for pid, hs in hints.items()
            for slot, h in enumerate(hs, start=1)
        ],
    )
    db.execute("UPDATE participants SET viewed_at = NULL, guesses_updated_at = NULL")
    set_setting("phase", "playing")
    set_setting("guesses_closed", "0")
    set_setting("reveal_step", "0")
    db.commit()
    return ok()


@app.post("/api/admin/undo-draw")
@admin_required
def undo_draw():
    require_phase("playing")
    db = get_db()
    viewed = db.execute("SELECT COUNT(*) FROM participants WHERE viewed_at IS NOT NULL").fetchone()[0]
    if viewed:
        return fail("Qualcuno ha già visto il proprio abbinamento: l'estrazione non si può più annullare.", 409)
    db.execute("DELETE FROM assignments")
    db.execute("DELETE FROM guesses")
    db.execute("DELETE FROM hints")
    set_setting("phase", "setup")
    db.commit()
    return ok()


@app.post("/api/admin/guesses")
@admin_required
def toggle_guesses():
    require_phase("playing")
    set_setting("guesses_closed", "1" if body().get("closed") else "0")
    get_db().commit()
    return ok()


# ====================================================== admin: rivelazione

@app.post("/api/admin/reveal")
@admin_required
def reveal_control():
    action = body().get("action")
    s = get_settings()
    total = get_db().execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
    step = int(s["reveal_step"])

    if action == "start":
        require_phase("playing")
        set_setting("phase", "reveal")
        set_setting("guesses_closed", "1")
        set_setting("reveal_step", 0)
    elif action == "stop":
        require_phase("reveal")
        if step > 0:
            return fail("La rivelazione è già iniziata: torna prima a 0 coppie svelate.", 409)
        set_setting("phase", "playing")
    elif action in ("next", "prev", "all"):
        require_phase("reveal")
        step = {"next": min(step + 1, total), "prev": max(step - 1, 0), "all": total}[action]
        set_setting("reveal_step", step)
    else:
        return fail("Azione sconosciuta.")
    get_db().commit()
    return ok()


@app.get("/api/admin/remote")
@admin_required
def remote_state():
    """Stato minimo per il telecomando: solo contatori, mai le coppie
    (l'admin gioca anche lui: la coppia la scopre sul maxischermo con gli altri)."""
    db = get_db()
    s = get_settings()
    return ok(
        phase=s["phase"],
        step=int(s["reveal_step"]),
        total=db.execute("SELECT COUNT(*) FROM assignments").fetchone()[0],
        players=len(participants()),
        submitted=db.execute(
            "SELECT COUNT(*) FROM participants WHERE guesses_updated_at IS NOT NULL").fetchone()[0],
        guesses_open=guesses_open(s),
    )


def lan_ip():
    """IP del PC nella rete locale (nessun pacchetto viene inviato davvero)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return None


@app.get("/api/remote-qr")
def remote_qr():
    """QR con l'indirizzo del telecomando, da mostrare sul maxischermo.
    Contiene solo l'indirizzo: per usare il telecomando serve comunque la password admin."""
    url = app.config.get("REMOTE_URL")
    if not url:
        if request.host.split(":")[0] in ("localhost", "127.0.0.1", "[::1]"):
            # Da localhost il telefono non arriva: se il server non è aperto alla rete, niente QR.
            return fail("Server non raggiungibile dalla rete locale.", 404)
        url = request.host_url.rstrip("/") + "/telecomando"
    qr = segno.make(url, error="m")
    return ok(url=url, svg=qr.svg_data_uri(scale=8, border=2, dark="#0b1f2a", light="#ffffff"))


# =================================================== rivelazione pubblica

@app.get("/api/reveal")
def reveal_state():
    db = get_db()
    s = get_settings()
    people = participants()
    names = {p["id"]: p["name"] for p in people}
    data = {"game": game_public(s), "players": len(people)}

    if s["phase"] != "reveal":
        data["submitted"] = db.execute(
            "SELECT COUNT(*) FROM participants WHERE guesses_updated_at IS NOT NULL"
        ).fetchone()[0]
        return ok(**data)

    step = int(s["reveal_step"])
    rows = db.execute(
        "SELECT giver_id, receiver_id FROM assignments ORDER BY reveal_order LIMIT ?", (step,)
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
    shown = {r["giver_id"] for r in rows}
    board = logic.compute_scores(
        [(p["id"], p["name"]) for p in people],
        assignments_map(),
        {pid: guesses_of(pid) for pid in names},
        shown,
        int(s["bonus_points"]),
        {p["id"]: p["guesses_updated_at"] for p in people},
    )
    # Per ogni coppia svelata: chi l'aveva indovinata e l'errore più comune.
    pairs = []
    for r in rows:
        votes = db.execute(
            "SELECT player_id, receiver_id FROM guesses WHERE giver_id = ? AND player_id != ?",
            (r["giver_id"], r["giver_id"]),
        ).fetchall()
        right = sorted((names[v["player_id"]] for v in votes if v["receiver_id"] == r["receiver_id"]), key=str.lower)
        wrong = defaultdict(int)
        for v in votes:
            if v["receiver_id"] != r["receiver_id"]:
                wrong[v["receiver_id"]] += 1
        top_wrong = None
        if wrong:
            rid, n = min(wrong.items(), key=lambda kv: (-kv[1], names[kv[0]].lower()))
            if n >= 2:   # un errore isolato non è una notizia
                top_wrong = {"receiver": names[rid], "count": n}
        pairs.append({
            "giver": names[r["giver_id"]], "receiver": names[r["receiver_id"]], "hits": len(right),
            "guessed_by": right,
            # il destinatario aveva indovinato chi gli fa il regalo (bonus)
            "receiver_knew": any(v["player_id"] == r["receiver_id"] and v["receiver_id"] == r["receiver_id"]
                                 for v in votes),
            "top_wrong": top_wrong,
        })
    all_hints = []
    if step >= total:
        # A rivelazione completa si mostrano tutti gli indizi distribuiti, con vero/falso.
        rows = db.execute(
            "SELECT h.*, t.name AS trait_name FROM hints h JOIN traits t ON t.id = h.trait_id "
            "ORDER BY h.player_id, h.slot"
        ).fetchall()
        all_hints = [
            {"player": names.get(r["player_id"], "?"), "slot": r["slot"], **_hint_payload(r, names, True)}
            for r in rows
        ]
        all_hints.sort(key=lambda x: (x["player"].lower(), x["slot"]))
    data.update(
        step=step,
        total=total,
        complete=step >= total,
        hints=all_hints,
        pairs=pairs,
        leaderboard=[{k: row[k] for k in ("rank", "name", "points", "correct", "bonus")} for row in board],
    )
    return ok(**data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    if os.environ.get("REMOTE_URL"):
        app.config["REMOTE_URL"] = os.environ["REMOTE_URL"]
    elif host not in ("127.0.0.1", "localhost") and lan_ip():
        app.config["REMOTE_URL"] = f"http://{lan_ip()}:{port}/telecomando"
    app.run(host=host, port=port, debug=os.environ.get("DEBUG") == "1")
