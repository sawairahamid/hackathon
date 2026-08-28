import sqlite3
from app.trace import db_path, _connect

conn = _connect()
cur = conn.cursor()
cur.execute("PRAGMA table_info(workflows)")
for row in cur.fetchall():
    print(dict(row))
