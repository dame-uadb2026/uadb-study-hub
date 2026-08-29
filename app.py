import os
import sqlite3
import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, 
    flash, session, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'uadb_study_hub_secret_key_change_in_production'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB max per upload

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'zip', 'rar'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uadb.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Table des administrateurs
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            filiere TEXT DEFAULT 'Toutes'
        )
    ''')
    
    # Table des matières
    c.execute('''
        CREATE TABLE IF NOT EXISTS matieres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            niveau TEXT NOT NULL,
            filiere TEXT NOT NULL,
            UNIQUE(nom, niveau, filiere)
        )
    ''')
    
    # Table des documents
    c.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL,
            type_doc TEXT NOT NULL,
            matiere_id INTEGER NOT NULL,
            fichier TEXT,
            lien_drive TEXT,
            date_ajout DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (matiere_id) REFERENCES matieres (id) ON DELETE CASCADE
        )
    ''')

    # Table des statistiques de visite
    c.execute('''
        CREATE TABLE IF NOT EXISTS vues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_visite DATE UNIQUE NOT NULL,
            nb_vues INTEGER DEFAULT 0
        )
    ''')
    
    # Administrateur par défaut s'il n'y en a pas
    c.execute('SELECT COUNT(*) FROM admins')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO admins (username, password, filiere) VALUES (?, ?, ?)',
                  ('admin', generate_password_hash('admin123'), 'Toutes'))
        
    conn.commit()
    conn.close()

init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def enregistrer_vue():
    today = datetime.date.today().isoformat()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO vues (date_visite, nb_vues) VALUES (?, 1) ON CONFLICT(date_visite) DO UPDATE SET nb_vues = nb_vues + 1', (today,))
    conn.commit()
    conn.close()

@app.before_request
def count_views():
    if not request.path.startswith('/static') and not request.path.startswith('/uploads'):
        enregistrer_vue()

@app.context_processor
def inject_globals():
    return dict(now=datetime.datetime.utcnow())

@app.route('/')
def index():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT DISTINCT niveau FROM matieres ORDER BY niveau')
    niveaux = [row['niveau'] for row in c.fetchall()]
    conn.close()
    return render_template('index.html', niveaux=niveaux)

@app.route('/niveau/<niveau>')
def voir_niveau(niveau):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT DISTINCT filiere FROM matieres WHERE niveau = ? ORDER BY filiere', (niveau,))
    filieres = [row['filiere'] for row in c.fetchall()]
    conn.close()
    return render_template('niveau.html', niveau=niveau, filieres=filieres)

@app.route('/niveau/<niveau>/filiere/<filiere>')
def voir_filiere(niveau, filiere):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM matieres WHERE niveau = ? AND filiere = ? ORDER BY nom', (niveau, filiere))
    matieres = c.fetchall()
    conn.close()
    return render_template('filiere.html', niveau=niveau, filiere=filiere, matieres=matieres)

@app.route('/matiere/<int:matiere_id>')
def voir_matiere(matiere_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM matieres WHERE id = ?', (matiere_id,))
    matiere = c.fetchone()
    if not matiere:
        flash('Matière introuvable.', 'danger')
        return redirect(url_for('index'))
    
    c.execute('SELECT * FROM documents WHERE matiere_id = ? ORDER BY date_ajout DESC', (matiere_id,))
    documents = c.fetchall()
    conn.close()
    return render_template('matiere.html', matiere=matiere, documents=documents)

@app.route('/recherche')
def recherche():
    query = request.args.get('q', '').strip()
    results = []
    if query:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            SELECT d.*, m.nom as matiere_nom, m.niveau, m.filiere 
            FROM documents d 
            JOIN matieres m ON d.matiere_id = m.id 
            WHERE d.titre LIKE ? OR m.nom LIKE ? OR m.filiere LIKE ?
            ORDER BY d.date_ajout DESC
        ''', (f'%{query}%', f'%{query}%', f'%{query}%'))
        results = c.fetchall()
        conn.close()
    return render_template('recherche.html', query=query, results=results)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM admins WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['filiere'] = user['filiere']
            flash('Connexion réussie !', 'success')
            return redirect(url_for('admin'))
        else:
            flash('Identifiant ou mot de passe incorrect.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Vous êtes déconnecté.', 'info')
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    c = conn.cursor()
    
    # Traitement des ajouts
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_matiere':
            nom = request.form.get('nom').strip()
            niveau = request.form.get('niveau')
            filiere = request.form.get('filiere')
            try:
                c.execute('INSERT INTO matieres (nom, niveau, filiere) VALUES (?, ?, ?)', (nom, niveau, filiere))
                conn.commit()
                flash('Matière ajoutée avec succès.', 'success')
            except sqlite3.IntegrityError:
                flash('Cette matière existe déjà pour ce niveau et cette filière.', 'danger')
                
        elif action == 'add_doc':
            titre = request.form.get('titre').strip()
            type_doc = request.form.get('type_doc')
            matiere_id = request.form.get('matiere_id')
            lien_drive = request.form.get('lien_drive', '').strip()
            
            file = request.files.get('fichier')
            filename = None
            
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
            if filename or lien_drive:
                c.execute('INSERT INTO documents (titre, type_doc, matiere_id, fichier, lien_drive) VALUES (?, ?, ?, ?, ?)',
                          (titre, type_doc, matiere_id, filename, lien_drive))
                conn.commit()
                flash('Document ajouté avec succès.', 'success')
            else:
                flash('Veuillez fournir un fichier ou un lien Google Drive.', 'danger')

        elif action == 'add_admin' and session.get('filiere') == 'Toutes':
            new_username = request.form.get('username').strip()
            new_password = request.form.get('password')
            new_filiere = request.form.get('filiere')
            try:
                c.execute('INSERT INTO admins (username, password, filiere) VALUES (?, ?, ?)',
                          (new_username, generate_password_hash(new_password), new_filiere))
                conn.commit()
                flash(f'Compte {new_username} créé avec succès.', 'success')
            except sqlite3.IntegrityError:
                flash('Cet identifiant existe déjà.', 'danger')

    # Récupération des données selon les droits
    if session.get('filiere') == 'Toutes':
        c.execute('SELECT * FROM matieres ORDER BY niveau, filiere, nom')
        matieres = c.fetchall()
        c.execute('SELECT * FROM admins')
        admins = c.fetchall()
    else:
        c.execute('SELECT * FROM matieres WHERE filiere = ? ORDER BY niveau, nom', (session['filiere'],))
        matieres = c.fetchall()
        admins = []
        
    c.execute('SELECT d.*, m.nom as matiere_nom FROM documents d JOIN matieres m ON d.matiere_id = m.id ORDER BY d.date_ajout DESC')
    documents = c.fetchall()
    
    # Statistiques de vues
    today = datetime.date.today().isoformat()
    c.execute('SELECT nb_vues FROM vues WHERE date_visite = ?', (today,))
    row_today = c.fetchone()
    vues_jour = row_today['nb_vues'] if row_today else 0
    
    c.execute('SELECT SUM(nb_vues) FROM vues')
    row_total = c.fetchone()
    vues_total = row_total[0] if row_total and row_total[0] else 0

    conn.close()
    return render_template('admin.html', matieres=matieres, documents=documents, admins=admins, vues_jour=vues_jour, vues_total=vues_total)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
