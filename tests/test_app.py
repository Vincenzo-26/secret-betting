"""Test di logica e API. Esegui con:  python -m unittest discover tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# DB temporaneo e password admin di test, impostati prima di importare l'app.
_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["ADMIN_PASSWORD"] = "test-admin"
os.environ["SECRET_KEY"] = "test-secret"

import logic  # noqa: E402
from logic import GameError  # noqa: E402


class LogicTests(unittest.TestCase):
    def test_draw_is_valid_derangement(self):
        ids = list(range(1, 16))
        for _ in range(200):
            res = logic.draw(ids)
            self.assertEqual(sorted(res), ids)
            self.assertEqual(sorted(res.values()), ids)
            self.assertTrue(all(g != r for g, r in res.items()))

    def test_draw_respects_exclusions(self):
        ids = [1, 2, 3, 4, 5, 6]
        forbidden = {(1, 2), (2, 1), (3, 4), (4, 3), (5, 6), (6, 5)}
        for _ in range(200):
            res = logic.draw(ids, forbidden)
            self.assertFalse(set(res.items()) & forbidden)

    def test_draw_impossible(self):
        with self.assertRaises(GameError):
            logic.draw([1, 2, 3], {(1, 2), (1, 3)})
        with self.assertRaises(GameError):
            logic.draw([1, 2])

    def test_validate_guesses(self):
        ids = [1, 2, 3, 4]
        # giocatore 1 ha pescato 2
        self.assertEqual(logic.validate_guesses(1, 2, ids, {"3": "4", "4": "1"}), {3: 4, 4: 1})
        bad = [
            {"1": "3"},            # la propria coppia
            {"3": "3"},            # regalo a se stesso
            {"3": "2"},            # 2 riceve già da me
            {"3": "1", "4": "1"},  # destinatario ripetuto
            {"9": "1"},            # sconosciuto
        ]
        for guesses in bad:
            with self.assertRaises(GameError, msg=guesses):
                logic.validate_guesses(1, 2, ids, guesses)

    def test_scores_with_bonus(self):
        players = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]
        assign = {1: 2, 2: 3, 3: 4, 4: 1}
        guesses = {
            1: {2: 3, 3: 4, 4: 1},   # tutto giusto, incluso chi regala a lui (4) -> 3 + bonus
            2: {1: 4, 3: 1, 4: 2},   # tutto sbagliato
            3: {1: 2},               # 1 giusta, non bonus
        }
        board = {r["name"]: r for r in logic.compute_scores(players, assign, guesses, bonus_points=1)}
        self.assertEqual(board["A"]["points"], 4)
        self.assertTrue(board["A"]["bonus"])
        self.assertEqual(board["B"]["points"], 0)
        self.assertEqual(board["C"]["points"], 1)
        self.assertEqual(board["A"]["rank"], 1)
        self.assertEqual(board["B"]["rank"], board["D"]["rank"])  # parità (nessuno ha consegnato)

    def test_santa_pair_worth_three_by_default(self):
        players = [(1, "A"), (2, "B"), (3, "C")]
        assign = {1: 2, 2: 3, 3: 1}           # chi regala ad A è C
        board = {r["name"]: r for r in logic.compute_scores(players, assign, {1: {3: 1}})}
        self.assertEqual(board["A"]["points"], 3)
        self.assertTrue(board["A"]["bonus"])

    def test_tiebreak_earliest_save_wins(self):
        players = [(1, "Zoe"), (2, "Anna"), (3, "Bea"), (4, "Carlo")]
        assign = {1: 2, 2: 3, 3: 4, 4: 1}
        guesses = {1: {2: 3}, 2: {3: 4}, 3: {4: 1}}       # tutti 1 punto, nessun bonus
        saved = {1: 100.0, 2: 300.0, 3: 200.0}            # Carlo non ha consegnato
        board = logic.compute_scores(players, assign, guesses, submitted_at=saved)
        self.assertEqual([r["name"] for r in board], ["Zoe", "Bea", "Anna", "Carlo"])
        self.assertEqual([r["rank"] for r in board], [1, 2, 3, 4])
        # Punti diversi contano sempre più dell'orario
        guesses[2] = {3: 4, 4: 1}
        board = logic.compute_scores(players, assign, guesses, submitted_at=saved)
        self.assertEqual(board[0]["name"], "Anna")

    def test_scores_only_revealed(self):
        players = [(1, "A"), (2, "B"), (3, "C")]
        assign = {1: 2, 2: 3, 3: 1}
        guesses = {1: {2: 3, 3: 1}}
        board = {r["name"]: r for r in logic.compute_scores(players, assign, guesses, revealed_givers={2})}
        self.assertEqual(board["A"]["points"], 1)

    def test_hints_rules(self):
        import random
        traits = {1: ["bassa", "media", "alta"], 2: ["biondi", "castani", "neri", "altro"],
                  3: ["mare", "montagna", "città"], 4: ["caffè", "tè", "niente"], 5: ["cane", "gatto", "nessuno"],
                  6: ["sì", "no"]}
        for n in (5, 8, 12, 15):
            for _ in range(20):
                ids = list(range(1, n + 1))
                attrs = {i: {t: random.choice(o) for t, o in traits.items()} for i in ids}
                assign = logic.draw(ids)
                santa_of = {r: g for g, r in assign.items()}
                hints = logic.generate_hints(assign, traits, attrs)
                statements = set()
                for p, hs in hints.items():
                    self.assertEqual(len(hs), 2)
                    self.assertEqual(sorted(x["is_true"] for x in hs), [False, True])  # uno vero, uno falso
                    pairs = set()
                    for x in hs:
                        self.assertEqual(logic.hint_is_true(x, assign, attrs), x["is_true"])
                        giver = santa_of[x["subject"]] if x["kind"] == "santa_of" else x["subject"]
                        self.assertNotEqual(giver, p)                 # non la propria coppia
                        self.assertNotEqual(assign[giver], p)         # non la coppia del bonus
                        pairs.add(giver)
                        st = (x["kind"], x["subject"], x["trait"], x["value"])
                        self.assertNotIn(st, statements)              # nessun indizio uguale
                        statements.add(st)
                    self.assertEqual(len(pairs), 2)                   # due coppie diverse

    def test_derived_traits(self):
        from datetime import date
        d = date
        self.assertEqual(logic.zodiac_sign(3, 20), "Pesci")
        self.assertEqual(logic.zodiac_sign(3, 21), "Ariete")
        self.assertEqual(logic.zodiac_sign(12, 21), "Sagittario")
        self.assertEqual(logic.zodiac_sign(12, 22), "Capricorno")
        self.assertEqual(logic.zodiac_sign(1, 19), "Capricorno")
        self.assertEqual(logic.zodiac_sign(1, 20), "Acquario")
        self.assertEqual(logic.derive_trait("elemento", d(1990, 8, 1), []), "fuoco")      # Leone
        self.assertEqual(logic.derive_trait("stagione", d(1990, 12, 25), []), "inverno")
        self.assertEqual(logic.derive_trait("stagione", d(1990, 9, 1), []), "autunno")
        self.assertEqual(logic.derive_trait("semestre", d(1990, 6, 30), []), "gennaio-giugno")
        group = [d(1990, 1, 1), d(1995, 1, 1), d(2000, 1, 1)]   # dispari: la persona di mezzo va con i più grandi
        self.assertEqual([logic.derive_trait("eta", x, group) for x in group],
                         ["metà più grande", "metà più grande", "metà più giovane"])
        for spec_kind, spec in logic.DERIVED_TRAITS.items():
            self.assertGreaterEqual(len(spec["options"]), 2)

    def test_no_traits_no_hints(self):
        self.assertEqual(logic.generate_hints({1: 2, 2: 3, 3: 1}, {}, {}), {})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.mod = app_module
        cls.app = app_module.app
        cls.app.config["TESTING"] = True

    def setUp(self):
        import sqlite3
        db = sqlite3.connect(self.mod.DB_PATH)
        db.executescript("DELETE FROM hints; DELETE FROM trait_values; DELETE FROM traits; DELETE FROM guesses; "
                         "DELETE FROM assignments; DELETE FROM exclusions; DELETE FROM participants;")
        db.execute("UPDATE settings SET value='setup' WHERE key='phase'")
        db.execute("UPDATE settings SET value='0' WHERE key IN ('guesses_closed','reveal_step')")
        db.execute("UPDATE settings SET value='' WHERE key IN ('deadline','hint1_at','hint2_at')")
        db.commit()
        db.close()
        self.admin = self.app.test_client()
        r = self.admin.post("/api/admin/login", json={"password": "test-admin"})
        self.assertEqual(r.status_code, 200)

    def add_people(self, names):
        for n in names:
            self.assertEqual(self.admin.post("/api/admin/participants", json={"name": n}).status_code, 200)
        return {p["name"]: p for p in self.admin.get("/api/admin/state").get_json()["participants"]}

    def login(self, code, pin="1234"):
        c = self.app.test_client()
        r = c.post("/api/auth/pin", json={"code": code, "pin": pin})
        self.assertEqual(r.status_code, 200, r.get_json())
        return c

    def test_admin_requires_password(self):
        anon = self.app.test_client()
        self.assertEqual(anon.get("/api/admin/state").status_code, 401)
        self.assertEqual(anon.post("/api/admin/login", json={"password": "nope"}).status_code, 401)
        self.assertEqual(anon.post("/api/admin/draw", json={}).status_code, 401)

    def test_player_cannot_use_admin_api(self):
        people = self.add_people(["Anna", "Bruno", "Carla"])
        anna = self.login(people["Anna"]["code"])
        self.assertEqual(anna.get("/api/admin/state").status_code, 401)
        self.assertEqual(anna.post("/api/admin/reveal", json={"action": "start"}).status_code, 401)

    def test_database_not_served(self):
        anon = self.app.test_client()
        for path in ["/instance/secret_santa.db", "/static/../instance/secret_santa.db", "/secret_santa.db", "/app.py", "/.env"]:
            self.assertIn(anon.get(path).status_code, (404, 400), path)

    def test_full_flow_and_privacy(self):
        names = ["Anna", "Bruno", "Carla", "Dario", "Elena"]
        people = self.add_people(names)
        self.admin.post("/api/admin/exclusions", json={"giver_id": people["Anna"]["id"],
                                                        "receiver_id": people["Bruno"]["id"], "both": True})
        self.assertEqual(self.admin.post("/api/admin/draw", json={}).status_code, 200)

        # L'admin non riceve mai le coppie.
        state = self.admin.get("/api/admin/state").get_json()
        self.assertNotIn("assignments", state)
        self.assertNotIn("receiver", str(state).replace("receiver_id", ""))

        clients = {n: self.login(people[n]["code"]) for n in names}
        mine = {n: clients[n].get("/api/me").get_json() for n in names}
        ids = {n: people[n]["id"] for n in names}
        truth = {ids[n]: mine[n]["assignment"]["id"] for n in names}

        # Vincolo rispettato
        self.assertNotEqual(truth[ids["Anna"]], ids["Bruno"])
        self.assertNotEqual(truth[ids["Bruno"]], ids["Anna"])

        # Ogni giocatore vede solo il proprio abbinamento
        for n in names:
            payload = mine[n]
            self.assertEqual(set(payload.keys()) & {"assignments", "all_guesses"}, set())

        # Anna pronostica tutto giusto
        anna_guess = {str(g): r for g, r in truth.items() if g != ids["Anna"]}
        r = clients["Anna"].put("/api/me/guesses", json={"guesses": anna_guess})
        self.assertEqual(r.status_code, 200, r.get_json())
        # Bruno non può vedere i pronostici di Anna
        self.assertEqual(clients["Bruno"].get("/api/me").get_json()["guesses"], {})

        # Prima della rivelazione la pagina pubblica non mostra coppie
        pub = self.app.test_client().get("/api/reveal").get_json()
        self.assertNotIn("pairs", pub)

        # Estrazione non annullabile dopo che qualcuno l'ha vista
        self.assertEqual(self.admin.post("/api/admin/undo-draw", json={}).status_code, 409)

        # Rivelazione completa
        self.admin.post("/api/admin/reveal", json={"action": "start"})
        self.assertEqual(clients["Anna"].put("/api/me/guesses", json={"guesses": anna_guess}).status_code, 403)
        self.admin.post("/api/admin/reveal", json={"action": "all"})
        pub = self.app.test_client().get("/api/reveal").get_json()
        self.assertTrue(pub["complete"])
        top = pub["leaderboard"][0]
        self.assertEqual(top["name"], "Anna")
        self.assertEqual(top["points"], len(names) - 1 + 2)  # 4 coppie + bonus di 2
        self.assertTrue(top["bonus"])

    def test_pin_lockout_and_reset(self):
        people = self.add_people(["Anna", "Bruno", "Carla"])
        code = people["Anna"]["code"]
        old = self.login(code, "1234")
        self.assertEqual(old.get("/api/me").status_code, 200)
        c = self.app.test_client()
        statuses = [c.post("/api/auth/pin", json={"code": code, "pin": "0000"}).status_code for _ in range(5)]
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(c.post("/api/auth/pin", json={"code": code, "pin": "1234"}).status_code, 429)
        # Il reset dell'admin invalida anche le sessioni aperte
        self.admin.post(f"/api/admin/participants/{people['Anna']['id']}/reset-pin", json={})
        self.assertEqual(old.get("/api/me").status_code, 401)
        self.login(code, "5678")

    def test_hints_flow_and_privacy(self):
        import random
        import time as _time
        names = ["Anna", "Bruno", "Carla", "Dario", "Elena", "Fabio"]
        people = self.add_people(names)
        traits = {"Altezza": ["bassa", "media", "alta"], "Capelli": ["biondi", "castani", "neri"], "Fidanzato": ["sì", "no"]}
        for tname, opts in traits.items():
            r = self.admin.post("/api/admin/traits", json={"name": tname, "options": ", ".join(opts)})
            self.assertEqual(r.status_code, 200, r.get_json())
        # Meno di 3 valori: rifiutato
        self.assertEqual(self.admin.post("/api/admin/traits", json={"name": "X", "options": "a, A"}).status_code, 400)  # 1 solo valore distinto
        state = self.admin.get("/api/admin/state").get_json()
        tids = {t["name"]: t["id"] for t in state["traits"]}

        # Schede incomplete: l'estrazione è bloccata
        self.assertEqual(self.admin.post("/api/admin/draw", json={}).status_code, 400)
        for n in names:
            for tname, opts in traits.items():
                r = self.admin.put("/api/admin/trait-values", json={
                    "participant_id": people[n]["id"], "trait_id": tids[tname], "value": random.choice(opts)})
                self.assertEqual(r.status_code, 200)
        # Valore non previsto: rifiutato
        self.assertEqual(self.admin.put("/api/admin/trait-values", json={
            "participant_id": people["Anna"]["id"], "trait_id": tids["Altezza"], "value": "gigante"}).status_code, 400)

        self.assertEqual(self.admin.post("/api/admin/draw", json={}).status_code, 200)
        state = self.admin.get("/api/admin/state").get_json()
        self.assertEqual(state["hints_count"], 2 * len(names))
        self.assertNotIn("Chi fa", str(state))
        # Dopo l'estrazione le caratteristiche non si toccano più
        self.assertEqual(self.admin.post("/api/admin/traits", json={"name": "Y", "options": "a,b,c"}).status_code, 400)

        anna = self.login(people["Anna"]["code"])
        # Le schede sono visibili ai giocatori
        sch = anna.get("/api/schede").get_json()
        self.assertEqual(len(sch["people"]), len(names))
        self.assertEqual(self.app.test_client().get("/api/schede").status_code, 401)

        # Senza date: indizi bloccati, nessun contenuto inviato
        hints = anna.get("/api/me").get_json()["hints"]
        self.assertEqual(len(hints), 2)
        for x in hints:
            self.assertFalse(x["unlocked"])
            self.assertNotIn("value", x)
            self.assertNotIn("is_true", x)

        # Indizio 1 sbloccato, 2 nel futuro
        self.admin.put("/api/admin/settings", json={"hint1_at": _time.time() - 10, "hint2_at": _time.time() + 3600})
        hints = anna.get("/api/me").get_json()["hints"]
        self.assertTrue(hints[0]["unlocked"])
        self.assertIn("value", hints[0])
        self.assertNotIn("is_true", hints[0])        # vero/falso resta segreto
        self.assertFalse(hints[1]["unlocked"])
        self.assertNotIn("value", hints[1])

        # Rivelazione parziale: tutti sbloccati ma nessun vero/falso, nessun elenco pubblico
        self.admin.post("/api/admin/reveal", json={"action": "start"})
        self.admin.post("/api/admin/reveal", json={"action": "next"})
        hints = anna.get("/api/me").get_json()["hints"]
        self.assertTrue(all(x["unlocked"] and "is_true" not in x for x in hints))
        self.assertEqual(self.app.test_client().get("/api/reveal").get_json()["hints"], [])

        # Rivelazione completa: compaiono tutti gli indizi con vero/falso
        self.admin.post("/api/admin/reveal", json={"action": "all"})
        pub = self.app.test_client().get("/api/reveal").get_json()
        self.assertEqual(len(pub["hints"]), 2 * len(names))
        self.assertEqual(sum(x["is_true"] for x in pub["hints"]), len(names))
        hints = anna.get("/api/me").get_json()["hints"]
        self.assertEqual(sorted(x["is_true"] for x in hints), [False, True])

    def test_birthdate_traits_api(self):
        people = self.add_people(["Anna", "Bruno", "Carla", "Dario"])
        self.assertEqual(self.admin.post("/api/admin/traits", json={"derived": "segno"}).status_code, 200)
        self.assertEqual(self.admin.post("/api/admin/traits", json={"derived": "eta"}).status_code, 200)
        self.assertEqual(self.admin.post("/api/admin/traits", json={"derived": "segno"}).status_code, 400)  # doppione
        self.assertEqual(self.admin.post("/api/admin/traits", json={"derived": "boh"}).status_code, 400)
        dates = {"Anna": "1990-08-01", "Bruno": "1992-03-21", "Carla": "1995-12-25", "Dario": "1998-01-10"}
        for n, dt in dates.items():
            r = self.admin.put(f"/api/admin/participants/{people[n]['id']}/birthdate", json={"birthdate": dt})
            self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.admin.put(f"/api/admin/participants/{people['Anna']['id']}/birthdate",
                                        json={"birthdate": "2999-01-01"}).status_code, 400)

        state = self.admin.get("/api/admin/state").get_json()
        tids = {t["derived"]: t["id"] for t in state["traits"]}
        vals = state["trait_values"]
        self.assertEqual(vals[str(people["Anna"]["id"])][str(tids["segno"])], "Leone")
        self.assertEqual(vals[str(people["Bruno"]["id"])][str(tids["segno"])], "Ariete")
        self.assertEqual(vals[str(people["Anna"]["id"])][str(tids["eta"])], "metà più grande")
        self.assertEqual(vals[str(people["Dario"]["id"])][str(tids["eta"])], "metà più giovane")
        # I valori automatici non si impostano a mano, e la caratteristica non si modifica
        self.assertEqual(self.admin.put("/api/admin/trait-values", json={
            "participant_id": people["Anna"]["id"], "trait_id": tids["segno"], "value": "Toro"}).status_code, 400)
        self.assertEqual(self.admin.put(f"/api/admin/traits/{tids['segno']}",
                                        json={"name": "X", "options": "a,b"}).status_code, 400)

        # Togliendo una data, il valore sparisce e l'estrazione si blocca
        self.admin.put(f"/api/admin/participants/{people['Dario']['id']}/birthdate", json={"birthdate": ""})
        self.assertEqual(self.admin.post("/api/admin/draw", json={}).status_code, 400)
        self.admin.put(f"/api/admin/participants/{people['Dario']['id']}/birthdate", json={"birthdate": "1998-01-10"})
        self.assertEqual(self.admin.post("/api/admin/draw", json={}).status_code, 200)

        # La data di nascita non arriva mai ai giocatori
        anna = self.login(people["Anna"]["code"])
        for payload in (anna.get("/api/schede").get_json(), anna.get("/api/me").get_json()):
            text = str(payload)
            for dt in dates.values():
                self.assertNotIn(dt, text)
            self.assertNotIn("birthdate", text)

    def test_migration_adds_columns(self):
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.executescript("CREATE TABLE participants (id INTEGER PRIMARY KEY, name TEXT);"
                         "CREATE TABLE traits (id INTEGER PRIMARY KEY, name TEXT, options TEXT);"
                         "INSERT INTO participants(name) VALUES ('Vecchio');")
        self.mod.migrate(db)
        cols = {r[1] for r in db.execute("PRAGMA table_info(participants)")}
        self.assertIn("birthdate", cols)
        self.assertIn("derived", {r[1] for r in db.execute("PRAGMA table_info(traits)")})
        self.assertEqual(db.execute("SELECT name FROM participants").fetchone()[0], "Vecchio")
        self.mod.migrate(db)   # rieseguirla non fa danni

    def test_non_json_writes_rejected(self):
        r = self.admin.post("/api/admin/draw", data="x", content_type="text/plain")
        self.assertEqual(r.status_code, 415)


if __name__ == "__main__":
    unittest.main()
