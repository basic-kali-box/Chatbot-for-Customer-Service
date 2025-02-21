from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain.chains import LLMChain
import os
from dotenv import load_dotenv
from booking_info import add_to_db
from datetime import datetime

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

class HotelBookingChatbot:
    def __init__(self):
        # Initialize ChatGroq
        self.chat = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name="mixtral-8x7b-32768",
            temperature=0
        )
        
        # Define the prompt template with conversation history and state
        self.template = """
        You are a hotel booking assistant. Start every response with "Hello!" unless the user is confirming the booking.
        Help the user book a hotel by collecting these parameters:
        1. Destination city
        2. Check-in date (in YYYY-MM-DD format)
        3. Check-out date (in YYYY-MM-DD format)
        4. Number of guests
        
        Conversation history:
        {history}
        
        Current booking info: {booking_info}
        
        Current state: {state}
        
        Guide the conversation naturally to collect missing information based on the history and current booking info. 
        If all required information (destination, check-in, check-out, guests) is collected, summarize the booking like this:
        "I have your booking details: a hotel in [destination] from [check_in] to [check_out] for [guests] guests. Please confirm by saying 'yes' or 'no'."
        If the state is 'awaiting_confirmation' and the user says 'yes' or 'confirm', respond with "Your booking has been confirmed and saved!" 
        If they say 'no', ask "What would you like to change?" and continue collecting info.
        Respond only with the assistant's message, nothing else.
        """
        
        self.prompt = ChatPromptTemplate.from_template(self.template)
        self.chain = LLMChain(llm=self.chat, prompt=self.prompt)
        
        # Initialize booking info, conversation history, and state
        self.booking_info = {
            "destination": None,
            "check_in": None,
            "check_out": None,
            "guests": None
        }
        self.history = []  # Store conversation history
        self.state = "collecting_info"  # Track whether we're collecting info or awaiting confirmation

    def process_message(self, user_message):
        # Handle confirmation first if in awaiting_confirmation state
        if self.state == "awaiting_confirmation":
            user_message_lower = user_message.lower().strip("'\"")
            if "yes" in user_message_lower or "confirm" in user_message_lower:
                # Save to database
                add_to_db(
                    self.booking_info["destination"],
                    self.booking_info["check_in"],
                    self.booking_info["check_out"],
                    int(self.booking_info["guests"])
                )
                response = "Your booking has been confirmed and saved!"
                self.reset()  # Reset after saving
                self.history.append(f"User: {user_message}")
                self.history.append(f"Assistant: {response}")
                return response
            elif "no" in user_message_lower:
                self.state = "collecting_info"
                response = "Hello! What would you like to change?"
                self.history.append(f"User: {user_message}")
                self.history.append(f"Assistant: {response}")
                return response

        # Update booking info based on user message if collecting info
        if self.state == "collecting_info":
            self._update_booking_info(user_message)
        
        # Add user message to history
        self.history.append(f"User: {user_message}")
        
        # Generate response with full context and extract the 'text' field
        result = self.chain.invoke({
            "booking_info": str(self.booking_info),
            "history": "\n".join(self.history),
            "state": self.state,
            "user_message": user_message
        })
        response = result.get('text', 'Error: No text in response')  # Extract 'text' or fallback
        
        # Add bot response to history
        self.history.append(f"Assistant: {response}")
        
        # Check if all info is collected and transition to confirmation state
        if (self.state == "collecting_info" and 
            all(value is not None for value in self.booking_info.values()) and
            "Please confirm" in response):
            self.state = "awaiting_confirmation"

        return response

    def _update_booking_info(self, message):
        message = message.lower()
        
        # Update destination (only if not set)
        if not self.booking_info["destination"]:
            words = message.split()
            for word in words:
                if word not in ["heyy", "hello", "hi", "hey", "mr", "ai", "from", "to", "on", "for"]:
                    self.booking_info["destination"] = word
                    break
        
        # Update check-in and check-out dates
        words = message.split()
        for i, word in enumerate(words):
            # Handle YYYY-MM-DD format
            if "-" in word and len(word.split("-")) == 3:
                if not self.booking_info["check_in"]:
                    self.booking_info["check_in"] = word
                elif not self.booking_info["check_out"]:
                    self.booking_info["check_out"] = word
            # Handle textual dates (e.g., "February 20")
            elif i + 1 < len(words) and word in ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]:
                date_str = f"{word} {words[i + 1]}"
                parsed_date = self._parse_text_date(date_str)
                if parsed_date:
                    if not self.booking_info["check_in"]:
                        self.booking_info["check_in"] = parsed_date
                    elif not self.booking_info["check_out"]:
                        self.booking_info["check_out"] = parsed_date
        
        # Update guests (only if explicitly related to guests)
        if "guest" in message or "people" in message or "alone" in message or any(w.isdigit() for w in message.split()):
            if "alone" in message:
                self.booking_info["guests"] = "1"
            else:
                for word in message.split():
                    if word.isdigit() and word not in ["2025", "12", "02", "12"]:  # Avoid years or day numbers
                        self.booking_info["guests"] = word
                        break

    def _parse_text_date(self, date_str):
        # Parse "February 20" to "2025-02-20" (correcting typo "Febraury")
        months = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
            "febraury": "02"  # Handle typo
        }
        parts = date_str.split()
        if len(parts) >= 2:
            month = months.get(parts[0].lower())
            day = parts[1].zfill(2)
            year = "2025"  # Default to 2025 based on current date (Feb 21, 2025)
            if month and day:
                return f"{year}-{month}-{day}"
        return None

    def reset(self):
        self.booking_info = {
            "destination": None,
            "check_in": None,
            "check_out": None,
            "guests": None
        }
        self.history = []
        self.state = "collecting_info"
        return "Booking and conversation history reset. How can I help you with your new booking?"