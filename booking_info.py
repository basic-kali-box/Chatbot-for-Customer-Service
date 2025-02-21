import mysql.connector
from mysql.connector import Error

def create_connection(host_name, user_name, user_password, db_name):
    connection = None
    try:
        connection = mysql.connector.connect(
            host=host_name,
            user=user_name,
            passwd=user_password,
            database=db_name
        )
        print("Connection to MySQL DB successful")
    except Error as e:
        print(f"The error '{e}' occurred")
    return connection

def add_to_db(city, check_in, check_out, guests):
    connection = create_connection("localhost", "mehdi", "mehdi_password", "HotelCheckInSystem")
    if connection:
        try:
            # Corrected query: Exclude 'id' since it's auto-incremented
            query = "INSERT INTO booking_infos (city, check_in, check_out, guests) VALUES (%s, %s, %s, %s)"
            values = (city, check_in, check_out, guests)
            cursor = connection.cursor()
            cursor.execute(query, values)
            connection.commit()  # Save the changes to the database
            print("Booking information added successfully")
        except Error as e:
            print(f"Failed to add booking: {e}")
        finally:
            cursor.close()
            connection.close()  # Clean up resources