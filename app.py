from pydoc import pager
from flask import Flask, jsonify, render_template, request, redirect, session, flash, url_for
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from db import connect_to_db
from config import DATABASE_CONFIG, UPLOAD_FOLDER, SECRET_KEY
import os
from datetime import datetime, timedelta

app = Flask(__name__,static_url_path='/static')
app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def get_connection():
    return connect_to_db(**DATABASE_CONFIG)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/suggest')
def suggest():
    q = request.args.get('q', '').lower()

    conn = connect_to_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT movie_id, title FROM movies WHERE LOWER(title) LIKE %s LIMIT 8",
        (q + '%',)
    )

    data = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([{"movie_id": m[0], "title": m[1]} for m in data])


@app.route('/')
def home():
    if 'user_id' in session:
        return redirect('/dashboard')
    
    conn = connect_to_db(**DATABASE_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT movie_id, title, description, release_date, rating, genre, poster_url, trailer_link
        FROM movies
        WHERE poster_url IS NOT NULL AND poster_url != ''
        ORDER BY RANDOM()
        LIMIT 15
    """)
    movies = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('page.html', movies=movies)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, password_hash FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect('/dashboard')
        flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash, created_at) VALUES (%s, %s, %s, NOW())",
                    (username, email, hashed_pw))
        conn.commit()
        cur.close()
        conn.close()
        flash("Registration successful.") 
    return render_template('register.html')

from datetime import datetime, timedelta

@app.route('/dashboard')
def dashboard():
    query = request.args.get('q', '').lower()

    conn = get_connection()
    cur = conn.cursor()

    if query:
        # If search query exists, filter by movie title (case-insensitive)
        cur.execute(
            "SELECT movie_id, title, release_date, poster_url FROM movies WHERE LOWER(title) LIKE %s",
            ('%' + query + '%',)
        )
    else:
        # If no search, show all movies
        cur.execute("SELECT movie_id, title, release_date, poster_url FROM movies")

    movies = cur.fetchall()
    cur.close()
    conn.close()

    # Convert tuples to dictionaries
    movies_dict = []
    for movie in movies:
        movies_dict.append({
            'movie_id': movie[0],
            'title': movie[1],
            'release_date': movie[2],
            'poster_url': movie[3]
        })

    recent_threshold = (datetime.now() - timedelta(days=30)).date()

    return render_template(
        'dashboard.html',
        movies=movies_dict,
        recent_threshold=recent_threshold
    )
@app.route('/search')
def search_movies():
    query = request.args.get('q', '').strip()
    conn = get_connection()
    cur = conn.cursor()

    if query:
        # Don't limit when searching
        cur.execute("""
            SELECT movie_id, title, release_date, poster_url, rating, trailer_link 
            FROM movies 
            WHERE LOWER(title) LIKE LOWER(%s)
        """, ('%' + query + '%',))
    else:
        # Limit only when no query (default 8 random or recent)
        cur.execute("""
            SELECT movie_id, title, release_date, poster_url, rating, trailer_link 
            FROM movies 
            ORDER BY created_at DESC 
            LIMIT 8
        """)

    movies = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for m in movies:
        result.append({
            'movie_id': m[0],
            'title': m[1],
            'release_date': m[2].isoformat() if m[2] else '',
            'poster_url': m[3],
            'rating': m[4],
            'trailer_link': m[5]
        })

    return jsonify(result)


@app.route('/filter', methods=['GET'])
def filter_movies():
    year = request.args.get('year')
    genre = request.args.get('genre')
    rating = request.args.get('rating')
    query = request.args.get('q')

    conn = get_connection()
    cur = conn.cursor()

    # Start with base query
    sql = "SELECT movie_id, title, release_date, genre, rating, trailer_link, poster_url FROM movies WHERE 1=1"
    params = []

    if year:
        sql += " AND EXTRACT(YEAR FROM release_date) = %s"
        params.append(year)

    if genre:
        sql += " AND genre ILIKE %s"
        params.append(f"%{genre}%")

    if rating:
        try:
            rating_float = float(rating)
            sql += " AND rating >= %s"
            params.append(rating_float)
        except ValueError:
            pass  # ignore invalid rating input

    if query:
        sql += " AND title ILIKE %s"
        params.append(f"%{query}%")

    cur.execute(sql, tuple(params))
    results = cur.fetchall()
    cur.close()
    conn.close()

    # Convert to list of dicts for JSON response
    movies = []
    for row in results:
        movies.append({
            "movie_id": row[0],
            "title": row[1],
            "release_date": row[2].strftime('%Y-%m-%d') if row[2] else '',
            "genre": row[3],
            "rating": float(row[4]),
            "trailer_link": row[5],
            "poster_url": row[6]
        })

    return jsonify(movies)


@app.route('/add_movie', methods=['GET', 'POST'])
def add_movie():
    if 'user_id' not in session:
        flash('Please log in to add a movie.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        genre = request.form['genre']
        release_date = request.form['release_date']
        description = request.form['description']
        trailer_link = request.form['trailer_link']
        director = request.form.get('director')
        cast_names = request.form.get('cast_names')
        user_id = session.get('user_id')  # 🔴 This is the key line!

        # Handle poster upload
        poster = request.files['poster']
        poster_filename = None
        if poster and poster.filename:
            poster_filename = secure_filename(poster.filename)
            poster.save(os.path.join(UPLOAD_FOLDER, poster_filename))

        # Save to database
        conn = connect_to_db(**DATABASE_CONFIG)
        cur = conn.cursor()
        cur.execute("""
    INSERT INTO movies (
        title, genre, release_date, description,
        trailer_link, poster_url, user_id, director, cast_names
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (
    title,
    genre,
    release_date,
    description,
    trailer_link,
    poster_filename,
    user_id,
    director,
    cast_names
))



        conn.commit()
        cur.close()
        conn.close()

        flash('Movie added successfully!')
        return redirect(url_for('dashboard'))

    return render_template('add_movie.html')


@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT movie_id, title, release_date, poster_url, genre, director, cast_names, trailer_link, description
        FROM movies WHERE movie_id = %s
    """, (movie_id,))
    row = cur.fetchone()

    cur.execute("""
        SELECT r.rating, r.comment, u.username
        FROM reviews r JOIN users u ON r.user_id = u.user_id
        WHERE r.movie_id = %s
        ORDER BY r.review_id DESC
    """, (movie_id,))
    reviews = cur.fetchall()

    cur.execute("SELECT ROUND(AVG(rating),1) FROM reviews WHERE movie_id = %s", (movie_id,))
    avg_rating = cur.fetchone()[0] or 0

    cur.close()
    conn.close()

    if not row:
        return "Movie not found", 404

    movie = {
        "movie_id": row[0],
        "title": row[1],
        "release_date": row[2],
        "poster_url": row[3],
        "genre": row[4],
        "director": row[5],
        "cast_names": row[6],
        "trailer_link": row[7],
        "description": row[8],
    }

    return render_template("movie_detail.html", movie=movie, reviews=reviews, avg_rating=avg_rating)

@app.route('/movie/<int:movie_id>/review', methods=['POST'])
def add_review(movie_id):
    if 'user_id' not in session:
        return redirect('/login')

    try:
        rating = int(request.form['rating'])
        comment = request.form['comment'].strip()
    except:
        flash("Invalid review data.")
        return redirect(f'/movie/{movie_id}')

    if rating < 1 or rating > 5 or not comment:
        flash("Rating must be 1–5 and comment cannot be empty.")
        return redirect(f'/movie/{movie_id}')

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO reviews (user_id, movie_id, rating, comment) VALUES (%s, %s, %s, %s)",
                (session['user_id'], movie_id, rating, comment))
    conn.commit()
    cur.close()
    conn.close()
    flash("Review added!")
    return redirect(f'/movie/{movie_id}')

@app.route('/edit_movie/<int:movie_id>', methods=['GET', 'POST'])
def edit_movie(movie_id):
    if 'user_id' not in session:
        flash('Please log in to edit a movie.')
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        release_date = request.form['release_date']
        genre = request.form['genre']
        director = request.form['director']
        cast_names = request.form['cast_names']
        trailer_link = request.form['trailer_link']
        rating = request.form['rating']

        poster = request.files.get('poster')
        poster_url = None

        if poster and poster.filename != '':
            poster_filename = secure_filename(poster.filename)
            poster_path = os.path.join(app.config['UPLOAD_FOLDER'], poster_filename)
            poster.save(poster_path)
            poster_url = poster_filename

        # Update query
        update_query = """
            UPDATE movies SET 
                title = %s, description = %s, release_date = %s,
                genre = %s, director = %s, cast_names = %s,
                trailer_link = %s, rating = %s
                {poster_clause}
            WHERE movie_id = %s
        """

        poster_clause = ", poster_url = %s" if poster_url else ""
        final_query = update_query.format(poster_clause=poster_clause)

        params = [
            title, description, release_date, genre,
            director, cast_names, trailer_link, rating
        ]
        if poster_url:
            params.append(poster_url)
        params.append(movie_id)

        cur.execute(final_query, tuple(params))
        conn.commit()
        cur.close()
        conn.close()

        flash('Movie updated successfully!')
        return redirect(url_for('movie_detail', movie_id=movie_id))

    # GET request: fetch movie details
    cur.execute("""
        SELECT movie_id, title, description, release_date, poster_url,
               genre, director, cast_names, trailer_link, rating
        FROM movies WHERE movie_id = %s
    """, (movie_id,))
    movie = cur.fetchone()
    cur.close()
    conn.close()

    if not movie:
        return "Movie not found", 404

    return render_template('edit_movie.html', movie=movie)



@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=True)