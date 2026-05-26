import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
lista_chaves = [k.strip().strip('"').strip("'") for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
client = genai.Client(api_key=lista_chaves[0])

for m in client.models.list():
    if 'embed' in m.name.lower():
        print(m.name)
