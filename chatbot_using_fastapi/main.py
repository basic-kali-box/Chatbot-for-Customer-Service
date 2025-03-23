from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from chatbot import HotelBookingChatbot
import os

# Initialize FastAPI app
app = FastAPI()

# Mount static files directory (pointing to root-level static/)
app.mount("/static", StaticFiles(directory="../static"), name="static")

# Initialize chatbot instance
chatbot = HotelBookingChatbot()

# Load index.html content (from root-level templates/)
with open("../templates/index.html", "r") as f:
    index_html = f.read()

@app.get("/", response_class=HTMLResponse)
async def get_root():
    """Serve the main HTML page."""
    return HTMLResponse(content=index_html)

@app.post("/chat", response_class=JSONResponse)
async def chat(request: Request):
    """Handle chat messages from the user."""
    try:
        data = await request.json()
        user_message = data.get("message")
        if not user_message:
            raise HTTPException(status_code=400, detail="Message is required")
        
        print(f"Received user message: {user_message}")
        response = await chatbot.process_message(user_message)
        print(f"Chat response (raw): {response}")
        
        return JSONResponse(content={"response": response})
    except Exception as e:
        print(f"Error processing chat message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reset", response_class=JSONResponse)
async def reset_chat():
    """Reset the chatbot conversation."""
    reset_message = chatbot.reset()
    return JSONResponse(content={"response": reset_message})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090, reload=True)