CREATE TABLE IF NOT EXISTS ordini (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asporto BOOLEAN NOT NULL,
    data_ordine DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    nome_cliente TEXT NOT NULL,
    numero_tavolo INTEGER CHECK (numero_tavolo > 0),
    numero_persone INTEGER CHECK (numero_persone > 0),
    metodo_pagamento TEXT NOT NULL CHECK (metodo_pagamento IN ('Contanti', 'Carta')),
    completato BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prodotti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    prezzo REAL NOT NULL,
    categoria_menu TEXT NOT NULL,
    categoria_dashboard TEXT NOT NULL CHECK (categoria_dashboard IN ('Bar', 'Cucina', 'Gnoccheria', 'Griglia', 'Coperto')),
    disponibile BOOLEAN NOT NULL DEFAULT 0,
    quantita INTEGER NOT NULL,
    venduti INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ordini_prodotti (
    ordine_id INTEGER REFERENCES ordini(id) ON DELETE CASCADE,
    prodotto_id INTEGER REFERENCES prodotti(id),
    quantita INTEGER NOT NULL CHECK (quantita > 0),
    stato TEXT NOT NULL DEFAULT 'In Attesa' CHECK (stato IN ('In Attesa', 'In Preparazione', 'Pronto', 'Completato')),
    PRIMARY KEY (ordine_id, prodotto_id)
);

/* Tabelle per statistiche */
CREATE TABLE stats_totali (
    id INT PRIMARY KEY,
    ordini_totali INT NOT NULL DEFAULT 0,
    ordini_completati INT NOT NULL DEFAULT 0,
    totale_incasso DECIMAL NOT NULL DEFAULT 0,
    totale_contanti DECIMAL NOT NULL DEFAULT 0,
    totale_carta DECIMAL NOT NULL DEFAULT 0
);

CREATE TABLE stats_categorie (
    categoria_dashboard TEXT PRIMARY KEY,
    totale INT NOT NULL DEFAULT 0
);

CREATE TABLE stats_ore (
    ora TINYINT PRIMARY KEY,
    totale INT NOT NULL DEFAULT 0
);

CREATE TABLE stats_prodotti (
    prodotto_id INT PRIMARY KEY,
    totale_venduto INT NOT NULL DEFAULT 0
);
