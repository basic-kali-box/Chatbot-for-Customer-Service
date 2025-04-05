from datetime import datetime, timedelta
from typing import Dict, List
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
import random

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
        self.chat = ChatGroq(groq_api_key=GROQ_API_KEY, model_name="gemma2-9b-it", temperature=0.3)
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.greetings = [
            "Hi there! I'm your friendly booking assistant. Ready to find you the perfect stay? 🌆",
            "Hello! I'm here to help with your hotel booking. Let's get started! 🏨",
            "Welcome! Where should we book your next adventure? 🌍"
        ]
        self.template = """
        You are a friendly and enthusiastic hotel booking assistant. Your goal is to have natural conversations while collecting:
        1. Destination city
        2. Check-in date (current date: {current_date})
        3. Check-out date
        4. Number of guests
        
        Conversation history:
        {history}
        
        Current booking info:
        {booking_info}
        
        Current state:
        {state}
        
        Guidelines:
        - Start with a friendly greeting if there's no history
        - Use natural language and vary your responses
        - Acknowledge user inputs positively
        - For date handling: Today is {current_date}. Convert relative dates (e.g., "tomorrow") to YYYY-MM-DD
        - If multiple dates are mentioned, ask for clarification
        - For ambiguous destinations, ask follow-up questions
        - Add occasional emojis to keep it friendly
        - Handle small talk gracefully before returning to booking tasks
        
        Response Examples:
        - "Paris sounds wonderful! When will you be checking in? 🗓️"
        - "Got it! How many guests will be joining you? 👨👩👧👦"
        - "Let me confirm: {summary}. Does this look right? 😊"
        
        If all information is collected:
        - Create a friendly summary with emojis
        - Ask for confirmation using positive language
        
        Respond conversationally in 1-2 short sentences.
        """
        self.prompt = ChatPromptTemplate.from_template(self.template)
        self.chain = RunnableSequence(self.prompt | self.chat)
        
        self.extract_template = """
        Extract booking details from this conversation history: {history}. 
        Today's date is {current_date}. Convert relative dates to absolute dates using YYYY-MM-DD format.
        
        Return JSON with:
        - destination: city name or null
        - check_in: earliest mentioned date or null
        - check_out: latest mentioned date or null
        - guests: integer or null
        
        Handle these cases:
        - "next week" => calculate from {current_date}
        - "tomorrow" => {current_date + 1 day}
        - Date ranges: "March 5th-8th" => check_in: 2024-03-05, check_out: 2024-03-08
        - Implicit check-out: "3 nights" => check_out = check_in + 3 days
        """
        self.extract_prompt = ChatPromptTemplate.from_template(self.extract_template)
        self.extract_chain = RunnableSequence(self.extract_prompt | self.chat | parser)
        
        self.booking_info: Dict[str, str] = {"destination": None, "check_in": None, "check_out": None, "guests": None}
        self.history: List[str] = []
        self.state: str = "collecting_info"
        self.last_change_request: str = None

    async def get_initial_message(self) -> str:
        """Return a random friendly greeting"""
        if not self.history:
            greeting = random.choice(self.greetings)
            self.history.append(f"Assistant: {greeting}")
            return greeting
        return ""

    async def process_message(self, user_message: str) -> str:
        user_message = user_message.strip()
        
        # Handle empty input
        if not user_message:
            return "Just checking - are you still there? 😊"
            
        # Add small talk handling
        small_talk_response = await self._handle_small_talk(user_message)
        if small_talk_response:
            self.history.append(f"User: {user_message}")
            self.history.append(f"Assistant: {small_talk_response}")
            return small_talk_response

        # Process booking-related messages
        if self.state == "awaiting_confirmation":
            return await self._handle_confirmation(user_message)
            
        await self._update_booking_info(user_message)
        
        response = await self._generate_natural_response()
        
        self.history.append(f"User: {user_message}")
        self.history.append(f"Assistant: {response}")
        return response

    async def _handle_small_talk(self, message: str) -> str:
        message_lower = message.lower()
        responses = {
            r"(hi|hello|hey)": ["Hello! 😊", "Hi there!", "Hey! Ready to book?"],
            r"how are you": ["I'm great, thanks for asking! Ready to help with your booking.", "Doing well! Let's find you a great hotel."],
            r"thank(s| you)": ["You're welcome! 😊", "My pleasure!", "Happy to help!"],
            r"(bye|goodbye)": ["Have a great day! 🌟", "Goodbye! Let me know if you need anything else."]
        }
        
        for pattern, replies in responses.items():
            if re.search(pattern, message_lower):
                return random.choice(replies) + " " + await self._get_next_question()
        return ""

    async def _get_next_question(self) -> str:
        questions = {
            "destination": [
                "Where should we book your stay? 🌍",
                "Which city are you looking at? 🏙️",
                "Ready to pick a destination? ✈️"
            ],
            "check_in": [
                "When will you be arriving? 🗓️",
                "What's your check-in date? 📅",
                "When should we book your stay from? �"
            ],
            "guests": [
                "How many people will be joining? 👨👩👧👦",
                "Number of guests? 😊",
                "How many travelers should we plan for? 🧳"
            ]
        }
        
        missing = [field for field, value in self.booking_info.items() if not value]
        if not missing:
            return ""
        return random.choice(questions.get(missing[0], ["Let's continue with your booking details."]))

    async def _handle_confirmation(self, user_message: str) -> str:
        message_lower = user_message.lower()
        
        if re.search(r"\b(yes|yeah|yep|confirm|correct)\b", message_lower):
            return await self._confirm_booking()
        elif re.search(r"\b(no|nope|change|wrong)\b", message_lower):
            return await self._handle_changes(user_message)
        else:
            return "Just to confirm: Should I finalize this booking? (yes/no) 😊"

    async def _confirm_booking(self) -> str:
        # ... existing confirmation logic ...
        
        # Enhanced success message
        success_messages = [
            "All set! Your booking is confirmed 🎉 Enjoy your stay in {destination}!",
            "Confirmed! 🎊 We're excited for your trip to {destination}!",
            "Booking saved! Have an amazing time in {destination}! 🌟"
        ]
        
        response = random.choice(success_messages).format(**self.booking_info)
        self.reset()
        return response

    async def _handle_changes(self, message: str) -> str:
        # Use LLM to detect what to change
        analysis = await self._analyze_change_request(message)
        field_to_change = analysis.get("field")
        
        change_prompts = {
            "destination": "No problem! Where would you like to go instead? 🌍",
            "check_in": "Got it! What's the new check-in date? 🗓️",
            "check_out": "Sure! When would you like to check out? 📅",
            "guests": "Okay! How many guests should we update to? 👨👩👧👦"
        }
        
        if field_to_change in change_prompts:
            self.state = "collecting_info"
            self.booking_info[field_to_change] = None
            return change_prompts[field_to_change]
        
        return "What would you like to adjust? You can say 'destination', 'dates', or 'guests'."

    async def _analyze_change_request(self, message: str) -> Dict:
        prompt = f"""
        Analyze this change request: "{message}"
        Return JSON with:
        - field: one of [destination, check_in, check_out, guests]
        - reason: short explanation
        """
        chain = ChatPromptTemplate.from_template(prompt) | self.chat | JsonOutputParser()
        return await chain.ainvoke({})

    async def _update_booking_info(self, user_message: str):
        input_data = {
            "history": "\n".join(self.history + [f"User: {user_message}"]),
            "current_date": self.current_date
        }
        
        try:
            extracted = await self.extract_chain.ainvoke(input_data)
            logger.info(f"Extracted data: {extracted}")
            
            # Date validation
            if extracted.get("check_in") and extracted.get("check_out"):
                check_in = datetime.strptime(extracted["check_in"], "%Y-%m-%d")
                check_out = datetime.strptime(extracted["check_out"], "%Y-%m-%d")
                if check_out <= check_in:
                    extracted["check_out"] = (check_in + timedelta(days=1)).strftime("%Y-%m-%d")
                    
            # Update booking info with validation
            for field in ["destination", "check_in", "check_out", "guests"]:
                if extracted.get(field):
                    self.booking_info[field] = str(extracted[field])
                    
            # Special handling for guests
            if self.booking_info["guests"]:
                try:
                    guests = int(self.booking_info["guests"])
                    if guests < 1:
                        self.booking_info["guests"] = None
                        raise ValueError("Invalid number of guests")
                except ValueError:
                    self.booking_info["guests"] = None
                    
        except Exception as e:
            logger.error(f"Extraction error: {str(e)}")

    async def _generate_natural_response(self) -> str:
        if all(self.booking_info.values()):
            summary = f"a hotel in {self.booking_info['destination']} from {self.booking_info['check_in']} to {self.booking_info['check_out']} for {self.booking_info['guests']} guests"
            responses = [
                f"All set! Here's your plan: {summary}. Should I finalize this? 😊",
                f"Let me confirm: {summary}. Does this look right? 👍",
                f"Ready to book! 🎉 Your details: {summary}. Confirm?"
            ]
            self.state = "awaiting_confirmation"
            return random.choice(responses)
            
        missing = [field for field, value in self.booking_info.items() if not value]
        prompt_fields = {
            "destination": "destination city 🌍",
            "check_in": "check-in date 📅",
            "check_out": "check-out date 🏨",
            "guests": "number of guests 👨👩👧👦"
        }
        
        prompts = [
            "Just need your {fields} to complete the booking!",
            "Almost there! Could you provide your {fields}? 😊",
            "Let's finish up! I just need: {fields} 🎉"
        ]
        
        fields = ", ".join([prompt_fields[field] for field in missing])
        return random.choice(prompts).format(fields=fields)

    def reset(self):
        self.booking_info = {k: None for k in self.booking_info}
        self.history = []
        self.state = "collecting_info"
        logger.info("System reset")

# ... rest of the code remains similar ...