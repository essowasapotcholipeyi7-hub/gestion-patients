# tasks.py
from app import app, db
from models import Prescription, StructureMapping
import requests
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def sync_prescriptions_to_ghp():
    """
    Synchronise les prescriptions non envoyées vers GHP
    """
    with app.app_context():
        try:
            # Récupérer les prescriptions non synchronisées
            prescriptions = Prescription.query.filter_by(
                synced_at=None,
                statut='active'
            ).all()
            
            if not prescriptions:
                logger.info("📭 Aucune prescription à synchroniser")
                return {'success': True, 'message': 'Aucune prescription à synchroniser'}
            
            # Récupérer le mapping GHP
            mapping = StructureMapping.query.filter_by(actif=True).first()
            if not mapping:
                logger.error("❌ Configuration GHP non trouvée")
                return {'success': False, 'message': 'Configuration GHP non trouvée'}
            
            # ⭐ Formater les données
            data = []
            for p in prescriptions:
                # ⭐ Récupérer le type (directement depuis le modèle)
                type_presc = getattr(p, 'type_prescription', 'medicament') or 'medicament'
                
                # ⭐ Construction de l'objet
                presc_data = {
                    'id': p.id,
                    'patient_id': p.id_patient,
                    'patient_nom': p.patient.nom if p.patient else '',
                    'patient_prenom': p.patient.prenom if p.patient else '',
                    'medicament': p.medicament or p.acte_nom or '',  # 🔥 FIXE ICI
                    'dosage': p.dosage or '',
                    'forme': p.forme or '',
                    'quantite': p.quantite or '1',
                    'duree_jours': p.duree_jours or 0,
                    'frequence': p.frequence or '',
                    'instructions': p.instructions or '',
                    'type_prescription': type_presc,  # ⭐ Le type
                    'date_prescription': p.date_prescription.isoformat() if p.date_prescription else datetime.now().isoformat(),
                    'prescripteur': p.prescripteur or ''
                }
                
                data.append(presc_data)
            
            if not data:
                logger.info("📭 Aucune donnée valide à synchroniser")
                return {'success': True, 'message': 'Aucune donnée valide à synchroniser'}
            
            # Envoyer vers GHP
            url = f"{mapping.api_url}/api/prescriptions"
            params = {'token': mapping.api_key}
            
            logger.info(f"📡 Envoi de {len(data)} prescriptions vers GHP")
            logger.info(f"   Types: {set([d['type_prescription'] for d in data])}")
            
            response = requests.post(
                url,
                json={'prescriptions': data},
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                # Marquer comme synchronisées
                for p in prescriptions:
                    p.synced_at = datetime.utcnow()
                db.session.commit()
                
                logger.info(f"✅ {len(data)} prescriptions synchronisées")
                return {
                    'success': True,
                    'message': f'✅ {len(data)} prescriptions synchronisées',
                    'count': len(data)
                }
            else:
                logger.error(f"❌ Erreur GHP: {response.status_code} - {response.text[:200]}")
                return {
                    'success': False,
                    'message': f'Erreur GHP: {response.status_code}',
                    'response': response.text[:500]
                }
                
        except Exception as e:
            logger.error(f"❌ Erreur sync prescriptions: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}