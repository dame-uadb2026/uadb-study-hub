import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = 'uadb_secret_key_change_this'

DB_NAME = 'uadb.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            level TEXT NOT NULL,
            filiere TEXT NOT NULL,
            description TEXT
        )
    ''')
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
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    query = request.args.get('q', '')
    conn = get_db_connection()
    if query:
        courses = conn.execute(
            'SELECT * FROM courses WHERE title LIKE ? OR filiere LIKE ? OR level LIKE ?',
            (f'%{query}%', f'%{query}%', f'%{query}%')
        ).fetchall()
    else:
        courses = conn.execute('SELECT * FROM courses').fetchall()
    conn.close()
    return render_template('index.html', courses=courses, query=query)

@app.route('/course/<int:course_id>')
def course_detail(course_id):
    conn = get_db_connection()
    course = conn.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
    documents = conn.execute('SELECT * FROM documents WHERE course_id = ?', (course_id,)).fetchall()
    conn.close()
    if course is None:
        return "Cours non trouvé", 404
    return render_template('course.html', course=course, documents=documents)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'admin' and password == 'admin123':
            session['user_id'] = 1
            return redirect(url_for('admin'))
        else:
            flash('Identifiants incorrects', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        level = request.form.get('level')
        filiere = request.form.get('filiere')
        description = request.form.get('description')
        
        if title and level and filiere:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO courses (title, level, filiere, description) VALUES (?, ?, ?, ?)',
                (title, level, filiere, description)
            )
            conn.commit()
            conn.close()
            flash('Matière ajoutée avec succès !', 'success')
            return redirect(url_for('admin'))

    return render_template('admin.html')

if __name__ == '__main__':
    app.run(debug=True)
