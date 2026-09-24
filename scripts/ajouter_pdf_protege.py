"""
Ajoute la colonne `pdf_password` à `analyses_demandes` — code d'ouverture du
PDF de résultat chiffré remis au patient (voir pdf_protege_analyse dans
app.py). Idempotent — peut être relancé sans risque.

Usage :
    python scripts/ajouter_pdf_protege.py
"""
import io
import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text

SQL_ANALYSES_DEMANDES = """
ALTER TABLE analyses_demandes
    ADD COLUMN IF NOT EXISTS pdf_password VARCHAR(20);
"""

if __name__ == "__main__":
    with app.app_context():
        db.session.execute(text(SQL_ANALYSES_DEMANDES))
        db.session.commit()

        check = db.session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='analyses_demandes' AND column_name = 'pdf_password'"
        )).fetchall()
        print("OK analyses_demandes (nouvelle colonne) :")
        for c in check:
            print(f"   - {c[0]} ({c[1]})")
