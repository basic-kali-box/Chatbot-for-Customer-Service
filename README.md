Hotel Booking Chatbot

A Flask-based AI chatbot for booking hotels, powered by LangChain and Grok (xAI). This project allows users to conversationally book hotels by specifying a destination city, check-in/check-out dates, and number of guests. The chatbot uses natural language processing to parse inputs, stores bookings in a MySQL database, and integrates with a REST API endpoint for processing. Features include:

    Conversational Interface: Guides users to provide booking details naturally.
    Structured Parsing: Leverages LangChain’s tools to extract parameters from text.
    Database & API Integration: Saves bookings to MySQL and sends them to a Flask /booking endpoint.
    Animated UI: Includes a fade-in animation for the initial message.

Tech Stack: Python, Flask, LangChain, Grok (xAI), Pydantic, MySQL, Requests.

Setup: Requires a .env file with GROQ_API_KEY and MySQL setup via booking_info.py. Run with python app.py.
