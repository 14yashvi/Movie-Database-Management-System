import psycopg2

def connect_to_db(host, database, user, password, port):
    return psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=password,
        port=port
    )