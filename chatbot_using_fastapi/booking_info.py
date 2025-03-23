import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "chatbot_db")

async def add_to_db(destination: str, check_in: str, check_out: str, guests: int) -> bool:
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                destination VARCHAR(255),
                check_in DATE,
                check_out DATE,
                guests INT
            )
        """)
        cursor.execute("""
            INSERT INTO bookings (destination, check_in, check_out, guests)
            VALUES (%s, %s, %s, %s)
        """, (destination, check_in, check_out, guests))
        conn.commit()
        return True
    except mysql.connector.Error as e:
        print(f"Database error: {str(e)}")
        return False
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()