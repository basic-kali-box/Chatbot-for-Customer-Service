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

if __name__ == '__main__':
    app.run(debug=True)