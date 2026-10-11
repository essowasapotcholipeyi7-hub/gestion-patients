"""Migration ponctuelle : origine miroir des protocoles reçus de GHP
(2026-10-11) — voir models.py (ProtocoleSoins, OrdonnanceType, ExamenType :
source_app, source_id, source_synced_at) et /api/protocoles/sync-externe.

Additive et idempotente (ADD COLUMN IF NOT EXISTS) : sans risque à relancer.

Usage (depuis la racine du projet) :
    python scripts/ajouter_sync_protocoles_ghp.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
import psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
for table in ('protocoles_soins', 'ordonnances_types', 'examens_types'):
    cur.execute(f"""
        ALTER TABLE {table}
        ADD COLUMN IF NOT EXISTS source_app VARCHAR(30),
        ADD COLUMN IF NOT EXISTS source_id INTEGER,
        ADD COLUMN IF NOT EXISTS source_synced_at TIMESTAMP
    """)
    cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_origine_ghp ON {table} (structure_id, source_app, source_id) "
                f"WHERE source_app IS NOT NULL")
conn.commit()
conn.close()
print('OK : colonnes d\'origine GHP présentes sur protocoles_soins, ordonnances_types, examens_types.')
