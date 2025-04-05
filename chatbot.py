import os
import re
import logging
from dotenv import load_dotenv
from aiomysql import Error  # Import Error for exception handling
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union # Added Optional, Union
import asyncio
import random
from functools import partial # Needed for log_async if using getattr approach
import json # Added for fallback JSON parsing
import uuid
import aiohttp
from typing import Tuple
from weather_utils import get_weather_tip

from booking_info import add_to_db , create_connection
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableSequence
from pydantic import BaseModel, Field, field_validator, validator # validator is deprecated, use field_validator



# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
load_dotenv()
# FLASK_API_URL = os.getenv("FLASK_API_URL", "http://localhost:5000") # Not used in this snippet

# --- Pydantic Model ---
class BookingDetails(BaseModel):
    destination: Optional[str] = Field(None, description="The city where the hotel is to be booked")
    check_in: Optional[str] = Field(None, description="Check-in date in YYYY-MM-DD format")
    check_out: Optional[str] = Field(None, description="Check-out date in YYYY-MM-DD format")
    guests: Optional[int] = Field(None, description="Number of guests staying")

    @field_validator('check_in', 'check_out', mode='before')
    def validate_date_format(cls, value):
        if value is None:
            return value
        try:
            # Basic format check - detailed validation happens later
            if isinstance(value, str):
                 datetime.strptime(value, "%Y-%m-%d")
                 return value
            return None # Treat non-strings as invalid here
        except (ValueError, TypeError):
            # Let the LLM attempt extraction, validation happens later
            logger.warning(f"Extractor returned potentially invalid date format: {value}. Will validate later.")
            return None # Treat as not extracted if format is wrong initially

    @field_validator('guests', mode='before')
    def validate_guests(cls, value):
        if value is None:
            return value
        try:
            num_guests = int(value)
            if num_guests > 0:
                return num_guests
            else:
                logger.warning(f"Extractor returned invalid guest count: {value}")
                return None
        except (ValueError, TypeError):
            logger.warning(f"Extractor returned non-integer guest count: {value}")
            return None

parser = JsonOutputParser(pydantic_object=BookingDetails)

# --- Async Logging Helper ---
async def log_async(level: str, message: str, **kwargs):
    """Logs messages asynchronously using asyncio.to_thread."""
    try:
        log_func = getattr(logger, level.lower())
        # Use asyncio.to_thread to run the blocking I/O log operation in a separate thread
        await asyncio.to_thread(log_func, message, **kwargs)
    except AttributeError:
        # Fallback to error logging if invalid level is provided
        await asyncio.to_thread(logger.error, f"Invalid log level '{level}' used for message: {message}")
    except Exception as e:
        # Catch any other unexpected errors during logging
        print(f"Error during async logging: {e}") # Use print as logger might be the issue

# --- Chatbot Class ---
class HotelBookingChatbot:
          
    async def _confirm_booking(self) -> list[str]:
        """Finalizes the booking and saves to database, returning a list of messages"""
        await log_async("info", f"Attempting to confirm booking: {self.booking_info}")
        
        if None in self.booking_info.values():
            return ["Missing some booking information. Please complete all fields."]

        try:
            # Prepare booking data
            booking_data = {
                'destination': self.booking_info['destination'],
                'check_in': self.booking_info['check_in'],
                'check_out': self.booking_info['check_out'],
                'guests': self.booking_info['guests']
            }

            # Call add_to_db synchronously with unpacked arguments
            db_result = add_to_db(
                booking_data['destination'],
                booking_data['check_in'],
                booking_data['check_out'],
                booking_data['guests']
            )
            
            if db_result:  # Check for True (successful insertion)
                import uuid  # Ensure uuid is imported at the top of chatbot.py
                booking_id = str(uuid.uuid4())  # Generate booking ID locally
                
                # Build confirmation message with the desired structure
                confirmation_message = (
                    f"Booking confirmed! 🎉\n"
                    f"• ID: {booking_id}\n"
                    f"• Destination: **{self.booking_info['destination']}**\n"
                    f"• Dates: **{self.booking_info['check_in']}** to **{self.booking_info['check_out']}**\n"
                    f"• Guests: **{self.booking_info['guests']}**\n"
                    f"Wishing you a wonderful journey! ✈️"
                )
                
                # Get weather tip using the standalone function
                weather_tip = await get_weather_tip(self.booking_info['destination'], log_async)
                
                self.reset()
                
                # Return a list of messages
                messages = [confirmation_message]
                if weather_tip:
                    messages.append(weather_tip)
                return messages
            else:
                await log_async("error", "Database insertion failed")
                return ["Booking failed ❌: Could not save to database. Please try again."]

        except Exception as e:
            await log_async("error", f"Confirmation error: {str(e)}", exc_info=True)
            return ["There was an error processing your booking. Please try again."]        

    async def reset(self):
        """Resets the booking information and conversation history."""
        self.booking_info = {"destination": None, "check_in": None, "check_out": None, "guests": None}
        self.history = []
        self.state = "collecting_info"
        # Log reset action explicitly
        # await log_async("info", "Chatbot state has been reset.") # Can't await in non-async
        logger.info("Chatbot state has been reset.") # Use synchronous logger here
        print("--- Chatbot Reset ---") # Use print for explicit reset signal in console

    def __init__(self):
        self.chat = ChatGroq(groq_api_key=GROQ_API_KEY, model_name="gemma2-9b-it", temperature=0.3)
        self.current_date = datetime.now().date() # Store as date object
        self.current_date_str = self.current_date.strftime("%Y-%m-%d") # String version for prompts
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

        Current booking info (use only if provided by user, otherwise ask):
        Destination: {destination}
        Check-in: {check_in}
        Check-out: {check_out}
        Guests: {guests}

        Current state: {state}

        Guidelines:
        - Start with a friendly greeting if there's no history.
        - Use natural language, be conversational, and vary your responses. Use 1-2 short sentences.
        - Acknowledge user inputs positively (e.g., "Great!", "Sounds good!").
        - For date handling: Today is {current_date}. Convert relative dates (e.g., "tomorrow", "next Tuesday", "weekend after next") to YYYY-MM-DD format. Ensure check-in is not in the past. Ensure check-out is after check-in. If only duration is given (e.g., "3 nights"), calculate check-out based on check-in.
        - If multiple dates or destinations are mentioned ambiguously, ask for clarification.
        - For ambiguous destinations (e.g., "Springfield"), ask for the state or country.
        - Use occasional emojis to maintain a friendly tone. ☀️🏖️🌴
        - Handle simple small talk (greetings, thanks, how are you) gracefully before returning to the booking task.
        - If all information is collected, provide a clear summary with emojis and ask for confirmation.
        - If the user wants to change something after confirmation is requested, identify the field and ask for the new value.

        Response Examples:
        - "Paris sounds wonderful! 🗼 When are you planning to check in? 🗓️"
        - "Got it, 2 guests! And what's your check-in date? 📅"
        - "Okay, checking in tomorrow, {tomorrow_date}. How many nights will you stay, or what's your check-out date? 🏨"
        - "Let me confirm: A stay in {destination} from {check_in} to {check_out} for {guests} person(s). Does this look right? 👍"
        - "Sure, we can change the dates. What new check-in date were you thinking of? 🤔"

        Focus on the next piece of missing information based on the current booking info and history.
        Respond conversationally.
        """
        self.prompt = ChatPromptTemplate.from_template(self.template)
        # Removed RunnableSequence here, will invoke prompt and chat directly for more control

        self.extract_template = """
        Analyze the latest user message in the context of the conversation history to extract booking details.
        Today's date is {current_date}. Convert relative dates (like "tomorrow", "next Friday", "August 15th") to absolute YYYY-MM-DD format.
        If a duration is mentioned (e.g., "3 nights", "a week"), calculate the check-out date based on the check-in date if available.

        Conversation History:
        {history}

        Current User Message: {user_message}

        Return ONLY JSON with the extracted values for these keys. Use null if a value isn't mentioned or is unclear in the *latest user message*.
        {{
            "destination": "city name or null",
            "check_in": "YYYY-MM-DD or null",
            "check_out": "YYYY-MM-DD or null",
            "guests": "integer or null"
        }}

        Examples:
        - User says "I want to go to London next week for 5 nights": Infer check-in based on "next week" and calculate check-out.
        - User says "tomorrow": Extract check_in as {tomorrow_date}.
        - User says "check in March 5th, check out March 8th": Extract both dates.
        - User says "2 people": Extract guests: 2.
        """
        self.extract_prompt = ChatPromptTemplate.from_template(self.extract_template)
        self.extract_chain = RunnableSequence(self.extract_prompt | self.chat | parser)

        self.booking_info: Dict[str, Union[str, int, None]] = {"destination": None, "check_in": None, "check_out": None, "guests": None}
        self.history: List[str] = []
        self.state: str = "collecting_info" # states: collecting_info, awaiting_confirmation, changing_info
        

    async def get_initial_message(self) -> str:
        """Return a random friendly greeting if conversation hasn't started."""
        if not self.history:
            greeting = random.choice(self.greetings)
            self.history.append(f"Assistant: {greeting}")
            await log_async("info", "Started new conversation.")
            return greeting
        # If history exists, initial message is not needed, process_message will handle it.
        return ""

    async def process_message(self, user_message: str) -> list[str]:
        """Processes the user's message and returns the chatbot's responses as a list."""
        user_message = user_message.strip()

        if not user_message:
            response = random.choice([
                "Just checking - are you still there? 😊 Let me know how I can help!",
                "No message received. Need help with a booking? 🤔"
            ])
            self.history.append(f"Assistant: {response}")
            await log_async("info", f"Assistant response (empty message): {response}")
            return [response]

        self.history.append(f"User: {user_message}")
        await log_async("info", f"User message: {user_message}")

        # 1. Handle Small Talk First
        small_talk_response = await self._handle_small_talk(user_message)
        if small_talk_response:
            self.history.append(f"Assistant: {small_talk_response}")
            await log_async("info", f"Assistant response (small talk): {small_talk_response}")
            return [small_talk_response]

        # 2. Handle Confirmation/Changes if applicable
        if self.state == "awaiting_confirmation":
            responses = await self._handle_confirmation(user_message)
            for response in responses:
                self.history.append(f"Assistant: {response}")
                await log_async("info", f"Assistant response (confirmation): {response}")
            return responses

        # 3. Extract Information and Update State (Main booking flow)
        update_status_message = await self._update_booking_info(user_message)
        if update_status_message:
            # _update_booking_info handled an error or needs specific clarification
            self.history.append(f"Assistant: {update_status_message}")
            await log_async("warning", f"Assistant response (update issue): {update_status_message}")
            return [update_status_message]

        # 4. Generate Next Conversational Response
        response = await self._generate_natural_response()
        self.history.append(f"Assistant: {response}")
        await log_async("info", f"Assistant response (booking flow): {response}")
        return [response]

    async def _handle_small_talk(self, message: str) -> Optional[str]:
        """Handles simple greetings, thanks, etc., and returns to the booking task."""
        message_lower = message.lower()
        responses = {
            r"\b(hi|hello|hey|yo|wassup)\b": ["Hello! 😊", "Hi there!", "Hey! Ready to book a hotel?"],
            r"\bhow are you\b": ["I'm doing great, ready to find you the perfect hotel!", "I'm operational and ready to assist with your booking!"],
            r"\b(thank(s| you)|cheers)\b": ["You're very welcome! 😊", "My pleasure!", "Happy to help! What's next?"],
            r"\b(bye|goodbye|see ya)\b": ["Goodbye! 👋 Feel free to return anytime!", "Have a great day! Let me know if you need booking help later."],
            r"\b(what'?s up|how'?s it going)\b": ["Just here, ready to help you book a stay! 🏨", "All good! Thinking about a trip? 😊"]
        }

        for pattern, replies in responses.items():
            if re.search(pattern, message_lower):
                base_reply = random.choice(replies)
                # If booking is in progress, gently nudge back
                if any(self.booking_info.values()) and not all(self.booking_info.values()):
                     next_q = await self._get_next_question_prompt()
                     if next_q:
                         # Avoid asking question if last message was already a question
                         last_assistant_msg = self.history[-1] if self.history and "Assistant:" in self.history[-1] else ""
                         if "?" not in last_assistant_msg:
                              return f"{base_reply} {next_q}"
                         else:
                              return base_reply # Just reply if already asked question
                elif self.state == "collecting_info" and not any(self.booking_info.values()):
                     # If starting out, ask the first question
                     return f"{base_reply} Where would you like to book a hotel? 🌍"
                return base_reply # Just reply if booking is complete or not started

        return None # Not small talk

    # --- THIS METHOD IS UPDATED ---
    async def _update_booking_info(self, user_message: str) -> Optional[str]:
        """Extracts info, validates, updates self.booking_info. Returns error/clarification message or None."""
        input_data = {
            "history": "\n".join(self.history),
            "user_message": user_message, # Pass separately for clarity in prompt
            "current_date": self.current_date_str,
            "tomorrow_date": (self.current_date + timedelta(days=1)).strftime("%Y-%m-%d")
        }

        try:
            # Update type hint to reflect the actual runtime type based on the error
            extracted_data: dict = await self.extract_chain.ainvoke(input_data)

            # Log the received data and its type for debugging
            await log_async("info", f"Extractor chain returned type: {type(extracted_data)}")
            await log_async("info", f"Extractor chain returned value: {extracted_data}")

            # Ensure it's actually a dictionary before proceeding
            if not isinstance(extracted_data, dict):
                 await log_async("error", f"Extractor did not return a dictionary as expected. Got type: {type(extracted_data)}, value: {extracted_data}")
                 # Try to recover if it's a string containing JSON that the parser missed
                 if isinstance(extracted_data, str):
                     try:
                         # import json # Already imported at top
                         extracted_data = json.loads(extracted_data)
                         if not isinstance(extracted_data, dict): raise ValueError("Parsed JSON is not a dict")
                         await log_async("info", "Successfully parsed string output into dict.")
                     except Exception as parse_err:
                         await log_async("error", f"Failed to parse string output from extractor: {parse_err}")
                         return "Sorry, I had trouble reading the details. Could you please try rephrasing?"
                 else:
                    return "Sorry, I encountered an unexpected issue processing the details. Could you try again?"


            # --- FIX: Use the dictionary directly ---
            # No need for .model_dump() if extracted_data is already a dict.
            extracted = extracted_data
            # --------------------------------------

            updated = False
            validation_message = None

            # Update fields if newly extracted - Use .get() for safe access
            new_destination = extracted.get("destination")
            # Check type just in case LLM returns something odd
            if new_destination and isinstance(new_destination, str) and self.booking_info["destination"] != new_destination:
                self.booking_info["destination"] = new_destination.strip() # Add strip
                updated = True
                await log_async("info", f"Updated destination to: {self.booking_info['destination']}")


            new_guests = extracted.get("guests")
             # Check type explicitly
            if new_guests is not None: # Check for None explicitly
                try:
                    guest_count = int(new_guests) # Ensure it's an int
                    if guest_count > 0:
                        if self.booking_info["guests"] != guest_count:
                           self.booking_info["guests"] = guest_count
                           updated = True
                           await log_async("info", f"Updated guests to: {self.booking_info['guests']}")
                    else:
                        await log_async("warning", f"Extractor dictionary contained invalid guest count: {new_guests}")
                        validation_message = "The number of guests must be at least 1. How many people are travelling? 👨‍👩‍👧‍👦"
                except (ValueError, TypeError):
                     await log_async("warning", f"Extractor dictionary contained non-numeric guest count: {new_guests}")
                     # Don't set validation message here, let _generate_natural_response ask again if needed


            # Date validation and updating
            new_check_in_str = extracted.get("check_in")
            new_check_out_str = extracted.get("check_out")
            current_check_in = self.booking_info.get("check_in")
            current_check_out = self.booking_info.get("check_out")

            # Validate and update check-in date (ensure it's a string before processing)
            if new_check_in_str and isinstance(new_check_in_str, str) and new_check_in_str != current_check_in:
                try:
                    # Attempt to parse potential variations (e.g. "March 5") if direct parse fails - Robustness enhancement
                    check_in_date = None
                    try:
                         check_in_date = datetime.strptime(new_check_in_str, "%Y-%m-%d").date()
                    except ValueError:
                         await log_async("warning", f"Could not parse check-in '{new_check_in_str}' as YYYY-MM-DD directly.")
                         # Stick to strict YYYY-MM-DD based on prompt for now
                         raise ValueError("Invalid date format")


                    if check_in_date < self.current_date:
                        await log_async("warning", f"User provided past check-in date: {new_check_in_str}")
                        validation_message = f"Oops! It looks like the check-in date {new_check_in_str} is in the past. Please provide a date from {self.current_date_str} onwards. 🗓️"
                        new_check_in_str = None # Mark as invalid for subsequent logic
                        new_check_out_str = None # If check-in is bad, check-out likely needs re-eval anyway
                    else:
                        self.booking_info["check_in"] = new_check_in_str
                        updated = True
                        await log_async("info", f"Updated check-in to: {self.booking_info['check_in']}")
                        # If check-in changes, clear check-out unless it was provided *simultaneously* and is valid relative to NEW check-in
                        check_out_date_valid_relative = False
                        if new_check_out_str and isinstance(new_check_out_str, str):
                             try:
                                 check_out_dt_temp = datetime.strptime(new_check_out_str, "%Y-%m-%d").date()
                                 if check_out_dt_temp > check_in_date:
                                     check_out_date_valid_relative = True
                                     if self.booking_info["check_out"] != new_check_out_str:
                                        self.booking_info["check_out"] = new_check_out_str
                                        updated = True # Mark updated=True also if check_out is updated here
                                        await log_async("info", f"Updated check-out simultaneously to: {self.booking_info['check_out']}")
                             except ValueError:
                                 pass # Invalid format for check-out, will be handled below or asked again

                        if not check_out_date_valid_relative and self.booking_info["check_out"] is not None:
                             self.booking_info["check_out"] = None # Require new check-out confirmation/input if not provided validly with new check-in
                             await log_async("info", "Check-in date updated, cleared potentially invalid/old check-out date.")

                except ValueError:
                    await log_async("error", f"Invalid check-in date format received or failed parsing: {new_check_in_str}")
                    if not validation_message: # Don't overwrite past date message
                        validation_message = "Hmm, I couldn't quite understand that check-in date format. Could you please use YYYY-MM-DD? 🤔"
                    new_check_in_str = None # Mark as invalid

            # Validate and update check-out date (only if check-in is valid and check-out is new/different)
            # Check self.booking_info['check_out'] again in case it was updated simultaneously above
            if new_check_out_str and isinstance(new_check_out_str, str) and self.booking_info.get("check_in") and new_check_out_str != self.booking_info.get("check_out"):
                 if validation_message is None: # Don't process if check-in had issues
                    try:
                        check_out_date = datetime.strptime(new_check_out_str, "%Y-%m-%d").date()
                        # Ensure check_in date string is valid before parsing for comparison
                        check_in_date = datetime.strptime(self.booking_info["check_in"], "%Y-%m-%d").date()

                        if check_out_date <= check_in_date:
                            await log_async("warning", f"Check-out date {new_check_out_str} is not after check-in date {self.booking_info['check_in']}.")
                            validation_message = f"Got {new_check_out_str} for check-out, but it needs to be after your check-in date ({self.booking_info['check_in']}). What should the check-out date be? 📅"
                            # No need to mark new_check_out_str as None, just return the message
                        else:
                            # Check if check_out was already updated simultaneously with check_in above
                            # This condition check is slightly redundant now but safe
                            if self.booking_info["check_out"] != new_check_out_str:
                                self.booking_info["check_out"] = new_check_out_str
                                updated = True
                                await log_async("info", f"Updated check-out to: {self.booking_info['check_out']}")

                    except ValueError:
                        await log_async("error", f"Invalid check-out date format received: {new_check_out_str} or check-in was invalid: {self.booking_info.get('check_in')}")
                        if not validation_message: # Don't overwrite other messages
                            validation_message = "Hmm, I couldn't quite understand that check-out date format. Could you please use YYYY-MM-DD? 🤔"
                        # No need to mark new_check_out_str as None

            if not updated and not validation_message and any(extracted.values()):
                # If some info was extracted but didn't update anything (e.g., repeated info)
                await log_async("info", "Extracted info matched existing info or was invalid/already handled.")
                # Let _generate_natural_response ask the next logical question

            elif not updated and not validation_message and not any(val for key, val in extracted.items() if val is not None): # Check specifically for None values
                 # Nothing useful extracted, no errors - likely just small talk missed earlier or irrelevant input
                 await log_async("info", "No new booking information extracted from the message.")
                 # Let _generate_natural_response ask the next logical question


            await log_async("info", f"Current booking info after update attempt: {self.booking_info}")
            return validation_message # Return message if validation failed, otherwise None

        except Exception as e:
            # Catch broader exceptions during the whole process
            await log_async("error", f"Exception in _update_booking_info: {str(e)}", exc_info=True) # Add traceback
            # Fallback message
            return "I encountered an unexpected issue while processing that. Could you please try again or rephrase? 🙏"
    # --- END OF UPDATED METHOD ---


    async def _generate_natural_response(self) -> str:
        """Generates the next response based on the current state and missing info."""

        # Check if all information is collected
        # Ensure guests is treated properly (can be int)
        all_collected = all(val is not None for val in self.booking_info.values())

        if all_collected:
            # Format guest number correctly
            guest_text = f"{self.booking_info['guests']} guest(s)" if self.booking_info['guests'] else "guest info missing"

            summary = (f"a hotel in **{self.booking_info['destination']}** "
                       f"from **{self.booking_info['check_in']}** to **{self.booking_info['check_out']}** "
                       f"for **{guest_text}**")
            responses = [
                f"Okay, great! Let's confirm: You're booking {summary}. Does this look correct? (yes/no) 👍",
                f"Perfect! So that's {summary}. Ready to finalize this booking? (yes/no) 🎉",
                f"Got it all! Just to double-check: {summary}. Shall I proceed? (yes/no) 😊"
            ]
            self.state = "awaiting_confirmation"
            await log_async("info", "All info collected. Moving to awaiting_confirmation state.")
            return random.choice(responses)

        # If info is missing, determine the next question
        next_q = await self._get_next_question_prompt()
        if next_q:
            # Acknowledge last input if something was just updated (check history - look for user message then successful update log?)
            # Simplified acknowledgement logic:
            ack = ""
            # Check if the last assistant message wasn't already asking a question or showing an error
            last_assistant_msg = ""
            if len(self.history) >= 2 and "Assistant:" in self.history[-2]:
                 last_assistant_msg = self.history[-2]

            # Avoid redundant ack if last message was error or already a question
            if "Assistant:" in last_assistant_msg and "?" not in last_assistant_msg and "Sorry" not in last_assistant_msg and "Oops" not in last_assistant_msg and "Hmm" not in last_assistant_msg:
                # Check if something was actually updated based on logs (more complex) or just assume update if no error
                 if "update issue" not in last_assistant_msg : # Basic check based on log message text
                    ack = random.choice(["Got it. ", "Okay. ", "Alright. ", "Sounds good. "])

            return f"{ack}{next_q}"
        else:
            # Should not happen if not all info is collected, but have a fallback.
            await log_async("warning", "In _generate_natural_response but couldn't determine next question. Booking info: {self.booking_info}")
            return "Is there anything else I can help you with regarding the booking? 🤔"


    async def _get_next_question_prompt(self) -> Optional[str]:
        """Determines the next question based on missing information."""
        if not self.booking_info["destination"]:
            return random.choice([
                "Where would you like to book your stay? 🌍",
                "Which city are you interested in visiting? 🏙️",
                "What's the destination for your hotel booking? ✈️"
            ])
        if not self.booking_info["check_in"]:
             # Mention today's date for context
            return random.choice([
                f"Great choice ({self.booking_info['destination']})! When will you be checking in? (Today is {self.current_date_str}) 🗓️",
                f"Sounds lovely! What's your planned check-in date? (Use YYYY-MM-DD) 📅",
                f"Perfect! And the arrival date? (Starting from {self.current_date_str}) 🏨"
            ])
        if not self.booking_info["check_out"]:
             # Give context based on check-in
             check_in_date_str = self.booking_info['check_in']
             return random.choice([
                 f"Okay, checking in on {check_in_date_str}. When will you be checking out? 📅",
                 f"Got the check-in ({check_in_date_str}). How long will you stay, or what's the check-out date? 🏨",
                 f"Check-in is set for {check_in_date_str}. What date should the check-out be? 🤔"
            ])
        # Check for guests - ensure it's None or 0/invalid before asking
        if not self.booking_info["guests"] or int(self.booking_info["guests"]) <= 0:
            return random.choice([
                "Almost done! How many guests will be staying? 👨‍👩‍👧‍👦",
                "And how many people should I book for? 😊",
                "Just need the number of guests to complete this. 🧳"
            ])
        return None # All info present

    async def _handle_confirmation(self, user_message: str) -> str:
        """Handles user response (yes/no) during the confirmation state."""
        message_lower = user_message.lower()

        if re.search(r"\b(okey|ok|yes|yeah|yep|confirm|correct|ok|okay|proceed|finalize|do it|sure|sounds good)\b", message_lower): # Added more positive affirmations
            return await self._confirm_booking()
        elif re.search(r"\b(no|nope|change|wrong|wait|hold on|cancel|actually|different)\b", message_lower): # Added more negative/change indicators
            # Ask what needs changing
            # self.state = "changing_info" # A specific state to handle changes - reverting to collecting_info immediately after asking
            await log_async("info", "User wants to change details.")
            # Use LLM to try and understand what to change, or ask generically
            # Refined prompt for better field detection
            change_prompt = f"""The user wants to change the booking details based on their last message: "{user_message}".
            Analyze the user message and identify which field they most likely want to change.
            Respond with ONLY ONE word: 'destination', 'check_in', 'check_out', 'dates' (if both or unclear which date), 'guests', or 'unknown' if it's unclear."""
            try:
                change_field_response = await self.chat.ainvoke(change_prompt)
                change_field = change_field_response.content.strip().lower()
                # Clean up potential extra text from LLM
                change_field = re.split(r'\s|\n', change_field)[0] # Take first word
                await log_async("info", f"LLM suggested change field: {change_field}")
            except Exception as llm_err:
                await log_async("error", f"LLM call failed during change analysis: {llm_err}")
                change_field = "unknown"


            prompts = {
                "destination": "No problem! Which destination should it be instead? 🌍",
                "check_in": "Got it. What's the new check-in date? (YYYY-MM-DD) 🗓️",
                "check_out": "Okay. What new check-out date were you thinking of? (YYYY-MM-DD) 📅",
                "dates": "Sure thing. Let's update the dates. What is the new check-in date? (YYYY-MM-DD) 🗓️", # Ask for check-in first if 'dates'
                "guests": "Okay, how many guests should it be? 👨‍👩‍👧‍👦",
                "unknown": "Okay, what part of the booking would you like to change? (e.g., 'change destination to Paris', 'change dates', 'set guests to 3') 🤔"
            }
            # Reset the specific field(s) if identified, otherwise ask generally
            if change_field == "destination":
                 self.booking_info["destination"] = None
            elif change_field == "check_in":
                 self.booking_info["check_in"] = None
                 self.booking_info["check_out"] = None # Also clear check-out if check-in changes
            elif change_field == "check_out":
                 self.booking_info["check_out"] = None
            elif change_field == "dates": # Handle combined 'dates'
                 self.booking_info["check_in"] = None
                 self.booking_info["check_out"] = None
            elif change_field == "guests":
                 self.booking_info["guests"] = None

            # Fallback or if 'unknown'
            response = prompts.get(change_field, prompts["unknown"])
            self.state = "collecting_info" # Go back to collecting after asking change question
            await log_async("info", f"Reset field(s) based on '{change_field}', moving to collecting_info state.")
            return response

        else:
            # Unclear response
            return "Sorry, I didn't quite catch that. Should I finalize the booking as summarized? Please reply with 'yes' or 'no'. 😊"

