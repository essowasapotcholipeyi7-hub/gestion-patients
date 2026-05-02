import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Base de données
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
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