from app.db import get_connection

conn = get_connection()
print("DB 연결 성공")
conn.close()