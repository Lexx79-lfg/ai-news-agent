import os
from dotenv import load_dotenv
import anthropic

# Load the secret API key from the .env file
load_dotenv()

# Create a client that talks to Claude using that key
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Send one simple message
response = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=200,
    messages=[{"role": "user", "content": "In one sentence, what is an AI agent?"}]
)

# Print Claude's reply
print(response.content[0].text)
