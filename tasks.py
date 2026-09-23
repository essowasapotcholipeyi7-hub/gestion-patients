# tasks.py
from app import app, db
from models import Prescription, ActePose, Patient, StructureMapping, HospitalisationFacturation, AnalyseDemande, ModeleResultat
import requests
import base64
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ⭐ Garde-fou de taille pour le transport base64 (résultats/modèles) — un
# fichier au-delà de cette taille est volumineux pour un simple aller-retour
# JSON synchrone (timeout=30s des deux côtés) : on préfère le signaler
# clairement dans les logs plutôt que de tenter l'envoi et échouer par un
# timeout silencieux, difficile à diagnostiquer ensuite.
TAILLE_MAX_FICHIER_SYNC = 5 * 1024 * 1024  # 5 Mo


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
                        ActePose.valide == True,  # ⭐ seuls les actes validés (voir onglet Actes posés) partent vers GHP
                        Patient.id_structure == mapping.local_structure_id,
                    )
                    .all()
                )

                if not actes:
                    continue

                data = []
                for a in actes:
                    instructions = a.notes or ''
                    if a.produit_administre:
                        instructions = f"Produit administré : {a.produit_administre}" + (f" — {instructions}" if instructions else '')
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
                        'instructions': instructions,
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


def _type_prestation_ghp(type_analyse):
    """BIOLOGIE/IMAGERIE (vocabulaire gestion_patients) -> analyse/examen
    (vocabulaire GHP) — GHP n'a que ces deux catégories, 'AUTRE' bascule sur
    'analyse' par défaut (fait rare, pas de 3e catégorie côté GHP)."""
    return 'examen' if type_analyse == 'IMAGERIE' else 'analyse'


def sync_resultats_examens_to_ghp():
    """
    Synchronise vers GHP les résultats d'analyses/examens saisis dans
    gestion_patients (labo/radio, voir saisir_resultats_analyse) ainsi que
    les modèles de résultats — voir /api/resultats-examens/sync-externe
    côté GHP. Même principe multi-structure et même colonne de rattrapage
    (`source_synced_at IS NULL`) que les autres tâches de ce module.

    ⭐ `source_app` doit être NULL (pas juste absent de la boucle) : une
    fois la Phase 3 (synchro entrante GHP -> gestion_patients) en place,
    une ligne reçue DE GHP portera source_app='ghp' et ne doit jamais
    repartir vers GHP (boucle infinie) — condition déjà posée ici pour ne
    pas avoir à y revenir à ce moment-là.
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
                url = f"{mapping.api_url}/api/resultats-examens/sync-externe"
                params = {'token': mapping.api_key}

                # ---- Résultats (AnalyseDemande, une fois TERMINE) ----
                analyses = AnalyseDemande.query.filter(
                    AnalyseDemande.structure_id == mapping.local_structure_id,
                    AnalyseDemande.statut == 'TERMINE',
                    AnalyseDemande.source_synced_at.is_(None),
                    AnalyseDemande.source_app.is_(None),
                ).all()

                for a in analyses:
                    if a.fichier_data and len(a.fichier_data) > TAILLE_MAX_FICHIER_SYNC:
                        messages.append(f"structure {mapping.local_structure_id} analyse #{a.id}: fichier trop volumineux ({len(a.fichier_data) // 1024} Ko), non envoyé")
                        logger.error(f"⚠️ Fichier trop volumineux pour la synchro (analyse #{a.id}, {len(a.fichier_data) // 1024} Ko) — non envoyé, à réduire ou transmettre autrement.")
                        continue

                    patient = a.patient
                    auteur_nom = None
                    if a.responsable:
                        auteur_nom = f"{a.responsable.prenom} {a.responsable.nom}"

                    payload = {
                        'categorie': 'resultat',
                        'source_app': 'gestion_patients',
                        'source_model': 'AnalyseDemande',
                        'source_id': a.id,
                        'patient_source_id': patient.patient_source_id if patient else None,
                        'patient_nom': patient.nom if patient else '',
                        'patient_prenom': patient.prenom if patient else '',
                        'type_prestation': _type_prestation_ghp(a.type_analyse),
                        'acte_nom': a.nom_analyse,
                        'motif': a.description or '',
                        'resultats_texte': a.resultats or '',
                        'contenu_html': a.contenu_html or '',
                        'fichier_nom': a.fichier_nom,
                        'fichier_mime': a.fichier_mime,
                        'fichier_data_b64': base64.b64encode(a.fichier_data).decode('ascii') if a.fichier_data else None,
                        'nom_interprete': a.nom_interprete or '',
                        'titre_interprete': a.titre_interprete,
                        'signature_mime': a.signature_mime,
                        'signature_data_b64': base64.b64encode(a.signature_data).decode('ascii') if a.signature_data else None,
                        'modele_utilise_id': a.modele_utilise_id,
                        'auteur_nom': auteur_nom,
                    }

                    try:
                        response = requests.post(url, json=payload, params=params, timeout=30)
                    except Exception as e:
                        messages.append(f"structure {mapping.local_structure_id} analyse #{a.id}: échec réseau ({e})")
                        logger.error(f"❌ Push résultat GHP échoué (analyse #{a.id}): {e}")
                        continue

                    if response.status_code == 200:
                        a.source_synced_at = datetime.utcnow()
                        db.session.commit()
                        total_envoyees += 1
                    else:
                        messages.append(f"structure {mapping.local_structure_id} analyse #{a.id}: échec ({response.status_code})")
                        logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur GHP (analyse #{a.id}): {response.status_code} - {response.text[:200]}")

                # ---- Modèles de résultats ----
                modeles = ModeleResultat.query.filter(
                    ModeleResultat.structure_id == mapping.local_structure_id,
                    ModeleResultat.source_synced_at.is_(None),
                    ModeleResultat.source_app.is_(None),
                ).all()

                for m in modeles:
                    if m.fichier_data and len(m.fichier_data) > TAILLE_MAX_FICHIER_SYNC:
                        messages.append(f"structure {mapping.local_structure_id} modèle #{m.id}: fichier trop volumineux ({len(m.fichier_data) // 1024} Ko), non envoyé")
                        logger.error(f"⚠️ Fichier trop volumineux pour la synchro (modèle #{m.id}, {len(m.fichier_data) // 1024} Ko) — non envoyé, à réduire ou transmettre autrement.")
                        continue

                    payload = {
                        'categorie': 'modele',
                        'source_app': 'gestion_patients',
                        'source_model': 'ModeleResultat',
                        'source_id': m.id,
                        'type_prestation': _type_prestation_ghp(m.type_analyse),
                        'nom': m.nom,
                        'fichier_nom': m.fichier_nom,
                        'fichier_mime': m.fichier_mime,
                        'fichier_data_b64': base64.b64encode(m.fichier_data).decode('ascii') if m.fichier_data else None,
                        'contenu_html': m.contenu_html or '',
                        'auteur_nom': m.created_by,
                    }

                    try:
                        response = requests.post(url, json=payload, params=params, timeout=30)
                    except Exception as e:
                        messages.append(f"structure {mapping.local_structure_id} modèle #{m.id}: échec réseau ({e})")
                        logger.error(f"❌ Push modèle résultat GHP échoué (#{m.id}): {e}")
                        continue

                    if response.status_code == 200:
                        m.source_synced_at = datetime.utcnow()
                        db.session.commit()
                        total_envoyees += 1
                    else:
                        messages.append(f"structure {mapping.local_structure_id} modèle #{m.id}: échec ({response.status_code})")
                        logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur GHP (modèle #{m.id}): {response.status_code} - {response.text[:200]}")

            if total_envoyees == 0 and not messages:
                logger.info("📭 Aucun résultat/modèle à synchroniser")
                return {'success': True, 'message': 'Aucun résultat à synchroniser'}

            return {
                'success': True,
                'message': f"✅ {total_envoyees} résultat(s)/modèle(s) synchronisé(s)" + (" — " + "; ".join(messages) if messages else ""),
                'count': total_envoyees
            }

        except Exception as e:
            logger.error(f"❌ Erreur sync résultats examens: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}


def sync_hospitalisations_to_ghp():
    """
    Synchronise les lignes de facturation d'hospitalisation (une par palier)
    non envoyées vers GHP — même pipeline /api/prescriptions
    (type_prescription='hospitalisation') que les actes posés. Chaque ligne
    porte déjà le nom exact de l'acte GHP (résolu à la clôture via le
    mapping Salle.acte_ghp_semaineN) : GHP retrouve son prix/PBR dans son
    propre catalogue par ce nom, exactement comme pour tout autre acte.

    Même principe multi-structure que les deux fonctions ci-dessus.
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
                lignes = (
                    HospitalisationFacturation.query
                    .join(Patient, HospitalisationFacturation.patient_id == Patient.id)
                    .filter(
                        HospitalisationFacturation.synced_at.is_(None),
                        Patient.id_structure == mapping.local_structure_id,
                    )
                    .all()
                )

                if not lignes:
                    continue

                data = []
                for l in lignes:
                    data.append({
                        'id': l.id,
                        'patient_id': l.patient_id,
                        'patient_nom': l.patient.nom if l.patient else '',
                        'patient_prenom': l.patient.prenom if l.patient else '',
                        'medicament': l.acte_nom,
                        'dosage': '',
                        'forme': '',
                        'quantite': l.nombre_jours or 1,
                        'duree_jours': 0,
                        'frequence': '',
                        'instructions': f"Hospitalisation #{l.hospitalisation_id} — palier {l.palier}",
                        'type_prescription': 'hospitalisation',
                        'date_prescription': l.created_at.isoformat() if l.created_at else datetime.now().isoformat(),
                        'prescripteur': ''
                    })

                url = f"{mapping.api_url}/api/prescriptions"
                params = {'token': mapping.api_key}

                logger.info(f"📡 Structure locale {mapping.local_structure_id} : envoi de {len(data)} ligne(s) de facturation hospitalisation vers GHP")

                response = requests.post(
                    url,
                    json={'prescriptions': data},
                    params=params,
                    timeout=30
                )

                if response.status_code == 200:
                    for l in lignes:
                        l.synced_at = datetime.utcnow()
                    db.session.commit()

                    total_envoyees += len(data)
                    messages.append(f"structure {mapping.local_structure_id}: {len(data)} envoyée(s)")
                    logger.info(f"✅ Structure {mapping.local_structure_id} : {len(data)} ligne(s) hospitalisation synchronisées")
                else:
                    messages.append(f"structure {mapping.local_structure_id}: échec ({response.status_code})")
                    logger.error(f"❌ Structure {mapping.local_structure_id} — Erreur GHP: {response.status_code} - {response.text[:200]}")

            if total_envoyees == 0 and not messages:
                logger.info("📭 Aucune ligne de facturation hospitalisation à synchroniser")
                return {'success': True, 'message': 'Aucune ligne à synchroniser'}

            return {
                'success': True,
                'message': f"✅ {total_envoyees} ligne(s) synchronisée(s) — " + "; ".join(messages),
                'count': total_envoyees
            }

        except Exception as e:
            logger.error(f"❌ Erreur sync hospitalisations: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}