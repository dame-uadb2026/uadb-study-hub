import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_url, flash, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'uadb_secret_key_change_in_production'

# Utilisation du dossier /tmp pour la compatibilité avec Render
DB_PATH = '/tmp/uadb.db'
UPLOAD_FOLDER = '/tmp/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Extension autorisées pour les fichiers
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'pptx'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Table Utilisateurs / Admins
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # Table Matières / Cours
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            level TEXT NOT NULL,
            filiere TEXT NOT NULL,
            description TEXT
        )
    ''')

    # Table Fichiers / Documents
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            file_path TEXT,
            external_link TEXT,
            FOREIGN KEY (course_id) REFERENCES courses (id)
        )
    ''')
    
    # Compte admin par défaut (admin / admin123)
    cursor.execute("SELECT * FROM users WHERE username = ?", ('admin',))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash('admin123')
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', hashed_pw))
        
    conn.commit()
    conn.close()

# Initialisation au démarrage
with app.app_context():
    init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    query = request.args.get('q', '')
    conn = get_db_connection()
    if query:
        courses = conn.execute("SELECT * FROM courses WHERE title LIKE ? OR filiere LIKE ?", 
                               (f'%{query}%', f'%{query}%')).fetchall()
    else:
        courses = conn.execute("SELECT * FROM courses").fetchall()
    conn.close()
    return render_template('index.html', courses=courses, query=query)

@app.route('/course/<int:course_id>')
def course_detail(course_id):
    conn = get_db_connection()
    course = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    docs = conn.execute("SELECT * FROM documents WHERE course_id = ?", (course_id,)).fetchall()
    conn.close()
    return render_template('course.html', course=course, documents=docs)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Connexion réussie !', 'success')
            return redirect('/admin')
        else:
            flash('Identifiants incorrects.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Vous êtes déconnecté.', 'info')
    return redirect('/')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'user_id' not in session:
        return redirect('/login')
        
    conn = get_db_connection()
    if request.method == 'POST':
        title = request.form['title']
        level = request.form['level']
        filiere = request.form['filiere']
        description = request.form.get('description', '')
        
        cursor = conn.cursor()
        cursor.execute("INSERT INTO courses (title, level, filiere, description) VALUES (?, ?, ?, ?)",
                       (title, level, filiere, description))
        conn.commit()
        flash('Matière ajoutée avec succès !', 'success')
        return redirect('/admin')
        
    courses = conn.execute("SELECT * FROM courses").fetchall()
    conn.close()
    return render_template('admin.html', courses=courses)

@app.route('/admin/add_doc/<int:course_id>', methods=['POST'])
def add_doc(course_id):
    if 'user_id' not in session:
        return redirect('/login')
        
    title = request.form['title']
    external_link = request.form.get('external_link', '')
    file = request.files.get('file')
    file_path = None

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        file_path = filename

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO documents (course_id, title, file_path, external_link) VALUES (?, ?, ?, ?)",
                   (course_id, title, file_path, external_link))
    conn.commit()
    conn.close()
    
    flash('Document ajouté avec succès !', 'success')
    return redirect(f'/course/{course_id}')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
