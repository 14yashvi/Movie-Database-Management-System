import psycopg2
import os

DATABASE_CONFIG = {
    'database': 'postgres',
    'user': 'postgres',
    'password': 'yt13',
    'host': 'localhost',
    'port': '5432'
}

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static/uploads')
SECRET_KEY = 'yt13'