import os
import sys
from dotenv import load_dotenv
from google import genai

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

resp = client.models.generate_content(
    model="gemini-flash-lite-latest",
    contents="قل مرحبا بجملة واحدة.",
)
print(resp.text)