from flask import Flask, request, jsonify, render_template
import os
from groq import Groq

# Initialize the Groq client with your API key
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Initialize the Flask app
app = Flask(__name__)

# Route for the home page
@app.route("/")
def index():
    return render_template("index.html")

# Route to handle chat requests
@app.route("/ask", methods=["POST"])
def ask():
    user_message = request.form["user_message"]

    try:
        # Handle general chat
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
            model="llama-3.3-70b-versatile",  # Ensure the model is correct
        )

        # Get the chatbot's response
        chatbot_reply = chat_completion.choices[0].message.content


        return jsonify({"response": chatbot_reply, "action": "chat"})

    except Exception as e:
        return jsonify({"response": f"Sorry, an error occurred: {e}", "action": "error"})


# Run the app
if __name__ == "__main__":
    app.run(debug=True)