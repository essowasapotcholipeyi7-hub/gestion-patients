"""Migration ponctuelle : note de sortie obligatoire et notes de sortie préfaites (2026-10-22) — voir models.py
(NoteSortie, ModeleNoteSortie), cloturer_hospitalisation et la page /hospitalisation/<id>/sortie.

Additive et idempotente (CREATE TABLE IF NOT EXISTS) : sans risque à relancer, rien d'existant n'est modifié.

Usage (depuis la racine du projet) :
    python scripts/ajouter_notes_sortie.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
import psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS modeles_note_sortie (
        id SERIAL PRIMARY KEY,
        structure_id INTEGER NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
        nom VARCHAR(200) NOT NULL,
        diagnostic_sortie TEXT,
        evolution_sejour TEXT,
        etat_sortie TEXT,
        traitement_sortie TEXT,
        suivi TEXT,
        fichier_nom VARCHAR(255),
        fichier_mime VARCHAR(100),
        fichier_data BYTEA,
        actif BOOLEAN NOT NULL DEFAULT TRUE,
        created_by INTEGER REFERENCES utilisateurs(id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_modeles_note_sortie_structure ON modeles_note_sortie (structure_id)")
cur.execute("""
    CREATE TABLE IF NOT EXISTS notes_sortie (
        id SERIAL PRIMARY KEY,
        hospitalisation_id INTEGER NOT NULL UNIQUE REFERENCES hospitalisations(id) ON DELETE CASCADE,
        mode_sortie VARCHAR(20) NOT NULL DEFAULT 'sortie',
        motif_sortie TEXT,
        resume_entree TEXT NOT NULL,
        evolution_sejour TEXT NOT NULL,
        etat_sortie TEXT NOT NULL,
        diagnostic_entree TEXT NOT NULL,
        diagnostic_sortie TEXT NOT NULL,
        traitement_sortie TEXT,
        suivi TEXT,
        modele_id INTEGER REFERENCES modeles_note_sortie(id) ON DELETE SET NULL,
        redige_par INTEGER REFERENCES utilisateurs(id) ON DELETE SET NULL,
        date_redaction TIMESTAMP DEFAULT NOW()
    )""")
conn.commit()
conn.close()
print('OK : tables notes_sortie et modeles_note_sortie présentes.')
