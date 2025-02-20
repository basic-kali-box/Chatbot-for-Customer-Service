let isBooking = false;
let bookingFields = [];
let bookingData = {};

function displayMessage(content, type) {
    let messageDiv = document.createElement("div");
    messageDiv.classList.add("message");

    let messageContent = document.createElement("div");
    messageContent.classList.add(type === "user" ? "user-message" : "bot-message");
    messageContent.textContent = content;

    messageDiv.appendChild(messageContent);
    document.getElementById("chatbox").appendChild(messageDiv);
    document.getElementById("chatbox").scrollTop = document.getElementById("chatbox").scrollHeight;
}

function showTypingIndicator() {
    let typingIndicator = document.createElement("div");
    typingIndicator.id = "typingIndicator";
    typingIndicator.classList.add("typing-indicator");
    typingIndicator.textContent = "Chatbot is typing...";
    document.getElementById("chatbox").appendChild(typingIndicator);
    document.getElementById("chatbox").scrollTop = document.getElementById("chatbox").scrollHeight;
}

function hideTypingIndicator() {
    let typingIndicator = document.getElementById("typingIndicator");
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

function checkEnter(event) {
    if (event.key === "Enter") {
        sendMessage();
    }
}

async function sendMessage() {
    let userMessage = document.getElementById("user_message").value;

    if (userMessage.trim() === "") {
        return;
    }

    // Display user's message
    displayMessage(userMessage, "user");
    document.getElementById("user_message").value = "";

    // Show typing indicator
    showTypingIndicator();

    // Allow UI to update before sending the request
    await new Promise(resolve => setTimeout(resolve, 100));

    try {
        let response;
        if (isBooking) {
            // If in booking mode, collect the required field
            bookingData[bookingFields[0]] = userMessage;
            bookingFields.shift(); // Remove the collected field

            if (bookingFields.length > 0) {
                // Ask for the next field
                displayMessage(`Please provide your ${bookingFields[0]}:`, "bot");
                hideTypingIndicator();
                return;
            } else {
                // All fields collected, send booking data to the server
                response = await fetch("/book", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(bookingData),
                });
                isBooking = false; // Reset booking mode
            }
        } else {
            // Handle general chat
            response = await fetch("/ask", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: "user_message=" + encodeURIComponent(userMessage),
            });
        }

        const data = await response.json();

        // Hide typing indicator after receiving response
        hideTypingIndicator();

        if (data.action === "booking") {
            // Start booking process
            isBooking = true;
            bookingFields = data.fields;
            bookingData = {}; // Reset booking data
            displayMessage(data.response, "bot");
            displayMessage(`Please provide your ${bookingFields[0]}:`, "bot");
        } else {
            // Display chatbot's response
            displayMessage(data.response, "bot");
        }

    } catch (error) {
        hideTypingIndicator();
        displayMessage("Error: Unable to connect to chatbot.", "bot");
    }
}