"""Logica di gioco pura (nessun accesso a DB): estrazione, validazione pronostici, punteggi."""
import secrets

_rng = secrets.SystemRandom()


class GameError(Exception):
    """Errore mostrabile all'utente."""


# ---------------------------------------------------------------- estrazione

def draw(ids, forbidden=()):
    """Restituisce {giver_id: receiver_id}: nessuno pesca se stesso,
    ognuno riceve da una sola persona, le coppie in `forbidden` sono escluse.

    Prima prova il campionamento per rifiuto (distribuzione uniforme su tutte
    le estrazioni valide); se i vincoli sono molto stretti ripiega su un
    backtracking casuale.
    """
    ids = list(ids)
    if len(ids) < 3:
        raise GameError("Servono almeno 3 partecipanti per l'estrazione.")
    forbidden = set(forbidden)

    def valid(g, r):
        return g != r and (g, r) not in forbidden

    options = {g: [r for r in ids if valid(g, r)] for g in ids}
    for g, opts in options.items():
        if not opts:
            raise GameError("I vincoli sono troppo stretti: qualcuno non può pescare nessuno.")

    receivers = ids[:]
    for _ in range(20000):
        _rng.shuffle(receivers)
        if all(valid(g, r) for g, r in zip(ids, receivers)):
            return dict(zip(ids, receivers))

    # Fallback: backtracking casuale, partendo dal partecipante più vincolato.
    givers = sorted(ids, key=lambda g: (len(options[g]), _rng.random()))
    result, used, budget = {}, set(), [500000]

    def bt(i):
        if i == len(givers):
            return True
        budget[0] -= 1
        if budget[0] < 0:
            return False
        g = givers[i]
        cands = [r for r in options[g] if r not in used]
        _rng.shuffle(cands)
        for r in cands:
            result[g] = r
            used.add(r)
            if bt(i + 1):
                return True
            used.discard(r)
            del result[g]
        return False

    if not bt(0):
        raise GameError("Impossibile trovare un'estrazione che rispetti tutti i vincoli.")
    return result


def _hint_tier(candidates):
    """Più basso = migliore. Ideale: l'indizio lascia 2-3 persone possibili."""
    if 2 <= candidates <= 3:
        return 0
    if candidates == 4:
        return 1
    if candidates >= 5:
        return 2
    if candidates == 1:
        return 3     # darebbe la risposta (se vero) o è poco credibile (se falso)
    return 4         # falso e impossibile: nessuno corrisponde


HINTS_PER_PLAYER = 4      # di cui la metà veri
HINTS_PER_DATE = 2        # indizi 1-2 alla prima data, 3-4 alla seconda


def hint_group(slot):
    """A quale data di sblocco appartiene l'indizio numero `slot` (1-based): 1 o 2."""
    return (slot - 1) // HINTS_PER_DATE + 1


def generate_hints(assignments, traits, attrs, per_player=HINTS_PER_PLAYER):
    """Genera `per_player` indizi a testa: metà veri e metà falsi, in ordine casuale.

    assignments: {giver_id: receiver_id}
    traits: {trait_id: [valori possibili]}
    attrs: {participant_id: {trait_id: valore}}

    Tipi di indizio, riferiti a una coppia G -> R:
      - "santa_of": "Chi fa il regalo a R ha <caratteristica> = <valore>"  (valore vero = quello di G)
      - "gives_to": "G fa il regalo a qualcuno con <caratteristica> = <valore>"  (valore vero = quello di R)

    Regole: per il giocatore P si escludono la sua coppia (P -> X) e quella del
    bonus (chi -> P); ogni indizio di P riguarda una coppia diversa; nessuna frase
    è uguale a un'altra; ogni "fatto" (tipo + persona + caratteristica) compare
    al massimo una volta in tutto il gioco, così confrontando gli indizi non si
    trovano contraddizioni (vincolo morbido: cede solo se le caratteristiche sono
    troppo poche). Si preferiscono indizi che, dal punto di vista di P, lasciano
    2-3 candidati e coppie usate meno spesso.

    Restituisce {player_id: [hint, ...]} con hint = dict(kind, subject, trait, value, is_true).
    """
    if not traits:
        return {}
    ids = list(assignments)
    if len(ids) < per_player + 2:
        raise GameError(f"Per {per_player} indizi a testa servono almeno {per_player + 2} partecipanti.")

    used_statements = set()
    fact_usage = {}           # (kind, subject, trait) -> quante volte usato
    pair_usage = {g: 0 for g in ids}
    order = ids[:]
    _rng.shuffle(order)
    result = {}

    for p in order:
        x = assignments[p]
        truths = [True] * (per_player // 2) + [False] * (per_player - per_player // 2)
        _rng.shuffle(truths)
        used_pairs = set()
        hints = []
        for is_true in truths:
            best = None
            for g, r in assignments.items():
                if g == p or r == p or g in used_pairs:
                    continue
                for tid, options in traits.items():
                    for kind in ("santa_of", "gives_to"):
                        if kind == "santa_of":
                            subject, true_val = r, attrs[g][tid]
                            # Chi può regalare a R, secondo P: tutti tranne R e P stesso.
                            pool = [c for c in ids if c not in (r, p)]
                        else:
                            subject, true_val = g, attrs[r][tid]
                            # A chi può regalare G, secondo P: tutti tranne G e X (che riceve da P).
                            pool = [c for c in ids if c not in (g, x)]
                        fact = (kind, subject, tid)
                        values = [true_val] if is_true else [v for v in options if v != true_val]
                        for v in values:
                            stmt = (kind, subject, tid, v)
                            if stmt in used_statements:
                                continue
                            n = sum(1 for c in pool if attrs[c][tid] == v)
                            score = (fact_usage.get(fact, 0), _hint_tier(n), pair_usage[g], _rng.random())
                            if best is None or score < best[0]:
                                best = (score, stmt, g)
            if best is None:
                raise GameError("Impossibile generare gli indizi: aggiungi caratteristiche o partecipanti.")
            _, (kind, subject, tid, v), g = best
            used_statements.add((kind, subject, tid, v))
            fact_usage[(kind, subject, tid)] = fact_usage.get((kind, subject, tid), 0) + 1
            used_pairs.add(g)
            pair_usage[g] += 1
            hints.append({"kind": kind, "subject": subject, "trait": tid, "value": v, "is_true": is_true})
        result[p] = hints
    return result


def hint_is_true(hint, assignments, attrs):
    """Verifica (usata nei test) se un indizio è vero rispetto all'estrazione."""
    santa_of = {r: g for g, r in assignments.items()}
    if hint["kind"] == "santa_of":
        person = santa_of[hint["subject"]]
    else:
        person = assignments[hint["subject"]]
    return attrs[person][hint["trait"]] == hint["value"]


# ------------------------------------------------- caratteristiche da data di nascita

ZODIAC = [  # (segno, mese, giorno di inizio)
    ("Capricorno", 1, 1), ("Acquario", 1, 20), ("Pesci", 2, 19), ("Ariete", 3, 21),
    ("Toro", 4, 20), ("Gemelli", 5, 21), ("Cancro", 6, 21), ("Leone", 7, 23),
    ("Vergine", 8, 23), ("Bilancia", 9, 23), ("Scorpione", 10, 23), ("Sagittario", 11, 22),
    ("Capricorno", 12, 22),
]
ELEMENT = {
    "Ariete": "fuoco", "Leone": "fuoco", "Sagittario": "fuoco",
    "Toro": "terra", "Vergine": "terra", "Capricorno": "terra",
    "Gemelli": "aria", "Bilancia": "aria", "Acquario": "aria",
    "Cancro": "acqua", "Scorpione": "acqua", "Pesci": "acqua",
}

# Caratteristiche calcolate in automatico dalla data di nascita.
DERIVED_TRAITS = {
    "stagione": {"name": "Stagione di nascita", "options": ["inverno", "primavera", "estate", "autunno"]},
    "elemento": {"name": "Elemento zodiacale", "options": ["fuoco", "terra", "aria", "acqua"]},
    "segno": {"name": "Segno zodiacale", "options": [z[0] for z in ZODIAC[1:]]},
    "semestre": {"name": "Semestre di nascita", "options": ["gennaio-giugno", "luglio-dicembre"]},
    "eta": {"name": "Età nel gruppo", "options": ["metà più grande", "metà più giovane"]},
}


def zodiac_sign(month, day):
    sign = ZODIAC[0][0]
    for name, m, d in ZODIAC:
        if (month, day) >= (m, d):
            sign = name
    return sign


def derive_trait(kind, birthdate, all_birthdates):
    """Valore della caratteristica `kind` per la data `birthdate` (datetime.date).
    `all_birthdates` serve per "eta": il gruppo viene diviso a metà per età
    (con un numero dispari, la persona di mezzo va nella metà più grande)."""
    m, d = birthdate.month, birthdate.day
    if kind == "stagione":   # stagioni "per mesi": dic-feb, mar-mag, giu-ago, set-nov
        return {12: "inverno", 1: "inverno", 2: "inverno", 3: "primavera", 4: "primavera", 5: "primavera",
                6: "estate", 7: "estate", 8: "estate"}.get(m, "autunno")
    if kind == "segno":
        return zodiac_sign(m, d)
    if kind == "elemento":
        return ELEMENT[zodiac_sign(m, d)]
    if kind == "semestre":
        return "gennaio-giugno" if m <= 6 else "luglio-dicembre"
    if kind == "eta":
        ordered = sorted(all_birthdates)
        older_count = (len(ordered) + 1) // 2
        return "metà più grande" if birthdate <= ordered[older_count - 1] else "metà più giovane"
    raise GameError("Caratteristica automatica sconosciuta.")


def reveal_order(ids):
    order = list(ids)
    _rng.shuffle(order)
    return order


# ---------------------------------------------------------------- pronostici

def validate_guesses(player_id, my_receiver_id, participant_ids, guesses):
    """Valida i pronostici di un giocatore e restituisce {giver_id: receiver_id}.

    Regole:
    - non si pronostica la propria coppia (è già nota);
    - nessuno regala a se stesso;
    - la persona che ho pescato io non può ricevere da altri;
    - ognuno riceve da una sola persona (niente destinatari ripetuti).
    I pronostici possono essere parziali.
    """
    ids = set(participant_ids)
    clean = {}
    for g, r in guesses.items():
        try:
            g, r = int(g), int(r)
        except (TypeError, ValueError):
            raise GameError("Pronostico non valido.")
        if g not in ids or r not in ids:
            raise GameError("Partecipante sconosciuto nei pronostici.")
        if g == player_id:
            raise GameError("La tua coppia la conosci già: non va pronosticata.")
        if g == r:
            raise GameError("Nessuno può fare il regalo a se stesso.")
        if r == my_receiver_id:
            raise GameError("La persona che hai pescato riceve già il regalo da te.")
        clean[g] = r
    if len(set(clean.values())) != len(clean):
        raise GameError("Ognuno riceve il regalo da una sola persona: hai ripetuto un destinatario.")
    return clean


# ---------------------------------------------------------------- punteggi

def compute_scores(players, assignments, guesses_by_player, revealed_givers=None, bonus_points=2,
                   submitted_at=None):
    """Classifica.

    players: lista di (id, name)
    assignments: {giver_id: receiver_id}
    guesses_by_player: {player_id: {giver_id: receiver_id}}
    revealed_givers: insieme dei giver già svelati (None = tutti)
    submitted_at: {player_id: epoch dell'ultimo salvataggio dei pronostici}
    Punteggio: 1 punto per coppia indovinata (esclusa la propria) +
    `bonus_points` extra se si indovina chi fa il regalo a se stessi.
    Spareggio: a pari punti è più in alto chi ha salvato i pronostici prima
    (conta l'ultimo salvataggio). Resta pari merito solo chi ha stessi punti
    e stesso orario (in pratica: chi non ha mai consegnato).
    """
    submitted_at = submitted_at or {}
    if revealed_givers is None:
        revealed_givers = set(assignments)
    santa_of = {r: g for g, r in assignments.items()}

    rows = []
    for pid, name in players:
        guesses = guesses_by_player.get(pid, {})
        correct = {
            g for g, r in guesses.items()
            if g != pid and g in revealed_givers and assignments.get(g) == r
        }
        bonus = santa_of.get(pid) in correct
        points = len(correct) + (bonus_points if bonus else 0)
        rows.append({
            "id": pid,
            "name": name,
            "points": points,
            "correct": len(correct),
            "bonus": bonus,
            "submitted_at": submitted_at.get(pid),
        })

    def tiebreak(row):
        # Chi non ha mai salvato va in fondo a parità di punti.
        t = row["submitted_at"]
        return float("inf") if t is None else t

    rows.sort(key=lambda x: (-x["points"], tiebreak(x), x["name"].lower()))
    rank = 0
    prev = None
    for i, row in enumerate(rows, start=1):
        key = (row["points"], tiebreak(row))
        if key != prev:
            rank, prev = i, key
        row["rank"] = rank
    return rows
