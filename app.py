# -*- coding: utf-8 -*-
"""
UADB Study Hub - Application principale
=========================================
Plateforme de partage de ressources pédagogiques pour les étudiants
de l'Université Alioune Diop de Bambey (UADB).

Ce fichier contient :
  - la configuration de l'application Flask
  - la connexion à la base de données SQLite (aucun ORM, pour rester simple)
  - les routes "étudiant" (accueil, navigation, recherche, téléchargement)
  - les routes "administrateur" (connexion, ajout/modification/suppression)

Le code est volontairement écrit de façon simple et commentée pour
qu'un étudiant débutant en Python puisse le comprendre et le faire évoluer.
"""

import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory, abort, g
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Configuration générale
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "uadb.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf"}
MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 Mo max par fichier

TYPES_DOCUMENTS = [
    "Cours", "TD", "Exercices", "Corrigés",
    "Annales", "Résumés", "Examens", "Autres"
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("UADB_SECRET_KEY", "cle-secrete-a-changer-en-production")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------------------------
# Connexion à la base de données
# ---------------------------------------------------------------------------

def get_db():
    """Retourne une connexion SQLite réutilisée pendant la requête en cours."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def compter_visite():
    """Incrémente le compteur du jour pour les pages consultées par les étudiants
    (on ignore les fichiers statiques et l'espace admin, pour ne compter que
    le vrai trafic de consultation)."""
    endpoint = request.endpoint or ""
    if endpoint.startswith("static") or endpoint.startswith("admin"):
        return
    if request.method != "GET":
        return
    jour = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    db.execute("""
        INSERT INTO visites_quotidiennes (jour, total) VALUES (?, 1)
        ON CONFLICT(jour) DO UPDATE SET total = total + 1
    """, (jour,))
    db.commit()


def init_db():
    """Crée les tables si elles n'existent pas encore."""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS niveaux (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        ordre INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS filieres (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        niveau_id INTEGER NOT NULL REFERENCES niveaux(id) ON DELETE CASCADE,
        nom TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        ordre INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS matieres (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filiere_id INTEGER NOT NULL REFERENCES filieres(id) ON DELETE CASCADE,
        nom TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        semestre INTEGER DEFAULT 0,
        ordre INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        matiere_id INTEGER NOT NULL REFERENCES matieres(id) ON DELETE CASCADE,
        titre TEXT NOT NULL,
        type TEXT NOT NULL,
        nom_fichier TEXT,
        lien_drive TEXT,
        date_ajout TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        filiere_id INTEGER REFERENCES filieres(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS visites_quotidiennes (
        jour TEXT PRIMARY KEY,
        total INTEGER NOT NULL DEFAULT 0
    );
    """)
    # Migration douce pour les bases existantes sans colonne filiere_id sur admins.
    colonnes_admins = [row[1] for row in db.execute("PRAGMA table_info(admins)")]
    if "filiere_id" not in colonnes_admins:
        db.execute("ALTER TABLE admins ADD COLUMN filiere_id INTEGER REFERENCES filieres(id)")
    # Migration douce : si la base existait déjà avant l'ajout du semestre,
    # on ajoute la colonne sans rien effacer.
    colonnes = [row[1] for row in db.execute("PRAGMA table_info(matieres)")]
    if "semestre" not in colonnes:
        db.execute("ALTER TABLE matieres ADD COLUMN semestre INTEGER DEFAULT 0")
    # Migration douce : ajout du lien Google Drive (pour l'hébergement en ligne).
    colonnes_documents = [row[1] for row in db.execute("PRAGMA table_info(documents)")]
    if "lien_drive" not in colonnes_documents:
        db.execute("ALTER TABLE documents ADD COLUMN lien_drive TEXT")
    db.commit()
    db.close()


def slugify(texte):
    """Transforme un nom en identifiant d'URL simple (sans accents ni espaces)."""
    import unicodedata
    import re
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    texte = texte.lower().strip()
    texte = re.sub(r"[^a-z0-9]+", "-", texte)
    return texte.strip("-")


# Matières confirmées, d'après les maquettes officielles des formations.
# Format : (filiere_slug, semestre, [liste des matières du semestre])
# Cette liste grandit au fil du temps, à mesure que les fiches officielles
# sont fournies pour chaque filière. Elle est utilisée à la fois pour la
# création initiale de la base (seed_db) et pour la mise à jour d'une base
# déjà existante (voir maj_matieres.py).
MATIERES_OFFICIELLES = [
    ("mpci", 1, [
        "Algorithmique et programmation en Pascal",
        "Anglais scientifique I",
        "Chimie atomistique I",
        "Chimie physique I",
        "Électrostatique et magnétostatique",
        "Mécanique du point",
        "Logique et structures algébriques",
        "Topologie de ℝ et fonctions numériques",
    ]),
    ("mpci", 2, [
        "Algorithmique et programmation en C",
        "Anglais scientifique II",
        "Chimie atomistique II",
        "Chimie physique II",
        "Électrocinétique",
        "Optique géométrique",
        "Algèbre linéaire",
        "Calcul différentiel et intégration sur ℝ",
    ]),
    ("mpi", 3, [
        "Intégrales et séries",
        "Complément d'algèbre linéaire",
        "Calcul de probabilités",
        "Mécanique quantique",
        "Thermodynamique physique",
        "Algorithmique et structures de données en C",
        "Anglais scientifique III",
    ]),
    ("mpi", 4, [
        "Calcul différentiel et intégral sur ℝⁿ",
        "Algèbre bilinéaire et sesquilinéaire",
        "Calcul numérique",
        "Électromagnétisme dans le vide et relativité restreinte",
        "Mécanique du solide",
        "Programmation orientée objet en Python",
        "Anglais scientifique IV",
    ]),
    # PC semestre 3 (semestre 1 de la filière) : en attente d'une fiche officielle.
    # PC semestre 4 : liste provisoire déduite d'un emploi du temps (pas une
    # fiche officielle de formation), à la demande de l'utilisateur.
    # PC : confirmé par la fiche officielle de la formation.
    ("pc", 3, [
        "Chimie minérale",
        "Cinétique chimique",
        "Chimie organique",
        "Mécanique quantique",
        "Thermodynamique physique",
        "Algèbre linéaire",
        "Intégrales généralisées",
    ]),
    ("pc", 4, [
        "Chimie organique",
        "Chimie des solides",
        "Biochimie",
        "Mécanique du point",
        "Magnétisme",
        "Probabilités",
        "Intégrales généralisées (suite)",
    ]),
    # SID : liste provisoire déduite de plannings de cours (pas une fiche
    # officielle de formation), à la demande de l'utilisateur.
    ("sid", 3, [
        "Complément d'algèbre linéaire",
        "Système d'information",
        "Intégrales et séries",
        "Économie",
        "Algorithme et programmation en C",
        "Statistique descriptive",
        "Calcul de probabilités",
        "Anglais",
    ]),
    ("sid", 4, [
        "Algèbre bilinéaire et sesquilinéaire linéaire",
        "Reporting",
        "Calcul différentiel et intégral sur ℝⁿ",
        "Outils de probabilité",
        "Base de données",
        "Comptabilité",
        "Estimation et test",
        "Programmation web",
    ]),
]


def ajouter_matieres_officielles(db):
    """
    Insère dans la base les matières de MATIERES_OFFICIELLES qui n'y sont
    pas encore (reconnues par filière + nom). Ne touche jamais aux matières
    ou documents déjà présents. Retourne le nombre de matières ajoutées.
    """
    cur = db.cursor()
    filiere_ids = {row["slug"]: row["id"] for row in cur.execute("SELECT id, slug FROM filieres")}
    matieres_existantes = set()
    for row in cur.execute("""
        SELECT filieres.slug AS filiere_slug, matieres.semestre AS semestre, matieres.nom
        FROM matieres JOIN filieres ON filieres.id = matieres.filiere_id
    """):
        matieres_existantes.add((row["filiere_slug"], row["semestre"], row["nom"]))

    nb_ajoutees = 0
    for filiere_slug, semestre, noms in MATIERES_OFFICIELLES:
        if filiere_slug not in filiere_ids:
            continue
        for i, nom in enumerate(noms, start=1):
            if (filiere_slug, semestre, nom) in matieres_existantes:
                continue
            slug = slugify(nom)
            while cur.execute("SELECT id FROM matieres WHERE slug = ?", (slug,)).fetchone():
                slug = f"{slug}-{filiere_slug}"
            ordre = cur.execute(
                "SELECT COALESCE(MAX(ordre), 0) + 1 AS n FROM matieres WHERE filiere_id = ?",
                (filiere_ids[filiere_slug],),
            ).fetchone()["n"]
            cur.execute(
                "INSERT INTO matieres (filiere_id, nom, slug, semestre, ordre) VALUES (?, ?, ?, ?, ?)",
                (filiere_ids[filiere_slug], nom, slug, semestre, ordre),
            )
            matieres_existantes.add((filiere_slug, semestre, nom))
            nb_ajoutees += 1
    db.commit()
    return nb_ajoutees


def seed_db():
    """
    Remplit la base avec les données CONFIRMÉES du cahier des charges :
    L1 MPCI (8 matières), et les niveaux/filières à venir (vides pour l'instant).
    On ne fait rien si la base contient déjà des niveaux (pour ne pas dupliquer).
    """
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) AS n FROM niveaux")
    if cur.fetchone()["n"] > 0:
        db.close()
        return

    # --- Niveaux -----------------------------------------------------
    niveaux = [("L1", "l1", 1), ("L2", "l2", 2), ("L3", "l3", 3)]
    niveau_ids = {}
    for nom, slug, ordre in niveaux:
        cur.execute("INSERT INTO niveaux (nom, slug, ordre) VALUES (?, ?, ?)", (nom, slug, ordre))
        niveau_ids[slug] = cur.lastrowid

    # --- Filières ------------------------------------------------------
    filieres = [
        ("MPCI", "mpci", "l1", 1),
        ("MPI", "mpi", "l2", 1),
        ("PC", "pc", "l2", 2),
        ("SID", "sid", "l2", 3),
    ]
    filiere_ids = {}
    for nom, slug, niveau_slug, ordre in filieres:
        cur.execute(
            "INSERT INTO filieres (niveau_id, nom, slug, ordre) VALUES (?, ?, ?, ?)",
            (niveau_ids[niveau_slug], nom, slug, ordre),
        )
        filiere_ids[slug] = cur.lastrowid

    db.commit()  # les filières doivent être commitées avant l'ajout des matières
    ajouter_matieres_officielles(db)

    # --- Compte administrateur par défaut -------------------------------
    # Identifiant : admin | Mot de passe : uadb2026
    # A CHANGER dès la première connexion (voir README.md)
    cur.execute(
        "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
        ("admin", generate_password_hash("uadb2026")),
    )

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Authentification administrateur (basée sur la session Flask)
# ---------------------------------------------------------------------------

def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Veuillez vous connecter pour accéder à l'espace administrateur.", "erreur")
            return redirect(url_for("admin_login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


def super_admin_required(view_func):
    """Réservé au compte admin sans filière assignée (accès à tout, gère les comptes)."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Veuillez vous connecter pour accéder à l'espace administrateur.", "erreur")
            return redirect(url_for("admin_login", next=request.path))
        if session.get("admin_filiere_id") is not None:
            flash("Cette page est réservée à l'administrateur général.", "erreur")
            return redirect(url_for("admin_dashboard"))
        return view_func(*args, **kwargs)
    return wrapped


def peut_gerer_filiere(filiere_id):
    """Un admin sans filiere_id (super admin) gère tout. Sinon, seulement la sienne."""
    admin_filiere_id = session.get("admin_filiere_id")
    if admin_filiere_id is None:
        return True
    return str(admin_filiere_id) == str(filiere_id)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Routes "étudiant"
# ---------------------------------------------------------------------------

@app.route("/")
def accueil():
    db = get_db()
    niveaux = db.execute("SELECT * FROM niveaux ORDER BY ordre").fetchall()

    # Accès rapides : on récupère chaque filière avec son niveau parent
    filieres = db.execute("""
        SELECT filieres.*, niveaux.nom AS niveau_nom, niveaux.slug AS niveau_slug
        FROM filieres
        JOIN niveaux ON niveaux.id = filieres.niveau_id
        ORDER BY niveaux.ordre, filieres.ordre
    """).fetchall()

    # Nombre de documents par filière, pour indiquer ce qui est déjà disponible
    compte_docs = db.execute("""
        SELECT matieres.filiere_id AS filiere_id, COUNT(documents.id) AS total
        FROM matieres
        LEFT JOIN documents ON documents.matiere_id = matieres.id
        GROUP BY matieres.filiere_id
    """).fetchall()
    compte_par_filiere = {row["filiere_id"]: row["total"] for row in compte_docs}

    # 6 derniers documents ajoutés, toutes matières confondues
    recents = db.execute("""
        SELECT documents.*, matieres.nom AS matiere_nom, matieres.slug AS matiere_slug
        FROM documents
        JOIN matieres ON matieres.id = documents.matiere_id
        ORDER BY documents.date_ajout DESC, documents.id DESC
        LIMIT 6
    """).fetchall()

    # Statistiques globales affichées sur l'accueil
    stats = {
        "total_documents": db.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"],
        "total_matieres": db.execute("SELECT COUNT(*) AS n FROM matieres").fetchone()["n"],
        "total_filieres": len(filieres),
    }

    return render_template(
        "index.html",
        niveaux=niveaux,
        filieres=filieres,
        compte_par_filiere=compte_par_filiere,
        recents=recents,
        stats=stats,
    )


@app.route("/a-propos")
def a_propos():
    return render_template("a_propos.html")


@app.route("/niveau/<slug>")
def voir_niveau(slug):
    db = get_db()
    niveau = db.execute("SELECT * FROM niveaux WHERE slug = ?", (slug,)).fetchone()
    if niveau is None:
        abort(404)
    filieres = db.execute(
        "SELECT * FROM filieres WHERE niveau_id = ? ORDER BY ordre", (niveau["id"],)
    ).fetchall()
    return render_template("niveau.html", niveau=niveau, filieres=filieres)


@app.route("/filiere/<slug>")
def voir_filiere(slug):
    db = get_db()
    filiere = db.execute("""
        SELECT filieres.*, niveaux.nom AS niveau_nom, niveaux.slug AS niveau_slug
        FROM filieres JOIN niveaux ON niveaux.id = filieres.niveau_id
        WHERE filieres.slug = ?
    """, (slug,)).fetchone()
    if filiere is None:
        abort(404)

    matieres = db.execute("""
        SELECT matieres.*, COUNT(documents.id) AS total_documents,
               MAX(documents.date_ajout) AS derniere_maj
        FROM matieres
        LEFT JOIN documents ON documents.matiere_id = matieres.id
        WHERE matieres.filiere_id = ?
        GROUP BY matieres.id
        ORDER BY matieres.semestre, matieres.ordre
    """, (filiere["id"],)).fetchall()

    # On regroupe les matières par semestre pour l'affichage
    matieres_par_semestre = {}
    for m in matieres:
        matieres_par_semestre.setdefault(m["semestre"], []).append(m)

    return render_template(
        "filiere.html", filiere=filiere, matieres=matieres,
        matieres_par_semestre=matieres_par_semestre,
    )


@app.route("/matiere/<slug>")
def voir_matiere(slug):
    db = get_db()
    matiere = db.execute("""
        SELECT matieres.*, filieres.nom AS filiere_nom, filieres.slug AS filiere_slug,
               niveaux.nom AS niveau_nom, niveaux.slug AS niveau_slug
        FROM matieres
        JOIN filieres ON filieres.id = matieres.filiere_id
        JOIN niveaux ON niveaux.id = filieres.niveau_id
        WHERE matieres.slug = ?
    """, (slug,)).fetchone()
    if matiere is None:
        abort(404)

    documents = db.execute(
        "SELECT * FROM documents WHERE matiere_id = ? ORDER BY type, date_ajout DESC",
        (matiere["id"],),
    ).fetchall()

    # On regroupe les documents par type pour l'affichage (Cours, TD, ...)
    documents_par_type = {}
    for doc in documents:
        documents_par_type.setdefault(doc["type"], []).append(doc)

    return render_template(
        "matiere.html",
        matiere=matiere,
        documents_par_type=documents_par_type,
        types_ordre=TYPES_DOCUMENTS,
    )


@app.route("/recherche")
def recherche():
    q = request.args.get("q", "").strip()
    resultats_matieres = []
    resultats_documents = []

    if q:
        db = get_db()
        motif = f"%{q}%"
        resultats_matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            WHERE matieres.nom LIKE ?
            ORDER BY matieres.nom
        """, (motif,)).fetchall()

        resultats_documents = db.execute("""
            SELECT documents.*, matieres.nom AS matiere_nom, matieres.slug AS matiere_slug
            FROM documents
            JOIN matieres ON matieres.id = documents.matiere_id
            WHERE documents.titre LIKE ? OR documents.type LIKE ?
            ORDER BY documents.date_ajout DESC
        """, (motif, motif)).fetchall()

    return render_template(
        "recherche.html", q=q,
        resultats_matieres=resultats_matieres,
        resultats_documents=resultats_documents,
    )


@app.route("/uploads/<path:nom_fichier>")
def telecharger(nom_fichier):
    return send_from_directory(app.config["UPLOAD_FOLDER"], nom_fichier, as_attachment=False)


# ---------------------------------------------------------------------------
# Routes "administrateur"
# ---------------------------------------------------------------------------

@app.route("/admin/connexion", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        admin = db.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            session["admin_filiere_id"] = admin["filiere_id"]
            flash("Connexion réussie.", "succes")
            destination = request.args.get("next") or url_for("admin_dashboard")
            return redirect(destination)
        flash("Identifiant ou mot de passe incorrect.", "erreur")

    return render_template("login.html")


@app.route("/admin/deconnexion")
def admin_logout():
    session.clear()
    flash("Vous avez été déconnecté.", "succes")
    return redirect(url_for("accueil"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    admin_filiere_id = session.get("admin_filiere_id")
    if admin_filiere_id is None:
        matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom,
                   COUNT(documents.id) AS total_documents
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            LEFT JOIN documents ON documents.matiere_id = matieres.id
            GROUP BY matieres.id
            ORDER BY niveaux.ordre, filieres.ordre, matieres.ordre
        """).fetchall()
        total_documents = db.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
    else:
        matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom,
                   COUNT(documents.id) AS total_documents
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            LEFT JOIN documents ON documents.matiere_id = matieres.id
            WHERE matieres.filiere_id = ?
            GROUP BY matieres.id
            ORDER BY niveaux.ordre, filieres.ordre, matieres.ordre
        """, (admin_filiere_id,)).fetchall()
        total_documents = db.execute("""
            SELECT COUNT(*) AS n FROM documents
            JOIN matieres ON matieres.id = documents.matiere_id
            WHERE matieres.filiere_id = ?
        """, (admin_filiere_id,)).fetchone()["n"]
    return render_template("admin/dashboard.html", matieres=matieres, total_documents=total_documents)


@app.route("/admin/statistiques")
@super_admin_required
def admin_statistiques():
    db = get_db()
    aujourdhui = datetime.now()

    total_semaine = db.execute("""
        SELECT COALESCE(SUM(total), 0) AS n FROM visites_quotidiennes
        WHERE jour >= date('now', '-6 days')
    """).fetchone()["n"]

    total_mois = db.execute("""
        SELECT COALESCE(SUM(total), 0) AS n FROM visites_quotidiennes
        WHERE strftime('%Y-%m', jour) = strftime('%Y-%m', 'now')
    """).fetchone()["n"]

    total_annee = db.execute("""
        SELECT COALESCE(SUM(total), 0) AS n FROM visites_quotidiennes
        WHERE strftime('%Y', jour) = strftime('%Y', 'now')
    """).fetchone()["n"]

    total_general = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS n FROM visites_quotidiennes"
    ).fetchone()["n"]

    derniers_jours = db.execute("""
        SELECT jour, total FROM visites_quotidiennes
        ORDER BY jour DESC LIMIT 14
    """).fetchall()

    return render_template(
        "admin/statistiques.html",
        total_semaine=total_semaine,
        total_mois=total_mois,
        total_annee=total_annee,
        total_general=total_general,
        derniers_jours=derniers_jours,
    )


@app.route("/admin/comptes")
@super_admin_required
def admin_comptes():
    db = get_db()
    comptes = db.execute("""
        SELECT admins.id, admins.username, filieres.nom AS filiere_nom
        FROM admins LEFT JOIN filieres ON filieres.id = admins.filiere_id
        ORDER BY admins.username
    """).fetchall()
    filieres = db.execute("""
        SELECT filieres.*, niveaux.nom AS niveau_nom
        FROM filieres JOIN niveaux ON niveaux.id = filieres.niveau_id
        ORDER BY niveaux.ordre, filieres.ordre
    """).fetchall()
    return render_template("admin/comptes.html", comptes=comptes, filieres=filieres)


@app.route("/admin/comptes/ajouter", methods=["POST"])
@super_admin_required
def admin_compte_ajouter():
    db = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    filiere_id = request.form.get("filiere_id") or None
    if not username or not password:
        flash("Identifiant et mot de passe sont obligatoires.", "erreur")
    elif len(password) < 6:
        flash("Le mot de passe doit faire au moins 6 caractères.", "erreur")
    else:
        existe = db.execute("SELECT id FROM admins WHERE username = ?", (username,)).fetchone()
        if existe:
            flash("Cet identifiant existe déjà.", "erreur")
        else:
            db.execute(
                "INSERT INTO admins (username, password_hash, filiere_id) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), filiere_id),
            )
            db.commit()
            flash(f"Compte « {username} » créé.", "succes")
    return redirect(url_for("admin_comptes"))


@app.route("/admin/comptes/<int:admin_id>/supprimer", methods=["POST"])
@super_admin_required
def admin_compte_supprimer(admin_id):
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS n FROM admins").fetchone()["n"]
    if total <= 1:
        flash("Impossible de supprimer le dernier compte admin.", "erreur")
    else:
        db.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
        db.commit()
        flash("Compte supprimé.", "succes")
    return redirect(url_for("admin_comptes"))


@app.route("/admin/matiere/ajouter", methods=["GET", "POST"])
@admin_required
def admin_matiere_ajouter():
    db = get_db()
    admin_filiere_id = session.get("admin_filiere_id")
    if admin_filiere_id is None:
        filieres = db.execute("""
            SELECT filieres.*, niveaux.nom AS niveau_nom
            FROM filieres JOIN niveaux ON niveaux.id = filieres.niveau_id
            ORDER BY niveaux.ordre, filieres.ordre
        """).fetchall()
    else:
        filieres = db.execute("""
            SELECT filieres.*, niveaux.nom AS niveau_nom
            FROM filieres JOIN niveaux ON niveaux.id = filieres.niveau_id
            WHERE filieres.id = ?
        """, (admin_filiere_id,)).fetchall()

    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        filiere_id = request.form.get("filiere_id")
        semestre = request.form.get("semestre", "0") or "0"
        if not nom or not filiere_id:
            flash("Le nom de la matière et la filière sont obligatoires.", "erreur")
        elif not peut_gerer_filiere(filiere_id):
            flash("Vous ne pouvez ajouter des matières que dans votre propre filière.", "erreur")
        else:
            slug = slugify(nom)
            existe = db.execute("SELECT id FROM matieres WHERE slug = ?", (slug,)).fetchone()
            if existe:
                slug = f"{slug}-{filiere_id}"
            ordre = db.execute(
                "SELECT COALESCE(MAX(ordre), 0) + 1 AS n FROM matieres WHERE filiere_id = ?",
                (filiere_id,),
            ).fetchone()["n"]
            db.execute(
                "INSERT INTO matieres (filiere_id, nom, slug, semestre, ordre) VALUES (?, ?, ?, ?, ?)",
                (filiere_id, nom, slug, int(semestre), ordre),
            )
            db.commit()
            flash(f"Matière « {nom} » ajoutée.", "succes")
            return redirect(url_for("admin_dashboard"))

    return render_template("admin/matiere_form.html", filieres=filieres, matiere=None)


@app.route("/admin/matiere/<int:matiere_id>/modifier", methods=["GET", "POST"])
@admin_required
def admin_matiere_modifier(matiere_id):
    db = get_db()
    matiere = db.execute("SELECT * FROM matieres WHERE id = ?", (matiere_id,)).fetchone()
    if matiere is None:
        abort(404)
    if not peut_gerer_filiere(matiere["filiere_id"]):
        flash("Vous n'avez pas accès à cette matière.", "erreur")
        return redirect(url_for("admin_dashboard"))

    admin_filiere_id = session.get("admin_filiere_id")
    if admin_filiere_id is None:
        filieres = db.execute("""
            SELECT filieres.*, niveaux.nom AS niveau_nom
            FROM filieres JOIN niveaux ON niveaux.id = filieres.niveau_id
            ORDER BY niveaux.ordre, filieres.ordre
        """).fetchall()
    else:
        filieres = db.execute("""
            SELECT filieres.*, niveaux.nom AS niveau_nom
            FROM filieres JOIN niveaux ON niveaux.id = filieres.niveau_id
            WHERE filieres.id = ?
        """, (admin_filiere_id,)).fetchall()

    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        filiere_id = request.form.get("filiere_id")
        semestre = request.form.get("semestre", "0") or "0"
        if not nom or not filiere_id:
            flash("Le nom de la matière et la filière sont obligatoires.", "erreur")
        elif not peut_gerer_filiere(filiere_id):
            flash("Vous ne pouvez déplacer une matière que dans votre propre filière.", "erreur")
        else:
            db.execute(
                "UPDATE matieres SET nom = ?, filiere_id = ?, semestre = ? WHERE id = ?",
                (nom, filiere_id, int(semestre), matiere_id),
            )
            db.commit()
            flash("Matière mise à jour.", "succes")
            return redirect(url_for("admin_dashboard"))

    return render_template("admin/matiere_form.html", filieres=filieres, matiere=matiere)


@app.route("/admin/matiere/<int:matiere_id>/supprimer", methods=["POST"])
@admin_required
def admin_matiere_supprimer(matiere_id):
    db = get_db()
    matiere = db.execute("SELECT filiere_id FROM matieres WHERE id = ?", (matiere_id,)).fetchone()
    if matiere is None:
        abort(404)
    if not peut_gerer_filiere(matiere["filiere_id"]):
        flash("Vous n'avez pas accès à cette matière.", "erreur")
        return redirect(url_for("admin_dashboard"))
    # On supprime aussi les fichiers PDF associés du disque
    documents = db.execute("SELECT nom_fichier FROM documents WHERE matiere_id = ?", (matiere_id,)).fetchall()
    for doc in documents:
        chemin = os.path.join(app.config["UPLOAD_FOLDER"], doc["nom_fichier"])
        if os.path.exists(chemin):
            os.remove(chemin)
    db.execute("DELETE FROM matieres WHERE id = ?", (matiere_id,))
    db.commit()
    flash("Matière supprimée.", "succes")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/document/ajouter", methods=["GET", "POST"])
@admin_required
def admin_document_ajouter():
    db = get_db()
    admin_filiere_id = session.get("admin_filiere_id")
    if admin_filiere_id is None:
        matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            ORDER BY niveaux.ordre, filieres.ordre, matieres.ordre
        """).fetchall()
    else:
        matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            WHERE matieres.filiere_id = ?
            ORDER BY matieres.ordre
        """, (admin_filiere_id,)).fetchall()

    matiere_preselectionnee = request.args.get("matiere_id", type=int)

    if request.method == "POST":
        titre = request.form.get("titre", "").strip()
        type_doc = request.form.get("type", "")
        matiere_id = request.form.get("matiere_id")
        lien_drive = request.form.get("lien_drive", "").strip()

        matiere_cible = db.execute("SELECT filiere_id FROM matieres WHERE id = ?", (matiere_id,)).fetchone() if matiere_id else None

        erreurs = []
        if not titre:
            erreurs.append("Le titre est obligatoire.")
        if type_doc not in TYPES_DOCUMENTS:
            erreurs.append("Le type de document est invalide.")
        if not matiere_id or matiere_cible is None:
            erreurs.append("La matière est obligatoire.")
        elif not peut_gerer_filiere(matiere_cible["filiere_id"]):
            erreurs.append("Vous ne pouvez ajouter des documents que dans votre propre filière.")
        if not lien_drive:
            erreurs.append("Le lien Google Drive est obligatoire.")
        elif "drive.google.com" not in lien_drive and "docs.google.com" not in lien_drive:
            erreurs.append("Le lien doit être un lien Google Drive (drive.google.com).")

        if erreurs:
            for e in erreurs:
                flash(e, "erreur")
        else:
            db.execute(
                "INSERT INTO documents (matiere_id, titre, type, nom_fichier, lien_drive, date_ajout) VALUES (?, ?, ?, ?, ?, ?)",
                (matiere_id, titre, type_doc, "", lien_drive, datetime.now().strftime("%Y-%m-%d")),
            )
            db.commit()
            flash(f"Document « {titre} » ajouté.", "succes")
            return redirect(url_for("admin_dashboard"))

    return render_template(
        "admin/document_form.html",
        matieres=matieres,
        types_documents=TYPES_DOCUMENTS,
        document=None,
        matiere_preselectionnee=matiere_preselectionnee,
    )


@app.route("/admin/document/<int:document_id>/modifier", methods=["GET", "POST"])
@admin_required
def admin_document_modifier(document_id):
    db = get_db()
    document = db.execute("""
        SELECT documents.*, matieres.filiere_id AS matiere_filiere_id
        FROM documents JOIN matieres ON matieres.id = documents.matiere_id
        WHERE documents.id = ?
    """, (document_id,)).fetchone()
    if document is None:
        abort(404)
    if not peut_gerer_filiere(document["matiere_filiere_id"]):
        flash("Vous n'avez pas accès à ce document.", "erreur")
        return redirect(url_for("admin_dashboard"))

    admin_filiere_id = session.get("admin_filiere_id")
    if admin_filiere_id is None:
        matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            ORDER BY niveaux.ordre, filieres.ordre, matieres.ordre
        """).fetchall()
    else:
        matieres = db.execute("""
            SELECT matieres.*, filieres.nom AS filiere_nom, niveaux.nom AS niveau_nom
            FROM matieres
            JOIN filieres ON filieres.id = matieres.filiere_id
            JOIN niveaux ON niveaux.id = filieres.niveau_id
            WHERE matieres.filiere_id = ?
            ORDER BY matieres.ordre
        """, (admin_filiere_id,)).fetchall()

    if request.method == "POST":
        titre = request.form.get("titre", "").strip()
        type_doc = request.form.get("type", "")
        matiere_id = request.form.get("matiere_id")
        lien_drive = request.form.get("lien_drive", "").strip()

        matiere_cible = db.execute("SELECT filiere_id FROM matieres WHERE id = ?", (matiere_id,)).fetchone() if matiere_id else None

        erreurs = []
        if not titre:
            erreurs.append("Le titre est obligatoire.")
        if type_doc not in TYPES_DOCUMENTS:
            erreurs.append("Le type de document est invalide.")
        if not matiere_id or matiere_cible is None:
            erreurs.append("La matière est obligatoire.")
        elif not peut_gerer_filiere(matiere_cible["filiere_id"]):
            erreurs.append("Vous ne pouvez déplacer un document que dans votre propre filière.")
        if not lien_drive:
            erreurs.append("Le lien Google Drive est obligatoire.")
        elif "drive.google.com" not in lien_drive and "docs.google.com" not in lien_drive:
            erreurs.append("Le lien doit être un lien Google Drive (drive.google.com).")

        if erreurs:
            for e in erreurs:
                flash(e, "erreur")
        else:
            db.execute(
                "UPDATE documents SET titre = ?, type = ?, matiere_id = ?, lien_drive = ? WHERE id = ?",
                (titre, type_doc, matiere_id, lien_drive, document_id),
            )
            db.commit()
            flash("Document mis à jour.", "succes")
            return redirect(url_for("admin_dashboard"))

    return render_template(
        "admin/document_form.html", matieres=matieres,
        types_documents=TYPES_DOCUMENTS, document=document,
        matiere_preselectionnee=None,
    )


@app.route("/admin/document/<int:document_id>/supprimer", methods=["POST"])
@admin_required
def admin_document_supprimer(document_id):
    db = get_db()
    document = db.execute("""
        SELECT documents.*, matieres.filiere_id AS matiere_filiere_id
        FROM documents JOIN matieres ON matieres.id = documents.matiere_id
        WHERE documents.id = ?
    """, (document_id,)).fetchone()
    if document:
        if not peut_gerer_filiere(document["matiere_filiere_id"]):
            flash("Vous n'avez pas accès à ce document.", "erreur")
            return redirect(url_for("admin_dashboard"))
        if document["nom_fichier"]:
            chemin = os.path.join(app.config["UPLOAD_FOLDER"], document["nom_fichier"])
            if os.path.exists(chemin):
                os.remove(chemin)
        db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        db.commit()
        flash("Document supprimé.", "succes")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Filtres Jinja utilitaires
# ---------------------------------------------------------------------------

@app.template_filter("date_fr")
def date_fr(valeur):
    try:
        d = datetime.strptime(valeur, "%Y-%m-%d")
        mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                "août", "septembre", "octobre", "novembre", "décembre"]
        return f"{d.day} {mois[d.month - 1]} {d.year}"
    except Exception:
        return valeur


# ---------------------------------------------------------------------------
# Initialisation de la base
# ---------------------------------------------------------------------------
# Appelées ici (au chargement du module) et non seulement dans le bloc
# __main__ ci-dessous, car sur Render l'appli est démarrée via gunicorn
# (gunicorn app:app), qui importe ce fichier sans jamais exécuter le bloc
# __main__. Ces deux fonctions ne font rien si la base existe déjà.
init_db()
seed_db()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
