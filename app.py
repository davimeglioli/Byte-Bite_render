from flask import Flask, json, jsonify, redirect, render_template, request, session, abort, url_for
import sqlite3 as sq
import socket
import bcrypt
import secrets
from flask_socketio import SocketIO, join_room
import uuid
from functools import wraps
import os

timers_attivi = {}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,      # quanto tempo il server aspetta un PONG
    ping_interval=25,     # ogni quanto manda un PING
    
)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login/")
        return f(*args, **kwargs)
    return wrapper

def get_logged_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    return query_db(
        "SELECT id, username, is_admin, attivo FROM utenti WHERE id = ?",
        (user_id,),
        one=True
    )

def require_permission(pagina):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):

            # Utente NON loggato
            if "user_id" not in session:
                return redirect("/login/")

            user = get_logged_user()

            # Utente disattivo → espellilo
            if not user or user["attivo"] != 1:
                session.clear()
                return redirect("/login/")

            # Admin → ha accesso totale
            if user["is_admin"] == 1:
                return f(*args, **kwargs)

            # Controlla se ha il permesso richiesto
            perm = query_db("""
                SELECT 1 FROM permessi_pagine
                WHERE utente_id = ? AND pagina = ?
            """, (user["id"], pagina), one=True)

            if perm:
                return f(*args, **kwargs)

            # Altrimenti → accesso negato
            abort(403)

        return wrapper
    return decorator


# chiude in automatico la connessione con il db in caso di errore
def query_db(query, args=(), one=False, commit=False):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, args)
        rows = None
        if not commit:
            rows = cur.fetchall()
        if commit:
            conn.commit()
    return (rows[0] if rows else None) if one else (rows or [])

# invia un messaggio SocketIO senza far crashare il server in caso di errore
def safe_emit(event, data, room=None):
    try:
        socketio.emit(event, data, room=room)
    except Exception as e:
        app.logger.warning(f"[SocketIO] Errore durante emit: {e}")

@socketio.on('join')
def on_join(data):
    categoria = data.get('categoria')
    if categoria:
        # es: "Cucina", "Bar", "Griglia"...
        join_room(categoria)
        print(f"[WS] Dashboard entrata nella stanza: {categoria}")

def get_db():
    db_path = os.environ.get("DATABASE_PATH", "db.sqlite3")
    conn = sq.connect(db_path)
    conn.row_factory = sq.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/cassa/')
@login_required
@require_permission("CASSA")
def cassa():
    conn = get_db()
    conn.row_factory = sq.Row
    cur = conn.cursor()

    # usa GROUP BY per ottenere categorie uniche mantenendo l'ordine originale
    categorie_rows = query_db('SELECT categoria_menu FROM prodotti GROUP BY categoria_menu ORDER BY MIN(id)')
    categorie = [row['categoria_menu'] for row in categorie_rows]

    # prodotti per ogni categoria
    prodotti_per_categoria = {}
    for categoria in categorie:
        prodotti_per_categoria[categoria] = query_db(
            'SELECT * FROM prodotti WHERE categoria_menu = ?', (categoria,)
        )

    return render_template(
        'cassa.html',
        categorie=categorie,
        prodotti_per_categoria=prodotti_per_categoria
    )

@app.route('/aggiungi_ordine/', methods=['POST'])
def aggiungi_ordine():
    # Recupera i dati dal form
    asporto = 1 if request.form.get('isTakeaway') == 'on' else 0
    nome_cliente = request.form.get('nome_cliente')
    numero_tavolo = request.form.get('numero_tavolo')
    numero_persone = request.form.get('numero_persone')
    metodo_pagamento = request.form.get('metodo_pagamento')
    prodotti_json = request.form.get('prodotti')

    if asporto:
        numero_tavolo = None
        numero_persone = None

    # Converte la stringa JSON in una lista di dizionari
    try:
        prodotti = json.loads(prodotti_json) if prodotti_json else []
    except json.JSONDecodeError:
        prodotti = []

    # Inserisce il nuovo ordine
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ordini (asporto, nome_cliente, numero_tavolo, numero_persone, metodo_pagamento)
            VALUES (?, ?, ?, ?, ?)
        """, (asporto, nome_cliente, numero_tavolo, numero_persone, metodo_pagamento))
        order_id = cur.lastrowid  # ID dell'ordine appena creato

        # Inserisci i prodotti e aggiorna il magazzino
        for p in prodotti:
            cur.execute("""
                INSERT INTO ordini_prodotti (ordine_id, prodotto_id, quantita, stato)
                VALUES (?, ?, ?, ?)
            """, (order_id, p["id"], p["quantita"], "In Attesa"))
            cur.execute("""
                UPDATE prodotti
                SET quantita = quantita - ?, venduti = venduti + ?
                WHERE id = ?
            """, (p["quantita"], p["quantita"], p["id"]))

        # Ottieni tutte le categorie dashboard coinvolte in questo ordine
        cur.execute("""
            SELECT DISTINCT prodotti.categoria_dashboard
            FROM ordini_prodotti
            JOIN prodotti ON prodotti.id = ordini_prodotti.prodotto_id
            WHERE ordini_prodotti.ordine_id = ?
        """, (order_id,))
        categorie_dashboard = [row[0] for row in cur.fetchall()] # Trasforma il risultato SQL in una lista Python
        conn.commit()  # Chiude automaticamente alla fine del blocco

    # Avvisa le dashboard in tempo reale
    for cat in categorie_dashboard:
        safe_emit('aggiorna_dashboard', {'categoria': cat}, room=cat)
    socketio.start_background_task(ricalcola_statistiche)

    return redirect(url_for('cassa') + f'?last_order_id={order_id}', code=303)

@app.route('/dashboard/<category>/')
@login_required
def dashboard(category):
    permesso = "DASHBOARD_" + category.upper()

    require_permission(permesso)(lambda: None)()

    ordini_non_completati, ordini_completati = get_ordini_per_categoria(category)
    return render_template(
        'dashboard.html',
        category=category.capitalize(),
        ordini_non_completati=ordini_non_completati,
        ordini_completati=ordini_completati
    )

@app.route('/cambia_stato/', methods=['POST'])
def cambia_stato():
    data = request.get_json()
    ordine_id = data.get('ordine_id')
    categoria = data.get('categoria')

    # Leggi stato attuale
    stato_attuale_row = query_db("""
        SELECT stato 
        FROM ordini_prodotti
        JOIN prodotti ON prodotti.id = ordini_prodotti.prodotto_id
        WHERE ordine_id = ? AND prodotti.categoria_dashboard = ?
        LIMIT 1;
    """, (ordine_id, categoria), one=True)

    stato_attuale = stato_attuale_row["stato"]

    # Calcola nuovo stato
    stati = ["In Attesa", "In Preparazione", "Pronto", "Completato"]

    timer_key = (ordine_id, categoria)

    if stato_attuale == "Pronto":
        # Se esiste un timer, annullalo
        if timer_key in timers_attivi:
            timers_attivi[timer_key]["annulla"] = True
            del timers_attivi[timer_key]
            print(f"[AUTO] Timer annullato per ordine {ordine_id} ({categoria})")

        nuovo_stato = "In Preparazione"

    # Altrimenti avanza di stato normalmente
    else:
        nuovo_stato = stati[stati.index(stato_attuale) + 1]

    # Aggiorna lo stato nel DB
    query_db("""
        UPDATE ordini_prodotti
        SET stato = ?
        WHERE ordine_id = ?
        AND prodotto_id IN (
            SELECT id FROM prodotti WHERE categoria_dashboard = ?
        );
    """, (nuovo_stato, ordine_id, categoria), commit=True)

    residui = query_db(
        "SELECT COUNT(*) AS c FROM ordini_prodotti WHERE ordine_id = ? AND stato != 'Completato'",
        (ordine_id,),
        one=True
    )["c"]
    query_db(
        "UPDATE ordini SET completato = ? WHERE id = ?",
        (1 if residui == 0 else 0, ordine_id),
        commit=True
    )

    # Avvisa subito la dashboard
    safe_emit('aggiorna_dashboard', {'categoria': categoria}, room=categoria)
    socketio.start_background_task(ricalcola_statistiche)

    if nuovo_stato == "Pronto":
    # Invalida qualsiasi vecchio timer
        if timer_key in timers_attivi:
            timers_attivi[timer_key]["annulla"] = True
            timers_attivi.pop(timer_key, None)

        socketio.sleep(0.1)  # piccolo delay per sicurezza
        timer_id = str(uuid.uuid4())  # ID univoco per questo timer
        timers_attivi[timer_key] = {"annulla": False, "id": timer_id}
        socketio.start_background_task(cambia_stato_automatico, ordine_id, categoria, timer_id)
        print(f"[AUTO] Timer avviato per ordine {ordine_id} ({categoria}) → {timer_id}")

    # Ricarica ordini aggiornati per quella categoria
    ordini_non_completati, ordini_completati = get_ordini_per_categoria(categoria)
    html_non_completati = render_template(
        'partials/_ordini.html', ordini=ordini_non_completati, category=categoria
    )
    html_completati = render_template(
        'partials/_ordini.html', ordini=ordini_completati, category=categoria, completati=True
    )

    return jsonify({
        "nuovo_stato": nuovo_stato,
        "html_non_completati": html_non_completati,
        "html_completati": html_completati
    })


@app.route('/dashboard/<category>/partial')
def dashboard_partial(category):
    ordini_non_completati, ordini_completati = get_ordini_per_categoria(category)

    html_non_completati = render_template(
        'partials/_ordini.html',
        ordini=ordini_non_completati,
        category=category
    )
    html_completati = render_template(
        'partials/_ordini.html',
        ordini=ordini_completati,
        category=category,
        completati=True
    )

    return jsonify({
        "html_non_completati": html_non_completati,
        "html_completati": html_completati
    })


def get_ordini_per_categoria(categoria):
    categoria = categoria.capitalize()
    
    ordini_db = query_db("""
        SELECT 
            o.id AS ordine_id,
            o.nome_cliente,
            o.numero_tavolo,
            o.numero_persone,
            o.data_ordine,
            op.stato,
            p.nome AS prodotto_nome,
            op.quantita
        FROM ordini AS o
        JOIN ordini_prodotti AS op ON o.id = op.ordine_id
        JOIN prodotti AS p ON p.id = op.prodotto_id
        WHERE p.categoria_dashboard = ?
        ORDER BY o.data_ordine ASC;
    """, (categoria,))

    # Raggruppa per ordine
    ordini = {}
    for o in ordini_db:
        oid = o["ordine_id"]
        ordini.setdefault(oid, {
            "id": oid,
            "nome_cliente": o["nome_cliente"],
            "numero_tavolo": o["numero_tavolo"],
            "numero_persone": o["numero_persone"],
            "data_ordine": o["data_ordine"],
            "stato": o["stato"],
            "prodotti": []
        })["prodotti"].append({
            "nome": o["prodotto_nome"],
            "quantita": o["quantita"]
        })

    # Divide ordini completati e non completati
    ordini_non_completati = []
    ordini_completati = []

    for o in ordini.values():
        if o["stato"] == "Completato":
            ordini_completati.append(o)
        else:
            ordini_non_completati.append(o)

    # Ordina i completati dal più recente
    ordini_completati.sort(key=lambda o: o["data_ordine"], reverse=True)


    return ordini_non_completati, ordini_completati

def cambia_stato_automatico(ordine_id, categoria, timer_id):
    timer_key = (ordine_id, categoria)
    
    for i in range(10):
        socketio.sleep(1)
        # Se è stato richiesto di annullare, interrompi
        if (
            timer_key not in timers_attivi
            or timers_attivi[timer_key]["id"] != timer_id
            or timers_attivi[timer_key]["annulla"]
        ):
            return

    # Controlla che non sia stato annullato nel frattempo
    if timer_key not in timers_attivi or timers_attivi[timer_key]["annulla"]:
        return

    # Aggiorna stato a completato
    query_db("""
        UPDATE ordini_prodotti
        SET stato = 'Completato'
        WHERE ordine_id = ?
        AND prodotto_id IN (
            SELECT id FROM prodotti WHERE categoria_dashboard = ?
        );
    """, (ordine_id, categoria), commit=True)

    residui = query_db(
        "SELECT COUNT(*) AS c FROM ordini_prodotti WHERE ordine_id = ? AND stato != 'Completato'",
        (ordine_id,),
        one=True
    )["c"]
    query_db(
        "UPDATE ordini SET completato = ? WHERE id = ?",
        (1 if residui == 0 else 0, ordine_id),
        commit=True
    )

    # Rimuovi il timer dalla lista
    timers_attivi.pop(timer_key, None)

    safe_emit('aggiorna_dashboard', {'categoria': categoria}, room=categoria)
    socketio.start_background_task(ricalcola_statistiche)

@app.route('/api/statistiche/')
@login_required
@require_permission("AMMINISTRAZIONE")
def api_statistiche():
    ordini_totali = query_db("SELECT COUNT(*) AS c FROM ordini", one=True)["c"]
    ordini_completati = query_db("SELECT COUNT(*) AS c FROM ordini WHERE completato = 1", one=True)["c"]

    totale_incasso_row = query_db(
        """
        SELECT SUM(p.prezzo * op.quantita) AS totale
        FROM ordini_prodotti op
        JOIN prodotti p ON p.id = op.prodotto_id
        """,
        one=True
    )
    totale_incasso = totale_incasso_row["totale"] or 0

    totale_contanti_row = query_db(
        """
        SELECT SUM(p.prezzo * op.quantita) AS totale
        FROM ordini_prodotti op
        JOIN prodotti p ON p.id = op.prodotto_id
        JOIN ordini o ON o.id = op.ordine_id
        WHERE o.metodo_pagamento = 'Contanti'
        """,
        one=True
    )
    totale_contanti = (totale_contanti_row["totale"] or 0)

    totale_carta_row = query_db(
        """
        SELECT SUM(p.prezzo * op.quantita) AS totale
        FROM ordini_prodotti op
        JOIN prodotti p ON p.id = op.prodotto_id
        JOIN ordini o ON o.id = op.ordine_id
        WHERE o.metodo_pagamento = 'Carta'
        """,
        one=True
    )
    totale_carta = (totale_carta_row["totale"] or 0)

    ore_rows = query_db(
        """
        SELECT CAST(strftime('%H', data_ordine) AS INT) AS ora, COUNT(*) AS totale
        FROM ordini
        GROUP BY ora
        ORDER BY ora ASC
        """
    )
    ore = [dict(r) for r in ore_rows] if ore_rows else []

    cat_rows = query_db(
        """
        SELECT p.categoria_dashboard, SUM(op.quantita) AS totale
        FROM ordini_prodotti op
        JOIN prodotti p ON p.id = op.prodotto_id
        GROUP BY p.categoria_dashboard
        """
    )
    categorie = [dict(r) for r in cat_rows] if cat_rows else []

    top10_rows = query_db(
        """
        SELECT nome, venduti
        FROM prodotti
        ORDER BY venduti DESC
        LIMIT 10
        """
    )
    top10 = [dict(r) for r in top10_rows] if top10_rows else []

    return jsonify({
        "totali": {
            "ordini_totali": ordini_totali,
            "ordini_completati": ordini_completati,
            "totale_incasso": totale_incasso,
            "totale_contanti": totale_contanti,
            "totale_carta": totale_carta
        },
        "categorie": categorie,
        "ore": ore,
        "top10": top10
    })

@app.route('/api/ordine/<int:ordine_id>')
def api_ordine(ordine_id):
    header = query_db(
        """
        SELECT id, nome_cliente, numero_tavolo, numero_persone, metodo_pagamento, data_ordine
        FROM ordini
        WHERE id = ?
        """,
        (ordine_id,),
        one=True
    )
    if not header:
        abort(404)
    items_rows = query_db(
        """
        SELECT p.nome AS nome, op.quantita AS quantita, p.prezzo AS prezzo
        FROM ordini_prodotti op
        JOIN prodotti p ON p.id = op.prodotto_id
        WHERE op.ordine_id = ?
        """,
        (ordine_id,)
    )
    items = [
        {"nome": r["nome"], "quantita": r["quantita"], "prezzo": r["prezzo"]}
        for r in items_rows
    ]
    return jsonify({
        "id": header["id"],
        "nome_cliente": header["nome_cliente"],
        "numero_tavolo": header["numero_tavolo"],
        "numero_persone": header["numero_persone"],
        "metodo_pagamento": header["metodo_pagamento"],
        "data_ordine": header["data_ordine"],
        "items": items
    })

@app.route('/amministrazione/')
@login_required
@require_permission("AMMINISTRAZIONE")
def amministrazione():
    return render_template(
        "amministrazione.html"
    )

def ricalcola_statistiche():
    conn = get_db()
    cur = conn.cursor()

    # carica tutti gli ordini
    ordini = query_db("""
        SELECT id, metodo_pagamento, data_ordine, completato
        FROM ordini
    """)

    # totale ordini e completati
    ordini_totali = len(ordini)
    ordini_completati = sum(1 for o in ordini if o["completato"] == 1)

    # reset statistiche totali
    query_db("DELETE FROM statistiche_totali", commit=True)

    # reset statistiche categorie
    query_db("DELETE FROM statistiche_categorie", commit=True)

    # reset statistiche ore
    query_db("DELETE FROM statistiche_ore", commit=True)

    # categorie dashboard fisse
    categorie = ["Bar", "Cucina", "Griglia", "Gnoccheria"]

    # inserisce le categorie
    for cat in categorie:
        query_db("""
            INSERT INTO statistiche_categorie (categoria_dashboard, totale)
            VALUES (?, 0)
        """, (cat,), commit=True)

    # inizializza ore da 0 a 23
    for h in range(24):
        query_db("""
            INSERT INTO statistiche_ore (ora, totale)
            VALUES (?, 0)
        """, (h,), commit=True)

    # inizializza totali incasso
    totale_incasso = 0
    totale_contanti = 0
    totale_carta = 0

    # ciclo su tutti gli ordini
    for ordine in ordini:
        ordine_id = ordine["id"]
        metodo = ordine["metodo_pagamento"]

        # calcola incasso dell'ordine
        incasso_ordine = query_db("""
            SELECT SUM(p.prezzo * op.quantita) AS totale
            FROM ordini_prodotti op
            JOIN prodotti p ON p.id = op.prodotto_id
            WHERE op.ordine_id = ?
        """, (ordine_id,), one=True)["totale"] or 0

        # somma incasso totale
        totale_incasso += incasso_ordine

        # aggiorna incassi contanti/carta
        if metodo == "Contanti":
            totale_contanti += incasso_ordine
        else:
            totale_carta += incasso_ordine

        # calcola ora dell'ordine
        ora = query_db("""
            SELECT CAST(strftime('%H', data_ordine) AS INT) AS h
            FROM ordini WHERE id = ?
        """, (ordine_id,), one=True)["h"]

        # aggiorna statistiche per ora
        query_db("""
            UPDATE statistiche_ore
            SET totale = totale + 1
            WHERE ora = ?
        """, (ora,), commit=True)

        # calcola categorie dashboard coinvolte
        righe_cat = query_db("""
            SELECT p.categoria_dashboard, SUM(op.quantita) AS qta
            FROM ordini_prodotti op
            JOIN prodotti p ON p.id = op.prodotto_id
            WHERE op.ordine_id = ?
            GROUP BY p.categoria_dashboard
        """, (ordine_id,))

        # aggiorna statistiche categorie
        for r in righe_cat:
            query_db("""
                UPDATE statistiche_categorie
                SET totale = totale + ?
                WHERE categoria_dashboard = ?
            """, (r["qta"], r["categoria_dashboard"]), commit=True)

    # inserisce statistiche totali
    query_db("""
        INSERT INTO statistiche_totali
        (id, ordini_totali, ordini_completati, totale_incasso, totale_contanti, totale_carta)
        VALUES (1, ?, ?, ?, ?, ?)
    """, (
        ordini_totali,
        ordini_completati,
        totale_incasso,
        totale_contanti,
        totale_carta
    ), commit=True)

    return None

@app.route('/genera_statistiche/')
def genera_statistiche():
    ricalcola_statistiche()
    return redirect('/amministrazione/')

@app.route('/debug/reset_dati/')
@login_required
@require_permission("AMMINISTRAZIONE")
def debug_reset_dati():
    query_db("DELETE FROM ordini_prodotti", commit=True)
    query_db("DELETE FROM ordini", commit=True)
    query_db("UPDATE prodotti SET disponibile = 1, quantita = 100, venduti = 0", commit=True)
    ricalcola_statistiche()
    return redirect('/amministrazione/')

@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password").encode()

        user = query_db("""
            SELECT id, username, password_hash, is_admin, attivo
            FROM utenti WHERE username = ?
        """, (username,), one=True)

        if not user:
            return render_template("login.html", error="Username o password errata")

        if user["attivo"] != 1:
            return render_template("login.html", error="Account disattivato")

        # verifica password
        if not bcrypt.checkpw(password, user["password_hash"].encode()):
            return render_template("login.html", error="Username o password errata")

        # login riuscito
        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return redirect("/")

    return render_template("login.html")


if __name__ == '__main__':
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    port = int(os.environ.get("PORT", 5001))
    print(f'Avvio server — apri: http://{ip}:{port}/')
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
    
