from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain.chains import LLMChain
import os
from dotenv import load_dotenv

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
        
        # Define the prompt template with conversation history
        self.template = """
        You are a hotel booking assistant. Help the user book a hotel by collecting these parameters:
        1. Destination city
        2. Check-in date
        3. Check-out date
        4. Number of guests
        
        Conversation history:
        {history}
        
        Current booking info: {booking_info}
        
        Guide the conversation naturally to collect missing information based on the history and current booking info. 
        If all required information (destination, check-in, check-out, guests) is collected, summarize the booking and ask for confirmation. 
        Respond only with the assistant's message, nothing else.
        """
        
        self.prompt = ChatPromptTemplate.from_template(self.template)
        self.chain = LLMChain(llm=self.chat, prompt=self.prompt)
        
        # Initialize booking info and conversation history (budget removed)
        self.booking_info = {
            "destination": None,
            "check_in": None,
            "check_out": None,
            "guests": None
        }
        self.history = []  # List to store conversation history

    def process_message(self, user_message):
        # Update booking info based on user message
        self._update_booking_info(user_message)
        
        # Add user message to history
        self.history.append(f"User: {user_message}")
        
        # Generate response with full context
        response = self.chain.run({
            "booking_info": str(self.booking_info),
            "history": "\n".join(self.history),
            "user_message": user_message
        })
        
        # Add bot response to history
        self.history.append(f"Assistant: {response}")
        
        return response

    def _update_booking_info(self, message):
        message = message.lower()
        
        # Parsing logic (budget parsing removed)
        if "in " in message and not self.booking_info["destination"]:
            self.booking_info["destination"] = message.split("in ")[-1].split()[0]
        if "check-in" in message or "from" in message:
            for word in message.split():
                if "-" in word or word.replace("/", "").isdigit():
                    self.booking_info["check_in"] = word
                    break
        if "check-out" in message or "to" in message:
            for word in message.split():
                if "-" in word or word.replace("/", "").isdigit():
                    self.booking_info["check_out"] = word
                    break
        if "guest" in message or "people" in message:
            for word in message.split():
                if word.isdigit():
                    self.booking_info["guests"] = word
                    break

    def reset(self):
        self.booking_info = {
            "destination": None,
            "check_in": None,
            "check_out": None,
            "guests": None
        }
        self.history = []  # Clear conversation history on reset
        return "Booking and conversation history reset. How can I help you with your new booking?"