import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

try:
    url = os.getenv('DATABASE_URL')
    print(f"URL de connexion: {url[:50]}...")  # Affiche le début seulement
    conn = psycopg2.connect(url)
    print("✅ Connexion à PostgreSQL réussie !")
    conn.close()
except Exception as e:
    print(f"❌ Erreur de connexion : {e}")