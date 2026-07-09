from app import app, db
from models import StructureMapping

with app.app_context():
    mapping = StructureMapping.query.filter_by(actif=True).first()
    if mapping:
        print(f"🔍 Ancienne URL: {mapping.api_url}")
        mapping.api_url = "http://10.156.62.79:5000"
        db.session.commit()
        print(f"✅ Nouvelle URL: {mapping.api_url}")
    else:
        print("❌ Aucun mapping trouvé")