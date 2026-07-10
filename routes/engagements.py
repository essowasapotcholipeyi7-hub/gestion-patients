from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from models import db, Engagement, Patient, Utilisateur, Structure
from datetime import datetime
import json

engagements_bp = Blueprint('engagements', __name__, url_prefix='/engagements')

# ==================== RECHERCHE PATIENT ====================
@engagements_bp.route('/api/patients/search')
@login_required
def search_patients():
    """API de recherche de patients pour les engagements"""
    if current_user.role not in ['medecin', 'super_admin']:
        return jsonify({'error': 'Non autorisé'}), 403
    
    term = request.args.get('q', '').strip()
    if len(term) < 2:
        return jsonify([])
    
    # Rechercher les patients de la structure du médecin
    query = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        archived=False
    )
    
    # Pour le médecin, filtrer par ses patients ou ceux sans référent
    if current_user.role == 'medecin':
        query = query.filter(
            db.or_(
                Patient.id_medecin_referent == current_user.id,
                Patient.id_medecin_referent.is_(None)
            )
        )
    
    # ✅ CORRECTION : CAST pour patient_source_id
    patients = query.filter(
        db.or_(
            Patient.nom.ilike(f'%{term}%'),
            Patient.prenom.ilike(f'%{term}%'),
            db.cast(Patient.patient_source_id, db.String).ilike(f'%{term}%')  # ⭐ CAST
        )
    ).limit(20).all()
    
    result = []
    for p in patients:
        result.append({
            'id': p.id,
            'nom': p.nom,
            'prenom': p.prenom,
            'date_naissance': p.date_naissance.strftime('%d/%m/%Y') if p.date_naissance else '',
            'telephone': p.telephone or '',
            'numero_dossier': p.patient_source_id or f'P{p.id:05d}',
            'medecin_referent': f"{p.medecin_referent.prenom} {p.medecin_referent.nom}" if p.medecin_referent else 'Aucun'
        })
    
    return jsonify(result)

# ==================== LISTE DES ENGAGEMENTS ====================
# ⭐ RENOMMÉE DE index → liste
@engagements_bp.route('/')
@login_required
def liste():
    """Liste des engagements du patient sélectionné"""
    if current_user.role not in ['medecin', 'super_admin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    patient_id = request.args.get('patient_id')
    patient = None
    engagements = []
    
    if patient_id:
        patient = Patient.query.get(patient_id)
        if patient:
            # Vérifier que le médecin a accès à ce patient
            if current_user.role == 'medecin' and patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
                flash('Accès non autorisé à ce patient', 'danger')
                return redirect(url_for('engagements.liste'))  # ⭐ CHANGÉ
    
            engagements = Engagement.query.filter_by(
                patient_id=patient.id
            ).order_by(Engagement.date_creation.desc()).all()
    
    return render_template('engagements/index.html',
                         patient=patient,
                         engagements=engagements,
                         now=datetime.now())

# ==================== AJOUTER UN ENGAGEMENT ====================
@engagements_bp.route('/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter():
    """Créer un nouvel engagement"""
    if current_user.role not in ['medecin', 'super_admin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    patient_id = request.args.get('patient_id') or request.form.get('patient_id')
    patient = None
    
    if patient_id:
        patient = Patient.query.get(patient_id)
        if patient and current_user.role == 'medecin' and patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
            flash('Accès non autorisé à ce patient', 'danger')
            return redirect(url_for('engagements.liste'))
    
    if request.method == 'POST':
        patient_id = request.form.get('patient_id')
        type_engagement = request.form.get('type_engagement')
        traitement_refuse = request.form.get('traitement_refuse')
        motif_refus = request.form.get('motif_refus')
        observations = request.form.get('observations_global')
        
        # ⭐ RÉCUPÉRATION DES TÉMOINS ET REPRÉSENTANT
        temoin1_nom = request.form.get('temoin1_nom')
        temoin2_nom = request.form.get('temoin2_nom')
        representant_nom = request.form.get('representant_nom')
        representant_lien = request.form.get('representant_lien')
        
        patient = Patient.query.get(patient_id)
        if not patient:
            flash('Patient non trouvé', 'danger')
            return redirect(url_for('engagements.ajouter'))
        
        # Vérifier que le médecin a accès
        if current_user.role == 'medecin' and patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
            flash('Accès non autorisé à ce patient', 'danger')
            return redirect(url_for('engagements.liste'))
        
        # Récupérer la structure
        structure = Structure.query.get(current_user.id_structure)
        
        # ⭐ GÉNÉRER LE CONTENU AVEC LES TÉMOINS
        contenu = generer_contenu_engagement(
            patient=patient,
            medecin=current_user,
            structure=structure,
            type_engagement=type_engagement,
            traitement_refuse=traitement_refuse,
            motif_refus=motif_refus,
            observations=observations,
            temoin1_nom=temoin1_nom,
            temoin2_nom=temoin2_nom,
            representant_nom=representant_nom,
            representant_lien=representant_lien
        )
        
        # Créer l'engagement
        engagement = Engagement(
            patient_id=patient.id,
            medecin_id=current_user.id,
            structure_id=current_user.id_structure,
            type_engagement=type_engagement,
            contenu=contenu,
            traitement_refuse=traitement_refuse,
            motif_refus=motif_refus,
            observations=observations,
            temoin1_nom=temoin1_nom,
            temoin2_nom=temoin2_nom,
            representant_nom=representant_nom,
            representant_lien=representant_lien,
            numero_dossier=patient.patient_source_id or f"P{patient.id:05d}"
        )
        
        db.session.add(engagement)
        db.session.commit()
        
        flash('Engagement créé avec succès', 'success')
        return redirect(url_for('engagements.detail', id=engagement.id))
    
    return render_template('engagements/ajouter.html',
                         patient=patient,
                         now=datetime.now())

# ==================== DÉTAIL D'UN ENGAGEMENT ====================
@engagements_bp.route('/<int:id>')
@login_required
def detail(id):
    """Voir le détail d'un engagement"""
    engagement = Engagement.query.get_or_404(id)
    
    # Vérifier l'accès
    if current_user.role == 'medecin':
        patient = engagement.patient
        if patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
            flash('Accès non autorisé', 'danger')
            return redirect(url_for('engagements.liste'))  # ⭐ CHANGÉ
    
    return render_template('engagements/detail.html',
                         engagement=engagement,
                         now=datetime.now())

# ==================== IMPRESSION ====================
@engagements_bp.route('/<int:id>/print')
@login_required
def print_view(id):
    """Version imprimable de l'engagement"""
    engagement = Engagement.query.get_or_404(id)
    
    # Vérifier l'accès
    if current_user.role == 'medecin':
        patient = engagement.patient
        if patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
            flash('Accès non autorisé', 'danger')
            return redirect(url_for('engagements.liste'))  # ⭐ CHANGÉ
    
    return render_template('engagements/print.html',
                         engagement=engagement,
                         now=datetime.now())

# ==================== SIGNATURE PATIENT ====================
@engagements_bp.route('/<int:id>/signer_patient', methods=['POST'])
@login_required
def signer_patient(id):
    """Marquer que le patient a signé"""
    engagement = Engagement.query.get_or_404(id)
    
    # Vérifier l'accès
    if current_user.role == 'medecin':
        patient = engagement.patient
        if patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
            return jsonify({'error': 'Non autorisé'}), 403
    
    engagement.signe_par_patient = True
    engagement.date_signature_patient = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

# ==================== SIGNATURE MÉDECIN ====================
@engagements_bp.route('/<int:id>/signer_medecin', methods=['POST'])
@login_required
def signer_medecin(id):
    """Marquer que le médecin a signé"""
    engagement = Engagement.query.get_or_404(id)
    
    # Vérifier que c'est le médecin qui a créé l'engagement
    if engagement.medecin_id != current_user.id and current_user.role != 'super_admin':
        return jsonify({'error': 'Non autorisé'}), 403
    
    engagement.signe_par_medecin = True
    engagement.date_signature_medecin = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

# ==================== SUPPRIMER ====================
@engagements_bp.route('/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer(id):
    """Supprimer un engagement"""
    engagement = Engagement.query.get_or_404(id)
    
    # Vérifier que c'est le médecin qui a créé l'engagement
    if engagement.medecin_id != current_user.id and current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('engagements.liste'))  # ⭐ CHANGÉ
    
    db.session.delete(engagement)
    db.session.commit()
    
    flash('Engagement supprimé', 'success')
    return redirect(url_for('engagements.liste', patient_id=engagement.patient_id))  # ⭐ CHANGÉ

# ==================== FONCTION DE GÉNÉRATION DE CONTENU ====================
def generer_contenu_engagement(patient, medecin, structure, type_engagement, 
                               traitement_refuse=None, motif_refus=None, observations=None,
                               temoin1_nom=None, temoin2_nom=None, 
                               representant_nom=None, representant_lien=None):
    """Génère le contenu HTML du formulaire d'engagement"""
    
    now = datetime.now()
    date_str = now.strftime('%d/%m/%Y')
    heure_str = now.strftime('%H:%M')
    
    nom_patient = f"{patient.prenom or ''} {patient.nom or ''}".strip()
    nom_medecin = f"{medecin.prenom} {medecin.nom}".strip()
    nom_hopital = structure.nom if structure else 'HÔPITAL'
    
    # Numéro dossier
    num_dossier = patient.patient_source_id or f"P{patient.id:05d}"
    
    # Date naissance
    date_naissance = patient.date_naissance.strftime('%d/%m/%Y') if patient.date_naissance else '__/__/____'
    
    # ⭐ SERVICE - Récupération sécurisée
    service = '_____________________________'
    if hasattr(patient, 'service') and patient.service:
        service = patient.service
    
    # ⭐ RÉCUPÉRATION DES NOMS SAISIS
    temoin1 = temoin1_nom or '____________________________'
    temoin2 = temoin2_nom or '____________________________'
    representant = representant_nom or '____________________________'
    representant_lien_text = representant_lien or '____________________________'
    
    # ⭐ VERSION OPTIMISÉE (plus compacte)
    templates = {
        'DNR': f"""
HÔPITAL {nom_hopital}
FORMULAIRE DE VOLONTÉ DU PATIENT - DNR

N° dossier: {num_dossier}  |  Patient: {nom_patient}  |  Né(e): {date_naissance}
Service: {service}  |  Médecin: Dr {nom_medecin}  |  Date: {date_str} à {heure_str}

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

I. DÉCLARATION DU PATIENT
Je soussigné(e), M./Mme {nom_patient}, certifie être en pleine possession de mes facultés mentales et déclare avoir reçu des explications claires sur mon état de santé, les traitements proposés, leurs bénéfices, risques et alternatives.

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

II. ORDRE DE NON-RÉANIMATION (DNR)
☐ En cas d'arrêt cardio-respiratoire, je demande qu'aucune réanimation ne soit entreprise.
Je comprends que cette décision peut entraîner mon décès.

▸ Signature du patient: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

III. DÉCLARATION DU MÉDECIN
Je certifie avoir informé le patient et confirme qu'il a compris et exprimé sa décision librement.

▸ Médecin: Dr {nom_medecin}  ▸ Signature & cachet: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

IV. TÉMOINS (recommandé)
Témoin 1: {temoin1}  ▸ Signature: __________________
Témoin 2: {temoin2}  ▸ Signature: __________________

V. REPRÉSENTANT LÉGAL (si patient incapable)
Nom: {representant}  ▸ Lien: {representant_lien_text}  ▸ Signature: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

Observations: {observations or 'Aucune'}

────────────────────────────────────────
Document conservé dans le dossier médical.
""",
        
        'REFUS_TRAITEMENT': f"""
HÔPITAL {nom_hopital}
FORMULAIRE DE VOLONTÉ DU PATIENT - REFUS DE TRAITEMENT

N° dossier: {num_dossier}  |  Patient: {nom_patient}  |  Né(e): {date_naissance}
Service: {service}  |  Médecin: Dr {nom_medecin}  |  Date: {date_str} à {heure_str}

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

I. DÉCLARATION DU PATIENT
Je soussigné(e), M./Mme {nom_patient}, certifie être en pleine possession de mes facultés mentales et déclare avoir reçu des explications claires sur mon état de santé, les traitements proposés, leurs bénéfices, risques et alternatives.

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

II. REFUS DE TRAITEMENT
Je refuse le(s) traitement(s) suivant(s):
{traitement_refuse or '______________________________________________________'}

Motif: {motif_refus or '______________________________________________________'}

Je reconnais avoir été informé(e) des risques d'aggravation, séquelles permanentes ou décès.

▸ Signature du patient: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

III. DÉCLARATION DU MÉDECIN
Je certifie avoir informé le patient et confirme qu'il a compris et exprimé sa décision librement.

▸ Médecin: Dr {nom_medecin}  ▸ Signature & cachet: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

IV. TÉMOINS (recommandé)
Témoin 1: {temoin1}  ▸ Signature: __________________
Témoin 2: {temoin2}  ▸ Signature: __________________

V. REPRÉSENTANT LÉGAL (si patient incapable)
Nom: {representant}  ▸ Lien: {representant_lien_text}  ▸ Signature: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

Observations: {observations or 'Aucune'}

────────────────────────────────────────
Document conservé dans le dossier médical.
""",
        
        'SORTIE_AVIS': f"""
HÔPITAL {nom_hopital}
FORMULAIRE DE VOLONTÉ DU PATIENT - SORTIE CONTRE AVIS MÉDICAL

N° dossier: {num_dossier}  |  Patient: {nom_patient}  |  Né(e): {date_naissance}
Service: {service}  |  Médecin: Dr {nom_medecin}  |  Date: {date_str} à {heure_str}

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

I. DÉCLARATION DU PATIENT
Je soussigné(e), M./Mme {nom_patient}, certifie être en pleine possession de mes facultés mentales et déclare avoir reçu des explications claires sur mon état de santé, les traitements proposés, leurs bénéfices, risques et alternatives.

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

II. SORTIE CONTRE AVIS MÉDICAL
Je demande à quitter l'établissement malgré l'avis médical.

Je reconnais avoir été informé(e) des risques:
• Aggravation de mon état de santé
• Complications médicales
• Invalidité permanente
• Décès

J'assume pleinement les conséquences de cette décision.

▸ Signature du patient: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

III. DÉCLARATION DU MÉDECIN
Je certifie avoir informé le patient et confirme qu'il a compris et exprimé sa décision librement.

▸ Médecin: Dr {nom_medecin}  ▸ Signature & cachet: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

IV. TÉMOINS (recommandé)
Témoin 1: {temoin1}  ▸ Signature: __________________
Témoin 2: {temoin2}  ▸ Signature: __________________

V. REPRÉSENTANT LÉGAL (si patient incapable)
Nom: {representant}  ▸ Lien: {representant_lien_text}  ▸ Signature: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

Observations: {observations or 'Aucune'}

────────────────────────────────────────
Document conservé dans le dossier médical.
""",
        
        'AUTRE': f"""
HÔPITAL {nom_hopital}
FORMULAIRE DE VOLONTÉ DU PATIENT - AUTRE ENGAGEMENT

N° dossier: {num_dossier}  |  Patient: {nom_patient}  |  Né(e): {date_naissance}
Service: {service}  |  Médecin: Dr {nom_medecin}  |  Date: {date_str} à {heure_str}

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

I. DÉCLARATION DU PATIENT
Je soussigné(e), M./Mme {nom_patient}, certifie être en pleine possession de mes facultés mentales et déclare avoir reçu des explications claires sur mon état de santé, les traitements proposés, leurs bénéfices, risques et alternatives.

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

II. ENGAGEMENT SPÉCIFIQUE
{observations or '______________________________________________________'}

▸ Signature du patient: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

III. DÉCLARATION DU MÉDECIN
Je certifie avoir informé le patient et confirme qu'il a compris et exprimé sa décision librement.

▸ Médecin: Dr {nom_medecin}  ▸ Signature & cachet: __________________

━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━═━

IV. TÉMOINS (recommandé)
Témoin 1: {temoin1}  ▸ Signature: __________________
Témoin 2: {temoin2}  ▸ Signature: __________________

V. REPRÉSENTANT LÉGAL (si patient incapable)
Nom: {representant}  ▸ Lien: {representant_lien_text}  ▸ Signature: __________________

────────────────────────────────────────
Document conservé dans le dossier médical.
"""
    }
    
    return templates.get(type_engagement, templates['AUTRE'])