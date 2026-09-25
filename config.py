import os
from dotenv import load_dotenv

load_dotenv()

def _url_postgres_pour_sqlalchemy(url):
    """⭐⭐ Un simple 'postgresql://...' (sans pilote précisé) ne suffit pas
    forcément avec SQLAlchemy — vu en prod sur medilogic_ghp et
    medilogic-BIASA_ghp : à partir de SQLAlchemy 2.1 (non épinglée dans
    leur requirements.txt, contrairement à ici où SQLAlchemy==2.0.49 est
    fixé), le pilote par défaut choisi pour une URL bare devient 'psycopg'
    (v3, pas installé, seul psycopg2-binary l'est) au lieu de psycopg2 —
    ModuleNotFoundError: No module named 'psycopg' au démarrage. On force
    donc TOUJOURS le pilote psycopg2 explicitement, peu importe le schéma
    fourni par Render/Neon (postgres://, postgresql://,
    postgresql+psycopg://...) — protection même si SQLAlchemy est un jour
    dépinglé/mis à jour ici aussi."""
    if not url or '://' not in url:
        return url
    schema, reste = url.split('://', 1)
    if schema.startswith('postgres'):
        return 'postgresql+psycopg2://' + reste
    return url


class Config:
    # Base de données
    SQLALCHEMY_DATABASE_URI = _url_postgres_pour_sqlalchemy(os.environ.get('DATABASE_URL'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Sécurité
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-par-defaut')
    
    # Uploads
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2MB max pour les logos
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'svg', 'webp'}
    
    # Session
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True