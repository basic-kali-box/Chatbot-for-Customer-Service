from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableSequence
from pydantic import BaseModel, Field
import os
import re
import httpx
import logging
from dotenv import load_dotenv
from booking_info import add_to_db
import asyncio

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FLASK_API_URL = os.getenv("FLASK_API_URL", "http://localhost:5000")

class BookingDetails(BaseModel):
    destination: str = Field(description="The city where the hotel is to be booked")
    check_in: str = Field(description="Check-in date in YYYY-MM-DD format")
    check_out: str = Field(description="Check-out date in YYYY-MM-DD format")
    guests: int = Field(description="Number of guests staying")

parser = JsonOutputParser(pydantic_object=BookingDetails)

class HotelBookingChatbot:
    def __init__(self):
        self.chat = ChatGroq(groq_api_key=GROQ_API_KEY, model_name="mixtral-8x7b-32768", temperature=0)
        self.template = """
        You are a hotel booking assistant. Say "Hello! I'm your AI Booking Assistant, where would you like to book a hotel?" only in your first response when the conversation history is empty. 
        Help the user book a hotel by collecting these parameters:
        1. Destination city
        2. Check-in date
        3. Check-out date
        4. Number of guests
        
        Conversation history:
        {history}
        
        Current booking info:
        {booking_info}
        
        Current state:
        {state}
        
        Guide the conversation naturally to collect missing information based on the history and current booking info. 
        If destination is missing, ask "Where would you like to book a hotel?"
        If check-in or check-out dates are missing, ask "When would you like to check in and check out?"
        If only check-out date is missing, ask "When would you like to check out?"
        If guests are missing, ask "How many guests will be staying?"
        If all required information (destination, check-in, check-out, guests) is collected, summarize the booking like this:
        "I have your booking details: a hotel in [destination] from [check_in] to [check_out] for [guests] guests. Please confirm by saying 'yes' or 'no'."
        If the state is 'awaiting_confirmation' and the user says 'yes' or 'confirm', respond with "Your booking has been confirmed and saved!" 
        If they say 'no', ask "What would you like to change?" and if they specify "guests" or "number of guests", ask "How many guests will be staying?" to collect the new number.
        Respond only with the assistant's message, nothing else.
        """
        self.prompt = ChatPromptTemplate.from_template(self.template)
        self.chain = RunnableSequence(self.prompt | self.chat)
        
        self.extract_template = """
        Extract booking details from this conversation history: {history}. Return as JSON: {{'destination': str or null, 'check_in': 'YYYY-MM-DD' or null, 'check_out': 'YYYY-MM-DD' or null, 'guests': int or null}}. Use 2025 as the year unless specified. Only include dates explicitly mentioned; do not guess defaults if dates are missing.
        """
        self.extract_prompt = ChatPromptTemplate.from_template(self.extract_template)
        self.extract_chain = RunnableSequence(self.extract_prompt | self.chat | parser)
        
        self.booking_info = {"destination": None, "check_in": None, "check_out": None, "guests": None}
        self.history = []
        self.state = "collecting_info"
        self.last_change_request = None

    async def get_initial_message(self) -> str:
        """Return the initial greeting message when the conversation starts."""
        if not self.history:  # If history is empty, return the greeting
            return "Hello! I'm your AI Booking Assistant, where would you like to book a hotel?"
        return ""

    async def process_message(self, user_message: str) -> str:
        # If history is empty, send the initial greeting
        if not self.history:
            response = "Hello! I'm your AI Booking Assistant, where would you like to book a hotel?"
            self.history.append(f"Assistant: {response}")
            return response

        user_message_lower = user_message.lower().strip("'")
        
        if self.state == "awaiting_confirmation":
            # Use regex to match 'yes' or 'confirm' more strictly
            if re.search(r'\b(yes|confirm)\b', user_message_lower):
                db_success = await add_to_db(
                    self.booking_info["destination"],
                    self.booking_info["check_in"],
                    self.booking_info["check_out"],
                    int(self.booking_info["guests"])
                )
                booking_data = {
                    "destination": self.booking_info["destination"],
                    "check_in": self.booking_info["check_in"],
                    "check_out": self.booking_info["check_out"],
                    "guests": self.booking_info["guests"]
                }
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(f"{FLASK_API_URL}/booking", json=booking_data, timeout=5)
                        response.raise_for_status()
                        response_data = response.json()
                        api_success = response_data.get("status") == "success"
                        if not api_success:
                            logger.error(f"API failed with response: {response_data}")
                except httpx.TimeoutException:
                    api_success = False
                    logger.error("API request timed out after 5 seconds")
                except httpx.HTTPStatusError as e:
                    api_success = False
                    logger.error(f"API HTTP error: {e.response.status_code} - {e.response.text}")
                except httpx.RequestError as e:
                    api_success = False
                    logger.error(f"API request failed: {str(e)}")
                
                if db_success and api_success:
                    response = "Your booking has been confirmed and saved!"
                elif db_success:
                    response = "Your booking was confirmed and saved to the database but couldn’t be processed by the booking system."
                elif api_success:
                    response = "Your booking was confirmed and processed by the booking system but couldn’t be saved to the database."
                else:
                    response = "Your booking was confirmed but couldn’t be saved to the database or processed by the booking system."
                
                self.reset()
            elif re.search(r'\b(no|cancel)\b', user_message_lower):
                self.state = "collecting_info"
                response = "What would you like to change? Please specify: destination, dates, or guests."
            else:
                response = "Please confirm your booking by saying 'yes' or 'no'."
        else:
            await self._update_booking_info(user_message)
            
            logger.info(f"Booking info after update: {self.booking_info}")
            
            if all(value is not None for value in self.booking_info.values()):
                response = f"I have your booking details: a hotel in {self.booking_info['destination']} from {self.booking_info['check_in']} to {self.booking_info['check_out']} for {self.booking_info['guests']} guests. Please confirm by saying 'yes' or 'no'."
                self.state = "awaiting_confirmation"
            else:
                missing_info = []
                if not self.booking_info["destination"]:
                    missing_info.append("destination")
                if not self.booking_info["check_in"] or not self.booking_info["check_out"]:
                    missing_info.append("dates")
                if not self.booking_info["guests"]:
                    missing_info.append("number of guests")
                response = f"I still need the following information: {', '.join(missing_info)}."

        self.history.append(f"User: {user_message}")
        self.history.append(f"Assistant: {response}")
        return response

    async def _update_booking_info(self, user_message: str):
        input_data = {"history": "\n".join(self.history + [f"User: {user_message}"])}
        
        try:
            extracted = await self.extract_chain.ainvoke(input_data)
            logger.info(f"Extracted data: {extracted}")
            if isinstance(extracted, dict) and 'text' in extracted:
                extracted = extracted['text']
        except Exception as e:
            logger.error(f"Extraction failed: {str(e)}", exc_info=True)
            extracted = {
                "destination": self.booking_info["destination"],
                "check_in": self.booking_info["check_in"],
                "check_out": self.booking_info["check_out"],
                "guests": self.booking_info["guests"]
            }

        if extracted.get("destination"):
            self.booking_info["destination"] = extracted["destination"]
        if extracted.get("check_in"):
            self.booking_info["check_in"] = extracted["check_in"]
        if extracted.get("check_out"):
            self.booking_info["check_out"] = extracted["check_out"]
        if extracted.get("guests") is not None:
            self.booking_info["guests"] = str(extracted["guests"])

    def _update_guests(self, message: str):
        message = message.lower()
        if "alone" in message:
            self.booking_info["guests"] = "1"
        else:
            for word in message.split():
                if word.isdigit():
                    self.booking_info["guests"] = word
                    break
            if "=" in message:
                parts = message.split("=")
                if len(parts) > 1:
                    value = parts[1].strip()
                    if value.isdigit():
                        self.booking_info["guests"] = value

    def reset(self):
        self.booking_info = {"destination": None, "check_in": None, "check_out": None, "guests": None}
        self.history = []
        self.state = "collecting_info"
        self.last_change_request = None
        logger.info("Conversation reset")
        # Return a reset confirmation message
        return "Booking and conversation history reset. The conversation will start fresh on the next message."