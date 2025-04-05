import os
import aiohttp
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

async def get_weather_tip(destination: str, log_async) -> str:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        await log_async("warning", "Weather API key missing")
        return "Weather tip unavailable (API key missing)."

    try:
        # Fetch weather data from OpenWeatherMap
        async with aiohttp.ClientSession() as session:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={destination}&appid={api_key}&units=metric"
            async with session.get(url) as response:
                if response.status != 200:
                    await log_async("error", f"Weather API returned status {response.status} for {destination}")
                    return "Weather tip unavailable for this destination."
                data = await response.json()
                weather = data['weather'][0]['description']
                temp = data['main']['temp']

        # Initialize the LLM (Grok)
        llm = ChatGroq(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            model_name="gemma2-9b-it",
            temperature=0.7,
            max_tokens=100
        )

        # Create a prompt for the LLM to generate a weather tip
        prompt_template = PromptTemplate(
            input_variables=["temp", "destination", "weather"],
            template="You are a travel assistant. Provide a concise weather tip (1-2 sentences) for a traveler going to {destination}, where the current temperature is {temp}°C and the weather is {weather}. Include a relevant emoji at the end."
        )

        # Format the prompt with the weather data
        prompt = prompt_template.format(temp=temp, destination=destination, weather=weather)

        # Generate the weather tip using the LLM
        weather_tip = await llm.apredict(prompt)
        if not weather_tip:
            return "Weather tip unavailable (LLM failed to generate a response)."

        # Format the final message with the temperature in bold
        tip = f"It's **{temp}°C** in {destination} with {weather}. {weather_tip}"
        return tip

    except Exception as e:
        await log_async("error", f"Weather API or LLM error: {str(e)}")
        return "Weather tip unavailable at this time."