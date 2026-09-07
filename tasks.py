# tasks.py
from app import app, db
from models import Prescription, ActePose, Patient, StructureMapping
import requests
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def sync_prescriptions_to_ghp():
    """
    Synchronise les prescriptions non envoyées vers GHP.

    ⭐ FIX : il peut y avoir PLUSIEURS structures (mappings actifs) sur ce
    même déploiement. L'ancienne version prenait le premier mapping actif
    trouvé (StructureMapping.query.filter_by(actif=True).first()) et lui
    envoyait TOUTES les prescriptions non synchronisées, peu importe leur
    structure d'origine — une prescription de la structure 5 partait donc
    avec le token/URL de la structure 1, et côté GHP le patient n'était
    jamais retrouvé (mauvaise structure). On boucle maintenant sur CHAQUE
    mapping actif, et pour chacun on ne prend que les prescriptions dont le
    patient appartient à sa structure locale.
    """
    with app.app_context():
        try:
            mappings = StructureMapping.query.filter_by(actif=True).all()
            if not mappings:
                logger.error("❌ Aucune configuration GHP active")
                return {'success': False, 'message': 'Configuration GHP non trouvée'}

            total_envoyees = 0
            messages = []

            for mapping in mappings:
                # ⭐ Uniquement les prescriptions dont le patient appartient
                # à LA structure locale de ce mapping précis.
                prescriptions = (
                    Prescription.query
                    .join(Patient, Prescription.id_patient == Patient.id)
                    .filter(
                        Prescription.synced_at.is_(None),
                        Prescription.statut == 'active',
                        Patient.id_structure == mapping.local_structure_id,
                    )
                    .all()
                )

                if not prescriptions:
                    continue

                # ⭐ Formater les données
                data = []
                for p in prescriptions:
                    type_presc = getattr(p, 'type_prescription', 'medicament') or 'medicament'
                    presc_data = {
                        'id': p.id,
                        'patient_id': p.id_patient,
                        'patient_nom': p.patient.nom if p.patient else '',
                        'patient_prenom': p.patient.prenom if p.patient else '',
                        'medicament': p.medicament or '',
                        'dosage': p.dosage or '',
                        'forme': p.forme or '',
                        'quantite': p.quantite or '1',
                        'duree_jours': p.duree_jours or 0,
                        'frequence': p.frequence or '',
                        'instructions': p.instructions or '',
                        'type_prescription': type_presc,
                        'date_prescription': p.date_prescription.isoformat() if p.date_prescription else datetime.now().isoformat(),
                        'prescripteur': p.prescripteur or ''
                    }
                    data.append(presc_data)

                # Envoyer vers GHP (l'URL/token propres à CETTE structure)
                url = f"{mapping.api_url}/api/prescriptions"
                params = {'token': mapping.api_key}

                logger.info(f"📡 Structure locale {mapping.local_structure_id} : envoi de {len(data)} prescriptions vers GHP")
                logger.info(f"   Types: {set([d['type_prescription'] for d in data])}")

                response = requests.post(
                    url,
                    json={'prescriptions': data},
                    params=params,
                    timeout=30
                )

                if response.status_code == 200:
                    for p in prescriptions:
                        p.synced_at = datetime.utcnow()
                    db.session.commit()

                    total_envoyees += len(data)
                    messages.append(f"structure {mapping.local_structure_id}: {len(data)} envoyée(s)")
                    logger.info(f"✅ Structure {mapping.local_structure_id} : {len(data)} prescriptions synchronisées")
                else:
                    messages.append(f"structure {mapping.local_structure_id}: échec ({response.status_code})")
                    logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur GHP: {response.status_code} - {response.text[:200]}")

            if total_envoyees == 0 and not messages:
                logger.info("📭 Aucune prescription à synchroniser")
                return {'success': True, 'message': 'Aucune prescription à synchroniser'}

            return {
                'success': True,
                'message': f"✅ {total_envoyees} prescription(s) synchronisée(s) — " + "; ".join(messages),
                'count': total_envoyees
            }

        except Exception as e:
            logger.error(f"❌ Erreur sync prescriptions: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}


def sync_actes_poses_to_ghp():
    """
    Synchronise les actes posés non envoyés vers GHP — réutilise le même
    pipeline /api/prescriptions (type_prescription='acte_pose') que les
    prescriptions : pas besoin d'un nouvel endpoint côté GHP, l'écran
    "Prescriptions reçues" range déjà tout ce qui n'est pas 'medicament'
    dans la liste des actes à facturer.

    Même principe multi-structure que sync_prescriptions_to_ghp() : on
    boucle sur chaque mapping actif, un acte posé n'est envoyé qu'avec le
    token/URL de SA structure locale.
    """
    with app.app_context():
        try:
            mappings = StructureMapping.query.filter_by(actif=True).all()
            if not mappings:
                logger.error("❌ Aucune configuration GHP active")
                return {'success': False, 'message': 'Configuration GHP non trouvée'}

            total_envoyees = 0
            messages = []

            for mapping in mappings:
                actes = (
                    ActePose.query
                    .join(Patient, ActePose.patient_id == Patient.id)
                    .filter(
                        ActePose.synced_at.is_(None),
                        ActePose.statut == 'actif',
                        Patient.id_structure == mapping.local_structure_id,
                    )
                    .all()
                )

                if not actes:
                    continue

                data = []
                for a in actes:
                    data.append({
                        'id': a.id,
                        'patient_id': a.patient_id,
                        'patient_nom': a.patient.nom if a.patient else '',
                        'patient_prenom': a.patient.prenom if a.patient else '',
                        'medicament': a.nom or '',
                        'dosage': '',
                        'forme': '',
                        'quantite': a.quantite or '1',
                        'duree_jours': 0,
                        'frequence': '',
                        'instructions': a.notes or '',
                        'type_prescription': 'acte_pose',
                        'date_prescription': a.date_pose.isoformat() if a.date_pose else datetime.now().isoformat(),
                        'prescripteur': f"{a.pose_par.prenom} {a.pose_par.nom}" if a.pose_par else ''
                    })

                url = f"{mapping.api_url}/api/prescriptions"
                params = {'token': mapping.api_key}

                logger.info(f"📡 Structure locale {mapping.local_structure_id} : envoi de {len(data)} actes posés vers GHP")

                response = requests.post(
                    url,
                    json={'prescriptions': data},
                    params=params,
                    timeout=30
                )

                if response.status_code == 200:
                    for a in actes:
                        a.synced_at = datetime.utcnow()
                    db.session.commit()

                    total_envoyees += len(data)
                    messages.append(f"structure {mapping.local_structure_id}: {len(data)} envoyé(s)")
                    logger.info(f"✅ Structure {mapping.local_structure_id} : {len(data)} actes posés synchronisés")
                else:
                    messages.append(f"structure {mapping.local_structure_id}: échec ({response.status_code})")
                    logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur GHP: {response.status_code} - {response.text[:200]}")

            if total_envoyees == 0 and not messages:
                logger.info("📭 Aucun acte posé à synchroniser")
                return {'success': True, 'message': 'Aucun acte posé à synchroniser'}

            return {
                'success': True,
                'message': f"✅ {total_envoyees} acte(s) posé(s) synchronisé(s) — " + "; ".join(messages),
                'count': total_envoyees
            }

        except Exception as e:
            logger.error(f"❌ Erreur sync actes posés: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}