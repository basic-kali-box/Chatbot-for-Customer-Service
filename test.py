from flask import Flask, render_template, request, jsonify
from chatbot import HotelBookingChatbot
from booking_info import add_to_db  # Import add_to_db
from datetime import datetime
import uuid

app = Flask(__name__)
chatbot = HotelBookingChatbot()

@app.route('/')
def index():
    chatbot.reset()
    initial_message = "Hello! I'm your AI Booking Assistant, where would you like to book a hotel?"
    # Pass the initial message to the template
    return render_template('index.html', initial_message=initial_message)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    print(f"Received user message: {user_message}")
    if user_message.lower() == 'reset':
        response = chatbot.reset()
        print(f"Reset response (raw): {response}")
        json_response = {'response': response}
        print(f"Reset JSON response: {json_response}")
        return jsonify(json_response)
    
    response = chatbot.process_message(user_message)
    print(f"Chat response (raw): {response}")
    json_response = {'response': response}
    print(f"Chat JSON response: {json_response}")
    return jsonify(json_response)

@app.route('/booking', methods=['POST'])
def get_booking():
    data = request.json

    # Basic validation: check if all required fields are present
    required_fields = ['destination', 'check_in', 'check_out', 'guests']
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({"status": "error", "message": f"Missing or empty field: {field}"}), 400
    
    # Additional validation
    try:
        check_in = datetime.strptime(data['check_in'], '%Y-%m-%d')
        check_out = datetime.strptime(data['check_out'], '%Y-%m-%d')
        if check_out <= check_in:
            return jsonify({"status": "error", "message": "Check-out date must be after check-in date"}), 400
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    if not str(data['guests']).isdigit() or int(data['guests']) <= 0:
        return jsonify({"status": "error", "message": "Guests must be a positive integer"}), 400

    # Save to database (sync with chatbot's add_to_db)
    db_success = add_to_db(data['destination'], data['check_in'], data['check_out'], int(data['guests']))
    
    print("Received booking:", data)

    # Generate a unique booking ID
    booking_id = str(uuid.uuid4())
    response = {
        "status": "success",
        "booking_id": booking_id,
        "db_saved": db_success  # Optional: Inform chatbot if DB save worked
    }
    return jsonify(response), 201

if __name__ == '__main__':
    app.run(debug=True)