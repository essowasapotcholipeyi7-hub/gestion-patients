"""
Ajoute les tables `modeles_resultats` / `signatures_intervenants`, et étend
`analyses_demandes` avec les colonnes de résultat riche (fichier, contenu
rédigé en ligne, signature figée) + traçabilité de synchro GHP — parité
avec le module labo/radio de GHP (voir models.py pour le détail de chaque
colonne). Idempotent — peut être relancé sans risque.

Usage :
    python scripts/ajouter_resultats_examens.py
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

SQL_MODELES_RESULTATS = """
CREATE TABLE IF NOT EXISTS modeles_resultats (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL REFERENCES structures(id),
    type_analyse VARCHAR(20) NOT NULL,
    nom VARCHAR(200) NOT NULL,
    fichier_nom VARCHAR(255),
    fichier_mime VARCHAR(100),
    fichier_data BYTEA,
    contenu_html TEXT,
    source_app VARCHAR(20),
    source_model VARCHAR(50),
    source_id INTEGER,
    source_synced_at TIMESTAMP,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_SIGNATURES_INTERVENANTS = """
CREATE TABLE IF NOT EXISTS signatures_intervenants (
    id SERIAL PRIMARY KEY,
    structure_id INTEGER NOT NULL REFERENCES structures(id),
    filiere VARCHAR(20) NOT NULL,
    nom VARCHAR(200) NOT NULL,
    titre VARCHAR(100),
    signature_data BYTEA NOT NULL,
    signature_mime VARCHAR(100),
    actif BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQL_ANALYSES_DEMANDES = """
ALTER TABLE analyses_demandes
    ADD COLUMN IF NOT EXISTS fichier_nom VARCHAR(255),
    ADD COLUMN IF NOT EXISTS fichier_mime VARCHAR(100),
    ADD COLUMN IF NOT EXISTS fichier_data BYTEA,
    ADD COLUMN IF NOT EXISTS contenu_html TEXT,
    ADD COLUMN IF NOT EXISTS modele_utilise_id INTEGER,
    ADD COLUMN IF NOT EXISTS nom_interprete VARCHAR(200),
    ADD COLUMN IF NOT EXISTS signature_intervenant_id INTEGER,
    ADD COLUMN IF NOT EXISTS titre_interprete VARCHAR(100),
    ADD COLUMN IF NOT EXISTS signature_data BYTEA,
    ADD COLUMN IF NOT EXISTS signature_mime VARCHAR(100),
    ADD COLUMN IF NOT EXISTS source_app VARCHAR(20),
    ADD COLUMN IF NOT EXISTS source_model VARCHAR(50),
    ADD COLUMN IF NOT EXISTS source_id INTEGER,
    ADD COLUMN IF NOT EXISTS source_synced_at TIMESTAMP;
"""

if __name__ == "__main__":
    with app.app_context():
        db.session.execute(text(SQL_MODELES_RESULTATS))
        db.session.execute(text(SQL_SIGNATURES_INTERVENANTS))
        db.session.execute(text(SQL_ANALYSES_DEMANDES))
        db.session.commit()

        for table in ("modeles_resultats", "signatures_intervenants"):
            check = db.session.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name=:t ORDER BY ordinal_position"
            ), {"t": table}).fetchall()
            print(f"OK {table} :")
            for c in check:
                print(f"   - {c[0]} ({c[1]})")

        check = db.session.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='analyses_demandes' AND column_name IN "
            "('fichier_nom','fichier_mime','fichier_data','contenu_html','modele_utilise_id',"
            "'nom_interprete','signature_intervenant_id','titre_interprete','signature_data',"
            "'signature_mime','source_app','source_model','source_id','source_synced_at') "
            "ORDER BY column_name"
        )).fetchall()
        print("OK analyses_demandes (nouvelles colonnes) :")
        for c in check:
            print(f"   - {c[0]} ({c[1]})")
