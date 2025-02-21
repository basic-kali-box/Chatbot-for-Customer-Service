from flask import Flask, render_template, request, jsonify
from chatbot import HotelBookingChatbot

app = Flask(__name__)
chatbot = HotelBookingChatbot()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    if user_message.lower() == 'reset':
        chatbot.reset()
        return jsonify({'response': 'Booking reset. How can I help you with your new booking?'})
    
    response = chatbot.process_message(user_message)
    return jsonify({'response': response})

if __name__ == '__main__':
    app.run(debug=True)