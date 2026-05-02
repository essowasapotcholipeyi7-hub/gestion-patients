from app import app, db
from sqlalchemy import text

with app.app_context():
    db.create_all()
    print("✅ Table messages créée")