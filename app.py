from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
import os
from dotenv import load_dotenv
from scheduler import start_scheduler, stop_scheduler
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import csv
from io import StringIO
from decorators import has_permission
import uuid
import logging
from models import db, Engagement, Patient
from models import Consultation, Patient, ExamenType, ExamenPrescrit



load_dotenv()

# Initialisation de l'application
app = Flask(__name__)
app.config.from_object('config.Config')
logger = logging.getLogger(__name__)

# Initialisation de la base de données
from models import db
db.init_app(app)

from routes.engagements import engagements_bp
app.register_blueprint(engagements_bp)

def create_structure_sheets(structure_id):
    """Crée automatiquement les feuilles Google Sheets pour une nouvelle structure"""
    from sheets_sync import GoogleSheetsSync
    import os
    
    SPREADSHEET_ID = "1nCUArOaWgXVFszjEhH1GqNJXGCV7cF754W87vXvQ-lQ"
    CREDENTIALS_FILE = 'credentials.json'
    
    if os.path.exists(CREDENTIALS_FILE):
        syncer = GoogleSheetsSync(SPREADSHEET_ID, CREDENTIALS_FILE)
        if syncer.authenticate():
            syncer.ensure_structure_sheets(structure_id)
            print(f"✅ Feuilles Sheets créées pour structure ID {structure_id}")
            return True
    return False

# Initialisation du login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'

@login_manager.user_loader
def load_user(user_id):
    from models import db, Utilisateur
    return db.session.get(Utilisateur, int(user_id))

@app.context_processor
def inject_non_lus():
    from models import Message
    if current_user.is_authenticated:
        non_lus = Message.query.filter_by(id_destinataire=current_user.id, lu=False).count()
        return dict(non_lus=non_lus)
    return dict(non_lus=0)

@app.context_processor
def utility_processor():
    from datetime import datetime
    return {
        'now': datetime.now()
    }

@app.template_filter('nl2br')
def nl2br_filter(text):
    """Convertit les sauts de ligne en <br>"""
    if not text:
        return text
    return text.replace('\n', '<br>')

@app.template_filter('from_json')
def from_json_filter(value):
    """Convertit une chaîne JSON en objet Python"""
    import json
    try:
        return json.loads(value) if value else []
    except:
        return []

# Routes principales
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        from models import Utilisateur, Structure
        
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = Utilisateur.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            # Vérifier que l'utilisateur est actif
            if not user.actif:
                flash('Votre compte a été désactivé. Contactez l\'administrateur.', 'danger')
                return redirect(url_for('login'))
            
            # Vérifier que la structure est active (sauf super_admin)
            if user.role != 'super_admin':
                structure = Structure.query.get(user.id_structure)
                if not structure:
                    flash('Structure non trouvée. Contactez l\'administrateur.', 'danger')
                    return redirect(url_for('login'))
                if structure.statut != 'actif':
                    flash('Votre structure n\'est pas active. Contactez l\'administrateur.', 'warning')
                    return redirect(url_for('login'))
            
            login_user(user)
            user.derniere_connexion = datetime.utcnow()
            db.session.commit()
            
            # ⭐ REDIRECTION SELON LE RÔLE
            if user.role == 'super_admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'admin_structure':
                return redirect(url_for('structure_dashboard'))
            elif user.role == 'infirmier':
                return redirect(url_for('infirmier_dashboard'))
            elif user.role == 'medecin':
                return redirect(url_for('medecin_dashboard'))
            elif user.role == 'laborantin':
                return redirect(url_for('laborantin_dashboard'))
            elif user.role == 'radiologue':
                return redirect(url_for('radiologue_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Email ou mot de passe incorrect', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register_structure():
    if request.method == 'POST':
        from models import Structure, Utilisateur, db
        import hashlib
        
        # Récupération des données
        nom_structure = request.form.get('nom_structure')
        nom_responsable = request.form.get('nom_responsable')
        prenom_responsable = request.form.get('prenom_responsable')
        adresse = request.form.get('adresse')
        email = request.form.get('email')
        telephone = request.form.get('telephone')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        reset_question = request.form.get('reset_question')
        reset_answer = request.form.get('reset_answer')
        
        # Validation
        if not nom_structure or not email or not password:
            flash('Tous les champs obligatoires doivent être remplis', 'danger')
            return redirect(url_for('register_structure'))
        
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('register_structure'))
        
        # Validation de la complexité du mot de passe
        import re
        errors = []
        if len(password) < 8:
            errors.append("Minimum 8 caractères")
        if not re.search(r"[A-Z]", password):
            errors.append("Au moins 1 majuscule")
        if not re.search(r"[a-z]", password):
            errors.append("Au moins 1 minuscule")
        if not re.search(r"[0-9]", password):
            errors.append("Au moins 1 chiffre")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            errors.append("Au moins 1 symbole")
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('register_structure'))
        
        # Vérifier si l'email existe déjà
        existing = Utilisateur.query.filter_by(email=email).first()
        if existing:
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('register_structure'))
        
        # Création de la structure
        structure = Structure(
            nom=nom_structure,
            email=email,
            telephone=telephone,
            adresse=adresse,
            statut='en_attente',
            reset_question=reset_question,
            reset_answer_hash=hashlib.sha256(reset_answer.lower().strip().encode()).hexdigest()
        )
        db.session.add(structure)
        db.session.flush()
        
        # Création de l'admin de structure (responsable)
        admin = Utilisateur(
            email=email,
            nom=nom_responsable,
            prenom=prenom_responsable,
            role='admin_structure',
            id_structure=structure.id,
            actif=True
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        
        flash('Votre demande d\'inscription a été envoyée. Un administrateur va la valider.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        from models import Utilisateur, Structure
        email = request.form.get('email')
        use_secret_question = request.form.get('use_secret_question') == 'on'
        
        user = Utilisateur.query.filter_by(email=email).first()
        
        if not user:
            flash('Aucun compte trouvé avec cet email', 'danger')
            return redirect(url_for('forgot_password'))
        
        if use_secret_question and user.reset_question:
            session['reset_user_id'] = user.id
            return redirect(url_for('verify_secret_question'))
        else:
            import secrets
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)  # ✅ CORRIGÉ
            db.session.commit()
            
            flash(f'Lien de réinitialisation (valable 24h) : /reset-password/{token}', 'info')
            return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/verify-secret-question', methods=['GET', 'POST'])
def verify_secret_question():
    user_id = session.get('reset_user_id')
    if not user_id:
        return redirect(url_for('forgot_password'))
    
    from models import Utilisateur
    user = Utilisateur.query.get(user_id)
    
    if request.method == 'POST':
        answer = request.form.get('answer')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('verify_secret_question'))
        
        if user.check_reset_answer(answer):
            user.set_password(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            session.pop('reset_user_id', None)
            flash('Mot de passe réinitialisé avec succès', 'success')
            return redirect(url_for('login'))
        else:
            flash('Réponse incorrecte', 'danger')
    
    return render_template('verify_secret_question.html', question=user.reset_question)

@app.route('/laborantin/dashboard')
@login_required
def laborantin_dashboard():
    """Dashboard pour le laborantin"""
    from models import AnalyseDemande
    
    if current_user.role != 'laborantin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Statistiques pour le laborantin
    en_attente = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        statut='EN_ATTENTE'
    ).count()
    
    en_cours = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        statut='EN_COURS'
    ).count()
    
    termine = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        statut='TERMINE'
    ).count()
    
    total = en_attente + en_cours + termine
    
    return render_template('laborantin/dashboard.html',
                         en_attente=en_attente,
                         en_cours=en_cours,
                         termine=termine,
                         total=total)

@app.route('/radiologue/dashboard')
@login_required
def radiologue_dashboard():
    """Dashboard pour le radiologue"""
    from models import AnalyseDemande
    
    if current_user.role != 'radiologue':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Analyses d'imagerie uniquement
    en_attente = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        type_analyse='IMAGERIE',
        statut='EN_ATTENTE'
    ).count()
    
    en_cours = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        type_analyse='IMAGERIE',
        statut='EN_COURS'
    ).count()
    
    termine = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        type_analyse='IMAGERIE',
        statut='TERMINE'
    ).count()
    
    total = en_attente + en_cours + termine
    
    return render_template('radiologue/dashboard.html',
                         en_attente=en_attente,
                         en_cours=en_cours,
                         termine=termine,
                         total=total)


@app.route('/dashboard')
@login_required
def dashboard():
    from models import Patient, Consultation, Prescription
    from datetime import date, datetime
    
    # ⭐ REDIRECTIONS POUR TOUS LES RÔLES
    if current_user.role == 'super_admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'admin_structure':
        return redirect(url_for('structure_dashboard'))
    elif current_user.role == 'infirmier':
        return redirect(url_for('infirmier_dashboard'))
    elif current_user.role == 'laborantin':
        return redirect(url_for('laborantin_dashboard'))  # ⭐ AJOUTÉ
    elif current_user.role == 'radiologue':
        return redirect(url_for('radiologue_dashboard'))  # ⭐ AJOUTÉ
    else:
        # Dashboard médecin
        patients_actifs = Patient.query.filter_by(
            id_structure=current_user.id_structure,
            id_medecin_referent=current_user.id,
            archived=False
        ).count()
        
        consultations_aujourdhui = Consultation.query.filter(
            Consultation.id_medecin == current_user.id,
            Consultation.date_consultation >= datetime.now().replace(hour=0, minute=0, second=0)
        ).count()
        
        prescriptions_actives = Prescription.query.filter_by(
            id_medecin=current_user.id,
            statut='active'
        ).count()
        
        patients_gueris = Patient.query.filter_by(
            id_structure=current_user.id_structure,
            id_medecin_referent=current_user.id,
            statut_medical='GUERI',
            archived=False
        ).count()
        
        derniers_patients = Patient.query.filter_by(
            id_structure=current_user.id_structure,
            id_medecin_referent=current_user.id,
            archived=False
        ).order_by(Patient.date_creation.desc()).limit(5).all()
        
        prochains_rdv = Consultation.query.filter(
            Consultation.id_medecin == current_user.id,
            Consultation.prochain_rdv >= datetime.now()
        ).order_by(Consultation.prochain_rdv.asc()).limit(5).all()
        
        return render_template('medecin_dashboard.html',
                             patients_actifs=patients_actifs,
                             consultations_aujourdhui=consultations_aujourdhui,
                             prescriptions_actives=prescriptions_actives,
                             patients_gueris=patients_gueris,
                             derniers_patients=derniers_patients,
                             prochains_rdv=prochains_rdv,
                             today=date.today(),
                             now=datetime.now())

# Routes admin super admin
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Structure, Utilisateur
    structures_en_attente = Structure.query.filter_by(statut='en_attente').count()
    structures_actives = Structure.query.filter_by(statut='actif').count()
    total_utilisateurs = Utilisateur.query.count()
    
    return render_template('admin/dashboard.html',
                         structures_en_attente=structures_en_attente,
                         structures_actives=structures_actives,
                         total_utilisateurs=total_utilisateurs)


@app.route('/radiologie')
@login_required
def liste_radiologie():
    """Liste des examens d'imagerie pour le radiologue"""
    from models import AnalyseDemande, Patient
    from sqlalchemy import or_
    
    if current_user.role not in ['admin_structure', 'radiologue', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    statut = request.args.get('statut', '')
    search = request.args.get('search', '')
    
    query = AnalyseDemande.query.filter_by(
        structure_id=current_user.id_structure,
        type_analyse='IMAGERIE'  # ⭐ UNIQUEMENT L'IMAGERIE
    )
    
    if statut:
        query = query.filter_by(statut=statut)
    
    if search:
        search = search.strip()
        filters = [Patient.nom.ilike(f'%{search}%'), Patient.prenom.ilike(f'%{search}%')]
        patients_trouves = Patient.query.filter(or_(*filters)).all()
        patient_ids = [p.id for p in patients_trouves]
        if patient_ids:
            query = query.filter(AnalyseDemande.patient_id.in_(patient_ids))
        else:
            query = query.filter(AnalyseDemande.patient_id == -1)
    
    analyses = query.order_by(AnalyseDemande.date_demande.desc()).all()
    
    patients_dict = {}
    for analyse in analyses:
        patient_id = analyse.patient_id
        if patient_id not in patients_dict:
            patients_dict[patient_id] = {
                'patient': analyse.patient,
                'analyses': []
            }
        patients_dict[patient_id]['analyses'].append(analyse)
    
    patients = list(patients_dict.values())
    statuts = ['EN_ATTENTE', 'EN_COURS', 'TERMINE']
    
    return render_template('radiologue/liste.html',
                         patients=patients,
                         statut_actuel=statut,
                         statuts=statuts,
                         search=search)


# ==================== DASHBOARD INFIRMIER ====================
@app.route('/infirmier/dashboard')
@login_required
def infirmier_dashboard():
    from models import Patient, Utilisateur
    from datetime import datetime
    
    # Vérifier que l'utilisateur est un infirmier
    if current_user.role != 'infirmier':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # ⭐ PATIENTS EN ATTENTE - TRIÉS PAR DATE DE CRÉATION (les plus récents d'abord)
    patients_attente = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        archived=False
    ).filter(
        db.or_(
            Patient.pre_consultation_faite == False,
            Patient.pre_consultation_faite.is_(None)
        )
    ).order_by(Patient.date_creation.desc()).all()  # ⭐ CHANGÉ
    
    # ⭐ PATIENTS DÉJÀ PRÉPARÉS - TRIÉS PAR DATE DE PRÉ-CONSULTATION
    patients_prets = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        archived=False,
        pre_consultation_faite=True
    ).order_by(Patient.pre_consultation_date.desc()).all()
    
    # Médecins actifs
    medecins = Utilisateur.query.filter_by(
        id_structure=current_user.id_structure,
        role='medecin',
        actif=True
    ).all()
    
    # Total patients
    total_patients = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        archived=False
    ).count()
    
    return render_template('infirmier/dashboard.html',
                         patients_attente=patients_attente,
                         patients_prets=patients_prets,
                         medecins=medecins,
                         total_patients=total_patients,
                         now=datetime.now())

@app.route('/infirmier/pre_consultation/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def infirmier_pre_consultation(patient_id):
    from models import Patient
    from datetime import datetime, timezone
    
    patient = Patient.query.get_or_404(patient_id)
    
    if current_user.role != 'infirmier':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if patient.id_structure != current_user.id_structure:
        flash('Accès non autorisé à ce patient', 'danger')
        return redirect(url_for('infirmier_dashboard'))
    
    # ⭐ RÉCUPÉRER LES PATIENTS EN ATTENTE
    patients_attente = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        archived=False
    ).filter(
        db.or_(
            Patient.pre_consultation_faite == False,
            Patient.pre_consultation_faite.is_(None)
        )
    ).order_by(Patient.date_creation.desc()).all()

    step = request.args.get('step', 1, type=int)
    if step < 1 or step > 4:
        step = 1
    
    if request.method == 'POST':
        # Motif
        patient.motif_pre_consultation = request.form.get('motif')
        
        # Constantes avec gestion des valeurs vides
        tension = request.form.get('tension')
        temperature = request.form.get('temperature')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        
        patient.tension_arterielle = tension if tension and tension.strip() else None
        
        try:
            patient.temperature_c = float(temperature) if temperature and temperature.strip() else None
        except (ValueError, TypeError):
            patient.temperature_c = None
        
        try:
            patient.pulse_bpm = int(pouls) if pouls and pouls.strip() else None
        except (ValueError, TypeError):
            patient.pulse_bpm = None
        
        try:
            patient.oxygene_saturation = int(saturation) if saturation and saturation.strip() else None
        except (ValueError, TypeError):
            patient.oxygene_saturation = None
        
        try:
            patient.poids_kg = float(poids) if poids and poids.strip() else None
        except (ValueError, TypeError):
            patient.poids_kg = None
        
        try:
            patient.taille_cm = float(taille) if taille and taille.strip() else None
        except (ValueError, TypeError):
            patient.taille_cm = None
        
        try:
            patient.imc = float(imc) if imc and imc.strip() else None
        except (ValueError, TypeError):
            patient.imc = None
        
        # Habitudes de vie
        patient.tabac = request.form.get('tabac')
        patient.alcool = request.form.get('alcool')
        patient.allaitement = request.form.get('allaitement') == 'Oui'
        patient.grossesse = request.form.get('grossesse') == 'Oui'
        patient.groupe_sanguin = request.form.get('groupe_sanguin')
        patient.mutuelle = request.form.get('mutuelle')
        patient.medecin_traitant = request.form.get('medecin_traitant')
        
        # Marquer la pré-consultation comme faite
        patient.pre_consultation_faite = True
        patient.pre_consultation_par = current_user.id
        patient.pre_consultation_date = datetime.now(timezone.utc)
        
        db.session.commit()
        
        flash('✅ Pré-consultation enregistrée avec succès !', 'success')
        return redirect(url_for('infirmier_pre_consultation', patient_id=patient_id))
    
    return render_template('infirmier/pre_consultation.html', 
                         patient=patient,
                         patients_attente=patients_attente,
                         step=step)

# ==================== SAUVEGARDE MOTIF (ÉTAPE 1) ====================
@app.route('/infirmier/pre_consultation/<int:patient_id>/save-motif', methods=['POST'])
@login_required
def save_motif_pre_consultation(patient_id):
    from models import Patient
    from flask import jsonify
    
    patient = Patient.query.get_or_404(patient_id)
    
    if current_user.role != 'infirmier':
        return jsonify({'success': False, 'message': 'Accès non autorisé'}), 403
    
    motif = request.form.get('motif', '').strip()
    patient.motif_pre_consultation = motif
    db.session.commit()
    
    return jsonify({'success': True})


# ==================== SAUVEGARDE CONSTANTES (ÉTAPE 2) ====================
@app.route('/infirmier/pre_consultation/<int:patient_id>/save-constantes', methods=['POST'])
@login_required
def save_constantes_pre_consultation(patient_id):
    from models import Patient
    from flask import jsonify
    
    patient = Patient.query.get_or_404(patient_id)
    
    if current_user.role != 'infirmier':
        return jsonify({'success': False, 'message': 'Accès non autorisé'}), 403
    
    # Récupérer les constantes
    tension = request.form.get('tension')
    temperature = request.form.get('temperature')
    pouls = request.form.get('pouls')
    saturation = request.form.get('saturation')
    poids = request.form.get('poids')
    taille = request.form.get('taille')
    imc = request.form.get('imc')
    
    # Sauvegarder avec gestion des valeurs vides
    patient.tension_arterielle = tension if tension and tension.strip() else None
    
    try:
        patient.temperature_c = float(temperature) if temperature and temperature.strip() else None
    except (ValueError, TypeError):
        patient.temperature_c = None
    
    try:
        patient.pulse_bpm = int(pouls) if pouls and pouls.strip() else None
    except (ValueError, TypeError):
        patient.pulse_bpm = None
    
    try:
        patient.oxygene_saturation = int(saturation) if saturation and saturation.strip() else None
    except (ValueError, TypeError):
        patient.oxygene_saturation = None
    
    try:
        patient.poids_kg = float(poids) if poids and poids.strip() else None
    except (ValueError, TypeError):
        patient.poids_kg = None
    
    try:
        patient.taille_cm = float(taille) if taille and taille.strip() else None
    except (ValueError, TypeError):
        patient.taille_cm = None
    
    try:
        patient.imc = float(imc) if imc and imc.strip() else None
    except (ValueError, TypeError):
        patient.imc = None
    
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/medecin/dashboard')
@login_required
def medecin_dashboard():
    from models import Patient, Consultation, Prescription
    from datetime import date, datetime
    
    if current_user.role != 'medecin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Statistiques pour le médecin
    patients_actifs = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        id_medecin_referent=current_user.id,
        archived=False
    ).count()
    
    consultations_aujourdhui = Consultation.query.filter(
        Consultation.id_medecin == current_user.id,
        Consultation.date_consultation >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()
    
    prescriptions_actives = Prescription.query.filter_by(
        id_medecin=current_user.id,
        statut='active'
    ).count()
    
    patients_gueris = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        id_medecin_referent=current_user.id,
        statut_medical='GUERI',
        archived=False
    ).count()
    
    derniers_patients = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        id_medecin_referent=current_user.id,
        archived=False
    ).order_by(Patient.date_creation.desc()).limit(5).all()
    
    prochains_rdv = Consultation.query.filter(
        Consultation.id_medecin == current_user.id,
        Consultation.prochain_rdv >= datetime.now()
    ).order_by(Consultation.prochain_rdv.asc()).limit(5).all()
    
    return render_template('medecin_dashboard.html',
                         patients_actifs=patients_actifs,
                         consultations_aujourdhui=consultations_aujourdhui,
                         prescriptions_actives=prescriptions_actives,
                         patients_gueris=patients_gueris,
                         derniers_patients=derniers_patients,
                         prochains_rdv=prochains_rdv,
                         today=date.today())

@app.route('/api/patient/<int:patient_id>/pre_consultation')
@login_required
def api_patient_pre_consultation(patient_id):
    from models import Patient
    
    patient = Patient.query.get_or_404(patient_id)
    
    return jsonify({
        'motif': patient.motif_pre_consultation or '',
        'pre_consultation_faite': patient.pre_consultation_faite or False,
        'tabac': patient.tabac or '',
        'alcool': patient.alcool or '',
        'allaitement': patient.allaitement or False,
        'grossesse': patient.grossesse or False,
        'groupe_sanguin': patient.groupe_sanguin or '',
        'mutuelle': patient.mutuelle or '',
        'medecin_traitant': patient.medecin_traitant or ''
    })

# ==================== GESTION DES UTILISATEURS PAR ADMIN STRUCTURE ====================

@app.route('/structure/utilisateurs')
@login_required
def structure_utilisateurs():
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur
    utilisateurs = Utilisateur.query.filter_by(id_structure=current_user.id_structure).all()
    return render_template('structure/utilisateurs.html', utilisateurs=utilisateurs)

@app.route('/structure/utilisateur/ajouter', methods=['GET', 'POST'])
@login_required
def structure_ajouter_utilisateur():
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur
    
    if request.method == 'POST':
        email = request.form.get('email')
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        role = request.form.get('role')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Vérifications
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('structure_ajouter_utilisateur'))
        
        # Vérifier si l'email existe déjà
        existing = Utilisateur.query.filter_by(email=email).first()
        if existing:
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('structure_ajouter_utilisateur'))
        
        # Créer l'utilisateur
        new_user = Utilisateur(
            email=email,
            nom=nom,
            prenom=prenom,
            role=role,
            id_structure=current_user.id_structure,
            actif=True
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'Utilisateur {prenom} {nom} créé avec succès', 'success')
        return redirect(url_for('structure_utilisateurs'))
    
    return render_template('structure/ajouter_utilisateur.html')

@app.route('/structure/utilisateur/<int:id>/modifier', methods=['GET', 'POST'])
@login_required
def structure_modifier_utilisateur(id):
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur
    user = Utilisateur.query.get_or_404(id)
    
    # Vérifier que l'utilisateur appartient à la structure
    if user.id_structure != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('structure_utilisateurs'))
    
    if request.method == 'POST':
        user.nom = request.form.get('nom')
        user.prenom = request.form.get('prenom')
        user.role = request.form.get('role')
        user.actif = request.form.get('actif') == 'on'
        
        # Changement de mot de passe optionnel
        new_password = request.form.get('new_password')
        if new_password:
            confirm = request.form.get('confirm_password')
            if new_password == confirm:
                user.set_password(new_password)
                flash('Mot de passe modifié', 'success')
            else:
                flash('Les mots de passe ne correspondent pas', 'danger')
                return redirect(url_for('structure_modifier_utilisateur', id=id))
        
        db.session.commit()
        flash(f'Utilisateur {user.prenom} {user.nom} modifié', 'success')
        return redirect(url_for('structure_utilisateurs'))
    
    return render_template('structure/modifier_utilisateur.html', user=user)

@app.route('/structure/utilisateur/<int:id>/supprimer')
@login_required
def structure_supprimer_utilisateur(id):
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur
    user = Utilisateur.query.get_or_404(id)
    
    # Ne pas permettre de supprimer son propre compte
    if user.id == current_user.id:
        flash('Vous ne pouvez pas supprimer votre propre compte', 'danger')
        return redirect(url_for('structure_utilisateurs'))
    
    if user.id_structure != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('structure_utilisateurs'))
    
    db.session.delete(user)
    db.session.commit()
    flash(f'Utilisateur {user.prenom} {user.nom} supprimé', 'success')
    return redirect(url_for('structure_utilisateurs'))

@app.route('/admin/structures')
@login_required
def admin_structures():
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Structure
    structures = Structure.query.all()
    return render_template('admin/structures.html', structures=structures)

@app.route('/admin/structure/<int:id>/activate')
@login_required
def admin_activate_structure(id):
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Structure
    structure = Structure.query.get_or_404(id)
    structure.statut = 'actif'
    structure.date_activation = datetime.utcnow()
    db.session.commit()
    
    # 👇 AJOUTEZ CETTE LIGNE
    create_structure_sheets(structure.id)
    
    flash(f'Structure {structure.nom} activée avec succès', 'success')
    return redirect(url_for('admin_structures'))

@app.route('/admin/structure/<int:id>/reset-password', methods=['GET', 'POST'])
@login_required
def admin_reset_structure_password(id):
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Structure, Utilisateur
    structure = Structure.query.get_or_404(id)
    admin = Utilisateur.query.filter_by(id_structure=id, role='admin_structure').first()
    
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
        else:
            admin.set_password(new_password)
            db.session.commit()
            flash(f'Mot de passe réinitialisé pour {structure.nom}', 'success')
            return redirect(url_for('admin_structures'))
    
    return render_template('admin/reset_password.html', structure=structure, admin=admin)

# Route pour tableau de bord structure admin
@app.route('/structure')
@login_required
def structure_dashboard():
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Patient, Utilisateur, Consultation
    total_patients = Patient.query.filter_by(id_structure=current_user.id_structure, archived=False).count()
    total_medecins = Utilisateur.query.filter_by(id_structure=current_user.id_structure, role='medecin').count()
    consultations_mois = Consultation.query.filter(
        Consultation.id_patient.in_(
            db.session.query(Patient.id).filter_by(id_structure=current_user.id_structure)
        ),
        Consultation.date_consultation >= datetime.utcnow().replace(day=1)
    ).count()
    
    return render_template('structure/dashboard.html',
                         total_patients=total_patients,
                         total_medecins=total_medecins,
                         consultations_mois=consultations_mois)

@app.route('/patients')
@login_required
@has_permission('PATIENTS')
def patients_list():
    # Super Admin n'a pas accès aux patients
    if current_user.role == 'super_admin':
        flash('Accès non autorisé. Zone réservée aux structures médicales.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    from models import Patient
    from sqlalchemy import or_
    
    # ⭐ RÉCUPÉRER LES FILTRES
    statut_filter = request.args.get('statut', '')
    search = request.args.get('search', '')
    
    # ⭐ CONSTRUIRE LA REQUÊTE DE BASE
    if current_user.role == 'admin_structure':
        query = Patient.query.filter_by(id_structure=current_user.id_structure, archived=False)
    elif current_user.role == 'medecin':
        query = Patient.query.filter_by(
            id_structure=current_user.id_structure, 
            id_medecin_referent=current_user.id,
            archived=False
        )
    else:  # secretaire
        query = Patient.query.filter_by(id_structure=current_user.id_structure, archived=False)
    
    # ⭐ APPLIQUER LE FILTRE STATUT
    if statut_filter:
        if statut_filter == 'GUERI':
            query = query.filter(Patient.statut_medical == 'GUERI')
        elif statut_filter == 'EN_TRAITEMENT':
            query = query.filter(Patient.statut_medical == 'EN_TRAITEMENT')
        elif statut_filter == 'PREMIERE_VISITE':
            query = query.filter(Patient.statut_medical == 'PREMIERE_VISITE')
        elif statut_filter == 'TRANSFERE':
            query = query.filter(Patient.statut_medical == 'TRANSFERE')
        elif statut_filter == 'PERDU_VUE':
            query = query.filter(Patient.statut_medical == 'PERDU_VUE')
    
    # ⭐ APPLIQUER LA RECHERCHE
    if search:
        search = search.strip()
        query = query.filter(
            or_(
                Patient.nom.ilike(f'%{search}%'),
                Patient.prenom.ilike(f'%{search}%'),
                Patient.telephone.ilike(f'%{search}%'),
                Patient.email.ilike(f'%{search}%')
            )
        )
    
    patients = query.order_by(Patient.date_creation.desc()).all()
    
    # ⭐ COMPTER LES STATUTS POUR LE FILTRE
    total_gueris = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        statut_medical='GUERI',
        archived=False
    ).count()
    
    total_traitement = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        statut_medical='EN_TRAITEMENT',
        archived=False
    ).count()
    
    total_attente = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        statut_medical='PREMIERE_VISITE',
        archived=False
    ).count()
    
    return render_template('patients/list.html', 
                         patients=patients,
                         statut_actuel=statut_filter,
                         search=search,
                         total_gueris=total_gueris,
                         total_traitement=total_traitement,
                         total_attente=total_attente)

@app.route('/patients/ajouter', methods=['GET', 'POST'])
@login_required
@has_permission('PATIENTS')
def patient_ajouter():
    from models import Patient, Utilisateur, Consultation
    from datetime import datetime
    
    # Récupérer la liste des médecins
    medecins = []
    if current_user.role in ['admin_structure', 'secretaire']:
        medecins = Utilisateur.query.filter_by(
            id_structure=current_user.id_structure, 
            role='medecin',
            actif=True
        ).all()
    elif current_user.role == 'medecin':
        medecins = [current_user]
    
    if request.method == 'POST':
        # Identité
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        date_naissance = request.form.get('date_naissance')
        sexe = request.form.get('sexe')
        telephone = request.form.get('telephone')
        email = request.form.get('email')
        adresse = request.form.get('adresse')
        profession = request.form.get('profession')
        
        # Assurance principale
        type_assurance = request.form.get('type_assurance')
        autre_assurance_nom = request.form.get('autre_assurance_nom')
        num_assure = request.form.get('num_assure')
        
        # ⭐ ASSURANCE 2 (NOUVEAU)
        assurance2_nom = request.form.get('assurance2_nom')
        taux_assurance2 = request.form.get('taux_assurance2')
        numero_assure2 = request.form.get('numero_assure2')
        
        # ⭐ PERSONNE À PRÉVENIR (NOUVEAU)
        personne_a_prevenir_nom = request.form.get('personne_a_prevenir_nom')
        personne_a_prevenir_telephone = request.form.get('personne_a_prevenir_telephone')
        personne_a_prevenir_relation = request.form.get('personne_a_prevenir_relation')
        
        # ⭐ TAUX DE PRISE EN CHARGE (NOUVEAU)
        taux_prise_charge = request.form.get('taux_prise_charge')

        groupe_sanguin = request.form.get('groupe_sanguin')

        # Médecin référent
        id_medecin_referent = request.form.get('id_medecin_referent')
        
        # Constantes vitales
        temperature = request.form.get('temperature')
        tension = request.form.get('tension')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        
        # Notes
        notes = request.form.get('notes')
        
        # Validation
        if not nom or not prenom:
            flash('Le nom et le prénom sont obligatoires', 'danger')
            return redirect(url_for('patient_ajouter'))
        
        # Création du patient avec TOUS les champs
        patient = Patient(
            id_structure=current_user.id_structure if current_user.id_structure else 1,
            nom=nom,
            prenom=prenom,
            date_naissance=datetime.strptime(date_naissance, '%Y-%m-%d') if date_naissance else None,
            sexe=sexe,
            telephone=telephone,
            email=email,
            adresse=adresse,
            profession=profession,
            groupe_sanguin=groupe_sanguin,
            # Assurance principale
            type_assurance=type_assurance,
            autre_assurance_nom=autre_assurance_nom if type_assurance == 'AUTRE_ASSURANCE' else None,
            num_assure=num_assure,
            
            # ⭐ ASSURANCE 2
            assurance2_nom=assurance2_nom,
            taux_assurance2=float(taux_assurance2) if taux_assurance2 else None,
            numero_assure2=numero_assure2,
            
            # ⭐ PERSONNE À PRÉVENIR
            personne_a_prevenir_nom=personne_a_prevenir_nom,
            personne_a_prevenir_telephone=personne_a_prevenir_telephone,
            personne_a_prevenir_relation=personne_a_prevenir_relation,
            
            # ⭐ TAUX DE PRISE EN CHARGE
            taux_prise_charge=float(taux_prise_charge) if taux_prise_charge else None,
            
            # Médecin référent
            id_medecin_referent=int(id_medecin_referent) if id_medecin_referent else None,
            
            # Constantes
            temperature_c=float(temperature) if temperature else None,
            tension_arterielle=tension,
            pulse_bpm=int(pouls) if pouls else None,
            oxygene_saturation=int(saturation) if saturation else None,
            poids_kg=float(poids) if poids else None,
            taille_cm=float(taille) if taille else None,
            imc=float(imc) if imc else None,
            
            # Notes
            notes=notes,
            
            # Statut
            statut_medical='PREMIERE_VISITE',
            date_premiere_visite=datetime.utcnow(),
            archived=False
        )
        
        db.session.add(patient)
        db.session.flush()
        
        # Créer une première consultation avec les constantes
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=current_user.id if current_user.role == 'medecin' else int(id_medecin_referent) if id_medecin_referent else None,
            motif="Première consultation - Enregistrement initial",
            temperature_c=float(temperature) if temperature else None,
            tension_arterielle=tension,
            pulse_bpm=int(pouls) if pouls else None,
            oxygene_saturation=int(saturation) if saturation else None,
            poids_kg=float(poids) if poids else None,
            taille_cm=float(taille) if taille else None,
            imc=float(imc) if imc else None,
            date_consultation=datetime.utcnow()
        )
        db.session.add(consultation)
        
        db.session.commit()
        
        flash(f'✅ Patient {prenom} {nom} créé avec succès !', 'success')
        flash('📝 Renseignez maintenant les antécédents du patient.', 'info')
        return redirect(url_for('patient_antecedents', patient_id=patient.id))
    
    return render_template('patients/ajouter.html', medecins=medecins)

@app.route('/patient/<int:id>')
@login_required
@has_permission('PATIENTS')
def patient_detail(id):
    from models import Patient, Consultation, Prescription, ExamenPhysique, SectionExamenPhysique
    from datetime import datetime
    import json
    
    patient = Patient.query.get_or_404(id)
    
    # Vérification pour le médecin
    if current_user.role == 'medecin' and patient.id_medecin_referent is not None and patient.id_medecin_referent != current_user.id:
        flash('Accès non autorisé - Ce patient n\'est pas votre patient référent', 'danger')
        return redirect(url_for('patients_list'))
    
    consultations = Consultation.query.filter_by(id_patient=patient.id).order_by(Consultation.date_consultation.desc()).all()
    prescriptions = Prescription.query.filter_by(id_patient=patient.id).order_by(Prescription.date_prescription.desc()).all()
    
    # ⭐ Récupérer les sections standard pour référence
    sections_standard = SectionExamenPhysique.query.filter_by(actif=True).order_by(SectionExamenPhysique.ordre).all()
    sections_standard_dict = {s.nom: s.texte_fr for s in sections_standard}
    
    # ⭐ Pour chaque consultation, récupérer les sections modifiées
    for consultation in consultations:
        examen = ExamenPhysique.query.filter_by(consultation_id=consultation.id).first()
        if examen and examen.sections_modifiees:
            try:
                consultation.sections_modifiees = json.loads(examen.sections_modifiees)
                consultation.examen_complet = examen.examen_complet
            except:
                consultation.sections_modifiees = {}
                consultation.examen_complet = None
        else:
            consultation.sections_modifiees = {}
            consultation.examen_complet = None
        
        # ⭐ Ajouter les sections standard pour comparaison
        consultation.sections_standard = sections_standard_dict
    
    return render_template('patients/detail.html', 
                         patient=patient, 
                         consultations=consultations,
                         prescriptions=prescriptions,
                         now=datetime.now())

@app.route('/consultation/ajouter', methods=['GET', 'POST'])
@login_required
def consultation_ajouter():
    from models import Patient, Consultation, AnalyseDemande, Prescription
    from datetime import datetime
    import json
    
    # Récupération des patients
    if current_user.role == 'medecin':
        patients = Patient.query.filter_by(
            id_structure=current_user.id_structure,
            id_medecin_referent=current_user.id,
            archived=False
        ).all()
    else:
        patients = Patient.query.filter_by(
            id_structure=current_user.id_structure,
            archived=False
        ).all()
    
    if request.method == 'POST':
        id_patient = request.form.get('id_patient')
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')

        # ============================================================
        # RÉCUPÉRATION DES CHAMPS HPI
        # ============================================================
        hpi_date_debut = request.form.get('hpi_date_debut')
        hpi_debut_type = request.form.get('hpi_debut_type')
        hpi_circonstances = request.form.get('hpi_circonstances')
        hpi_evolution = request.form.get('hpi_evolution')
        hpi_facteurs = request.form.get('hpi_facteurs')
        hpi_traitements = request.form.get('hpi_traitements')
        hpi_signes = request.form.get('hpi_signes')
        
        # ⭐ RÉCUPÉRER LES CHECKBOXES DES SIGNES ASSOCIÉS
        hpi_fievre = request.form.get('hpi_fievre') == 'on'
        hpi_nausees = request.form.get('hpi_nausees') == 'on'
        hpi_douleur = request.form.get('hpi_douleur') == 'on'
        hpi_cephalées = request.form.get('hpi_cephalées') == 'on'
        hpi_vertiges = request.form.get('hpi_vertiges') == 'on'
        hpi_dyspnee = request.form.get('hpi_dyspnee') == 'on'
        
        hpi_trauma_mecanisme = request.form.get('hpi_trauma_mecanisme')
        hpi_trauma_heure = request.form.get('hpi_trauma_heure')
        hpi_trauma_pc = request.form.get('hpi_trauma_pc')
        hpi_trauma_description = request.form.get('hpi_trauma_description')
        
        hpi_morsure_type = request.form.get('hpi_morsure_type')
        hpi_morsure_espece = request.form.get('hpi_morsure_espece')
        hpi_morsure_siege = request.form.get('hpi_morsure_siege')
        hpi_morsure_signes = request.form.get('hpi_morsure_signes')
        
        hpi_intox_substance = request.form.get('hpi_intox_substance')
        hpi_intox_heure = request.form.get('hpi_intox_heure')
        hpi_intox_circonstances = request.form.get('hpi_intox_circonstances')
        
        hpi_autres_signes = request.form.get('hpi_autres_signes')
        hpi_autre_infos = request.form.get('hpi_autre_infos')
        
        hpi_complements_medecin = request.form.get('hpi_complements_medecin')
        histoire_maladie = request.form.get('histoire_maladie')

        # Constantes
        tension = request.form.get('tension')
        temperature = request.form.get('temperature')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        
        # Examens
        examens_cliniques = request.form.get('examens_cliniques')
        examens_biologie = request.form.get('examens_biologie')
        examens_imagerie = request.form.get('examens_imagerie')
        
        traitement = request.form.get('traitement')
        notes = request.form.get('notes')
        prochain_rdv = request.form.get('prochain_rdv')
        arret_travail = request.form.get('arret_travail') == 'on'
        arret_jours = request.form.get('arret_jours')
        statut_medical = request.form.get('statut_medical')
        cim10 = request.form.get('cim10')
        
        allergies = request.form.get('allergies')
        traitements_en_cours = request.form.get('traitements_en_cours')
        antecedents_medicaux = request.form.get('antecedents_medicaux')
        antecedents_chirurgicaux = request.form.get('antecedents_chirurgicaux')
        
        medicaments_prescrits = request.form.get('medicaments_prescrits')
        
        # ⭐⭐⭐ RÉCUPÉRER LE PATIENT ⭐⭐⭐
        patient = Patient.query.get(id_patient)
        if not patient:
            flash('Patient non trouvé', 'danger')
            return redirect(url_for('consultation_ajouter'))
        
        # ⭐⭐⭐ LE MÉDECIN QUI CONSULTE DEVIENT LE RÉFÉRENT ⭐⭐⭐
        patient.id_medecin_referent = current_user.id
        print(f"✅ Médecin référent : Dr {current_user.nom} {current_user.prenom} pour le patient {patient.nom} {patient.prenom}")
        
        # ═══════════════════════════════════════════
        # ⭐ 2. RÉCUPÉRATION DE LA CONSULTATION TEMPORAIRE
        # ═══════════════════════════════════════════
        
        consultation = Consultation.query.filter_by(
            id_patient=patient.id,
            is_temporary=True
        ).first()
        
        if consultation:
            # ⭐ METTRE À JOUR LA CONSULTATION TEMPORAIRE
            print(f"✅ Consultation temporaire #{consultation.id} trouvée !")
            
            consultation.motif = motif
            consultation.diagnostic = diagnostic
            consultation.tension_arterielle = tension
            consultation.temperature_c = float(temperature) if temperature else None
            consultation.pulse_bpm = int(pouls) if pouls else None
            consultation.oxygene_saturation = int(saturation) if saturation else None
            consultation.poids_kg = float(poids) if poids else None
            consultation.taille_cm = float(taille) if taille else None
            consultation.imc = float(imc) if imc else None
            consultation.examens_cliniques = examens_cliniques
            consultation.examens_biologie = examens_biologie
            consultation.examens_imagerie = examens_imagerie
            consultation.traitement_prescrit = traitement
            consultation.notes_cliniques = notes
            consultation.cim10 = cim10
            consultation.arret_travail = arret_travail
            consultation.arret_jours = int(arret_jours) if arret_jours else None
            consultation.prochain_rdv = datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None
            consultation.allergies = allergies
            consultation.traitements_en_cours = traitements_en_cours
            consultation.antecedents_medicaux = antecedents_medicaux
            consultation.antecedents_chirurgicaux = antecedents_chirurgicaux
            
            # HPI - Champs texte
            consultation.hpi_date_debut = datetime.strptime(hpi_date_debut, '%Y-%m-%d').date() if hpi_date_debut else None
            consultation.hpi_debut_type = hpi_debut_type
            consultation.hpi_circonstances = hpi_circonstances
            consultation.hpi_evolution = hpi_evolution
            consultation.hpi_facteurs = hpi_facteurs
            consultation.hpi_traitements = hpi_traitements
            consultation.hpi_signes = hpi_signes
            consultation.hpi_trauma_mecanisme = hpi_trauma_mecanisme
            consultation.hpi_trauma_heure = datetime.fromisoformat(hpi_trauma_heure) if hpi_trauma_heure else None
            consultation.hpi_trauma_pc = hpi_trauma_pc
            consultation.hpi_trauma_description = hpi_trauma_description
            consultation.hpi_morsure_type = hpi_morsure_type
            consultation.hpi_morsure_espece = hpi_morsure_espece
            consultation.hpi_morsure_siege = hpi_morsure_siege
            consultation.hpi_morsure_signes = hpi_morsure_signes
            consultation.hpi_intox_substance = hpi_intox_substance
            consultation.hpi_intox_heure = datetime.fromisoformat(hpi_intox_heure) if hpi_intox_heure else None
            consultation.hpi_intox_circonstances = hpi_intox_circonstances
            consultation.hpi_autres_signes = hpi_autres_signes
            consultation.hpi_autre_infos = hpi_autre_infos
            consultation.hpi_complements_medecin = hpi_complements_medecin
            consultation.histoire_maladie = histoire_maladie
            
            # ⭐⭐⭐ AJOUTER LES SIGNES ASSOCIÉS ⭐⭐⭐
            consultation.hpi_fievre = hpi_fievre
            consultation.hpi_nausees = hpi_nausees
            consultation.hpi_douleur = hpi_douleur
            consultation.hpi_cephalées = hpi_cephalées
            consultation.hpi_vertiges = hpi_vertiges
            consultation.hpi_dyspnee = hpi_dyspnee
            
            # ⭐ MARQUER COMME DÉFINITIVE
            consultation.is_temporary = False
            consultation.statut = 'terminee'
            consultation.id_medecin = current_user.id
            consultation.date_consultation = datetime.utcnow()
            
        else:
            # ⭐ PAS DE CONSULTATION TEMPORAIRE : EN CRÉER UNE
            print(f"⚠️ Aucune consultation temporaire trouvée pour patient #{patient.id}")
            
            consultation = Consultation(
                id_patient=int(id_patient),
                id_medecin=current_user.id,
                motif=motif,
                diagnostic=diagnostic,
                tension_arterielle=tension,
                temperature_c=float(temperature) if temperature else None,
                pulse_bpm=int(pouls) if pouls else None,
                oxygene_saturation=int(saturation) if saturation else None,
                poids_kg=float(poids) if poids else None,
                taille_cm=float(taille) if taille else None,
                imc=float(imc) if imc else None,
                examens_cliniques=examens_cliniques,
                examens_biologie=examens_biologie,
                examens_imagerie=examens_imagerie,
                traitement_prescrit=traitement,
                notes_cliniques=notes,
                arret_travail=arret_travail,
                arret_jours=int(arret_jours) if arret_jours else None,
                prochain_rdv=datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None,
                allergies=allergies,
                traitements_en_cours=traitements_en_cours,
                antecedents_medicaux=antecedents_medicaux,
                antecedents_chirurgicaux=antecedents_chirurgicaux,
                cim10=cim10,
                hpi_date_debut=datetime.strptime(hpi_date_debut, '%Y-%m-%d').date() if hpi_date_debut else None,
                hpi_debut_type=hpi_debut_type,
                hpi_circonstances=hpi_circonstances,
                hpi_evolution=hpi_evolution,
                hpi_facteurs=hpi_facteurs,
                hpi_traitements=hpi_traitements,
                hpi_signes=hpi_signes,
                hpi_trauma_mecanisme=hpi_trauma_mecanisme,
                hpi_trauma_heure=datetime.fromisoformat(hpi_trauma_heure) if hpi_trauma_heure else None,
                hpi_trauma_pc=hpi_trauma_pc,
                hpi_trauma_description=hpi_trauma_description,
                hpi_morsure_type=hpi_morsure_type,
                hpi_morsure_espece=hpi_morsure_espece,
                hpi_morsure_siege=hpi_morsure_siege,
                hpi_morsure_signes=hpi_morsure_signes,
                hpi_intox_substance=hpi_intox_substance,
                hpi_intox_heure=datetime.fromisoformat(hpi_intox_heure) if hpi_intox_heure else None,
                hpi_intox_circonstances=hpi_intox_circonstances,
                hpi_autres_signes=hpi_autres_signes,
                hpi_autre_infos=hpi_autre_infos,
                hpi_complements_medecin=hpi_complements_medecin,
                histoire_maladie=histoire_maladie,
                date_consultation=datetime.utcnow(),
                is_temporary=False,
                # ⭐⭐⭐ AJOUTER LES SIGNES ASSOCIÉS ⭐⭐⭐
                hpi_fievre=hpi_fievre,
                hpi_nausees=hpi_nausees,
                hpi_douleur=hpi_douleur,
                hpi_cephalées=hpi_cephalées,
                hpi_vertiges=hpi_vertiges,
                hpi_dyspnee=hpi_dyspnee
            )
            db.session.add(consultation)
            db.session.flush()
            print(f"✅ Nouvelle consultation #{consultation.id} créée")
        
        # ═══════════════════════════════════════════
        # 3. CRÉATION DES ANALYSES
        # ═══════════════════════════════════════════
        
        if examens_biologie:
            for ligne in examens_biologie.split('\n'):
                nom = ligne.strip()
                if nom:
                    analyse = AnalyseDemande(
                        consultation_id=consultation.id,
                        patient_id=consultation.id_patient,
                        structure_id=current_user.id_structure,
                        type_analyse='BIOLOGIE',
                        nom_analyse=nom,
                        prescrit_par=current_user.id,
                        statut='EN_ATTENTE'
                    )
                    db.session.add(analyse)
        
        if examens_imagerie:
            for ligne in examens_imagerie.split('\n'):
                nom = ligne.strip()
                if nom:
                    analyse = AnalyseDemande(
                        consultation_id=consultation.id,
                        patient_id=consultation.id_patient,
                        structure_id=current_user.id_structure,
                        type_analyse='IMAGERIE',
                        nom_analyse=nom,
                        prescrit_par=current_user.id,
                        statut='EN_ATTENTE'
                    )
                    db.session.add(analyse)
        
        # ═══════════════════════════════════════════
        # 4. CRÉATION DES PRESCRIPTIONS
        # ═══════════════════════════════════════════
        
        prescriptions_creees = 0
        
        if medicaments_prescrits:
            try:
                meds_data = json.loads(medicaments_prescrits)
                
                for med in meds_data:
                    prescription = Prescription(
                        id_patient=int(id_patient),
                        id_consultation=consultation.id,
                        id_medecin=current_user.id,
                        medicament=med.get('nom', ''),
                        dosage=med.get('dosage', ''),
                        forme=med.get('forme', ''),
                        quantite=str(med.get('quantite', 1)),
                        duree_jours=med.get('duree', 7),
                        frequence=med.get('posologie', ''),
                        instructions=med.get('instructions', ''),
                        renouvelable=med.get('renouvelable', False),
                        type_prescription='medicament',
                        prescripteur=f"{current_user.prenom} {current_user.nom}",
                        statut='active',
                        date_prescription=datetime.utcnow(),
                        notes=med.get('notes', ''),
                        source_id=med.get('source_id'),
                        stock_disponible=med.get('stock')
                    )
                    db.session.add(prescription)
                    prescriptions_creees += 1
                    
                print(f"✅ {len(meds_data)} prescription(s) médicamenteuse(s) enregistrée(s)")
                
            except Exception as e:
                print(f"❌ Erreur sauvegarde prescriptions médicaments: {e}")
                import traceback
                traceback.print_exc()
        
        if examens_biologie:
            for ligne in examens_biologie.split('\n'):
                nom = ligne.strip()
                if nom:
                    prescription = Prescription(
                        id_patient=int(id_patient),
                        id_consultation=consultation.id,
                        id_medecin=current_user.id,
                        medicament=nom,
                        type_prescription='acte',
                        prescripteur=f"{current_user.prenom} {current_user.nom}",
                        statut='active',
                        date_prescription=datetime.utcnow()
                    )
                    db.session.add(prescription)
                    prescriptions_creees += 1
        
        if examens_imagerie:
            for ligne in examens_imagerie.split('\n'):
                nom = ligne.strip()
                if nom:
                    prescription = Prescription(
                        id_patient=int(id_patient),
                        id_consultation=consultation.id,
                        id_medecin=current_user.id,
                        medicament=nom,
                        type_prescription='acte',
                        prescripteur=f"{current_user.prenom} {current_user.nom}",
                        statut='active',
                        date_prescription=datetime.utcnow()
                    )
                    db.session.add(prescription)
                    prescriptions_creees += 1
        
        # ═══════════════════════════════════════════
        # 5. MISE À JOUR DU PATIENT
        # ═══════════════════════════════════════════
        
        if temperature:
            patient.temperature_c = float(temperature)
        if tension:
            patient.tension_arterielle = tension
        if pouls:
            patient.pulse_bpm = int(pouls)
        if saturation:
            patient.oxygene_saturation = int(saturation)
        if poids:
            patient.poids_kg = float(poids)
        if taille:
            patient.taille_cm = float(taille)
        if imc:
            patient.imc = float(imc)
        
        patient.date_derniere_consultation = datetime.utcnow()
        
        if statut_medical:
            patient.statut_medical = statut_medical
            if statut_medical == 'GUERI':
                patient.date_guerison = datetime.utcnow()
        elif patient.statut_medical == 'PREMIERE_VISITE':
            patient.statut_medical = 'EN_TRAITEMENT'
        
        # ═══════════════════════════════════════════
        # 6. COMMIT FINAL
        # ═══════════════════════════════════════════
        
        db.session.commit()
        
        if prescriptions_creees > 0:
            try:
                from tasks import sync_prescriptions_to_ghp
                result = sync_prescriptions_to_ghp()
                if result.get('success'):
                    print(f"✅ {result.get('message')}")
                else:
                    print(f"⚠️ {result.get('message')}")
            except Exception as e:
                print(f"⚠️ Erreur sync auto: {e}")
        
        flash('Consultation enregistrée avec succès', 'success')
        return redirect(url_for('patient_detail', id=id_patient))

    empty_consultation = Consultation()
    return render_template('consultations/ajouter.html', patients=patients, consultation=empty_consultation)


@app.route('/consultation/<int:id>')
@login_required
def consultation_detail(id):
    from models import Consultation, Patient, ExamenType
    
    consultation = Consultation.query.get_or_404(id)
    patient = Patient.query.get(consultation.id_patient)
    
    # ⭐ RÉCUPÉRER LES EXAMENS TYPES DISPONIBLES POUR LA STRUCTURE
    examens_types = ExamenType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    # ⭐ RÉCUPÉRER LES EXAMENS PRESCRITS (si la relation existe)
    examens_prescrits = []
    if hasattr(consultation, 'examens_prescrits'):
        examens_prescrits = consultation.examens_prescrits.order_by(
            ExamenPrescrit.date_prescription.desc()
        ).all() if consultation.examens_prescrits else []
    
    return render_template('consultations/detail.html',
                         consultation=consultation,
                         patient=patient,
                         examens_types=examens_types,
                         examens_prescrits=examens_prescrits,
                         now=datetime.utcnow())


# ==================== PRESCRIPTIONS ====================

@app.route('/prescription/ajouter', methods=['GET', 'POST'])
@login_required
def prescription_ajouter():
    from models import Patient, Prescription
    from datetime import datetime, timezone
    import json
    
    try:
        # ✅ FORCER UNE NOUVELLE SESSION
        db.session.expire_all()
        
        if current_user.role == 'medecin':
            patients = Patient.query.filter_by(
                id_structure=current_user.id_structure,
                id_medecin_referent=current_user.id,
                archived=False
            ).all()
        else:
            patients = Patient.query.filter_by(
                id_structure=current_user.id_structure,
                archived=False
            ).all()
    except Exception as e:
        print(f"❌ Erreur récupération patients: {e}")
        patients = []
        flash('Erreur de chargement des patients', 'danger')
    
    if request.method == 'POST':
        try:
            id_patient = request.form.get('id_patient')
            notes = request.form.get('notes', '')
            medicaments_prescrits = request.form.get('medicaments_prescrits')
            
            if not medicaments_prescrits:
                flash('Veuillez ajouter au moins un médicament', 'danger')
                return redirect(url_for('prescription_ajouter'))
            
            meds_data = json.loads(medicaments_prescrits)
            
            if not meds_data:
                flash('Aucun médicament valide', 'danger')
                return redirect(url_for('prescription_ajouter'))
            
            patient = db.session.get(Patient, int(id_patient))
            if not patient:
                flash('Patient non trouvé', 'danger')
                return redirect(url_for('prescription_ajouter'))
            
            prescriptions = []
            
            for med in meds_data:
                nom_med = med.get('nom', '').strip()
                if not nom_med:
                    continue
                
                prescription = Prescription(
                    id_patient=int(id_patient),
                    id_medecin=current_user.id,
                    medicament=nom_med,
                    dosage=med.get('dosage', ''),
                    quantite=str(med.get('quantite', 1)),
                    duree_jours=int(med.get('duree', 7) or 7),
                    frequence=med.get('posologie', ''),
                    instructions=med.get('instructions', ''),
                    prescripteur=f"{current_user.prenom} {current_user.nom}",
                    statut='active',
                    date_prescription=datetime.now(timezone.utc),
                    notes=notes
                )
                prescriptions.append(prescription)
                print(f"✅ Prescription préparée: {nom_med}")
            
            if len(prescriptions) == 0:
                flash('Aucun médicament valide à enregistrer', 'danger')
                return redirect(url_for('prescription_ajouter'))
            
            # ✅ AJOUTER UN PAR UN AVEC FLUSH
            for p in prescriptions:
                db.session.add(p)
                db.session.flush()  # ← Flush après chaque ajout
            
            # ✅ COMMIT FINAL
            db.session.commit()
            
            flash(f'✅ {len(prescriptions)} prescription(s) enregistrée(s)', 'success')
            return redirect(url_for('patients_list'))
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            flash(f'Erreur: {str(e)}', 'danger')
            return redirect(url_for('prescription_ajouter'))
    
    return render_template('prescriptions/ajouter.html', patients=patients)

# ==================== RECHERCHE ====================

@app.route('/recherche', methods=['GET', 'POST'])
@login_required
def recherche_patients():
    from models import Patient
    
    patients = []
    search_term = ''
    
    if request.method == 'POST':
        search_term = request.form.get('search_term', '').strip()
        
        if search_term:
            query = Patient.query.filter(
                Patient.id_structure == current_user.id_structure,
                Patient.archived == False
            )
            
            # Filtrer selon le rôle médecin
            if current_user.role == 'medecin':
                query = query.filter(Patient.id_medecin_referent == current_user.id)
            
            # Recherche multi-champs
            patients = query.filter(
                db.or_(
                    Patient.nom.ilike(f'%{search_term}%'),
                    Patient.prenom.ilike(f'%{search_term}%'),
                    Patient.telephone.ilike(f'%{search_term}%'),
                    Patient.email.ilike(f'%{search_term}%')
                )
            ).limit(50).all()
    
    return render_template('recherche.html', patients=patients, search_term=search_term)

# ==================== MODIFIER PATIENT ====================

@app.route('/patient/<int:id>/modifier', methods=['GET', 'POST'])
@login_required
@has_permission('PATIENTS')
def patient_modifier(id):
    from models import Patient, Utilisateur
    from datetime import datetime
    
    patient = Patient.query.get_or_404(id)
    
    # Vérifier l'accès
    if current_user.role == 'medecin' and patient.id_medecin_referent != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('patients_list'))
    
    # Récupérer les médecins
    medecins = Utilisateur.query.filter_by(
        id_structure=current_user.id_structure if current_user.id_structure else patient.id_structure,
        role='medecin',
        actif=True
    ).all()
    
    if request.method == 'POST':
        # ═══════════════════════════════════════════
        # IDENTITÉ
        # ═══════════════════════════════════════════
        patient.nom = request.form.get('nom')
        patient.prenom = request.form.get('prenom')
        
        date_naissance = request.form.get('date_naissance')
        if date_naissance:
            patient.date_naissance = datetime.strptime(date_naissance, '%Y-%m-%d').date()
        else:
            patient.date_naissance = None
        
        patient.lieu_naissance = request.form.get('lieu_naissance')
        patient.sexe = request.form.get('sexe')
        patient.telephone = request.form.get('telephone')
        patient.email = request.form.get('email')
        patient.profession = request.form.get('profession')
        patient.code_postal = request.form.get('code_postal')
        patient.ville = request.form.get('ville')
        patient.adresse = request.form.get('adresse')
        
        # ═══════════════════════════════════════════
        # ASSURANCE PRINCIPALE
        # ═══════════════════════════════════════════
        patient.type_assurance = request.form.get('type_assurance')
        
        autre_assurance_nom = request.form.get('autre_assurance_nom')
        if patient.type_assurance == 'AUTRE_ASSURANCE':
            patient.autre_assurance_nom = autre_assurance_nom
        else:
            patient.autre_assurance_nom = None
        
        patient.num_assure = request.form.get('num_assure')
        
        # ═══════════════════════════════════════════
        # ASSURANCE 2
        # ═══════════════════════════════════════════
        patient.assurance2_nom = request.form.get('assurance2_nom')
        
        taux_assurance2 = request.form.get('taux_assurance2')
        patient.taux_assurance2 = float(taux_assurance2) if taux_assurance2 else None
        
        patient.numero_assure2 = request.form.get('numero_assure2')
        
        # ═══════════════════════════════════════════
        # TAUX DE PRISE EN CHARGE
        # ═══════════════════════════════════════════
        taux_prise_charge = request.form.get('taux_prise_charge')
        patient.taux_prise_charge = taux_prise_charge if taux_prise_charge else None
        
        # ═══════════════════════════════════════════
        # PERSONNE À PRÉVENIR
        # ═══════════════════════════════════════════
        patient.personne_a_prevenir_nom = request.form.get('personne_a_prevenir_nom')
        patient.personne_a_prevenir_telephone = request.form.get('personne_a_prevenir_telephone')
        patient.personne_a_prevenir_relation = request.form.get('personne_a_prevenir_relation')
        
        # ═══════════════════════════════════════════
        # INFORMATIONS MÉDICALES
        # ═══════════════════════════════════════════
        patient.groupe_sanguin = request.form.get('groupe_sanguin')
        patient.mutuelle = request.form.get('mutuelle')
        patient.medecin_traitant = request.form.get('medecin_traitant')
        
        # ═══════════════════════════════════════════
        # HABITUDES DE VIE
        # ═══════════════════════════════════════════
        patient.tabac = request.form.get('tabac')
        patient.alcool = request.form.get('alcool')
        patient.allaitement = request.form.get('allaitement') == 'on'
        patient.grossesse = request.form.get('grossesse') == 'on'
        
        # ═══════════════════════════════════════════
        # MÉDECIN RÉFÉRENT
        # ═══════════════════════════════════════════
        id_medecin_referent = request.form.get('id_medecin_referent')
        patient.id_medecin_referent = int(id_medecin_referent) if id_medecin_referent else None
        
        # ═══════════════════════════════════════════
        # NOTES
        # ═══════════════════════════════════════════
        patient.notes = request.form.get('notes')
        
        # ═══════════════════════════════════════════
        # ALLERGIES ET ANTÉCÉDENTS (si présents dans le formulaire)
        # ═══════════════════════════════════════════
        # Si tu as ces champs dans le formulaire, décommente :
        # patient.allergies = request.form.get('allergies')
        # patient.antecedents_medicaux = request.form.get('antecedents')
        
        db.session.commit()
        flash('✅ Patient modifié avec succès', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    
    return render_template('patients/modifier.html', patient=patient, medecins=medecins)

# ==================== CONSULTATION AVEC PATIENT SPECIFIQUE ====================

@app.route('/patient/<int:id>/consultation/ajouter', methods=['GET', 'POST'])
@login_required
def consultation_ajouter_avec_patient(id):
    from models import Patient, Consultation, Prescription, AnalyseDemande
    from datetime import datetime
    import json
    
    patient = Patient.query.get_or_404(id)
    
    if current_user.role == 'medecin' and patient.id_medecin_referent != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('patients_list'))
    
    if request.method == 'POST':
        # ═══════════════════════════════════════════
        # 1. RÉCUPÉRATION DES DONNÉES DU FORMULAIRE
        # ═══════════════════════════════════════════
        
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')

        # RÉCUPÉRATION DES CHAMPS HPI
        hpi_date_debut = request.form.get('hpi_date_debut')
        hpi_debut_type = request.form.get('hpi_debut_type')
        hpi_circonstances = request.form.get('hpi_circonstances')
        hpi_evolution = request.form.get('hpi_evolution')
        hpi_facteurs = request.form.get('hpi_facteurs')
        hpi_traitements = request.form.get('hpi_traitements')
        hpi_signes = request.form.get('hpi_signes')
        
        # ⭐ RÉCUPÉRER LES CHECKBOXES (MAIS PAS ENCORE LES APPLIQUER)
        hpi_fievre = request.form.get('hpi_fievre') == 'on'
        hpi_nausees = request.form.get('hpi_nausees') == 'on'
        hpi_douleur = request.form.get('hpi_douleur') == 'on'
        hpi_cephalées = request.form.get('hpi_cephalées') == 'on'
        hpi_vertiges = request.form.get('hpi_vertiges') == 'on'
        hpi_dyspnee = request.form.get('hpi_dyspnee') == 'on'
        
        hpi_trauma_mecanisme = request.form.get('hpi_trauma_mecanisme')
        hpi_trauma_heure = request.form.get('hpi_trauma_heure')
        hpi_trauma_pc = request.form.get('hpi_trauma_pc')
        hpi_trauma_description = request.form.get('hpi_trauma_description')
        
        hpi_morsure_type = request.form.get('hpi_morsure_type')
        hpi_morsure_espece = request.form.get('hpi_morsure_espece')
        hpi_morsure_siege = request.form.get('hpi_morsure_siege')
        hpi_morsure_signes = request.form.get('hpi_morsure_signes')
        
        hpi_intox_substance = request.form.get('hpi_intox_substance')
        hpi_intox_heure = request.form.get('hpi_intox_heure')
        hpi_intox_circonstances = request.form.get('hpi_intox_circonstances')
        
        hpi_autres_signes = request.form.get('hpi_autres_signes')
        hpi_autre_infos = request.form.get('hpi_autre_infos')
        
        hpi_complements_medecin = request.form.get('hpi_complements_medecin')
        histoire_maladie = request.form.get('histoire_maladie')

        # Constantes
        tension = request.form.get('tension')
        temperature = request.form.get('temperature')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        
        # Examens
        examens_cliniques = request.form.get('examens_cliniques')
        examens_biologie = request.form.get('examens_biologie')
        examens_imagerie = request.form.get('examens_imagerie')
        
        traitement = request.form.get('traitement')
        notes = request.form.get('notes')
        cim10 = request.form.get('cim10')
        
        arret_travail = request.form.get('arret_travail') == 'on'
        arret_jours = request.form.get('arret_jours')
        
        prochain_rdv = request.form.get('prochain_rdv')
        statut_medical = request.form.get('statut_medical')
        
        allergies = request.form.get('allergies')
        traitements_en_cours = request.form.get('traitements_en_cours')
        antecedents_medicaux = request.form.get('antecedents_medicaux')
        antecedents_chirurgicaux = request.form.get('antecedents_chirurgicaux')
        
        medicaments_prescrits = request.form.get('medicaments_prescrits')
        
        # ═══════════════════════════════════════════
        # ⭐ 2. RÉCUPÉRATION DE LA CONSULTATION TEMPORAIRE
        # ═══════════════════════════════════════════
        
        consultation = Consultation.query.filter_by(
            id_patient=patient.id,
            is_temporary=True
        ).first()
        
        if consultation:
            # ⭐ METTRE À JOUR LA CONSULTATION TEMPORAIRE
            print(f"✅ Consultation temporaire #{consultation.id} trouvée !")
            
            consultation.motif = motif
            consultation.diagnostic = diagnostic
            consultation.tension_arterielle = tension
            consultation.temperature_c = float(temperature) if temperature else None
            consultation.pulse_bpm = int(pouls) if pouls else None
            consultation.oxygene_saturation = int(saturation) if saturation else None
            consultation.poids_kg = float(poids) if poids else None
            consultation.taille_cm = float(taille) if taille else None
            consultation.imc = float(imc) if imc else None
            consultation.examens_cliniques = examens_cliniques
            consultation.examens_biologie = examens_biologie
            consultation.examens_imagerie = examens_imagerie
            consultation.traitement_prescrit = traitement
            consultation.notes_cliniques = notes
            consultation.cim10 = cim10
            consultation.arret_travail = arret_travail
            consultation.arret_jours = int(arret_jours) if arret_jours else None
            consultation.prochain_rdv = datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None
            consultation.allergies = allergies
            consultation.traitements_en_cours = traitements_en_cours
            consultation.antecedents_medicaux = antecedents_medicaux
            consultation.antecedents_chirurgicaux = antecedents_chirurgicaux
            
            # HPI - Champs texte
            consultation.hpi_date_debut = datetime.strptime(hpi_date_debut, '%Y-%m-%d').date() if hpi_date_debut else None
            consultation.hpi_debut_type = hpi_debut_type
            consultation.hpi_circonstances = hpi_circonstances
            consultation.hpi_evolution = hpi_evolution
            consultation.hpi_facteurs = hpi_facteurs
            consultation.hpi_traitements = hpi_traitements
            consultation.hpi_signes = hpi_signes
            consultation.hpi_trauma_mecanisme = hpi_trauma_mecanisme
            consultation.hpi_trauma_heure = datetime.fromisoformat(hpi_trauma_heure) if hpi_trauma_heure else None
            consultation.hpi_trauma_pc = hpi_trauma_pc
            consultation.hpi_trauma_description = hpi_trauma_description
            consultation.hpi_morsure_type = hpi_morsure_type
            consultation.hpi_morsure_espece = hpi_morsure_espece
            consultation.hpi_morsure_siege = hpi_morsure_siege
            consultation.hpi_morsure_signes = hpi_morsure_signes
            consultation.hpi_intox_substance = hpi_intox_substance
            consultation.hpi_intox_heure = datetime.fromisoformat(hpi_intox_heure) if hpi_intox_heure else None
            consultation.hpi_intox_circonstances = hpi_intox_circonstances
            consultation.hpi_autres_signes = hpi_autres_signes
            consultation.hpi_autre_infos = hpi_autre_infos
            consultation.hpi_complements_medecin = hpi_complements_medecin
            consultation.histoire_maladie = histoire_maladie
            
            # ⭐⭐⭐ AJOUTER LES SIGNES ASSOCIÉS ICI ⭐⭐⭐
            consultation.hpi_fievre = hpi_fievre
            consultation.hpi_nausees = hpi_nausees
            consultation.hpi_douleur = hpi_douleur
            consultation.hpi_cephalées = hpi_cephalées
            consultation.hpi_vertiges = hpi_vertiges
            consultation.hpi_dyspnee = hpi_dyspnee
            
            # ⭐ MARQUER COMME DÉFINITIVE
            consultation.is_temporary = False
            consultation.statut = 'terminee'
            consultation.id_medecin = current_user.id if current_user.role == 'medecin' else None
            consultation.date_consultation = datetime.utcnow()
            
        else:
            # ⭐ PAS DE CONSULTATION TEMPORAIRE : EN CRÉER UNE
            print(f"⚠️ Aucune consultation temporaire trouvée pour patient #{patient.id}")
            
            consultation = Consultation(
                id_patient=patient.id,
                id_medecin=current_user.id if current_user.role == 'medecin' else None,
                motif=motif,
                diagnostic=diagnostic,
                tension_arterielle=tension,
                temperature_c=float(temperature) if temperature else None,
                pulse_bpm=int(pouls) if pouls else None,
                oxygene_saturation=int(saturation) if saturation else None,
                poids_kg=float(poids) if poids else None,
                taille_cm=float(taille) if taille else None,
                imc=float(imc) if imc else None,
                examens_cliniques=examens_cliniques,
                examens_biologie=examens_biologie,
                examens_imagerie=examens_imagerie,
                traitement_prescrit=traitement,
                notes_cliniques=notes,
                cim10=cim10,
                arret_travail=arret_travail,
                arret_jours=int(arret_jours) if arret_jours else None,
                prochain_rdv=datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None,
                allergies=allergies,
                traitements_en_cours=traitements_en_cours,
                antecedents_medicaux=antecedents_medicaux,
                antecedents_chirurgicaux=antecedents_chirurgicaux,
                hpi_date_debut=datetime.strptime(hpi_date_debut, '%Y-%m-%d').date() if hpi_date_debut else None,
                hpi_debut_type=hpi_debut_type,
                hpi_circonstances=hpi_circonstances,
                hpi_evolution=hpi_evolution,
                hpi_facteurs=hpi_facteurs,
                hpi_traitements=hpi_traitements,
                hpi_signes=hpi_signes,
                hpi_trauma_mecanisme=hpi_trauma_mecanisme,
                hpi_trauma_heure=datetime.fromisoformat(hpi_trauma_heure) if hpi_trauma_heure else None,
                hpi_trauma_pc=hpi_trauma_pc,
                hpi_trauma_description=hpi_trauma_description,
                hpi_morsure_type=hpi_morsure_type,
                hpi_morsure_espece=hpi_morsure_espece,
                hpi_morsure_siege=hpi_morsure_siege,
                hpi_morsure_signes=hpi_morsure_signes,
                hpi_intox_substance=hpi_intox_substance,
                hpi_intox_heure=datetime.fromisoformat(hpi_intox_heure) if hpi_intox_heure else None,
                hpi_intox_circonstances=hpi_intox_circonstances,
                hpi_autres_signes=hpi_autres_signes,
                hpi_autre_infos=hpi_autre_infos,
                hpi_complements_medecin=hpi_complements_medecin,
                histoire_maladie=histoire_maladie,
                date_consultation=datetime.utcnow(),
                is_temporary=False,
                # ⭐⭐⭐ AJOUTER LES SIGNES ASSOCIÉS ICI ⭐⭐⭐
                hpi_fievre=hpi_fievre,
                hpi_nausees=hpi_nausees,
                hpi_douleur=hpi_douleur,
                hpi_cephalées=hpi_cephalées,
                hpi_vertiges=hpi_vertiges,
                hpi_dyspnee=hpi_dyspnee
            )
            db.session.add(consultation)
            db.session.flush()
            print(f"✅ Nouvelle consultation #{consultation.id} créée")
        
        # ═══════════════════════════════════════════
        # 3. CRÉATION DES ANALYSES
        # ═══════════════════════════════════════════
        
        if examens_biologie:
            for ligne in examens_biologie.split('\n'):
                nom = ligne.strip()
                if nom:
                    analyse = AnalyseDemande(
                        consultation_id=consultation.id,
                        patient_id=consultation.id_patient,
                        structure_id=current_user.id_structure,
                        type_analyse='BIOLOGIE',
                        nom_analyse=nom,
                        prescrit_par=current_user.id,
                        statut='EN_ATTENTE'
                    )
                    db.session.add(analyse)
        
        if examens_imagerie:
            for ligne in examens_imagerie.split('\n'):
                nom = ligne.strip()
                if nom:
                    analyse = AnalyseDemande(
                        consultation_id=consultation.id,
                        patient_id=consultation.id_patient,
                        structure_id=current_user.id_structure,
                        type_analyse='IMAGERIE',
                        nom_analyse=nom,
                        prescrit_par=current_user.id,
                        statut='EN_ATTENTE'
                    )
                    db.session.add(analyse)
        
        # ═══════════════════════════════════════════
        # 4. CRÉATION DES PRESCRIPTIONS
        # ═══════════════════════════════════════════
        
        prescriptions_creees = 0
        
        if medicaments_prescrits:
            try:
                meds_data = json.loads(medicaments_prescrits)
                print(f"📦 Données reçues: {medicaments_prescrits}")

                for med in meds_data:
                    print(f"   Médicament: {med.get('nom')}, Durée: {med.get('duree')}")
                    prescription = Prescription(
                        id_patient=patient.id,
                        id_consultation=consultation.id,
                        id_medecin=current_user.id,
                        medicament=med.get('nom', ''),
                        dosage=med.get('dosage', ''),
                        forme=med.get('forme', ''),
                        quantite=str(med.get('quantite', 1)),
                        duree_jours=med.get('duree', 7),
                        frequence=med.get('posologie', ''),
                        instructions=med.get('instructions', ''),
                        renouvelable=med.get('renouvelable', False),
                        type_prescription='medicament',
                        prescripteur=f"{current_user.prenom} {current_user.nom}",
                        statut='active',
                        date_prescription=datetime.utcnow(),
                        notes=med.get('notes', ''),
                        source_id=med.get('source_id'),
                        stock_disponible=med.get('stock')
                    )
                    db.session.add(prescription)
                    prescriptions_creees += 1
                    
                print(f"✅ {len(meds_data)} prescription(s) médicamenteuse(s) enregistrée(s)")
                
            except Exception as e:
                print(f"❌ Erreur sauvegarde prescriptions médicaments: {e}")
                import traceback
                traceback.print_exc()
        
        if examens_biologie:
            for ligne in examens_biologie.split('\n'):
                nom = ligne.strip()
                if nom:
                    prescription = Prescription(
                        id_patient=patient.id,
                        id_consultation=consultation.id,
                        id_medecin=current_user.id,
                        medicament=nom,
                        type_prescription='acte',
                        prescripteur=f"{current_user.prenom} {current_user.nom}",
                        statut='active',
                        date_prescription=datetime.utcnow()
                    )
                    db.session.add(prescription)
                    prescriptions_creees += 1
                    print(f"📋 Prescription d'acte (biologie) ajoutée: {nom}")
        
        if examens_imagerie:
            for ligne in examens_imagerie.split('\n'):
                nom = ligne.strip()
                if nom:
                    prescription = Prescription(
                        id_patient=patient.id,
                        id_consultation=consultation.id,
                        id_medecin=current_user.id,
                        medicament=nom,
                        type_prescription='acte',
                        prescripteur=f"{current_user.prenom} {current_user.nom}",
                        statut='active',
                        date_prescription=datetime.utcnow()
                    )
                    db.session.add(prescription)
                    prescriptions_creees += 1
                    print(f"📋 Prescription d'acte (imagerie) ajoutée: {nom}")
        
        # ═══════════════════════════════════════════
        # 5. MISE À JOUR DU PATIENT
        # ═══════════════════════════════════════════
        
        if temperature:
            patient.temperature_c = float(temperature)
        if tension:
            patient.tension_arterielle = tension
        if pouls:
            patient.pulse_bpm = int(pouls)
        if saturation:
            patient.oxygene_saturation = int(saturation)
        if poids:
            patient.poids_kg = float(poids)
        if taille:
            patient.taille_cm = float(taille)
        if imc:
            patient.imc = float(imc)
        
        patient.date_derniere_consultation = datetime.utcnow()
        patient.id_medecin_referent = current_user.id  # ⭐ LE MÉDECIN QUI CONSULTE DEVIENT RÉFÉRENT
        
        if statut_medical:
            patient.statut_medical = statut_medical
            if statut_medical == 'GUERI':
                patient.date_guerison = datetime.utcnow()
        elif patient.statut_medical == 'PREMIERE_VISITE':
            patient.statut_medical = 'EN_TRAITEMENT'
        
        # ═══════════════════════════════════════════
        # 6. COMMIT FINAL
        # ═══════════════════════════════════════════
        
        db.session.commit()
        
        if prescriptions_creees > 0:
            try:
                from tasks import sync_prescriptions_to_ghp
                result = sync_prescriptions_to_ghp()
                if result.get('success'):
                    print(f"✅ {result.get('message')}")
                else:
                    print(f"⚠️ {result.get('message')}")
            except Exception as e:
                print(f"⚠️ Erreur sync auto: {e}")
        
        flash(f'Consultation pour {patient.prenom} {patient.nom} enregistrée avec succès', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    
    empty_consultation = Consultation()

    return render_template('consultations/ajouter_avec_patient.html', patient=patient, consultation=empty_consultation)

# ==================== STATISTIQUES ====================

@app.route('/statistiques')
@login_required
def statistiques():
    from models import Patient, Consultation, Utilisateur, Hospitalisation, ConstanteVitale, AnalyseDemande, HospitalisationInfirmier
    from datetime import datetime, timedelta
    from sqlalchemy import func, extract
    
    # Récupérer les filtres
    date_debut = request.args.get('date_debut', '')
    date_fin = request.args.get('date_fin', '')
    periode = request.args.get('periode', 'mois')
    medecin_id = request.args.get('medecin_id', '')
    type_assurance = request.args.get('type_assurance', '')
    
    # ========== Construction de la requête de base ==========
    base_query = Consultation.query.join(Patient, Consultation.id_patient == Patient.id)
    
    # Filtrer selon le rôle
    if current_user.role == 'medecin':
        base_query = base_query.filter(Consultation.id_medecin == current_user.id)
    elif current_user.role == 'admin_structure':
        base_query = base_query.filter(Patient.id_structure == current_user.id_structure)
    
    # Application des filtres de date
    if date_debut:
        base_query = base_query.filter(Consultation.date_consultation >= datetime.strptime(date_debut, '%Y-%m-%d'))
    if date_fin:
        base_query = base_query.filter(Consultation.date_consultation <= datetime.strptime(date_fin, '%Y-%m-%d') + timedelta(days=1))
    
    # Filtre par médecin
    if medecin_id and medecin_id != '':
        base_query = base_query.filter(Consultation.id_medecin == int(medecin_id))
    
    # Filtre par type d'assurance
    if type_assurance and type_assurance != '':
        base_query = base_query.filter(Patient.type_assurance == type_assurance)
    
    # ========== KPI principaux ==========
    total_consultations = base_query.count()
    total_patients = db.session.query(Patient).filter(Patient.id.in_(
        base_query.with_entities(Consultation.id_patient).distinct()
    )).count()
    
    # ========== Patients par période ==========
    patients_par_periode = []
    
    if periode == 'jour':
        periodes = base_query.with_entities(
            func.date(Consultation.date_consultation).label('jour'),
            func.count(func.distinct(Consultation.id_patient)).label('nb')
        ).group_by('jour').order_by('jour').limit(30).all()
        patients_par_periode = [{'periode': p.jour.strftime('%d/%m/%Y'), 'nb': p.nb} for p in periodes]
    elif periode == 'semaine':
        periodes = base_query.with_entities(
            extract('year', Consultation.date_consultation).label('annee'),
            extract('week', Consultation.date_consultation).label('semaine'),
            func.count(func.distinct(Consultation.id_patient)).label('nb')
        ).group_by('annee', 'semaine').order_by('annee', 'semaine').limit(30).all()
        patients_par_periode = [{'periode': f"S{int(p.semaine)}-{int(p.annee)}", 'nb': p.nb} for p in periodes]
    elif periode == 'mois':
        periodes = base_query.with_entities(
            func.to_char(Consultation.date_consultation, 'YYYY-MM').label('mois'),
            func.count(func.distinct(Consultation.id_patient)).label('nb')
        ).group_by('mois').order_by('mois').limit(12).all()
        patients_par_periode = [{'periode': p.mois, 'nb': p.nb} for p in periodes]
    else:
        periodes = base_query.with_entities(
            extract('year', Consultation.date_consultation).label('annee'),
            func.count(func.distinct(Consultation.id_patient)).label('nb')
        ).group_by('annee').order_by('annee').all()
        patients_par_periode = [{'periode': str(int(p.annee)), 'nb': p.nb} for p in periodes]
    
    # ========== Top pathologies ==========
    top_pathologies = base_query.with_entities(
        Consultation.diagnostic,
        func.count(Consultation.id).label('total')
    ).filter(
        Consultation.diagnostic.isnot(None),
        Consultation.diagnostic != '',
        Consultation.diagnostic != '-'
    ).group_by(Consultation.diagnostic).order_by(func.count(Consultation.id).desc()).limit(10).all()
    
    # ========== Répartition assurances ==========
    assurances = db.session.query(
        Patient.type_assurance,
        func.count(Patient.id).label('total')
    ).join(Consultation, Patient.id == Consultation.id_patient).filter(
        Consultation.id.in_(base_query.with_entities(Consultation.id))
    ).group_by(Patient.type_assurance).all()
    
    # ========== 📊 PERFORMANCE DES MÉDECINS ==========
    if current_user.role == 'admin_structure':
        stats_medecins = db.session.query(
            Utilisateur.id,
            Utilisateur.nom,
            Utilisateur.prenom,
            func.count(Consultation.id).label('nb_consultations'),
            func.count(func.distinct(Consultation.id_patient)).label('nb_patients')
        ).join(Consultation, Utilisateur.id == Consultation.id_medecin).filter(
            Consultation.id.in_(base_query.with_entities(Consultation.id))
        ).group_by(Utilisateur.id).all()
    else:
        stats_medecins = []
    
    # ========== 🩺 PERFORMANCE DES INFIRMIERS ==========
    stats_infirmiers = []
    if current_user.role == 'admin_structure':
        infirmiers = Utilisateur.query.filter_by(
            id_structure=current_user.id_structure,
            role='infirmier',
            actif=True
        ).all()
        
        for inf in infirmiers:
            nb_constantes = ConstanteVitale.query.filter_by(infirmier_id=inf.id).count()
            nb_hospitalisations = HospitalisationInfirmier.query.filter_by(
                infirmier_id=inf.id,
                actif=True
            ).count()
            derniere_constante = ConstanteVitale.query.filter_by(
                infirmier_id=inf.id
            ).order_by(ConstanteVitale.date_prise.desc()).first()
            
            stats_infirmiers.append({
                'id': inf.id,
                'nom': inf.nom,
                'prenom': inf.prenom,
                'nb_constantes': nb_constantes,
                'nb_hospitalisations': nb_hospitalisations,
                'derniere_constante': derniere_constante.date_prise if derniere_constante else None
            })
        
        stats_infirmiers.sort(key=lambda x: x['nb_constantes'], reverse=True)
    
    # ========== 📊 STATISTIQUES HOSPITALISATIONS ==========
    stats_hospitalisations = {}
    if current_user.role == 'admin_structure' or current_user.role == 'medecin':
        structure_id = current_user.id_structure if current_user.id_structure else 1
        
        # Récupérer les IDs des patients de la structure
        patient_ids = db.session.query(Patient.id).filter(
            Patient.id_structure == structure_id
        ).all()
        patient_ids = [p[0] for p in patient_ids]
        
        if patient_ids:
            total_hosp = Hospitalisation.query.filter(
                Hospitalisation.patient_id.in_(patient_ids)
            ).count()
            
            hosp_actives = Hospitalisation.query.filter(
                Hospitalisation.patient_id.in_(patient_ids),
                Hospitalisation.statut == 'actif'
            ).count()
            
            hosp_par_service = db.session.query(
                Hospitalisation.service,
                func.count(Hospitalisation.id).label('total')
            ).filter(
                Hospitalisation.patient_id.in_(patient_ids)
            ).group_by(Hospitalisation.service).all()
            
            stats_hospitalisations = {
                'total': total_hosp,
                'actives': hosp_actives,
                'par_service': [{'service': s[0], 'total': s[1]} for s in hosp_par_service]
            }
        else:
            stats_hospitalisations = {'total': 0, 'actives': 0, 'par_service': []}
    
    # ========== 📊 STATISTIQUES ANALYSES ==========
    stats_analyses = {}
    if current_user.role == 'admin_structure' or current_user.role == 'medecin' or current_user.role == 'laborantin':
        structure_id = current_user.id_structure if current_user.id_structure else 1
        
        # Récupérer les IDs des patients de la structure
        patient_ids = db.session.query(Patient.id).filter(
            Patient.id_structure == structure_id
        ).all()
        patient_ids = [p[0] for p in patient_ids]
        
        if patient_ids:
            total_analyses = AnalyseDemande.query.filter(
                AnalyseDemande.patient_id.in_(patient_ids)
            ).count()
            
            analyses_par_statut = db.session.query(
                AnalyseDemande.statut,
                func.count(AnalyseDemande.id).label('total')
            ).filter(
                AnalyseDemande.patient_id.in_(patient_ids)
            ).group_by(AnalyseDemande.statut).all()
            
            analyses_par_type = db.session.query(
                AnalyseDemande.type_analyse,
                func.count(AnalyseDemande.id).label('total')
            ).filter(
                AnalyseDemande.patient_id.in_(patient_ids)
            ).group_by(AnalyseDemande.type_analyse).all()
            
            stats_analyses = {
                'total': total_analyses,
                'par_statut': [{'statut': s[0], 'total': s[1]} for s in analyses_par_statut],
                'par_type': [{'type': t[0], 'total': t[1]} for t in analyses_par_type]
            }
        else:
            stats_analyses = {'total': 0, 'par_statut': [], 'par_type': []}
    
    # ========== Évolution quotidienne ==========
    evolution = base_query.with_entities(
        func.date_trunc('day', Consultation.date_consultation).label('date'),
        func.count(Consultation.id).label('total')
    ).group_by('date').order_by('date').limit(60).all()
    
    evolution_labels = [e.date.strftime('%d/%m') if e.date else '-' for e in evolution]
    evolution_data = [e.total for e in evolution]
    
    # Liste des médecins pour le filtre (admin structure)
    if current_user.role == 'admin_structure':
        medecins = Utilisateur.query.filter_by(id_structure=current_user.id_structure, role='medecin', actif=True).all()
    else:
        medecins = []
    
    types_assurance = ['AMU-CNSS', 'AMU-INAM', 'AUTRE_ASSURANCE', 'NON_ASSURÉ']
    
    return render_template('statistiques.html',
                         total_consultations=total_consultations,
                         total_patients=total_patients,
                         patients_par_periode=patients_par_periode,
                         top_pathologies=top_pathologies,
                         assurances=assurances,
                         stats_medecins=stats_medecins,
                         stats_infirmiers=stats_infirmiers,
                         stats_hospitalisations=stats_hospitalisations,
                         stats_analyses=stats_analyses,
                         medecins=medecins,
                         types_assurance=types_assurance,
                         evolution_labels=evolution_labels,
                         evolution_data=evolution_data,
                         periode=periode,
                         date_debut=date_debut,
                         date_fin=date_fin,
                         medecin_id=medecin_id,
                         type_assurance=type_assurance)

@app.route('/statistiques/export')
@login_required
@has_permission('STATISTIQUES')
def export_statistiques_csv():
    import csv
    from io import StringIO
    from flask import Response
    
    # Récupérer les données avec les mêmes filtres
    # (même logique que la route statistiques)
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Patient', 'Médecin', 'Motif', 'Diagnostic', 'Assurance'])
    
    # Ajouter les lignes...
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=statistiques.csv'})

@app.route('/admin/sync-sheets', methods=['POST'])
@login_required
def admin_sync_sheets():
    """Synchronisation manuelle vers Google Sheets (Super Admin uniquement)"""
    from flask import jsonify
    import traceback
    
    if current_user.role != 'super_admin':
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    
    try:
        from sheets_sync import GoogleSheetsSync
        SPREADSHEET_ID = "1nCUArOaWgXVFszjEhH1GqNJXGCV7cF754W87vXvQ-lQ"
        syncer = GoogleSheetsSync(SPREADSHEET_ID)
        syncer.sync_all()
        return jsonify({'success': True, 'message': '✅ Synchronisation terminée vers Google Sheets'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

# ==================== MESSAGERIE INTERNE ====================

@app.route('/messages')
@login_required
def messages_liste():
    from models import Message
    
    # Messages reçus
    messages_recus = Message.query.filter_by(id_destinataire=current_user.id).order_by(Message.date_envoi.desc()).all()
    
    # Messages envoyés
    messages_envoyes = Message.query.filter_by(id_expediteur=current_user.id).order_by(Message.date_envoi.desc()).all()
    
    # Nombre de messages non lus
    non_lus = Message.query.filter_by(id_destinataire=current_user.id, lu=False).count()
    
    return render_template('messages/liste.html', 
                         messages_recus=messages_recus,
                         messages_envoyes=messages_envoyes,
                         non_lus=non_lus)


@app.route('/messages/nouveau', methods=['GET', 'POST'])
@login_required
def messages_nouveau():
    from models import Message, Utilisateur
    
    # Récupérer les destinataires possibles (même structure)
    if current_user.role == 'super_admin':
        destinataires = Utilisateur.query.filter(Utilisateur.id != current_user.id).all()
    else:
        destinataires = Utilisateur.query.filter(
            Utilisateur.id_structure == current_user.id_structure,
            Utilisateur.id != current_user.id,
            Utilisateur.actif == True
        ).all()
    
    if request.method == 'POST':
        id_destinataire = request.form.get('id_destinataire')
        sujet = request.form.get('sujet')
        contenu = request.form.get('contenu')
        
        if not id_destinataire or not sujet or not contenu:
            flash('Tous les champs sont obligatoires', 'danger')
            return redirect(url_for('messages_nouveau'))
        
        message = Message(
            id_expediteur=current_user.id,
            id_destinataire=int(id_destinataire),
            id_structure=current_user.id_structure if current_user.id_structure else 1,
            sujet=sujet,
            contenu=contenu
        )
        
        db.session.add(message)
        db.session.commit()
        
        flash('Message envoyé avec succès', 'success')
        return redirect(url_for('messages_liste'))
    
    return render_template('messages/nouveau.html', destinataires=destinataires)


@app.route('/messages/lire/<int:id>')
@login_required
def messages_lire(id):
    from models import Message
    from datetime import datetime
    
    message = Message.query.get_or_404(id)
    
    # Vérifier que l'utilisateur est concerné
    if message.id_destinataire != current_user.id and message.id_expediteur != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('messages_liste'))
    
    # Marquer comme lu si c'est le destinataire
    if message.id_destinataire == current_user.id and not message.lu:
        message.lu = True
        message.lu_at = datetime.utcnow()
        db.session.commit()
    
    return render_template('messages/lire.html', message=message)


@app.route('/messages/supprimer/<int:id>')
@login_required
def messages_supprimer(id):
    from models import Message
    
    message = Message.query.get_or_404(id)
    
    # Vérifier que l'utilisateur est l'expéditeur ou le destinataire
    if message.id_expediteur != current_user.id and message.id_destinataire != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('messages_liste'))
    
    db.session.delete(message)
    db.session.commit()
    
    flash('Message supprimé', 'success')
    return redirect(url_for('messages_liste'))


# Démarrer le scheduler au lancement de l'application
start_scheduler()

# Arrêter le scheduler proprement à la fermeture
import atexit
atexit.register(stop_scheduler)

@app.route('/admin/profil', methods=['GET', 'POST'])
@login_required
def admin_profil():
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        ancien_mdp = request.form.get('ancien_mdp')
        nouveau_mdp = request.form.get('nouveau_mdp')
        confirmer_mdp = request.form.get('confirmer_mdp')
        
        if not current_user.check_password(ancien_mdp):
            flash('Ancien mot de passe incorrect', 'danger')
            return redirect(url_for('admin_profil'))
        
        if nouveau_mdp != confirmer_mdp:
            flash('Les nouveaux mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('admin_profil'))
        
        # Validation de la complexité
        import re
        if len(nouveau_mdp) < 8:
            flash('Minimum 8 caractères', 'danger')
        elif not re.search(r"[A-Z]", nouveau_mdp):
            flash('Au moins 1 majuscule', 'danger')
        elif not re.search(r"[a-z]", nouveau_mdp):
            flash('Au moins 1 minuscule', 'danger')
        elif not re.search(r"[0-9]", nouveau_mdp):
            flash('Au moins 1 chiffre', 'danger')
        elif not re.search(r"[!@#$%^&*(),.?\":{}|<>]", nouveau_mdp):
            flash('Au moins 1 symbole', 'danger')
        else:
            current_user.set_password(nouveau_mdp)
            db.session.commit()
            flash('Mot de passe modifié avec succès', 'success')
            return redirect(url_for('admin_profil'))
    
    return render_template('admin/profil.html')

@app.route('/admin/nouveau-super-admin', methods=['GET', 'POST'])
@login_required
def admin_nouveau_super_admin():
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur
    from datetime import datetime
    
    if request.method == 'POST':
        email = request.form.get('email')
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        password = request.form.get('password')
        
        # Vérifier si l'email existe déjà
        existing = Utilisateur.query.filter_by(email=email).first()
        if existing:
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('admin_nouveau_super_admin'))
        
        # Créer le Super Admin
        new_admin = Utilisateur(
            email=email,
            nom=nom,
            prenom=prenom,
            role='super_admin',
            actif=True
        )
        new_admin.set_password(password)
        db.session.add(new_admin)
        db.session.commit()
        
        flash(f'Super Admin {prenom} {nom} créé avec succès', 'success')
        return redirect(url_for('admin_structures'))
    
    return render_template('admin/nouveau_super_admin.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    from models import Utilisateur
    from datetime import datetime
    
    user = Utilisateur.query.filter_by(reset_token=token).first()
    
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        flash('Le lien de réinitialisation est invalide ou a expiré.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash('Les mots de passe ne correspondent pas.', 'danger')
        else:
            user.set_password(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            flash('Mot de passe réinitialisé avec succès.', 'success')
            return redirect(url_for('login'))
    
    return render_template('reset_password_token.html', token=token)

@app.route('/admin/structure/<int:id>/desactivate', methods=['GET', 'POST'])
@login_required
def admin_desactivate_structure(id):
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Structure
    structure = Structure.query.get_or_404(id)
    
    if request.method == 'POST':
        structure.statut = 'desactive'
        db.session.commit()
        flash(f'Structure {structure.nom} désactivée avec succès', 'success')
        return redirect(url_for('admin_structures'))
    
    return render_template('admin/desactiver_structure.html', structure=structure)

@app.route('/admin/structure/<int:id>/delete', methods=['GET', 'POST'])
@login_required
def admin_delete_structure(id):
    if current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Structure, Utilisateur, Patient, Consultation, Prescription
    
    structure = Structure.query.get_or_404(id)
    
    if request.method == 'POST':
        # Compter les données avant suppression
        nb_users = Utilisateur.query.filter_by(id_structure=id).count()
        nb_patients = Patient.query.filter_by(id_structure=id).count()
        nb_consultations = Consultation.query.join(Patient).filter(Patient.id_structure == id).count()
        nb_prescriptions = Prescription.query.join(Patient).filter(Patient.id_structure == id).count()
        
        # Supprimer en cascade
        # 1. Supprimer les prescriptions
        Prescription.query.filter(Prescription.id_patient.in_(
            db.session.query(Patient.id).filter_by(id_structure=id)
        )).delete(synchronize_session=False)
        
        # 2. Supprimer les consultations
        Consultation.query.filter(Consultation.id_patient.in_(
            db.session.query(Patient.id).filter_by(id_structure=id)
        )).delete(synchronize_session=False)
        
        # 3. Supprimer les patients
        Patient.query.filter_by(id_structure=id).delete()
        
        # 4. Supprimer les utilisateurs
        Utilisateur.query.filter_by(id_structure=id).delete()
        
        # 5. Supprimer la structure
        db.session.delete(structure)
        db.session.commit()
        
        flash(f'Structure {structure.nom} supprimée avec succès. Données supprimées : {nb_users} utilisateurs, {nb_patients} patients, {nb_consultations} consultations, {nb_prescriptions} prescriptions.', 'success')
        return redirect(url_for('admin_structures'))
    
    return render_template('admin/supprimer_structure.html', structure=structure)

# ==================== HOSPITALISATIONS ====================

@app.route('/hospitalisations')
@login_required
@has_permission('HOSPITALISATION')
def liste_hospitalisations():
    """Liste des hospitalisations"""
    from models import Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, Patient
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier', 'secretaire', 'super_admin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    statut = request.args.get('statut', 'tous')
    service = request.args.get('service', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Base de la requête
    if current_user.role == 'super_admin':
        query = Hospitalisation.query
    else:
        query = Hospitalisation.query.join(Patient).filter(Patient.id_structure == current_user.id_structure)
    
    # Filtrer par statut
    if statut == 'actif':
        query = query.filter(Hospitalisation.statut == 'actif')
    elif statut == 'sorti':
        query = query.filter(Hospitalisation.statut == 'sorti')
    elif statut == 'transfere':
        query = query.filter(Hospitalisation.statut == 'transfere')
    
    if service:
        query = query.filter(Hospitalisation.service.ilike(f'%{service}%'))
    
    # Filtrer selon le rôle
    if current_user.role == 'medecin':
        query = query.join(HospitalisationMedecin).filter(
            HospitalisationMedecin.medecin_id == current_user.id,
            HospitalisationMedecin.actif == True
        )
    elif current_user.role == 'infirmier':
        query = query.join(HospitalisationInfirmier).filter(
            HospitalisationInfirmier.infirmier_id == current_user.id,
            HospitalisationInfirmier.actif == True
        )
    
    hospitalisations = query.order_by(Hospitalisation.date_debut.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Liste des services
    if current_user.role == 'super_admin':
        services_query = db.session.query(Hospitalisation.service).distinct()
    else:
        services_query = db.session.query(Hospitalisation.service).join(Patient).filter(
            Patient.id_structure == current_user.id_structure
        ).distinct()
    services = [s[0] for s in services_query.all() if s[0]]
    
    return render_template('hospitalisations/liste.html',
                         hospitalisations=hospitalisations,
                         statut_actuel=statut,
                         services=services)


@app.route('/hospitalisation/nouvelle', methods=['GET', 'POST'])
@login_required
def nouvelle_hospitalisation():
    """Créer une nouvelle hospitalisation avec note d'admission structurée"""
    from models import Patient, Utilisateur, Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, Service, Salle, Lit, NoteAdmission
    
    if current_user.role not in ['admin_structure', 'medecin', 'secretaire']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # ============================================================
        # 1. RÉCUPÉRATION DES DONNÉES
        # ============================================================
        patient_id = request.form.get('patient_id')
        motif = request.form.get('motif')
        service = request.form.get('service')
        chambre = request.form.get('chambre')
        lit = request.form.get('lit')  # ⭐ Gardé pour compatibilité
        lit_id = request.form.get('lit_id', type=int)
        medecins_ids = request.form.getlist('medecins_ids')
        infirmiers_ids = request.form.getlist('infirmiers_ids')
        
        # ===== NOTE D'ADMISSION =====
        note_motif = request.form.get('note_motif', '').strip()
        note_contexte = request.form.get('note_contexte', '').strip()
        note_examen_clinique = request.form.get('note_examen_clinique', '').strip()
        note_diagnostic = request.form.get('note_diagnostic', '').strip()
        note_examens = request.form.get('note_examens', '').strip()
        note_traitement = request.form.get('note_traitement', '').strip()
        note_evolution_prevue = request.form.get('note_evolution_prevue', '').strip()
        note_conclusion = request.form.get('note_conclusion', '').strip()
        note_constantes = request.form.get('note_constantes', '').strip()
        
        # ============================================================
        # 2. VALIDATIONS
        # ============================================================
        
        if not patient_id:
            flash('Veuillez sélectionner un patient.', 'danger')
            return redirect(url_for('nouvelle_hospitalisation'))
        
        if not motif:
            flash('Le motif d\'hospitalisation est obligatoire.', 'danger')
            return redirect(url_for('nouvelle_hospitalisation'))
        
        if not service:
            flash('Le service est obligatoire.', 'danger')
            return redirect(url_for('nouvelle_hospitalisation'))
        
        # Validation de la note
        champs_obligatoires = {
            'Motif d\'hospitalisation': note_motif,
            'Contexte et antécédents': note_contexte,
            'Examen clinique initial': note_examen_clinique,
            'Diagnostic présumé': note_diagnostic,
            'Traitement initial': note_traitement,
            'Conclusion du médecin référent': note_conclusion
        }
        
        champs_manquants = []
        for nom, valeur in champs_obligatoires.items():
            if not valeur:
                champs_manquants.append(nom)
        
        if champs_manquants:
            flash(f'La note d\'admission est incomplète. Champs obligatoires : {", ".join(champs_manquants)}', 'danger')
            return redirect(url_for('nouvelle_hospitalisation'))
        
        # ============================================================
        # 3. CRÉATION
        # ============================================================
        try:
            # --- Création de l'hospitalisation ---
            hospitalisation = Hospitalisation(
                patient_id=int(patient_id),
                motif=motif,
                service=service,
                chambre=chambre,
                lit=lit,  # ⭐ Gardé comme avant
                notes_admission=None,
                statut='actif',
                created_by=current_user.id,
                created_at=datetime.utcnow()
            )
            db.session.add(hospitalisation)
            db.session.flush()
            
            # --- Assigner le lit ---
            if lit_id:
                lit_obj = Lit.query.get(lit_id)  # ⭐ Comme avant
                if lit_obj and lit_obj.statut == 'disponible':
                    lit_obj.occuper(hospitalisation.id)
                    hospitalisation.lit_id = lit_obj.id
                    hospitalisation.chambre = lit_obj.salle.nom
                    hospitalisation.lit = lit_obj.numero  # ⭐ Comme avant
            
            # --- Assigner les médecins ---
            for medecin_id in medecins_ids:
                hm = HospitalisationMedecin(
                    hospitalisation_id=hospitalisation.id,
                    medecin_id=int(medecin_id),
                    date_assignation=datetime.utcnow(),
                    actif=True
                )
                db.session.add(hm)
            
            # --- Assigner les infirmiers ---
            for infirmier_id in infirmiers_ids:
                hi = HospitalisationInfirmier(
                    hospitalisation_id=hospitalisation.id,
                    infirmier_id=int(infirmier_id),
                    date_assignation=datetime.utcnow(),
                    actif=True
                )
                db.session.add(hi)
            
            # --- Création de la note d'admission ---
            note = NoteAdmission(
                hospitalisation_id=hospitalisation.id,
                version=1,
                est_initial=True,
                est_verrouillee=True,
                motif_admission=note_motif,
                contexte_admission=note_contexte,
                examen_clinique_admission=note_examen_clinique,
                diagnostic_admission=note_diagnostic,
                examens_admission=note_examens if note_examens else None,
                traitement_admission=note_traitement,
                evolution_prevue=note_evolution_prevue if note_evolution_prevue else None,
                conclusion_admission=note_conclusion,
                constantes_admission=note_constantes if note_constantes else None,
                redige_par=current_user.id,
                date_redaction=datetime.utcnow(),
                valide_par=current_user.id,
                date_validation=datetime.utcnow()
            )
            db.session.add(note)
            db.session.flush()
            
            # --- Lier la note active ---
            hospitalisation.note_admission_active_id = note.id
            
            db.session.commit()
            
            flash(f'✅ Hospitalisation de {hospitalisation.patient.nom} {hospitalisation.patient.prenom} créée avec succès !', 'success')
            flash('📋 Note d\'admission verrouillée - Elle servira de référence pour le suivi.', 'info')
            
            return redirect(url_for('detail_hospitalisation', id=hospitalisation.id))
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
            flash(f'❌ Erreur lors de l\'enregistrement : {str(e)}', 'danger')
            return redirect(url_for('nouvelle_hospitalisation'))
    
    # ============================================================
    # GET : Afficher le formulaire
    # ============================================================
    if current_user.role == 'super_admin':
        patients = Patient.query.filter_by(archived=False).all()
        medecins = Utilisateur.query.filter_by(role='medecin', actif=True).all()
        infirmiers = Utilisateur.query.filter_by(role='infirmier', actif=True).all()
    else:
        patients = Patient.query.filter_by(
            id_structure=current_user.id_structure,
            archived=False
        ).all()
        medecins = Utilisateur.query.filter_by(
            id_structure=current_user.id_structure,
            role='medecin',
            actif=True
        ).all()
        infirmiers = Utilisateur.query.filter_by(
            id_structure=current_user.id_structure,
            role='infirmier',
            actif=True
        ).all()
    
    services = Service.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    return render_template('hospitalisations/nouvelle.html',
                         patients=patients,
                         medecins=medecins,
                         infirmiers=infirmiers,
                         services=services)


@app.route('/hospitalisation/<int:id>')
@login_required
def detail_hospitalisation(id):
    """Détails d'une hospitalisation avec note d'admission structurée"""
    from models import Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, ConstanteVitale, EvolutionPatient, NoteAdmission, ProtocoleSoins, ExamenType, ExamenPrescrit
    import json
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # Vérifier les permissions
    if current_user.role not in ['super_admin', 'admin_structure']:
        if current_user.role == 'medecin':
            assigne = HospitalisationMedecin.query.filter_by(
                hospitalisation_id=id,
                medecin_id=current_user.id,
                actif=True
            ).first()
            if not assigne:
                flash('Vous n\'etes pas assigne a cette hospitalisation', 'danger')
                return redirect(url_for('dashboard'))
        elif current_user.role == 'infirmier':
            assigne = HospitalisationInfirmier.query.filter_by(
                hospitalisation_id=id,
                infirmier_id=current_user.id,
                actif=True
            ).first()
            if not assigne:
                flash('Vous n\'etes pas assigne a cette hospitalisation', 'danger')
                return redirect(url_for('dashboard'))
    
    # ============================================================
    # 1. RÉCUPÉRATION DES DONNÉES ASSOCIÉES
    # ============================================================
    
    medecins = hospitalisation.medecins.filter_by(actif=True).all()
    infirmiers = hospitalisation.infirmiers.filter_by(actif=True).all()
    constantes = hospitalisation.constantes.order_by(ConstanteVitale.date_prise.desc()).limit(50).all()
    evolutions = hospitalisation.evolutions.order_by(EvolutionPatient.date_evolution.desc()).all()
    
    # ============================================================
    # 2. NOTES D'ADMISSION
    # ============================================================
    
    toutes_notes = hospitalisation.notes_admission_list.order_by(
        NoteAdmission.version.asc()
    ).all()
    
    note_active = None
    if hospitalisation.note_admission_active_id:
        note_active = NoteAdmission.query.get(hospitalisation.note_admission_active_id)
    
    if not note_active and toutes_notes:
        for note in reversed(toutes_notes):
            if note.est_verrouillee:
                note_active = note
                break
    
    if not note_active and toutes_notes:
        note_active = toutes_notes[0]
    
    nb_versions = len(toutes_notes)
    a_plusieurs_versions = nb_versions > 1
    
    # ============================================================
    # 3. COMPARAISON DES NOTES
    # ============================================================
    
    comparaison = None
    if a_plusieurs_versions and note_active:
        note_initiale = toutes_notes[0] if toutes_notes else None
        
        if note_initiale and note_initiale.id != note_active.id:
            diag_initial = note_initiale.diagnostic_admission or ''
            diag_actuel = note_active.diagnostic_admission or ''
            diag_change = diag_initial != diag_actuel
            
            trait_initial = note_initiale.traitement_admission or ''
            trait_actuel = note_active.traitement_admission or ''
            trait_change = trait_initial != trait_actuel
            
            comparaison = {
                'note_initiale': note_initiale,
                'note_active': note_active,
                'diag_change': diag_change,
                'trait_change': trait_change,
                'nb_versions': nb_versions
            }
    
    # ============================================================
    # 4. ⭐ PROTOCOLES DISPONIBLES
    # ============================================================
    protocoles_disponibles = ProtocoleSoins.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    # ============================================================
    # 5. ⭐ PROTOCOLE ACTIF
    # ============================================================
    protocole_actif = None
    if hospitalisation.protocole_id:
        try:
            protocole_actif = ProtocoleSoins.query.get(hospitalisation.protocole_id)
        except:
            protocole_actif = None
    
    # ============================================================
    # 6. ⭐ EXAMENS TYPES DISPONIBLES
    # ============================================================
    examens_types = ExamenType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    # ============================================================
    # 7. ⭐ EXAMENS PRESCRITS (CORRIGÉ - Requête directe)
    # ============================================================
    examens_prescrits = []
    nb_examens_prescrits = 0
    
    try:
        examens_prescrits = ExamenPrescrit.query.filter_by(
            hospitalisation_id=hospitalisation.id
        ).order_by(ExamenPrescrit.date_prescription.desc()).all()
        nb_examens_prescrits = len(examens_prescrits)
    except Exception as e:
        print(f"Erreur chargement examens prescrits: {e}")
        examens_prescrits = []
        nb_examens_prescrits = 0
    
    # ============================================================
    # 8. ⭐ ORDONNANCE
    # ============================================================
    ordonnance_medicaments = []
    if hospitalisation.ordonnance_prescite:
        try:
            ordonnance_medicaments = json.loads(hospitalisation.ordonnance_prescite)
            if not isinstance(ordonnance_medicaments, list):
                ordonnance_medicaments = []
        except:
            ordonnance_medicaments = []
    
    # ============================================================
    # 9. RENDU
    # ============================================================
    
    return render_template('hospitalisations/detail.html',
                         hospitalisation=hospitalisation,
                         medecins=medecins,
                         infirmiers=infirmiers,
                         constantes=constantes,
                         evolutions=evolutions,
                         notes=toutes_notes,
                         note_active=note_active,
                         nb_versions=nb_versions,
                         a_plusieurs_versions=a_plusieurs_versions,
                         comparaison=comparaison,
                         protocoles_disponibles=protocoles_disponibles,
                         protocole_actif=protocole_actif,
                         examens_types=examens_types,
                         examens_prescrits=examens_prescrits,
                         nb_examens_prescrits=nb_examens_prescrits,
                         ordonnance_medicaments=ordonnance_medicaments,
                         now=datetime.utcnow())

# ============================================================
# AJOUTER UNE NOUVELLE NOTE D'ADMISSION (RÉÉVALUATION)
# ============================================================
@app.route('/hospitalisation/<int:id>/note/ajouter', methods=['POST'])
@login_required
def ajouter_note_admission(id):
    """
    Ajouter une nouvelle version de la note d'admission
    (Réévaluation du patient par le médecin)
    """
    from models import Hospitalisation, NoteAdmission, HospitalisationMedecin
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # ============================================================
    # 1. VÉRIFICATION DES PERMISSIONS
    # ============================================================
    
    # Seuls les médecins et admins peuvent ajouter une note
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Seuls les médecins peuvent ajouter une note de réévaluation.', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # Vérifier que l'hospitalisation est active
    if hospitalisation.statut != 'actif':
        flash('Impossible d\'ajouter une note sur une hospitalisation clôturée.', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # Vérifier que le médecin est assigné à cette hospitalisation
    if current_user.role == 'medecin':
        assigne = HospitalisationMedecin.query.filter_by(
            hospitalisation_id=id,
            medecin_id=current_user.id,
            actif=True
        ).first()
        if not assigne:
            flash('Vous n\'êtes pas assigné à cette hospitalisation.', 'danger')
            return redirect(url_for('detail_hospitalisation', id=id))
    
    # ============================================================
    # 2. RÉCUPÉRATION DES DONNÉES DU FORMULAIRE
    # ============================================================
    
    note_motif = request.form.get('note_motif', '').strip()
    note_contexte = request.form.get('note_contexte', '').strip()
    note_examen_clinique = request.form.get('note_examen_clinique', '').strip()
    note_diagnostic = request.form.get('note_diagnostic', '').strip()
    note_examens = request.form.get('note_examens', '').strip()
    note_traitement = request.form.get('note_traitement', '').strip()
    note_evolution_prevue = request.form.get('note_evolution_prevue', '').strip()
    note_conclusion = request.form.get('note_conclusion', '').strip()
    note_constantes = request.form.get('note_constantes', '').strip()
    
    # ============================================================
    # 3. VALIDATION
    # ============================================================
    
    champs_obligatoires = {
        'Motif d\'hospitalisation': note_motif,
        'Contexte et antécédents': note_contexte,
        'Examen clinique initial': note_examen_clinique,
        'Diagnostic présumé': note_diagnostic,
        'Traitement initial': note_traitement,
        'Conclusion du médecin': note_conclusion
    }
    
    champs_manquants = []
    for nom, valeur in champs_obligatoires.items():
        if not valeur:
            champs_manquants.append(nom)
    
    if champs_manquants:
        flash(f'La note est incomplète. Champs obligatoires : {", ".join(champs_manquants)}', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # ============================================================
    # 4. CALCUL DU NUMÉRO DE VERSION
    # ============================================================
    
    notes_existantes = hospitalisation.notes_admission_list.count()
    nouvelle_version = notes_existantes + 1
    
    # Récupérer la note précédente pour référence
    note_precedente = None
    if hospitalisation.note_admission_active_id:
        note_precedente = NoteAdmission.query.get(hospitalisation.note_admission_active_id)
    
    # ============================================================
    # 5. CRÉATION DE LA NOUVELLE NOTE
    # ============================================================
    
    try:
        note = NoteAdmission(
            hospitalisation_id=hospitalisation.id,
            version=nouvelle_version,
            est_initial=False,  # Ce n'est pas la note initiale
            est_verrouillee=True,  # Verrouillée immédiatement
            motif_admission=note_motif,
            contexte_admission=note_contexte,
            examen_clinique_admission=note_examen_clinique,
            diagnostic_admission=note_diagnostic,
            examens_admission=note_examens if note_examens else None,
            traitement_admission=note_traitement,
            evolution_prevue=note_evolution_prevue if note_evolution_prevue else None,
            conclusion_admission=note_conclusion,
            constantes_admission=note_constantes if note_constantes else None,
            redige_par=current_user.id,
            date_redaction=datetime.utcnow(),
            valide_par=current_user.id,
            date_validation=datetime.utcnow()
        )
        
        db.session.add(note)
        db.session.flush()
        
        # ============================================================
        # 6. METTRE À JOUR LA NOTE ACTIVE
        # ============================================================
        
        hospitalisation.note_admission_active_id = note.id
        
        # ============================================================
        # 7. LOG DANS LES NOTES CLINIQUES (optionnel)
        # ============================================================
        
        # Ajouter une entrée dans les notes d'admission (texte libre) pour traçabilité
        ancienne_note = hospitalisation.notes_admission or ''
        nouvelle_entree = f"""
--- RÉÉVALUATION v{ nouvelle_version} - {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} ---
Médecin : Dr {current_user.prenom} {current_user.nom}
Motif : {note_motif[:100]}...
Diagnostic : {note_diagnostic[:100]}...
Traitement : {note_traitement[:100]}...
Conclusion : {note_conclusion[:100]}...
"""
        hospitalisation.notes_admission = (ancienne_note + nouvelle_entree) if ancienne_note else nouvelle_entree
        
        # ============================================================
        # 8. COMMIT FINAL
        # ============================================================
        
        db.session.commit()
        
        flash(f'✅ Nouvelle note de réévaluation (version {nouvelle_version}) enregistrée avec succès !', 'success')
        
        if note_precedente:
            flash(f'📋 Cette note remplace la version {note_precedente.version} comme référence active.', 'info')
        else:
            flash('📋 Cette note est désormais la référence active pour le suivi.', 'info')
        
        return redirect(url_for('detail_hospitalisation', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erreur lors de l\'enregistrement : {str(e)}', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))


# ============================================================
# COMPARER LES NOTES D'ADMISSION
# ============================================================
@app.route('/hospitalisation/<int:id>/notes/comparer')
@login_required
def comparer_notes_admission(id):
    """
    Comparer les différentes versions de la note d'admission
    Affiche un tableau comparatif des versions
    """
    from models import Hospitalisation, NoteAdmission, HospitalisationMedecin
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # ============================================================
    # 1. VÉRIFICATION DES PERMISSIONS
    # ============================================================
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé.', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # Vérifier que le médecin est assigné à cette hospitalisation
    if current_user.role == 'medecin':
        assigne = HospitalisationMedecin.query.filter_by(
            hospitalisation_id=id,
            medecin_id=current_user.id,
            actif=True
        ).first()
        if not assigne:
            flash('Vous n\'êtes pas assigné à cette hospitalisation.', 'danger')
            return redirect(url_for('detail_hospitalisation', id=id))
    
    # ============================================================
    # 2. RÉCUPÉRATION DES NOTES
    # ============================================================
    
    toutes_notes = hospitalisation.notes_admission_list.order_by(
        NoteAdmission.version.asc()
    ).all()
    
    if len(toutes_notes) < 2:
        flash('Il n\'y a pas assez de notes pour faire une comparaison (minimum 2).', 'warning')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # ============================================================
    # 3. ANALYSE DES DIFFÉRENCES
    # ============================================================
    
    # Préparer les données pour le tableau comparatif
    notes_data = []
    for note in toutes_notes:
        # Récupérer le nom du médecin
        medecin_nom = "Inconnu"
        if note.redacteur:
            medecin_nom = f"Dr {note.redacteur.prenom} {note.redacteur.nom}"
        
        notes_data.append({
            'id': note.id,
            'version': note.version,
            'est_initial': note.est_initial,
            'est_verrouillee': note.est_verrouillee,
            'date_redaction': note.date_redaction,
            'redacteur': medecin_nom,
            'motif': note.motif_admission or '-',
            'contexte': note.contexte_admission or '-',
            'examen_clinique': note.examen_clinique_admission or '-',
            'diagnostic': note.diagnostic_admission or '-',
            'examens': note.examens_admission or '-',
            'traitement': note.traitement_admission or '-',
            'evolution_prevue': note.evolution_prevue or '-',
            'conclusion': note.conclusion_admission or '-',
            'constantes': note.constantes_admission or '-'
        })
    
    # ============================================================
    # 4. DÉTECTION DES CHANGEMENTS MAJEURS
    # ============================================================
    
    changements = []
    
    # Comparer chaque note avec la précédente
    for i in range(1, len(notes_data)):
        note_prec = notes_data[i-1]
        note_act = notes_data[i]
        
        changements_note = {
            'version': note_act['version'],
            'changements': []
        }
        
        # Vérifier les changements dans les champs clés
        if note_prec['diagnostic'] != note_act['diagnostic']:
            changements_note['changements'].append({
                'champ': 'Diagnostic',
                'ancien': note_prec['diagnostic'],
                'nouveau': note_act['diagnostic']
            })
        
        if note_prec['traitement'] != note_act['traitement']:
            changements_note['changements'].append({
                'champ': 'Traitement',
                'ancien': note_prec['traitement'],
                'nouveau': note_act['traitement']
            })
        
        if note_prec['examen_clinique'] != note_act['examen_clinique']:
            changements_note['changements'].append({
                'champ': 'Examen clinique',
                'ancien': note_prec['examen_clinique'],
                'nouveau': note_act['examen_clinique']
            })
        
        if note_prec['conclusion'] != note_act['conclusion']:
            changements_note['changements'].append({
                'champ': 'Conclusion',
                'ancien': note_prec['conclusion'],
                'nouveau': note_act['conclusion']
            })
        
        if changements_note['changements']:
            changements.append(changements_note)
    
    # ============================================================
    # 5. RENDU DU TEMPLATE
    # ============================================================
    
    return render_template('hospitalisations/comparaison_notes.html',
                         hospitalisation=hospitalisation,
                         notes_data=notes_data,
                         changements=changements,
                         nb_notes=len(toutes_notes),
                         now=datetime.utcnow())


@app.route('/hospitalisation/<int:id>/evolution', methods=['GET', 'POST'])
@login_required
def ajouter_evolution(id):
    """
    Ajouter une évolution pour un patient hospitalisé
    Avec affichage de la note d'admission en référence
    """
    from models import Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, EvolutionPatient, NoteAdmission
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # ============================================================
    # 1. VÉRIFICATION DES PERMISSIONS
    # ============================================================
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if current_user.role != 'admin_structure':
        if current_user.role == 'medecin':
            assigne = HospitalisationMedecin.query.filter_by(
                hospitalisation_id=id,
                medecin_id=current_user.id,
                actif=True
            ).first()
            if not assigne:
                flash('Vous n\'êtes pas assigné à cette hospitalisation', 'danger')
                return redirect(url_for('dashboard'))
        elif current_user.role == 'infirmier':
            assigne = HospitalisationInfirmier.query.filter_by(
                hospitalisation_id=id,
                infirmier_id=current_user.id,
                actif=True
            ).first()
            if not assigne:
                flash('Vous n\'êtes pas assigné à cette hospitalisation', 'danger')
                return redirect(url_for('dashboard'))
    
    # ============================================================
    # 2. RÉCUPÉRATION DE LA NOTE D'ADMISSION ACTIVE (RÉFÉRENCE)
    # ============================================================
    
    note_active = None
    if hospitalisation.note_admission_active_id:
        note_active = NoteAdmission.query.get(hospitalisation.note_admission_active_id)
    
    # Si pas de note active, prendre la dernière verrouillée
    if not note_active:
        toutes_notes = hospitalisation.notes_admission_list.order_by(
            NoteAdmission.version.desc()
        ).all()
        for note in toutes_notes:
            if note.est_verrouillee:
                note_active = note
                break
    
    # Si toujours pas, prendre la première
    if not note_active:
        note_active = hospitalisation.notes_admission_list.first()
    
    # ============================================================
    # 3. TRAITEMENT DU POST
    # ============================================================
    
    if request.method == 'POST':
        etat_echelle = request.form.get('etat_echelle', type=int)
        temperature = request.form.get('temperature', type=float)
        pression = request.form.get('pression')
        fc = request.form.get('fc', type=int)
        symptomes = request.form.get('symptomes')
        traitement_administre = request.form.get('traitement_administre')
        observations = request.form.get('observations')
        prochaines_etapes = request.form.get('prochaines_etapes')
        
        # ⭐ NOUVEAU : Évolution par rapport à l'admission
        evolution_par_rapport = request.form.get('evolution_par_rapport')
        
        if etat_echelle is None or etat_echelle < 0 or etat_echelle > 10:
            flash('L\'état doit être entre 0 et 10', 'danger')
            return redirect(url_for('ajouter_evolution', id=id))
        
        try:
            evolution = EvolutionPatient(
                hospitalisation_id=id,
                etat_echelle=etat_echelle,
                temperature=temperature,
                pression=pression,
                fc=fc,
                symptomes=symptomes,
                traitement_administre=traitement_administre,
                observations=observations,
                prochaines_etapes=prochaines_etapes,
                evolution_par_rapport=evolution_par_rapport,  # ⭐ NOUVEAU
                redige_par=current_user.id,
                date_evolution=datetime.utcnow()
            )
            db.session.add(evolution)
            db.session.commit()
            
            # ⭐ Message avec rappel de la note de référence
            flash('✅ Évolution enregistrée avec succès', 'success')
            if note_active:
                flash(f'📋 Référence : Note d\'admission v{note_active.version} du {note_active.date_redaction.strftime("%d/%m/%Y")}', 'info')
            
            return redirect(url_for('detail_hospitalisation', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erreur : {str(e)}', 'danger')
            return redirect(url_for('ajouter_evolution', id=id))
    
    # ============================================================
    # 4. AFFICHAGE DU FORMULAIRE (GET)
    # ============================================================
    
    # Récupérer les évolutions précédentes pour référence
    evolutions_precedentes = hospitalisation.evolutions.order_by(
        EvolutionPatient.date_evolution.desc()
    ).limit(5).all()
    
    # Calculer la tendance
    tendance = None
    if len(evolutions_precedentes) >= 2:
        dernier_etat = evolutions_precedentes[0].etat_echelle if evolutions_precedentes else None
        avant_dernier = evolutions_precedentes[1].etat_echelle if len(evolutions_precedentes) > 1 else None
        
        if dernier_etat is not None and avant_dernier is not None:
            if dernier_etat > avant_dernier:
                tendance = 'amelioration'
            elif dernier_etat < avant_dernier:
                tendance = 'aggravation'
            else:
                tendance = 'stable'
    
    return render_template('hospitalisations/evolution.html',
                         hospitalisation=hospitalisation,
                         note_active=note_active,
                         evolutions_precedentes=evolutions_precedentes,
                         tendance=tendance,
                         now=datetime.utcnow())

@app.route('/hospitalisation/<int:id>/constante', methods=['GET', 'POST'])
@login_required
def ajouter_constante(id):
    """
    Ajouter des constantes vitales pour un patient hospitalisé
    Avec affichage de la note d'admission en référence
    """
    from models import Hospitalisation, HospitalisationInfirmier, HospitalisationMedecin, ConstanteVitale, NoteAdmission
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # ============================================================
    # 1. VÉRIFICATION DES PERMISSIONS
    # ============================================================
    
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if current_user.id_structure and hospitalisation.patient.id_structure != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_hospitalisations'))
    
    if current_user.role == 'infirmier':
        assigne = HospitalisationInfirmier.query.filter_by(
            hospitalisation_id=id,
            infirmier_id=current_user.id,
            actif=True
        ).first()
        if not assigne:
            flash('Vous n\'êtes pas assigné à cette hospitalisation', 'danger')
            return redirect(url_for('liste_hospitalisations'))
    
    if current_user.role == 'medecin':
        assigne = HospitalisationMedecin.query.filter_by(
            hospitalisation_id=id,
            medecin_id=current_user.id,
            actif=True
        ).first()
        if not assigne:
            flash('Vous n\'êtes pas assigné à cette hospitalisation', 'danger')
            return redirect(url_for('liste_hospitalisations'))
    
    # ============================================================
    # 2. RÉCUPÉRATION DE LA NOTE D'ADMISSION ACTIVE (RÉFÉRENCE)
    # ============================================================
    
    note_active = None
    if hospitalisation.note_admission_active_id:
        note_active = NoteAdmission.query.get(hospitalisation.note_admission_active_id)
    
    # Si pas de note active, prendre la dernière verrouillée
    if not note_active:
        toutes_notes = hospitalisation.notes_admission_list.order_by(
            NoteAdmission.version.desc()
        ).all()
        for note in toutes_notes:
            if note.est_verrouillee:
                note_active = note
                break
    
    # Si toujours pas, prendre la première
    if not note_active:
        note_active = hospitalisation.notes_admission_list.first()
    
    # ============================================================
    # 3. RÉCUPÉRATION DES DERNIÈRES CONSTANTES POUR COMPARAISON
    # ============================================================
    
    dernieres_constantes = hospitalisation.constantes.order_by(
        ConstanteVitale.date_prise.desc()
    ).first()
    
    # ============================================================
    # 4. TRAITEMENT DU POST
    # ============================================================
    
    if request.method == 'POST':
        temperature = request.form.get('temperature', type=float)
        pression_arterielle = request.form.get('pression_arterielle')
        frequence_cardiaque = request.form.get('frequence_cardiaque', type=int)
        frequence_respiratoire = request.form.get('frequence_respiratoire', type=int)
        saturation_oxygene = request.form.get('saturation_oxygene', type=float)
        glycemie = request.form.get('glycemie', type=float)
        poids = request.form.get('poids', type=float)
        taille = request.form.get('taille', type=float)
        
        # Nouveaux champs
        diurese = request.form.get('diurese')
        emission_gaz = request.form.get('emission_gaz')
        selles = request.form.get('selles')
        vomissements = request.form.get('vomissements')
        douleur = request.form.get('douleur', type=int)
        conscience = request.form.get('conscience')
        pouls_peripherique = request.form.get('pouls_peripherique')
        temperature_cutanee = request.form.get('temperature_cutanee')
        
        autres_constantes = request.form.get('autres_constantes')
        notes = request.form.get('notes')
        
        # ⭐ NOUVEAU : Évolution par rapport à l'admission
        evolution_par_rapport = request.form.get('evolution_par_rapport')
        
        # Calcul de l'IMC
        imc = None
        if poids and taille and taille > 0:
            imc = round(poids / ((taille/100) ** 2), 1)
        
        try:
            constante = ConstanteVitale(
                hospitalisation_id=id,
                infirmier_id=current_user.id,
                temperature=temperature,
                pression_arterielle=pression_arterielle,
                frequence_cardiaque=frequence_cardiaque,
                frequence_respiratoire=frequence_respiratoire,
                saturation_oxygene=saturation_oxygene,
                glycemie=glycemie,
                poids=poids,
                taille=taille,
                imc=imc,
                # Nouveaux champs
                diurese=diurese,
                emission_gaz=emission_gaz,
                selles=selles,
                vomissements=vomissements,
                douleur=douleur,
                conscience=conscience,
                pouls_peripherique=pouls_peripherique,
                temperature_cutanee=temperature_cutanee,
                # ⭐ NOUVEAU
                evolution_par_rapport=evolution_par_rapport,
                autres_constantes=autres_constantes,
                notes=notes,
                date_prise=datetime.utcnow()
            )
            db.session.add(constante)
            db.session.commit()
            
            # ⭐ Message avec rappel de la note de référence
            flash('✅ Constantes vitales enregistrées avec succès', 'success')
            if note_active:
                flash(f'📋 Référence : Note d\'admission v{note_active.version} du {note_active.date_redaction.strftime("%d/%m/%Y")}', 'info')
            
            return redirect(url_for('detail_hospitalisation', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erreur : {str(e)}', 'danger')
            return redirect(url_for('ajouter_constante', id=id))
    
    # ============================================================
    # 5. AFFICHAGE DU FORMULAIRE (GET)
    # ============================================================
    
    return render_template('hospitalisations/constante.html',
                         hospitalisation=hospitalisation,
                         note_active=note_active,
                         dernieres_constantes=dernieres_constantes,
                         now=datetime.utcnow())

@app.route('/hospitalisation/<int:id>/cloturer', methods=['POST'])
@login_required
def cloturer_hospitalisation(id):
    """Clôturer une hospitalisation (sortie du patient)"""
    from models import Hospitalisation, HospitalisationMedecin, Lit
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    # Vérifier l'appartenance à la structure
    if current_user.id_structure and hospitalisation.patient.id_structure != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_hospitalisations'))
    
    if current_user.role == 'medecin':
        assigne = HospitalisationMedecin.query.filter_by(
            hospitalisation_id=id,
            medecin_id=current_user.id,
            actif=True
        ).first()
        if not assigne:
            flash('Vous n\'êtes pas assigné à cette hospitalisation', 'danger')
            return redirect(url_for('liste_hospitalisations'))
    
    # Récupération des données du formulaire
    type_sortie = request.form.get('type_sortie', 'sortie')
    motif_sortie = request.form.get('motif_sortie', '')
    
    # --- Gestion du type de sortie ---
    if type_sortie == 'transfere':
        centre_transfert = request.form.get('centre_transfert')
        motif_transfert = request.form.get('motif_transfert')
        date_transfert_str = request.form.get('date_transfert')
        
        hospitalisation.statut = 'transfere'
        hospitalisation.centre_transfert = centre_transfert
        hospitalisation.motif_transfert = motif_transfert
        if date_transfert_str:
            hospitalisation.date_transfert = datetime.fromisoformat(date_transfert_str)
            
    elif type_sortie == 'deces':
        hospitalisation.statut = 'sorti'
        motif_sortie = f"DÉCÈS - {motif_sortie}" if motif_sortie else "DÉCÈS"
        
    elif type_sortie == 'autres':
        hospitalisation.statut = 'sorti'
        motif_autres = request.form.get('motif_autres')
        if motif_autres:
            motif_sortie = f"Autre motif: {motif_autres}"
        else:
            motif_sortie = "Autre motif non spécifié"
            
    else:  # sortie normale
        hospitalisation.statut = 'sorti'
    
    # ⭐ LIBÉRER LE LIT (corrigé)
    if hospitalisation.lit_id:
        lit = Lit.query.get(hospitalisation.lit_id)
        if lit:
            lit.liberer()
            hospitalisation.lit_id = None

    # --- Gestion des avis externes ---
    medecins_externes = request.form.get('medecins_externes')
    demandes_avis = request.form.get('demandes_avis')
    avis_externes = request.form.get('avis_externes')
    
    if medecins_externes:
        hospitalisation.medecins_externes = medecins_externes
    if demandes_avis:
        hospitalisation.demandes_avis = demandes_avis
    if avis_externes:
        hospitalisation.avis_externes = avis_externes
    
    hospitalisation.date_fin = datetime.utcnow()
    
    # --- Construction des notes de sortie ---
    notes_completes = f"\n--- SORTIE DU PATIENT ---\n"
    notes_completes += f"Date de sortie: {hospitalisation.date_fin.strftime('%d/%m/%Y %H:%M')}\n"
    notes_completes += f"Type: {type_sortie}\n"
    notes_completes += f"Motif: {motif_sortie}\n"
    
    if type_sortie == 'transfere':
        notes_completes += f"Transfert vers: {centre_transfert or 'Non spécifié'}\n"
        notes_completes += f"Motif du transfert: {motif_transfert or 'Non spécifié'}\n"
        if date_transfert_str:
            notes_completes += f"Date du transfert: {date_transfert_str}\n"
    
    if medecins_externes:
        notes_completes += f"Médecins externes consultés: {medecins_externes}\n"
    if demandes_avis:
        notes_completes += f"Demandes d'avis: {demandes_avis}\n"
    if avis_externes:
        notes_completes += f"Avis reçus: {avis_externes}\n"
    
    notes_completes += "---\n"
    
    hospitalisation.notes_admission = (hospitalisation.notes_admission or '') + notes_completes
    
    db.session.commit()
    
    flash(f'Hospitalisation clôturée avec succès ({type_sortie})', 'success')
    return redirect(url_for('liste_hospitalisations'))

@app.route('/patient/<int:patient_id>/hospitalisations')
@login_required
def patient_hospitalisations(patient_id):
    """Voir toutes les hospitalisations d'un patient"""
    from models import Patient, Hospitalisation
    
    patient = Patient.query.get_or_404(patient_id)
    
    # Vérifier les permissions
    if current_user.role not in ['super_admin']:
        if current_user.id_structure and patient.id_structure != current_user.id_structure:
            flash('Accès non autorisé', 'danger')
            return redirect(url_for('dashboard'))
        
        if current_user.role == 'medecin' and patient.id_medecin_referent != current_user.id:
            flash('Accès non autorisé', 'danger')
            return redirect(url_for('dashboard'))
    
    hospitalisations = Hospitalisation.query.filter_by(
        patient_id=patient_id
    ).order_by(Hospitalisation.date_debut.desc()).all()
    
    return render_template('hospitalisations/patient_hospitalisations.html',
                         patient=patient,
                         hospitalisations=hospitalisations)
@app.route('/hospitalisation/<int:id>/avis-externe', methods=['POST'])
@login_required
def ajouter_avis_externe(id):
    """Ajouter un nouvel avis de médecin externe"""
    from models import Hospitalisation, AvisExterne
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # Vérifier les permissions
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Vérifier l'appartenance à la structure
    if current_user.id_structure and hospitalisation.patient.id_structure != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_hospitalisations'))
    
    # Récupération des données
    medecin_nom = request.form.get('medecin_nom', '').strip()
    specialite = request.form.get('specialite', '').strip()
    etablissement = request.form.get('etablissement', '').strip()
    demande_avis = request.form.get('demande_avis', '').strip()
    avis_recu = request.form.get('avis_recu', '').strip()
    date_demande_str = request.form.get('date_demande')
    date_reception_str = request.form.get('date_reception')
    
    # Validation
    if not medecin_nom or not avis_recu:
        flash('Le nom du médecin et l\'avis reçu sont obligatoires', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # Création de l'avis
    avis = AvisExterne(
        hospitalisation_id=id,
        medecin_nom=medecin_nom,
        specialite=specialite if specialite else None,
        etablissement=etablissement if etablissement else None,
        demande_avis=demande_avis if demande_avis else None,
        avis_recu=avis_recu,
        created_by=current_user.id
    )
    
    if date_demande_str:
        avis.date_demande = datetime.fromisoformat(date_demande_str)
    if date_reception_str:
        avis.date_reception = datetime.fromisoformat(date_reception_str)
    
    db.session.add(avis)
    db.session.commit()
    
    flash('✅ Avis externe enregistré avec succès', 'success')
    return redirect(url_for('detail_hospitalisation', id=id))

@app.route('/consultation/<int:id>/resultats', methods=['POST'])
@login_required
def ajouter_resultats(id):
    """Ajouter ou mettre à jour les résultats des examens"""
    from models import Consultation
    from datetime import datetime
    
    consultation = Consultation.query.get_or_404(id)
    
    # Vérifier les permissions
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupération des données
    resultats_biologie = request.form.get('resultats_biologie', '').strip()
    resultats_imagerie = request.form.get('resultats_imagerie', '').strip()
    date_resultats_str = request.form.get('date_resultats')
    
    # Mise à jour
    if resultats_biologie:
        consultation.resultats_biologie = resultats_biologie
    if resultats_imagerie:
        consultation.resultats_imagerie = resultats_imagerie
    
    if date_resultats_str:
        consultation.date_resultats = datetime.fromisoformat(date_resultats_str)
    else:
        consultation.date_resultats = datetime.utcnow()
    
    db.session.commit()
    
    flash('✅ Résultats enregistrés avec succès', 'success')
    return redirect(url_for('consultation_detail', id=id))


# ==================== CIM-10 ====================

import csv
import os

_cim10_cache = None
_cim10_last_update = None

def get_cim10_list():
    """Récupère la liste des codes CIM-10 depuis le fichier local"""
    global _cim10_cache, _cim10_last_update
    
    if _cim10_cache and _cim10_last_update:
        from datetime import datetime
        if (datetime.now() - _cim10_last_update).seconds < 3600:
            return _cim10_cache
    
    try:
        cim10_file = os.path.join(os.path.dirname(__file__), 'cim10.csv')
        
        if not os.path.exists(cim10_file):
            print(f"❌ Fichier {cim10_file} non trouvé !")
            return []
        
        cim10_list = []
        with open(cim10_file, 'r', encoding='utf-8') as f:
            csv_reader = csv.reader(f)
            for i, row in enumerate(csv_reader):
                if i == 0:  # Ignorer l'en-tête "id,code"
                    continue
                if row and len(row) > 1:
                    code = row[1].strip()  # Colonne "code"
                    if code:
                        code = code.strip('"')
                        code = code.replace('""', '"')
                        cim10_list.append(code)
        
        _cim10_cache = cim10_list
        from datetime import datetime
        _cim10_last_update = datetime.now()
        
        return cim10_list
    except Exception as e:
        print(f"❌ Erreur chargement CIM-10: {e}")
        return []

def search_cim10(search_term, limit=30):
    """Recherche dans les codes CIM-10"""
    if not search_term or len(search_term) < 2:
        return []
    
    all_codes = get_cim10_list()
    search_term = search_term.lower().strip()
    
    results = []
    for code in all_codes:
        if search_term in code.lower():
            results.append({'nom': code})
            if len(results) >= limit:
                break
    
    return results

@app.route('/api/cim10/search')
@login_required
def api_cim10_search():
    """API de recherche CIM-10"""
    term = request.args.get('term', '')
    if len(term) < 2:
        return jsonify([])
    
    results = search_cim10(term)
    return jsonify(results)
# ==================== ANALYSES ====================

@app.route('/analyses')
@login_required
@has_permission('ANALYSES')  # ⭐ AJOUTER LE DÉCORATEUR
def liste_analyses():
    """Liste des analyses regroupées par patient"""
    from models import AnalyseDemande, Patient
    from sqlalchemy import or_
    
    # ⭐ ACCÈS POUR MÉDECIN, LABORANTIN ET ADMIN
    if current_user.role not in ['admin_structure', 'laborantin', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer les paramètres
    statut = request.args.get('statut', '')
    search = request.args.get('search', '')
    
    # Requête de base
    query = AnalyseDemande.query.filter_by(structure_id=current_user.id_structure)

    
    # ⭐ SI C'EST UN LABORANTIN, FILTRER UNIQUEMENT LA BIOLOGIE
    if current_user.role == 'laborantin':
        query = query.filter(AnalyseDemande.type_analyse == 'BIOLOGIE')
    
    
    # Filtrer par statut
    if statut:
        query = query.filter_by(statut=statut)
    
    # Recherche
    if search:
        search = search.strip()
        filters = []
        filters.append(Patient.nom.ilike(f'%{search}%'))
        filters.append(Patient.prenom.ilike(f'%{search}%'))
        
        if search.upper().startswith('P'):
            try:
                num = int(search[1:])
                filters.append(Patient.id == num)
            except ValueError:
                pass
        elif search.isdigit():
            filters.append(Patient.id == int(search))
        
        if filters:
            patients_trouves = Patient.query.filter(or_(*filters)).all()
            patient_ids = [p.id for p in patients_trouves]
            if patient_ids:
                query = query.filter(AnalyseDemande.patient_id.in_(patient_ids))
            else:
                query = query.filter(AnalyseDemande.patient_id == -1)
    
    # Regrouper par patient
    analyses = query.order_by(AnalyseDemande.date_demande.desc()).all()
    
    patients_dict = {}
    for analyse in analyses:
        patient_id = analyse.patient_id
        if patient_id not in patients_dict:
            patients_dict[patient_id] = {
                'patient': analyse.patient,
                'analyses': []
            }
        patients_dict[patient_id]['analyses'].append(analyse)
    
    patients = list(patients_dict.values())
    statuts = ['EN_ATTENTE', 'EN_COURS', 'TERMINE']
    
    return render_template('analyses/liste.html',
                         patients=patients,
                         statut_actuel=statut,
                         statuts=statuts,
                         search=search)

@app.route('/analyse/<int:id>')
@login_required
def detail_analyse(id):
    """Détail d'une analyse demandée"""
    from models import AnalyseDemande
    
    analyse = AnalyseDemande.query.get_or_404(id)
    
    # ⭐ PERMISSIONS - Médecin, Laborantin, Radiologue, Admin, Super Admin
    if current_user.role not in ['super_admin', 'admin_structure', 'laborantin', 'medecin', 'radiologue']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Vérifier la structure
    if current_user.role not in ['super_admin']:
        if analyse.structure_id != current_user.id_structure:
            flash('Accès non autorisé', 'danger')
            return redirect(url_for('liste_analyses'))
    
    return render_template('analyses/detail.html', analyse=analyse)

@app.route('/analyse/<int:id>/resultats', methods=['POST'])
@login_required
def saisir_resultats_analyse(id):
    """Saisir les résultats d'une analyse (Laborantin ou Radiologue)"""
    from models import AnalyseDemande, Consultation
    from datetime import datetime
    
    analyse = AnalyseDemande.query.get_or_404(id)
    
    # ⭐ PERMISSIONS : Laborantin, Radiologue, Admin, Super Admin
    if current_user.role not in ['laborantin', 'radiologue', 'admin_structure', 'super_admin']:
        flash('Accès non autorisé - réservé au laborantin ou radiologue', 'danger')
        return redirect(url_for('dashboard'))
    
    # ⭐ VÉRIFIER QUE LE RÔLE CORRESPOND AU TYPE D'ANALYSE
    if current_user.role == 'laborantin' and analyse.type_analyse != 'BIOLOGIE':
        flash('Accès non autorisé - vous ne pouvez saisir que les analyses de biologie', 'danger')
        return redirect(url_for('liste_analyses'))
    
    if current_user.role == 'radiologue' and analyse.type_analyse != 'IMAGERIE':
        flash('Accès non autorisé - vous ne pouvez saisir que les examens d\'imagerie', 'danger')
        return redirect(url_for('liste_radiologie'))
    
    if analyse.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_analyses'))
    
    resultats = request.form.get('resultats')
    statut = request.form.get('statut', 'TERMINE')
    
    if not resultats and statut == 'TERMINE':
        flash('Veuillez saisir les résultats', 'danger')
        return redirect(url_for('detail_analyse', id=id))
    
    # Mettre à jour l'analyse
    analyse.resultats = resultats
    analyse.statut = statut
    analyse.date_resultats = datetime.utcnow()
    analyse.resultats_par = current_user.id
    
    # Mettre à jour les résultats de la consultation
    consultation = Consultation.query.get(analyse.consultation_id)
    if consultation:
        if analyse.type_analyse == 'BIOLOGIE':
            if consultation.resultats_biologie:
                consultation.resultats_biologie += f"\n\n--- {analyse.nom_analyse} ---\n{resultats}"
            else:
                consultation.resultats_biologie = f"--- {analyse.nom_analyse} ---\n{resultats}"
        elif analyse.type_analyse == 'IMAGERIE':
            if consultation.resultats_imagerie:
                consultation.resultats_imagerie += f"\n\n--- {analyse.nom_analyse} ---\n{resultats}"
            else:
                consultation.resultats_imagerie = f"--- {analyse.nom_analyse} ---\n{resultats}"
        
        consultation.date_resultats = datetime.utcnow()
    
    db.session.commit()
    
    flash('✅ Résultats enregistrés avec succès', 'success')
    
    # ⭐ REDIRECTION SELON LE RÔLE
    if current_user.role == 'radiologue':
        return redirect(url_for('liste_radiologie'))
    else:
        return redirect(url_for('liste_analyses'))

@app.route('/analyse/<int:id>/imprimer')
@login_required
def imprimer_resultat_analyse(id):
    from models import AnalyseDemande, Structure
    from datetime import datetime
    import re
    
    analyse = AnalyseDemande.query.get_or_404(id)
    structure = Structure.query.get(current_user.id_structure)
    
    # ⭐ NETTOYER LE NOM DE L'ANALYSE
    nom_analyse = analyse.nom_analyse
    
    # Règle : supprimer le code qui commence par une ou plusieurs lettres suivies de chiffres
    # Exemples: 
    #   "Q426 - TDM CEREBRALE" → "TDM CEREBRALE"
    #   "Q426 TDM CEREBRALE" → "TDM CEREBRALE"
    #   "Q100 Examen radiologique du doigt" → "Examen radiologique du doigt"
    #   "B12 - NFS" → "NFS"
    #   "TDM CEREBRALE" (sans code) → "TDM CEREBRALE"
    #
    # Pattern: une ou plusieurs lettres majuscules + un ou plusieurs chiffres 
    #          + optionnel espace + optionnel tiret + optionnel espace
    pattern = r'^[A-Z]+[0-9]+\s*-?\s*'
    nom_analyse = re.sub(pattern, '', nom_analyse)
    
    return render_template('impressions/resultat.html',
                         analyse=analyse,
                         structure=structure,
                         nom_analyse=nom_analyse,  # ⭐ NOM NETTOYÉ
                         now=datetime.utcnow())

@app.route('/consultation/<int:id>/analyse/ajouter', methods=['POST'])
@login_required
def ajouter_analyse_demande(id):
    """Le médecin ajoute une demande d'analyse"""
    from models import Consultation, AnalyseDemande
    
    consultation = Consultation.query.get_or_404(id)
    
    if current_user.role not in ['medecin', 'admin_structure']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    type_analyse = request.form.get('type_analyse')
    nom_analyse = request.form.get('nom_analyse')
    description = request.form.get('description')
    
    if not type_analyse or not nom_analyse:
        flash('Le type et le nom de l\'analyse sont obligatoires', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    analyse = AnalyseDemande(
        consultation_id=consultation.id,
        patient_id=consultation.id_patient,
        structure_id=current_user.id_structure,
        type_analyse=type_analyse,
        nom_analyse=nom_analyse,
        description=description,
        prescrit_par=current_user.id,
        statut='EN_ATTENTE'
    )
    
    db.session.add(analyse)
    db.session.commit()
    
    flash(f'✅ Demande d\'analyse "{nom_analyse}" envoyée au laborantin', 'success')
    return redirect(url_for('consultation_detail', id=id))

@app.route('/patient/<int:patient_id>/analyses')
@login_required
def patient_analyses(patient_id):
    from models import Patient, AnalyseDemande
    
    patient = Patient.query.get_or_404(patient_id)
    
    if current_user.role not in ['super_admin']:
        if patient.id_structure != current_user.id_structure:
            flash('Accès non autorisé', 'danger')
            return redirect(url_for('liste_analyses'))
    
    # ⭐ REQUÊTE DE BASE
    query = AnalyseDemande.query.filter_by(
        patient_id=patient_id,
        structure_id=current_user.id_structure
    )
    
    # ⭐ FILTRER SELON LE RÔLE
    if current_user.role == 'laborantin':
        query = query.filter(AnalyseDemande.type_analyse == 'BIOLOGIE')
    elif current_user.role == 'radiologue':
        query = query.filter(AnalyseDemande.type_analyse == 'IMAGERIE')
    
    analyses = query.order_by(AnalyseDemande.date_demande.desc()).all()
    
    return render_template('analyses/patient_analyses.html',
                         patient=patient,
                         analyses=analyses)

@app.route('/consultation/<int:id>/reference/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_reference(id):
    """Ajouter une référence depuis une consultation"""
    from models import Consultation, Reference, Patient
    
    consultation = Consultation.query.get_or_404(id)
    patient = Patient.query.get(consultation.id_patient)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')
        centre_reference = request.form.get('centre_reference')
        service_reference = request.form.get('service_reference')
        medecin_referent = request.form.get('medecin_referent')
        resume_clinique = request.form.get('resume_clinique')
        examens_realises = request.form.get('examens_realises')
        traitements_en_cours = request.form.get('traitements_en_cours')
        
        if not motif or not centre_reference:
            flash('Le motif et le centre de référence sont obligatoires', 'danger')
            return redirect(url_for('ajouter_reference', id=id))
        
        # Créer la référence avec les dernières constantes du patient
        reference = Reference(
            patient_id=patient.id,
            consultation_id=consultation.id,
            structure_id=current_user.id_structure,
            motif=motif,
            diagnostic=diagnostic or consultation.diagnostic,
            centre_reference=centre_reference,
            service_reference=service_reference,
            medecin_referent=medecin_referent,
            derniere_tension=patient.tension_arterielle,
            derniere_temperature=patient.temperature_c,
            derniere_pulse=patient.pulse_bpm,
            derniere_saturation=patient.oxygene_saturation,
            dernier_poids=patient.poids_kg,
            derniere_taille=patient.taille_cm,
            dernier_imc=patient.imc,
            resume_clinique=resume_clinique,
            examens_realises=examens_realises,
            traitements_en_cours=traitements_en_cours,
            statut='ENVOYE',
            created_by=current_user.id
        )
        
        db.session.add(reference)
        db.session.commit()
        
        flash('✅ Référence créée avec succès', 'success')
        return redirect(url_for('imprimer_reference', id=reference.id))
    
    return render_template('consultations/ajouter_reference.html',
                         consultation=consultation,
                         patient=patient)
@app.route('/reference/<int:id>/imprimer')
@login_required
def imprimer_reference(id):
    """Imprimer une fiche de référence"""
    from models import Reference, Structure
    from datetime import datetime
    
    reference = Reference.query.get_or_404(id)
    
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if reference.structure_id != current_user.id_structure and current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # ⭐ RÉCUPÉRER LA STRUCTURE POUR LE LOGO
    structure = Structure.query.get(current_user.id_structure)
    
    return render_template('impressions/reference.html',
                         reference=reference,
                         structure=structure,
                         now=datetime.utcnow())

# ==================== GESTION DES RÉFÉRENCES ====================

@app.route('/references')
@login_required
@has_permission('REFERENCE')  # ⭐ AJOUTER LE DÉCORATEUR
def liste_references():
    """Liste des références effectuées"""
    from models import Reference, Patient
    from sqlalchemy import or_
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Filtres
    search = request.args.get('search', '')
    statut = request.args.get('statut', '')
    
    query = Reference.query.filter_by(structure_id=current_user.id_structure)
    
    # ⭐ RECHERCHE CORRIGÉE
    if search:
        search = search.strip()
        filters = []
        
        # Recherche par nom ou prénom
        filters.append(Patient.nom.ilike(f'%{search}%'))
        filters.append(Patient.prenom.ilike(f'%{search}%'))
        
        # Recherche par numéro de dossier (P00001)
        if search.upper().startswith('P'):
            try:
                num = int(search[1:])
                filters.append(Patient.id == num)
            except ValueError:
                pass
        elif search.isdigit():
            filters.append(Patient.id == int(search))
        
        # Recherche par numéro de référence (REF-00001)
        if search.upper().startswith('REF'):
            try:
                num = int(search[3:])
                filters.append(Reference.id == num)
            except ValueError:
                pass
        
        # Appliquer les filtres
        if filters:
            query = query.join(Patient).filter(or_(*filters))
    
    # Filtre par statut
    if statut:
        query = query.filter_by(statut=statut)
    
    references = query.order_by(Reference.date_reference.desc()).all()
    statuts = ['ENVOYE', 'ACCEPTE', 'REFUSE', 'EN_ATTENTE']
    
    return render_template('references/liste.html',
                         references=references,
                         search=search,
                         statut_actuel=statut,
                         statuts=statuts)

@app.route('/reference/<int:id>/reimprimer')
@login_required
def reimprimer_reference(id):
    """Réimprimer une référence existante"""
    from models import Reference
    
    reference = Reference.query.get_or_404(id)
    
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if reference.structure_id != current_user.id_structure and current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_references'))
    
    return render_template('references/imprimer.html', reference=reference)
@app.route('/reference/<int:id>/suivi', methods=['POST'])
@login_required
def suivi_reference(id):
    """Mettre à jour le suivi d'une référence"""
    from models import Reference
    from datetime import datetime
    
    reference = Reference.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if reference.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_references'))
    
    statut = request.form.get('statut')
    retour_info = request.form.get('retour_info')
    
    if statut:
        reference.statut = statut
        if statut in ['ACCEPTE', 'REFUSE']:
            reference.date_retour = datetime.utcnow()
    
    if retour_info:
        reference.retour_info = retour_info
    
    db.session.commit()
    
    flash('✅ Suivi mis à jour', 'success')
    return redirect(url_for('liste_references'))
# ==================== PERMISSIONS TEMPORAIRES ====================

@app.route('/structure/permissions')
@login_required
def gestion_permissions():
    """Gestion des permissions temporaires"""
    if current_user.role not in ['admin_structure']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur, PermissionTemp
    from datetime import datetime
    
    # Liste des utilisateurs de la structure (sauf admin)
    users = Utilisateur.query.filter(
        Utilisateur.id_structure == current_user.id_structure,
        Utilisateur.role != 'admin_structure',
        Utilisateur.actif == True
    ).all()
    
    # Permissions actives
    permissions_actives = PermissionTemp.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    # Historique
    historique = PermissionTemp.query.filter_by(
        structure_id=current_user.id_structure
    ).order_by(PermissionTemp.created_at.desc()).limit(50).all()
    
    # Liste des permissions disponibles
    permissions_list = [
        {'key': 'ANALYSES', 'label': '🧪 Accès Analyses', 'description': 'Voir et saisir les résultats d\'analyses'},
        {'key': 'REFERENCE', 'label': '🚑 Accès Références', 'description': 'Créer et gérer les références'},
        {'key': 'HOSPITALISATION', 'label': '🏥 Accès Hospitalisations', 'description': 'Gérer les hospitalisations'},
        {'key': 'STATISTIQUES', 'label': '📊 Accès Statistiques', 'description': 'Voir les statistiques'},
        {'key': 'PATIENTS', 'label': '👤 Accès Patients', 'description': 'Voir et modifier les patients'},
    ]
    
    # ⭐ PASSER now AU TEMPLATE
    return render_template('structure/permissions.html',
                         users=users,
                         permissions_actives=permissions_actives,
                         historique=historique,
                         permissions_list=permissions_list,
                         now=datetime.utcnow())  # ⭐ AJOUTER CETTE LIGNE

@app.route('/structure/permissions/ajouter', methods=['POST'])
@login_required
def ajouter_permission():
    """Ajouter une permission temporaire"""
    if current_user.role not in ['admin_structure']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import Utilisateur, PermissionTemp
    from datetime import datetime, timedelta
    
    user_id = request.form.get('user_id')
    permission = request.form.get('permission')
    duree = request.form.get('duree', 24)  # Heures par défaut
    motif = request.form.get('motif', '')
    
    if not user_id or not permission:
        flash('Veuillez sélectionner un utilisateur et une permission', 'danger')
        return redirect(url_for('gestion_permissions'))
    
    # Vérifier que l'utilisateur est dans la structure
    user = Utilisateur.query.get(user_id)
    if not user or user.id_structure != current_user.id_structure:
        flash('Utilisateur non trouvé', 'danger')
        return redirect(url_for('gestion_permissions'))
    
    # Vérifier si une permission active existe déjà
    existing = PermissionTemp.query.filter_by(
        user_id=user_id,
        permission=permission,
        actif=True
    ).first()
    
    if existing:
        flash(f'{user.prenom} {user.nom} a déjà cette permission active', 'warning')
        return redirect(url_for('gestion_permissions'))
    
    # Créer la permission
    permission_temp = PermissionTemp(
        user_id=user_id,
        granted_by=current_user.id,
        structure_id=current_user.id_structure,
        permission=permission,
        date_debut=datetime.utcnow(),
        date_fin=datetime.utcnow() + timedelta(hours=int(duree)),
        motif=motif
    )
    
    db.session.add(permission_temp)
    db.session.commit()
    
    flash(f'✅ Permission "{permission}" accordée à {user.prenom} {user.nom} pour {duree}h', 'success')
    return redirect(url_for('gestion_permissions'))


@app.route('/structure/permissions/revoke/<int:id>', methods=['POST'])
@login_required
def revoke_permission(id):
    """Révoquer une permission temporaire"""
    if current_user.role not in ['admin_structure']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    from models import PermissionTemp
    
    permission = PermissionTemp.query.get_or_404(id)
    
    if permission.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('gestion_permissions'))
    
    motif = request.form.get('motif_revocation', 'Révoquée par admin')
    
    permission.actif = False
    permission.date_revocation = datetime.utcnow()
    permission.revoked_by = current_user.id
    permission.motif_revocation = motif
    
    db.session.commit()
    
    flash(f'✅ Permission révoquée avec succès', 'success')
    return redirect(url_for('gestion_permissions'))


@app.route('/api/permissions/check')
@login_required
def check_permission():
    """Vérifier si l'utilisateur a une permission (pour les routes)"""
    permission = request.args.get('permission', '')
    
    if not permission:
        return jsonify({'has_permission': False})
    
    from models import PermissionTemp
    from datetime import datetime
    
    has_permission = PermissionTemp.query.filter_by(
        user_id=current_user.id,
        permission=permission,
        actif=True
    ).filter(
        PermissionTemp.date_fin > datetime.utcnow()
    ).first()
    
    # Vérifier le rôle de base
    role_permissions = {
        'medecin': ['PATIENTS', 'REFERENCE', 'HOSPITALISATION', 'STATISTIQUES'],
        'infirmier': ['PATIENTS', 'HOSPITALISATION'],
        'laborantin': ['ANALYSES'],
        'admin_structure': ['PATIENTS', 'REFERENCE', 'HOSPITALISATION', 'STATISTIQUES', 'ANALYSES']
    }
    
    base_permissions = role_permissions.get(current_user.role, [])
    
    return jsonify({
        'has_permission': bool(has_permission) or permission in base_permissions,
        'permission': permission
    })
@app.route('/reference/nouvelle', methods=['GET', 'POST'])
@login_required
def nouvelle_reference():
    """Créer une référence directement depuis l'onglet Références"""
    from models import Patient, Consultation, Reference
    from sqlalchemy import or_
    from datetime import datetime
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer les paramètres de recherche
    search = request.args.get('search', '')
    
    # Requête de base
    query = Patient.query.filter_by(
        id_structure=current_user.id_structure,
        archived=False
    )
    
    # Filtrer par recherche
    if search:
        query = query.filter(
            or_(
                Patient.nom.ilike(f'%{search}%'),
                Patient.prenom.ilike(f'%{search}%'),
                Patient.id.cast().ilike(f'%{search}%')
            )
        )
    
    patients = query.order_by(Patient.nom).all()
    
    if request.method == 'POST':
        patient_id = request.form.get('patient_id')
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')
        centre_reference = request.form.get('centre_reference')
        service_reference = request.form.get('service_reference')
        medecin_referent = request.form.get('medecin_referent')
        resume_clinique = request.form.get('resume_clinique')
        examens_realises = request.form.get('examens_realises')
        traitements_en_cours = request.form.get('traitements_en_cours')
        
        if not patient_id or not motif or not centre_reference:
            flash('Le patient, le motif et le centre de référence sont obligatoires', 'danger')
            return redirect(url_for('nouvelle_reference'))
        
        patient = Patient.query.get(patient_id)
        
        # Créer une consultation automatique
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=current_user.id,
            motif=f"Référence vers {centre_reference}",
            diagnostic=diagnostic,
            date_consultation=datetime.utcnow()
        )
        db.session.add(consultation)
        db.session.flush()
        
        # ⭐ RÉCUPÉRER LE DERNIER DIAGNOSTIC CORRECTEMENT
        dernier_diagnostic = None
        if patient.consultations:
            # Trier les consultations par date et prendre la plus récente
            consultations_triees = sorted(patient.consultations, key=lambda c: c.date_consultation, reverse=True)
            if consultations_triees and consultations_triees[0].diagnostic:
                dernier_diagnostic = consultations_triees[0].diagnostic
        
        # Créer la référence
        reference = Reference(
            patient_id=patient.id,
            consultation_id=consultation.id,
            structure_id=current_user.id_structure,
            motif=motif,
            diagnostic=diagnostic or dernier_diagnostic,
            centre_reference=centre_reference,
            service_reference=service_reference,
            medecin_referent=medecin_referent,
            derniere_tension=patient.tension_arterielle,
            derniere_temperature=patient.temperature_c,
            derniere_pulse=patient.pulse_bpm,
            derniere_saturation=patient.oxygene_saturation,
            dernier_poids=patient.poids_kg,
            derniere_taille=patient.taille_cm,
            dernier_imc=patient.imc,
            resume_clinique=resume_clinique,
            examens_realises=examens_realises,
            traitements_en_cours=traitements_en_cours,
            statut='ENVOYE',
            created_by=current_user.id
        )
        
        db.session.add(reference)
        db.session.commit()
        
        flash('✅ Référence créée avec succès', 'success')
        return redirect(url_for('imprimer_reference', id=reference.id))
    
    return render_template('references/nouvelle.html',
                         patients=patients,
                         search=search)

@app.route('/api/patient/<int:patient_id>/constantes')
@login_required
def api_patient_constantes(patient_id):
    """Récupérer les constantes d'un patient (pour AJAX)"""
    from models import Patient
    
    patient = Patient.query.get_or_404(patient_id)
    
    return jsonify({
        'tension': patient.tension_arterielle,
        'temperature': patient.temperature_c,
        'pouls': patient.pulse_bpm,
        'saturation': patient.oxygene_saturation,
        'poids': patient.poids_kg,
        'taille': patient.taille_cm,
        'imc': patient.imc
    })
@app.route('/api/patients/search')
@login_required
def api_patients_search():
    """Recherche de patients pour autocomplétion"""
    from models import Patient
    from sqlalchemy import or_, cast, String
    
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    
    patients = Patient.query.filter(
        Patient.id_structure == current_user.id_structure,
        Patient.archived == False,
        or_(
            Patient.nom.ilike(f'%{q}%'),
            Patient.prenom.ilike(f'%{q}%'),
            cast(Patient.id, String).ilike(f'%{q}%')
        )
    ).limit(20).all()
    
    result = []
    for p in patients:
        result.append({
            'id': p.id,
            'nom': p.nom,
            'prenom': p.prenom,
            'telephone': p.telephone,
            'id_padded': f"{p.id:05d}"
        })
    
    return jsonify(result)
@app.context_processor
def utility_processor():
    from models import PermissionTemp
    from datetime import datetime
    
    def has_temp_permission(permission):
        if not current_user.is_authenticated:
            return False
        
        # Vérifier les permissions temporaires
        temp_perm = PermissionTemp.query.filter(
            PermissionTemp.user_id == current_user.id,
            PermissionTemp.permission == permission,
            PermissionTemp.actif == True,
            PermissionTemp.date_fin > datetime.utcnow()
        ).first()
        
        return temp_perm is not None
    
    return dict(has_temp_permission=has_temp_permission)
# ==================== GESTION DES SALLES ====================

# ==================== GESTION DES SALLES ====================

@app.route('/salles')
@login_required
def liste_salles():
    """Liste des salles par service"""
    from models import Service, Salle, Lit  # ⭐ AJOUTER CET IMPORT
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    services = Service.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    return render_template('salles/liste.html', services=services)


@app.route('/salles/service/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_service():
    """Ajouter un service"""
    from models import Service  # ⭐ AJOUTER CET IMPORT
    
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nom = request.form.get('nom')
        description = request.form.get('description')
        
        if not nom:
            flash('Le nom du service est obligatoire', 'danger')
            return redirect(url_for('ajouter_service'))
        
        service = Service(
            structure_id=current_user.id_structure,
            nom=nom,
            description=description
        )
        db.session.add(service)
        db.session.commit()
        
        flash(f'Service "{nom}" créé avec succès', 'success')
        return redirect(url_for('liste_salles'))
    
    return render_template('salles/ajouter_service.html')


@app.route('/salles/salle/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_salle():
    """Ajouter une salle"""
    from models import Service, Salle, Lit  # ⭐ AJOUTER CES IMPORTS
    
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    services = Service.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    if request.method == 'POST':
        service_id = request.form.get('service_id')
        nom = request.form.get('nom')
        type_salle = request.form.get('type_salle')
        nombre_lits = request.form.get('nombre_lits', type=int)
        prix_journalier = request.form.get('prix_journalier', type=float)
        description = request.form.get('description')
        
        if not service_id or not nom or not type_salle or not nombre_lits:
            flash('Tous les champs obligatoires doivent être remplis', 'danger')
            return redirect(url_for('ajouter_salle'))
        
        salle = Salle(
            service_id=int(service_id),
            nom=nom,
            type_salle=type_salle,
            nombre_lits=nombre_lits,
            prix_journalier=prix_journalier,
            description=description
        )
        db.session.add(salle)
        db.session.flush()
        
        # Créer les lits
        for i in range(nombre_lits):
            lit = Lit(
                salle_id=salle.id,
                numero=chr(65 + i)  # A, B, C, D, ...
            )
            db.session.add(lit)
        
        db.session.commit()
        
        flash(f'Salle "{nom}" créée avec {nombre_lits} lits', 'success')
        return redirect(url_for('liste_salles'))
    
    return render_template('salles/ajouter_salle.html', services=services)


@app.route('/salles/salle/<int:id>')
@login_required
def detail_salle(id):
    """Détail d'une salle avec ses lits"""
    from models import Salle, Lit, Hospitalisation, Patient  # ⭐ AJOUTER CES IMPORTS
    
    salle = Salle.query.get_or_404(id)
    
    if salle.service.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_salles'))
    
    lits = Lit.query.filter_by(salle_id=id).all()
    
    # Récupérer les infos des patients pour les lits occupés
    for lit in lits:
        if lit.statut == 'occupe' and lit.hospitalisation_id:
            hospitalisation = Hospitalisation.query.get(lit.hospitalisation_id)
            if hospitalisation:
                lit.patient = hospitalisation.patient
    
    return render_template('salles/detail_salle.html', salle=salle, lits=lits)


@app.route('/hospitalisation/<int:id>/assigner-lit', methods=['POST'])
@login_required
def assigner_lit(id):
    """Assigner un lit à une hospitalisation"""
    from models import Hospitalisation, Lit
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    lit_id = request.form.get('lit_id', type=int)
    
    if not lit_id:
        flash('Veuillez sélectionner un lit', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    lit = Lit.query.get(lit_id)
    
    if not lit or lit.statut != 'disponible':
        flash('Ce lit n\'est pas disponible', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # Occuper le lit
    lit.occuper(id)
    hospitalisation.lit_id = lit.id
    hospitalisation.chambre = lit.salle.nom
    hospitalisation.lit = lit.numero
    
    db.session.commit()
    
    flash(f'Lit {lit.salle.nom} - {lit.numero} attribué avec succès', 'success')
    return redirect(url_for('detail_hospitalisation', id=id))

@app.route('/api/salles/disponibles')
@login_required
def api_salles_disponibles():
    from models import Salle, Service, Lit  # ⭐ TOUS LES IMPORTS
    
    service_nom = request.args.get('service', '')
    
    if not service_nom:
        return jsonify([])
    
    # Récupérer les salles du service
    salles = Salle.query.join(Service).filter(
        Service.nom == service_nom,
        Service.structure_id == current_user.id_structure,
        Salle.actif == True
    ).all()
    
    result = []
    for salle in salles:
        # Compter les lits disponibles
        lits_disponibles = Lit.query.filter_by(
            salle_id=salle.id,
            statut='disponible'
        ).count()
        
        result.append({
            'id': salle.id,
            'nom': salle.nom,
            'type': salle.type_salle,
            'lits_disponibles': lits_disponibles,
            'prix': salle.prix_journalier
        })
    
    return jsonify(result)

@app.route('/api/lits/disponibles')
@login_required
def api_lits_disponibles():
    """Récupérer les lits disponibles d'une salle"""
    from models import Lit
    
    salle_id = request.args.get('salle_id', type=int)
    
    if not salle_id:
        return jsonify([])
    
    lits = Lit.query.filter_by(
        salle_id=salle_id,
        statut='disponible'
    ).all()
    
    result = []
    for lit in lits:
        result.append({
            'id': lit.id,
            'numero': lit.numero
        })
    
    return jsonify(result)
# ==================== ANTÉCÉDENTS PATIENT ====================

@app.route('/patient/<int:patient_id>/antecedents')
@login_required
def patient_antecedents(patient_id):
    from models import Patient, AntecedentPatient
    
    patient = Patient.query.get_or_404(patient_id)
    antecedents = AntecedentPatient.query.filter_by(patient_id=patient_id).order_by(AntecedentPatient.date_recueil.desc()).all()
    
    # ⭐ Récupérer les paramètres de retour
    return_to = request.args.get('return_to')
    consultation_id = request.args.get('consultation_id')
    
    return render_template('patients/antecedents.html',
                         patient=patient,
                         antecedents=antecedents,
                         return_to=return_to,
                         consultation_id=consultation_id,
                         current_user=current_user)

@app.route('/patient/<int:patient_id>/antecedent/ajouter', methods=['POST'])
@login_required
def ajouter_antecedent(patient_id):
    from models import AntecedentPatient
    from datetime import datetime, timezone
    
    patient = Patient.query.get_or_404(patient_id)
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    type_antecedent = request.form.get('type_antecedent')
    type_precision = request.form.get('type_precision')
    description = request.form.get('description')
    severite = request.form.get('severite')
    date_debut = request.form.get('date_debut')
    date_fin = request.form.get('date_fin')
    traitement = request.form.get('traitement')
    notes = request.form.get('notes')
    actif = request.form.get('actif') == 'on'
    
    antecedent = AntecedentPatient(
        patient_id=patient_id,
        type_antecedent=type_antecedent,
        type_precision=type_precision if type_antecedent == 'AUTRE' else None,
        description=description,
        severite=severite if severite else None,
        date_debut=datetime.strptime(date_debut, '%Y-%m-%d').date() if date_debut else None,
        date_fin=datetime.strptime(date_fin, '%Y-%m-%d').date() if date_fin else None,
        traitement=traitement if traitement else None,
        notes=notes if notes else None,
        actif=actif,
        recueilli_par=current_user.id,
        date_recueil=datetime.now(timezone.utc)
    )
    
    db.session.add(antecedent)
    db.session.commit()
    
    # ⭐ AJOUTER UN PARAMÈTRE POUR DIFFÉRENCIER AJAX
    format = request.args.get('format')
    if format == 'json':
        return jsonify({
            'success': True,
            'message': 'Antécédent ajouté avec succès',
            'antecedent_id': antecedent.id
        })
    
    flash('✅ Antécédent ajouté avec succès', 'success')
    
    return_to = request.form.get('return_to')
    if return_to == 'pre_consultation' or current_user.role == 'infirmier':
        return redirect(url_for('infirmier_pre_consultation', patient_id=patient_id))
    else:
        return redirect(url_for('patient_antecedents', patient_id=patient_id))


@app.route('/antecedent/<int:id>/modifier', methods=['POST'])
@login_required
def modifier_antecedent(id):
    """Modifier un antécédent (médecin ou infirmier)"""
    from models import AntecedentPatient
    
    antecedent = AntecedentPatient.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Mise à jour des champs
    antecedent.type_antecedent = request.form.get('type_antecedent')
    antecedent.description = request.form.get('description')
    date_debut = request.form.get('date_debut')
    date_fin = request.form.get('date_fin')
    antecedent.actif = request.form.get('actif') == 'on'
    antecedent.severite = request.form.get('severite')
    antecedent.traitement = request.form.get('traitement')
    antecedent.notes = request.form.get('notes')
    antecedent.modified_by = current_user.id
    antecedent.modified_at = datetime.utcnow()
    
    if date_debut:
        antecedent.date_debut = datetime.strptime(date_debut, '%Y-%m-%d')
    if date_fin:
        antecedent.date_fin = datetime.strptime(date_fin, '%Y-%m-%d')
    
    db.session.commit()
    
    flash('✅ Antécédent modifié avec succès', 'success')
    return redirect(url_for('patient_antecedents', patient_id=antecedent.patient_id))


@app.route('/antecedent/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_antecedent(id):
    from models import AntecedentPatient
    
    antecedent = AntecedentPatient.query.get_or_404(id)
    patient_id = antecedent.patient_id
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    db.session.delete(antecedent)
    db.session.commit()
    
    flash('✅ Antécédent supprimé avec succès', 'success')
    
    # ⭐ REDIRECTION : Si c'est un infirmier, retour à la pré-consultation
    if current_user.role == 'infirmier':
        return redirect(url_for('infirmier_pre_consultation', patient_id=patient_id))
    else:
        return redirect(url_for('patient_antecedents', patient_id=patient_id))


@app.route('/patient/<int:patient_id>/habitudes_vie', methods=['POST'])
@login_required
def modifier_habitudes_vie(patient_id):
    from flask import jsonify
    
    patient = Patient.query.get_or_404(patient_id)
    
    patient.tabac = request.form.get('tabac')
    patient.alcool = request.form.get('alcool')
    patient.groupe_sanguin = request.form.get('groupe_sanguin')
    patient.medecin_traitant = request.form.get('medecin_traitant')
    patient.mutuelle = request.form.get('mutuelle')
    patient.allaitement = request.form.get('allaitement') == 'on'
    patient.grossesse = request.form.get('grossesse') == 'on'
    
    db.session.commit()
    
    # ⭐ SI C'EST UNE REQUÊTE AJAX, RETOURNER JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Habitudes de vie mises à jour'})
    
    # SINON, REDIRIGER NORMALEMENT
    flash('Habitudes de vie mises à jour avec succès', 'success')
    
    return_to = request.form.get('return_to') or request.args.get('return_to')
    consultation_id = request.form.get('consultation_id') or request.args.get('consultation_id')
    
    if return_to == 'consultation' and consultation_id:
        return redirect(url_for('consultation_detail', id=consultation_id))
    else:
        return redirect(url_for('patient_antecedents', patient_id=patient_id))

# Dans app.py
@app.route('/api/patient/<int:patient_id>/habitudes_vie')
@login_required
def api_patient_habitudes_vie(patient_id):
    """Récupère les habitudes de vie d'un patient"""
    from models import Patient
    
    patient = Patient.query.get_or_404(patient_id)
    
    return jsonify({
        'tabac': patient.tabac,
        'alcool': patient.alcool,
        'allaitement': patient.allaitement,
        'grossesse': patient.grossesse,
        'groupe_sanguin': patient.groupe_sanguin,
        'mutuelle': patient.mutuelle,
        'medecin_traitant': patient.medecin_traitant
    })

@app.route('/api/patient/<int:patient_id>/antecedents')
@login_required
def api_patient_antecedents(patient_id):
    """API pour récupérer les antécédents (pour le formulaire consultation)"""
    from models import AntecedentPatient
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        return jsonify([])
    
    antecedents = AntecedentPatient.query.filter_by(
        patient_id=patient_id,
        actif=True
    ).order_by(AntecedentPatient.date_recueil.desc()).all()
    
    result = []
    for a in antecedents:
        result.append({
            'id': a.id,
            'type': a.type_antecedent,
            'description': a.description,
            'date_debut': a.date_debut.strftime('%d/%m/%Y') if a.date_debut else None,
            'severite': a.severite,
            'traitement': a.traitement,
            'recueilli_par': f"{a.recueillant.prenom} {a.recueillant.nom}" if a.recueillant else 'Inconnu'
        })
    
    return jsonify(result)

@app.route('/patient/<int:id>/constante/ajouter', methods=['POST'])
@login_required
def ajouter_constante_patient(id):
    """Ajouter une nouvelle constante pour un patient (infirmier)"""
    from models import Patient
    from datetime import datetime
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    patient = Patient.query.get_or_404(id)
    
    temperature = request.form.get('temperature')
    tension = request.form.get('tension')
    pouls = request.form.get('pouls')
    saturation = request.form.get('saturation')
    poids = request.form.get('poids')
    taille = request.form.get('taille')
    imc = request.form.get('imc')
    
    # ✅ Mettre à jour les constantes (écraser les anciennes)
    if temperature:
        patient.temperature_c = float(temperature)
    if tension:
        patient.tension_arterielle = tension
    if pouls:
        patient.pulse_bpm = int(pouls)
    if saturation:
        patient.oxygene_saturation = int(saturation)
    if poids:
        patient.poids_kg = float(poids)
    if taille:
        patient.taille_cm = float(taille)
    if imc:
        patient.imc = float(imc)
    
    patient.updated_at = datetime.utcnow()
    db.session.commit()
    
    flash('✅ Nouvelles constantes enregistrées avec succès', 'success')
    return redirect(url_for('patient_detail', id=patient.id))

# ==================== ANALYSES DE RÉFÉRENCE ====================

import csv
import os
from flask import jsonify  # ⭐ IMPORTANT

_analyses_cache = None
_analyses_last_update = None

def charger_analyses_reference():
    """Charge les analyses depuis le fichier CSV (id, nom)"""
    global _analyses_cache, _analyses_last_update
    
    if _analyses_cache and _analyses_last_update:
        from datetime import datetime
        if (datetime.now() - _analyses_last_update).seconds < 3600:
            return _analyses_cache
    
    try:
        analyses_file = os.path.join(os.path.dirname(__file__), 'analyses_reference.csv')
        
        if not os.path.exists(analyses_file):
            print(f"Fichier {analyses_file} non trouve")
            return ['NFS', 'Glycemie', 'CRP', 'Radiographie']
        
        analyses_list = []
        with open(analyses_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row and len(row) >= 2:
                    nom = row[1].strip()
                    if nom:
                        analyses_list.append(nom)
                elif row and row[0].strip():
                    analyses_list.append(row[0].strip())
        
        _analyses_cache = analyses_list
        from datetime import datetime
        _analyses_last_update = datetime.now()
        
        print(f"{len(analyses_list)} analyses chargees depuis le fichier")
        return analyses_list
    except Exception as e:
        print(f"Erreur chargement analyses: {e}")
        return []

def search_analyses(search_term, limit=20):
    """Recherche des analyses par nom"""
    if not search_term or len(search_term) < 2:
        return []
    
    all_analyses = charger_analyses_reference()
    search_term = search_term.lower().strip()
    
    results = []
    for analyse in all_analyses:
        if search_term in analyse.lower():
            results.append({'nom': analyse})
            if len(results) >= limit:
                break
    
    return results

@app.route('/api/analyses/search')
@login_required
def api_analyses_search():
    """API de recherche d'analyses"""
    term = request.args.get('term', '')
    if len(term) < 2:
        return jsonify([])
    
    results = search_analyses(term)
    return jsonify(results)

@app.route('/api/analyses/ajouter', methods=['POST'])
@login_required
def api_analyses_ajouter():
    """Ajouter une nouvelle analyse au fichier CSV"""
    if current_user.role not in ['admin_structure', 'medecin']:
        return jsonify({'success': False, 'error': 'Non autorise'}), 403
    
    nom = request.json.get('nom', '').strip()
    if not nom:
        return jsonify({'success': False, 'error': 'Nom requis'}), 400
    
    analyses = charger_analyses_reference()
    if nom in analyses:
        return jsonify({'success': False, 'error': 'Deja existante'}), 400
    
    try:
        analyses_file = os.path.join(os.path.dirname(__file__), 'analyses_reference.csv')
        with open(analyses_file, 'a', encoding='utf-8') as f:
            f.write(f'\n{nom}')
        
        global _analyses_cache, _analyses_last_update
        _analyses_cache = None
        _analyses_last_update = None
        
        return jsonify({'success': True, 'message': f'Analyse "{nom}" ajoutee'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


import pdfkit
import tempfile
import os

@app.route('/patient/<int:id>/pdf')
@login_required
def patient_pdf(id):
    """Générer le dossier patient en PDF"""
    from models import Patient, Consultation, Prescription, Hospitalisation, AnalyseDemande, Reference, AntecedentPatient
    from datetime import datetime
    
    patient = Patient.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer les données
    consultations = Consultation.query.filter_by(id_patient=patient.id).order_by(
        Consultation.date_consultation.desc()
    ).all()
    
    prescriptions = Prescription.query.filter_by(id_patient=patient.id).order_by(
        Prescription.date_prescription.desc()
    ).all()
    
    hospitalisations = Hospitalisation.query.filter_by(patient_id=patient.id).order_by(
        Hospitalisation.date_debut.desc()
    ).all()
    
    analyses = AnalyseDemande.query.filter_by(patient_id=patient.id).order_by(
        AnalyseDemande.date_demande.desc()
    ).all()
    
    references = Reference.query.filter_by(patient_id=patient.id).order_by(
        Reference.date_reference.desc()
    ).all()
    
    antecedents = AntecedentPatient.query.filter_by(
        patient_id=patient.id,
        actif=True
    ).all()
    
    age = None
    if patient.date_naissance:
        today = datetime.utcnow().date()
        age = today.year - patient.date_naissance.year - ((today.month, today.day) < (patient.date_naissance.month, patient.date_naissance.day))
    
    # Rendre le template HTML
    html_content = render_template('patients/pdf.html',
                                 patient=patient,
                                 age=age,
                                 consultations=consultations,
                                 prescriptions=prescriptions,
                                 hospitalisations=hospitalisations,
                                 analyses=analyses,
                                 references=references,
                                 antecedents=antecedents,
                                 now=datetime.utcnow())
    
    # Chemin vers wkhtmltopdf
    path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
    
    # Options de configuration
    options = {
        'page-size': 'A4',
        'margin-top': '1.5cm',
        'margin-bottom': '1.5cm',
        'margin-left': '1.5cm',
        'margin-right': '1.5cm',
        'encoding': 'UTF-8',
        'enable-local-file-access': None,
        'no-stop-slow-scripts': None
    }
    
    config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
    
    # Générer le PDF
    pdf_file = pdfkit.from_string(html_content, False, options=options, configuration=config)
    
    # Créer un fichier temporaire
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as f:
        f.write(pdf_file)
        temp_path = f.name
    
    return send_file(
        temp_path,
        as_attachment=True,
        download_name=f'Dossier_Patient_{patient.prenom}_{patient.nom}_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
        mimetype='application/pdf'
    )
@app.route('/patient/<int:id>/pdf-impression')
@login_required
def patient_pdf_impression(id):
    """Version imprimable du dossier patient (pour PDF via navigateur)"""
    from models import Patient, Consultation, Prescription, Hospitalisation, AnalyseDemande, Reference, AntecedentPatient
    from datetime import datetime
    
    patient = Patient.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    consultations = Consultation.query.filter_by(id_patient=patient.id).order_by(
        Consultation.date_consultation.desc()
    ).all()
    
    prescriptions = Prescription.query.filter_by(id_patient=patient.id).order_by(
        Prescription.date_prescription.desc()
    ).all()
    
    hospitalisations = Hospitalisation.query.filter_by(patient_id=patient.id).order_by(
        Hospitalisation.date_debut.desc()
    ).all()
    
    analyses = AnalyseDemande.query.filter_by(patient_id=patient.id).order_by(
        AnalyseDemande.date_demande.desc()
    ).all()
    
    references = Reference.query.filter_by(patient_id=patient.id).order_by(
        Reference.date_reference.desc()
    ).all()
    
    antecedents = AntecedentPatient.query.filter_by(
        patient_id=patient.id,
        actif=True
    ).all()
    
    age = None
    if patient.date_naissance:
        today = datetime.utcnow().date()
        age = today.year - patient.date_naissance.year - ((today.month, today.day) < (patient.date_naissance.month, patient.date_naissance.day))
    
    return render_template('patients/pdf_impression.html',
                         patient=patient,
                         age=age,
                         consultations=consultations,
                         prescriptions=prescriptions,
                         hospitalisations=hospitalisations,
                         analyses=analyses,
                         references=references,
                         antecedents=antecedents,
                         now=datetime.utcnow())
# ==================== EXAMEN PHYSIQUE ====================

_SECTIONS_EXAMEN = None

def get_sections_examen():
    """Récupère les sections de l'examen physique"""
    global _SECTIONS_EXAMEN
    
    if _SECTIONS_EXAMEN is not None:
        return _SECTIONS_EXAMEN
    
    _SECTIONS_EXAMEN = [
        {
            'nom': 'Général',
            'icone': 'fa-user',
            'fr': 'Patient conscient, orienté, collaborant.\nBon état général.',
            'en': 'Patient conscious, oriented, cooperative.\nGood general condition.'
        },
        {
            'nom': 'Neurologique',
            'icone': 'fa-brain',
            'fr': 'Motricité et sensibilité conservées.\nRéflexes ostéotendineux présents et symétriques.\nPas de déficit neurologique.\nPas de trouble de la marche ou de l\'équilibre.',
            'en': 'Motor and sensory functions preserved.\nOsteotendinous reflexes present and symmetrical.\nNo neurological deficit.\nNo gait or balance disorders.'
        },
        {
            'nom': 'Cardiovasculaire',
            'icone': 'fa-heart',
            'fr': 'Bruits du cœur réguliers, rythme sinusal régulier.\nPas de souffle cardiaque.\nPulsations périphériques présentes et symétriques.\nPas d\'œdème des membres inférieurs.',
            'en': 'Regular heart sounds, regular sinus rhythm.\nNo heart murmur.\nPeripheral pulses present and symmetrical.\nNo lower limb edema.'
        },
        {
            'nom': 'Respiratoire',
            'icone': 'fa-lungs',
            'fr': 'Auscultation pulmonaire normale, murmure vésiculaire bien perçu.\nPas de bruits anormaux (crépitants, sibilants).\nPas de douleur thoracique à la respiration.',
            'en': 'Normal lung auscultation, vesicular breath sounds well heard.\nNo abnormal sounds (crackles, wheezes).\nNo chest pain on respiration.'
        },
        {
            'nom': 'Digestif',
            'icone': 'fa-stomach',
            'fr': 'Abdomen souple, non douloureux à la palpation.\nBruits hydro-aériques présents.\nPas de masse, pas de défense.\nPas de douleur à la décompression.',
            'en': 'Soft abdomen, non-tender on palpation.\nBowel sounds present.\nNo mass, no guarding.\nNo pain on decompression.'
        },
        {
            'nom': 'Splénoganglionnaire',
            'icone': 'fa-blood',
            'fr': 'Pas de splénomégalie palpable.\nPas de polyadénopathie périphérique palpable.\nAires ganglionnaires libres.',
            'en': 'No palpable splenomegaly.\nNo palpable peripheral lymphadenopathy.\nLymph node areas clear.'
        },
        {
            'nom': 'Urogénital',
            'icone': 'fa-kidney',
            'fr': 'Examen urogénital normal.\nPas de douleur à la palpation des fosses lombaires.\nPas de globe vésical.\nOrganes génitaux externes normaux.',
            'en': 'Normal urogenital examination.\nNo pain on palpation of the lumbar fossae.\nNo urinary retention.\nNormal external genitalia.'
        },
        {
            'nom': 'Odonto-stomatologique',
            'icone': 'fa-tooth',
            'fr': 'Cavité buccale normale, muqueuse buccale saine.\nPas de lésion, pas d\'infection.\nDents en bon état.\nPas de mobilité dentaire anormale.',
            'en': 'Normal oral cavity, healthy oral mucosa.\nNo lesions, no infection.\nTeeth in good condition.\nNo abnormal tooth mobility.'
        },
        {
            'nom': 'Dermatologique',
            'icone': 'fa-hand',
            'fr': 'Peau normale, pas de lésion, pas d\'éruption.\nMuqueuses sèches et normales.\nPas de prurit.\nOngles normaux.',
            'en': 'Normal skin, no lesions, no rash.\nMucous membranes dry and normal.\nNo pruritus.\nNormal nails.'
        },
        {
            'nom': 'Locomoteur (Ostéo-articulaire)',
            'icone': 'fa-bone',
            'fr': 'Amplitudes articulaires complètes.\nPas de déformation, pas de douleur à la mobilisation.\nPas de limitation de mouvement.\nPas de raideur.',
            'en': 'Complete joint ranges of motion.\nNo deformity, no pain on mobilization.\nNo limitation of movement.\nNo stiffness.'
        },
        {
            'nom': 'Oto-rhino-laryngologique',
            'icone': 'fa-ear-deaf',
            'fr': 'Conduits auditifs externes libres, tympans normaux.\nFosses nasales libres, muqueuse normale.\nPharynx normal.\nPas de douleur à la mastication.',
            'en': 'External auditory canals clear, normal tympanic membranes.\nNasal passages clear, normal mucosa.\nNormal pharynx.\nNo pain on mastication.'
        },
        {
            'nom': 'Endocrinien',
            'icone': 'fa-flask',
            'fr': 'Pas de goitre palpable à la palpation cervicale.\nPas de signe d\'hypo ou hyperthyroïdie.\nPas de trouble de la croissance ou du développement.',
            'en': 'No palpable goiter on cervical palpation.\nNo signs of hypo or hyperthyroidism.\nNo growth or developmental disorders.'
        },
        {
            'nom': 'Psychiatrique',
            'icone': 'fa-brain',
            'fr': 'Humeur stable, contact facile et approprié.\nPas de trouble du comportement, pas d\'idées délirantes.\nPas de trouble de l\'humeur.\nPas d\'anxiété ou de dépression.',
            'en': 'Stable mood, easy and appropriate contact.\nNo behavioral disorders, no delusional ideas.\nNo mood disorders.\nNo anxiety or depression.'
        },
        {
            'nom': 'Autre à préciser',
            'icone': 'fa-plus-circle',
            'fr': 'Section personnalisée à ajouter selon les besoins de l\'examen.',
            'en': 'Custom section to add according to the needs of the examination.'
        }
    ]
    
    return _SECTIONS_EXAMEN

@app.route('/api/examen-physique/sections')
@login_required
def api_sections_examen():
    """Récupère les sections de l'examen physique"""
    lang = request.args.get('lang', 'fr')
    sections = get_sections_examen()
    
    result = []
    for s in sections:
        result.append({
            'nom': s['nom'],
            'icone': s['icone'],
            'texte': s['fr'] if lang == 'fr' else s['en']
        })
    
    return jsonify(result)


@app.route('/consultation/<int:id>/examen-physique')
@login_required
def examen_physique(id):
    """Page de l'examen physique"""
    from models import Consultation, Patient, ExamenPhysique
    
    consultation = Consultation.query.get_or_404(id)
    patient = Patient.query.get(consultation.id_patient)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer l'examen existant
    examen = ExamenPhysique.query.filter_by(consultation_id=id).first()
    
    return render_template('consultations/examen_physique.html',
                         consultation=consultation,
                         patient=patient,
                         examen=examen)
@app.route('/patient/<int:patient_id>/examen-physique/ajouter')
@login_required
def examen_physique_ajouter(patient_id):
    from models import Patient, Consultation
    from datetime import datetime
    
    patient = Patient.query.get_or_404(patient_id)
    
    if patient.id_structure != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # ⭐ VÉRIFIER SI UNE CONSULTATION TEMPORAIRE EXISTE DÉJÀ
    consultation_temp = Consultation.query.filter_by(
        id_patient=patient.id,
        is_temporary=True
    ).first()
    
    if consultation_temp:
        consultation = consultation_temp
        print(f"📋 Consultation temporaire existante: #{consultation.id}")
    else:
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=current_user.id,
            date_consultation=datetime.utcnow(),
            is_temporary=True,
            statut='en_cours'
        )
        db.session.add(consultation)
        db.session.commit()
        print(f"✅ Nouvelle consultation temporaire créée avec ID: {consultation.id}")
    
    # ⭐ REDIRIGER VERS LA PAGE D'EXAMEN AVEC L'ID DANS L'URL
    return redirect(url_for('examen_physique_page', consultation_id=consultation.id))


@app.route('/examen-physique/<int:consultation_id>')
@login_required
def examen_physique_page(consultation_id):
    """Affiche la page d'examen physique avec l'ID de consultation"""
    from models import Consultation, Patient, ExamenPhysique
    
    consultation = Consultation.query.get_or_404(consultation_id)
    patient = Patient.query.get(consultation.id_patient)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer l'examen existant
    examen = ExamenPhysique.query.filter_by(consultation_id=consultation_id).first()
    
    return render_template('consultations/examen_physique.html',
                         patient=patient,
                         consultation=consultation,
                         examen=examen)

@app.route('/patient/<int:patient_id>/examen-physique/creer-temporaire', methods=['POST'])
@login_required
def creer_consultation_temporaire(patient_id):
    """Crée une consultation temporaire et retourne l'ID"""
    from models import Patient, Consultation
    from flask import jsonify
    from datetime import datetime
    
    patient = Patient.query.get_or_404(patient_id)
    
    if patient.id_structure != current_user.id_structure:
        return jsonify({'success': False, 'message': 'Accès non autorisé'}), 403
    
    # Vérifier si une consultation temporaire existe
    consultation_temp = Consultation.query.filter_by(
        id_patient=patient.id,
        is_temporary=True
    ).first()
    
    if consultation_temp:
        consultation = consultation_temp
    else:
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=current_user.id,
            date_consultation=datetime.utcnow(),
            is_temporary=True,
            statut='en_cours'
        )
        db.session.add(consultation)
        db.session.commit()
    
    return jsonify({
        'success': True,
        'consultation_id': consultation.id,
        'patient_id': patient.id
    })

@app.route('/consultation/<int:id>/examen-physique/enregistrer', methods=['POST'])
@login_required
def enregistrer_examen_physique(id):
    from models import Consultation, ExamenPhysique
    from datetime import datetime
    from flask import jsonify
    import json
    import re
    
    print(f"🟢 Enregistrement examen physique pour consultation ID: {id}")
    
    consultation = Consultation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Accès non autorisé'}), 403
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        examen_complet = request.form.get('examen_complet', '')
        sections_modifiees = request.form.get('sections_modifiees', '{}')
        
        print(f"📝 Examen complet reçu: {len(examen_complet)} caractères")
        
        examen_complet = nettoyer_examen_complet(examen_complet)
        
        examen = ExamenPhysique.query.filter_by(consultation_id=id).first()
        
        if examen:
            examen.examen_complet = examen_complet
            examen.sections_modifiees = sections_modifiees
            examen.modified_at = datetime.utcnow()
            print(f"🔄 Examen physique #{examen.id} mis à jour")
        else:
            examen = ExamenPhysique(
                consultation_id=id,
                examen_complet=examen_complet,
                sections_modifiees=sections_modifiees,
                created_by=current_user.id
            )
            db.session.add(examen)
            print(f"✅ Nouvel examen physique créé pour consultation #{id}")
        
        # Mettre à jour les notes cliniques
        if examen_complet and examen_complet.strip():
            if consultation.notes_cliniques:
                if "--- EXAMEN PHYSIQUE ---" not in consultation.notes_cliniques:
                    consultation.notes_cliniques = consultation.notes_cliniques + f"\n\n--- EXAMEN PHYSIQUE ---\n{examen_complet}"
                else:
                    pattern = r'--- EXAMEN PHYSIQUE ---\n.*?(?=\n---|$)'
                    consultation.notes_cliniques = re.sub(pattern, f"--- EXAMEN PHYSIQUE ---\n{examen_complet}", consultation.notes_cliniques, flags=re.DOTALL)
            else:
                consultation.notes_cliniques = f"--- EXAMEN PHYSIQUE ---\n{examen_complet}"
        
        db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'message': 'Examen enregistré avec succès',
                'examen_id': examen.id,
                'consultation_id': consultation.id,
                'examen_complet': examen_complet  # ⭐ AJOUTER CECI
            })
        
        flash('✅ Examen physique enregistré avec succès', 'success')
        return redirect(url_for('consultation_detail', id=id))
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500
        
        flash(f'❌ Erreur: {str(e)}', 'danger')
        return redirect(url_for('consultation_detail', id=id))


def nettoyer_examen_complet(examen_complet):
    """Supprime les sections vides ou non modifiées"""
    if not examen_complet:
        return ''
    
    lines = examen_complet.split('\n')
    result = []
    skip_next = False
    
    for line in lines:
        if '═══════════════════════════════════════════════════' in line:
            result.append(line)
            continue
        
        if 'section(s) active(s)' in line or 'modification(s)' in line:
            result.append(line)
            continue
        
        if '--- AUTRE À PRÉCISER ---' in line:
            skip_next = True
            continue
        
        if skip_next:
            if not line.strip() or line.strip() == '':
                skip_next = False
            continue
        
        if '---' in line and 'AUTRE À PRÉCISER' not in line:
            result.append(line)
            continue
        
        if line.strip() and 'Section personnalisée' not in line:
            result.append(line)
    
    return '\n'.join(result)


@app.route('/cleanup-temp-consultations')
@login_required
def cleanup_temp_consultations():
    """Supprime les consultations temporaires sans examen"""
    from models import Consultation, ExamenPhysique
    
    if current_user.role not in ['admin_structure']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Trouver les consultations temporaires sans examen
    temp_consultations = Consultation.query.filter_by(statut='en_cours').all()
    deleted = 0
    
    for c in temp_consultations:
        examen = ExamenPhysique.query.filter_by(consultation_id=c.id).first()
        if not examen:
            db.session.delete(c)
            deleted += 1
    
    db.session.commit()
    flash(f'{deleted} consultation(s) temporaire(s) nettoyée(s)', 'success')
    return redirect(url_for('dashboard'))


# ==================== SYNCHRONISATION GHP ====================

import requests
import uuid
from datetime import datetime

@app.route('/sync/ghp')
@login_required
def sync_ghp_config():
    """Page de configuration de la synchronisation GHP"""
    from models import Structure, StructureMapping
    
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    structures = Structure.query.filter_by(
        id_structure=current_user.id_structure,
        actif=True
    ).all() if current_user.role == 'super_admin' else Structure.query.filter_by(id=current_user.id_structure).all()
    
    mappings = StructureMapping.query.filter_by(local_structure_id=current_user.id_structure).all()
    
    return render_template('sync/mapping.html', 
                         structures=structures,
                         mappings=mappings)


@app.route('/sync/ghp', methods=['POST'])
@login_required
def sync_ghp_save():
    """Enregistrer une configuration de mapping"""
    from models import StructureMapping
    
    if current_user.role != 'admin_structure':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    local_structure_id = request.form.get('local_structure_id', type=int)
    source_structure_id = request.form.get('source_structure_id', type=int)
    api_url = request.form.get('api_url')
    api_key = request.form.get('api_key')
    
    if not local_structure_id or not source_structure_id:
        flash('Tous les champs sont obligatoires', 'danger')
        return redirect(url_for('sync_ghp_config'))
    
    # Vérifier si le mapping existe déjà
    mapping = StructureMapping.query.filter_by(
        local_structure_id=local_structure_id,
        source_structure_id=source_structure_id
    ).first()
    
    if mapping:
        mapping.api_url = api_url
        mapping.api_key = api_key
        mapping.actif = True
    else:
        mapping = StructureMapping(
            local_structure_id=local_structure_id,
            source_structure_id=source_structure_id,
            api_url=api_url,
            api_key=api_key,
            source_name='ghp'
        )
        db.session.add(mapping)
    
    db.session.commit()
    
    flash('✅ Configuration enregistrée avec succès', 'success')
    return redirect(url_for('sync_ghp_config'))

# ============================================================
# FONCTIONS DE NORMALISATION
# ============================================================

def normalize_assurance_type(value):
    """
    Normalise le type d'assurance pour standardiser les valeurs
    """
    if not value:
        return 'NON_ASSURÉ'
    
    # Convertir en string et mettre en minuscules
    value = str(value).lower().strip()
    
    # Mapping des valeurs
    mapping = {
        # AMU-CNSS
        'amu_cnss': 'AMU-CNSS',
        'amu-cnss': 'AMU-CNSS',
        'amucnss': 'AMU-CNSS',
        'amu cnss': 'AMU-CNSS',
        'cnss': 'AMU-CNSS',
        
        # AMU-INAM
        'amu_inam': 'AMU-INAM',
        'amu-inam': 'AMU-INAM',
        'amuinam': 'AMU-INAM',
        'amu inam': 'AMU-INAM',
        'inam': 'AMU-INAM',
        
        # Autre assurance
        'autre_assurance': 'AUTRE_ASSURANCE',
        'autre-assurance': 'AUTRE_ASSURANCE',
        'autre assurance': 'AUTRE_ASSURANCE',
        'autre': 'AUTRE_ASSURANCE',
        'other': 'AUTRE_ASSURANCE',
        
        # Non assuré
        'non_assure': 'NON_ASSURÉ',
        'non-assure': 'NON_ASSURÉ',
        'non assure': 'NON_ASSURÉ',
        'nonassure': 'NON_ASSURÉ',
        'non': 'NON_ASSURÉ',
        'aucune': 'NON_ASSURÉ',
        '': 'NON_ASSURÉ',
    }
    
    # Vérifier si la valeur existe dans le mapping
    if value in mapping:
        return mapping[value]
    
    # Si la valeur contient 'amu' ou 'assurance', essayer de deviner
    if 'amu' in value or 'assurance' in value:
        if 'cnss' in value or 'inam' in value:
            # Essayer de trouver le type
            if 'cnss' in value:
                return 'AMU-CNSS'
            elif 'inam' in value:
                return 'AMU-INAM'
    
    # Si rien ne correspond, retourner la valeur en majuscules
    return value.upper().replace('_', '-')

def sync_patients_from_ghp(structure_mapping):
    """
    Synchronise UNIQUEMENT les informations patient depuis GHP
    Version avec normalisation des données
    """
    from models import Patient, Utilisateur
    from datetime import datetime
    import uuid
    import requests
    
    try:
        token = structure_mapping.api_key
        
        if not token:
            print("❌ Token manquant dans le mapping")
            return {'cree': 0, 'mis_a_jour': 0, 'erreur': 0, 'message': 'Token manquant'}
        
        url = f"{structure_mapping.api_url}/api/sync/patients"
        params = {'token': token}
        
        print(f"🔄 Synchronisation depuis: {url}")
        
        response = requests.get(url, params=params, timeout=60)
        
        if response.status_code != 200:
            print(f"❌ Erreur API GHP: {response.status_code}")
            return {'cree': 0, 'mis_a_jour': 0, 'erreur': 1, 'message': f'Erreur API: {response.status_code}'}
        
        data = response.json()
        patients = data.get('patients', [])
        
        print(f"✅ {len(patients)} patients récupérés depuis GHP")
        
        compteur = {'cree': 0, 'mis_a_jour': 0, 'erreur': 0}
        
        # ⭐⭐⭐ AUCUN MÉDECIN RÉFÉRENT N'EST ASSIGNÉ ICI ⭐⭐⭐
        # Le médecin référent sera assigné lors de la première consultation
        print("ℹ️ Aucun médecin référent assigné automatiquement - assignation lors de la première consultation")
        
        for p_data in patients:
            try:
                source_id = p_data.get('ID')
                if not source_id:
                    compteur['erreur'] += 1
                    print(f"❌ Patient sans ID ignoré")
                    continue
                
                # NORMALISATION DES DONNÉES
                raw_type = p_data.get('type_assurance') or p_data.get('TypeAssurance') or 'non_assure'
                type_assurance = normalize_assurance_type(raw_type)
                
                taux_prise_charge = p_data.get('taux_assurance') or p_data.get('taux_prise_charge') or 0
                numero_assure = p_data.get('numero_assure') or p_data.get('NumeroAssure') or p_data.get('num_assure') or ''
                
                assurance2_nom = p_data.get('assurance2_nom') or p_data.get('Assurance2Nom') or ''
                if assurance2_nom:
                    assurance2_nom = assurance2_nom.upper().strip()
                
                taux_assurance2 = p_data.get('taux_assurance2') or p_data.get('TauxAssurance2') or 0
                numero_assure2 = p_data.get('numero_assure2') or p_data.get('NumeroAssure2') or ''
                
                personne_a_prevenir_nom = p_data.get('personne_a_prevenir_nom') or p_data.get('PersonneAPrevenirNom') or ''
                personne_a_prevenir_telephone = p_data.get('personne_a_prevenir_telephone') or p_data.get('PersonneAPrevenirTelephone') or ''
                personne_a_prevenir_relation = p_data.get('personne_a_prevenir_relation') or p_data.get('PersonneAPrevenirRelation') or ''
                
                # Date de naissance
                date_naissance = p_data.get('date_naissance')
                if date_naissance and isinstance(date_naissance, str):
                    try:
                        date_naissance = datetime.strptime(date_naissance, '%Y-%m-%d').date()
                    except:
                        date_naissance = None
                elif isinstance(date_naissance, datetime):
                    date_naissance = date_naissance.date()
                
                # Chercher si le patient existe déjà
                patient = Patient.query.filter_by(
                    patient_source_id=str(source_id),
                    source_structure_id=structure_mapping.source_structure_id,
                    id_structure=structure_mapping.local_structure_id
                ).first()
                
                if patient:
                    # 📝 MISE À JOUR DU PATIENT EXISTANT
                    print(f"📝 Mise à jour: {p_data.get('nom')} {p_data.get('prenom')} (ID GHP: {source_id})")
                    
                    patient.nom = p_data.get('nom') or ''
                    patient.prenom = p_data.get('prenom') or ''
                    patient.telephone = str(p_data.get('telephone') or '')
                    patient.adresse = p_data.get('adresse') or ''
                    patient.date_naissance = date_naissance
                    
                    # ASSURANCE PRINCIPALE
                    patient.type_assurance = type_assurance
                    patient.taux_prise_charge = str(taux_prise_charge) if taux_prise_charge else None
                    patient.numero_assure = str(numero_assure) if numero_assure else ''
                    
                    # ASSURANCE 2
                    patient.assurance2_nom = assurance2_nom if assurance2_nom else None
                    patient.taux_assurance2 = float(taux_assurance2) if taux_assurance2 else None
                    patient.numero_assure2 = str(numero_assure2) if numero_assure2 else ''
                    
                    # PERSONNE À PRÉVENIR
                    patient.personne_a_prevenir_nom = personne_a_prevenir_nom
                    patient.personne_a_prevenir_telephone = personne_a_prevenir_telephone
                    patient.personne_a_prevenir_relation = personne_a_prevenir_relation
                    
                    # ⭐⭐⭐ ON NE TOUCHE PAS AU MÉDECIN RÉFÉRENT ⭐⭐⭐
                    # Le médecin référent reste celui qui a été assigné lors de la première consultation
                    print(f"   👨‍⚕️ Médecin référent actuel: ID {patient.id_medecin_referent if patient.id_medecin_referent else 'Aucun'}")
                    
                    patient.synced_at = datetime.utcnow()
                    patient.synced_from = 'ghp'
                    compteur['mis_a_jour'] += 1
                    
                else:
                    # ➕ CRÉATION D'UN NOUVEAU PATIENT
                    print(f"➕ Création: {p_data.get('nom')} {p_data.get('prenom')} (ID GHP: {source_id})")
                    
                    patient = Patient(
                        id_structure=structure_mapping.local_structure_id,
                        uuid=str(uuid.uuid4()),
                        patient_source_id=str(source_id),
                        source_structure_id=structure_mapping.source_structure_id,
                        source_name='ghp',
                        
                        # Identité
                        nom=p_data.get('nom') or '',
                        prenom=p_data.get('prenom') or '',
                        telephone=str(p_data.get('telephone') or ''),
                        adresse=p_data.get('adresse') or '',
                        date_naissance=date_naissance,
                        
                        # ASSURANCE PRINCIPALE
                        type_assurance=type_assurance,
                        taux_prise_charge=str(taux_prise_charge) if taux_prise_charge else None,
                        numero_assure=str(numero_assure) if numero_assure else '',
                        
                        # ASSURANCE 2
                        assurance2_nom=assurance2_nom if assurance2_nom else None,
                        taux_assurance2=float(taux_assurance2) if taux_assurance2 else None,
                        numero_assure2=str(numero_assure2) if numero_assure2 else '',
                        
                        # PERSONNE À PRÉVENIR
                        personne_a_prevenir_nom=personne_a_prevenir_nom,
                        personne_a_prevenir_telephone=personne_a_prevenir_telephone,
                        personne_a_prevenir_relation=personne_a_prevenir_relation,
                        
                        # Autres champs
                        lieu_naissance=p_data.get('lieu_naissance') or '',
                        sexe=p_data.get('sexe') or '',
                        email=p_data.get('email') or '',
                        profession=p_data.get('profession') or '',
                        
                        # ⭐⭐⭐ PAS DE MÉDECIN RÉFÉRENT À LA CRÉATION ⭐⭐⭐
                        id_medecin_referent=None,  # Sera assigné lors de la première consultation
                        
                        # Statut
                        statut_medical='PREMIERE_VISITE',
                        archived=False,
                        
                        # Métadonnées
                        synced_at=datetime.utcnow(),
                        synced_from='ghp'
                    )
                    
                    db.session.add(patient)
                    compteur['cree'] += 1
                    
                    print(f"   ℹ️ Patient créé sans médecin référent - sera assigné lors de la première consultation")
                
                db.session.flush()
                
            except Exception as e:
                compteur['erreur'] += 1
                print(f"❌ Erreur patient {p_data.get('ID')}: {e}")
                import traceback
                traceback.print_exc()
                db.session.rollback()
                continue
        
        # Mettre à jour la date de dernière synchronisation
        structure_mapping.last_sync = datetime.utcnow()
        db.session.commit()
        
        message = f"✅ Sync terminée: {compteur['cree']} créés, {compteur['mis_a_jour']} mis à jour, {compteur['erreur']} erreurs"
        print(message)
        
        return {
            'cree': compteur['cree'],
            'mis_a_jour': compteur['mis_a_jour'],
            'erreur': compteur['erreur'],
            'message': message,
            'total': len(patients)
        }
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur de connexion à GHP: {e}")
        return {
            'cree': 0,
            'mis_a_jour': 0,
            'erreur': 1,
            'message': f'Erreur de connexion: {str(e)}'
        }
    except Exception as e:
        print(f"❌ Erreur générale: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return {
            'cree': 0,
            'mis_a_jour': 0,
            'erreur': 1,
            'message': f'Erreur: {str(e)}'
        }


@app.route('/api/sync/patients/<int:mapping_id>', methods=['POST'])
@login_required
def api_sync_patients(mapping_id):
    """Déclencher la synchronisation des patients depuis GHP"""
    from models import StructureMapping
    
    if current_user.role not in ['admin_structure', 'super_admin']:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    mapping = StructureMapping.query.get_or_404(mapping_id)
    
    if mapping.local_structure_id != current_user.id_structure:
        return jsonify({'success': False, 'message': 'Accès non autorisé'}), 403
    
    if not mapping.api_key:
        return jsonify({
            'success': False,
            'message': 'Token manquant dans la configuration'
        }), 400
    
    try:
        # ⭐ APPELER LA FONCTION DE SYNCHRONISATION
        resultat = sync_patients_from_ghp(mapping)
        
        if resultat.get('erreur', 0) > 0 and resultat.get('cree', 0) == 0 and resultat.get('mis_a_jour', 0) == 0:
            return jsonify({
                'success': False,
                'message': resultat.get('message', 'Erreur lors de la synchronisation'),
                'details': resultat
            }), 500
        
        return jsonify({
            'success': True,
            'message': resultat.get('message', 'Synchronisation terminée'),
            'details': {
                'cree': resultat.get('cree', 0),
                'mis_a_jour': resultat.get('mis_a_jour', 0),
                'erreur': resultat.get('erreur', 0),
                'total': resultat.get('total', 0)
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        }), 500

@app.route('/api/webhook/patient-created', methods=['POST'])
def webhook_patient_created():
    from models import StructureMapping
    from threading import Thread
    import os
    
    try:
        webhook_secret = os.environ.get('WEBHOOK_SECRET', 'mon_secret_webhook_123456')
        token = request.headers.get('X-Webhook-Token')
        
        if token != webhook_secret:
            return jsonify({'success': False, 'message': 'Token invalide'}), 401
        
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'Données JSON manquantes'}), 400
        
        patient_id = data.get('patient_id')
        structure_id = data.get('structure_id')
        
        if not patient_id or not structure_id:
            return jsonify({'success': False, 'message': 'patient_id et structure_id sont obligatoires'}), 400
        
        mapping = StructureMapping.query.filter_by(
            local_structure_id=structure_id,
            actif=True
        ).first()
        
        if not mapping:
            return jsonify({
                'success': False,
                'message': f'Configuration GHP non trouvée pour la structure {structure_id}'
            }), 404
        
        def sync_in_background():
            with app.app_context():
                try:
                    print(f"⚡ Webhook: Sync immédiate patient {patient_id}")
                    resultat = sync_patients_from_ghp(mapping)
                    
                    if resultat.get('cree', 0) > 0:
                        print(f"✅ Patient {patient_id} synchronisé immédiatement")
                    else:
                        print(f"⚠️ Patient {patient_id} déjà existant ou non trouvé")
                except Exception as e:
                    print(f"❌ Erreur webhook patient {patient_id}: {e}")
                    import traceback
                    traceback.print_exc()
        
        Thread(target=sync_in_background).start()
        
        print(f"📡 Webhook: Sync déclenchée pour patient {patient_id}")
        
        return jsonify({
            'success': True,
            'message': f'Synchronisation déclenchée en arrière-plan pour patient {patient_id}'
        })
        
    except Exception as e:
        print(f"❌ Erreur webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur interne: {str(e)}'
        }), 500

# ═══════════════════════════════════════════
# ROUTE DE TEST DU WEBHOOK
# ═══════════════════════════════════════════

# app.py - Ajouter cette route

@app.route('/api/webhook/test', methods=['GET', 'POST'])
def webhook_test():
    """
    Route de test pour vérifier que le webhook est accessible
    """
    if request.method == 'POST':
        data = request.json or {}
        return jsonify({
            'success': True,
            'message': 'Webhook accessible',
            'received_data': data,
            'headers': dict(request.headers)
        })
    else:
        return jsonify({
            'success': True,
            'message': '✅ Webhook accessible',
            'instructions': 'Envoyer une requête POST avec patient_id et structure_id',
            'example': {
                'url': '/api/webhook/patient-created',
                'method': 'POST',
                'headers': {
                    'X-Webhook-Token': 'mon_secret_webhook_123456',
                    'Content-Type': 'application/json'
                },
                'body': {
                    'patient_id': 123,
                    'structure_id': 1
                }
            }
        })

@app.route('/api/sync/mapping/<int:id>', methods=['DELETE'])
@login_required
def api_delete_mapping(id):
    """Supprimer un mapping"""
    from models import StructureMapping
    
    mapping = StructureMapping.query.get_or_404(id)
    
    if mapping.local_structure_id != current_user.id_structure:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    db.session.delete(mapping)
    db.session.commit()
    
    return jsonify({'success': True})
@app.route('/patient/<int:patient_id>/update-habitudes', methods=['POST'])
@login_required
def patient_update_habitudes(patient_id):
    """Mettre à jour les habitudes de vie du patient"""
    from models import Patient
    from flask import jsonify
    
    patient = Patient.query.get_or_404(patient_id)
    
    # Vérifier les permissions
    if current_user.role not in ['admin_structure', 'medecin', 'infirmier']:
        return jsonify({'success': False, 'message': 'Accès non autorisé'}), 403
    
    try:
        # Récupérer les données
        tabac = request.form.get('tabac')
        alcool = request.form.get('alcool')
        allaitement = request.form.get('allaitement')
        grossesse = request.form.get('grossesse')
        groupe_sanguin = request.form.get('groupe_sanguin')
        mutuelle = request.form.get('mutuelle')
        medecin_traitant = request.form.get('medecin_traitant')
        
        # Mettre à jour
        patient.tabac = tabac if tabac else None
        patient.alcool = alcool if alcool else None
        patient.allaitement = allaitement == 'Oui'
        patient.grossesse = grossesse == 'Oui'
        patient.groupe_sanguin = groupe_sanguin if groupe_sanguin else None
        patient.mutuelle = mutuelle if mutuelle else None
        patient.medecin_traitant = medecin_traitant if medecin_traitant else None
        
        db.session.commit()
        
        # ⭐ RETOURNER JSON (pour l'appel AJAX)
        return jsonify({'success': True, 'message': 'Habitudes de vie mises à jour avec succès'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/medicaments/disponibles')
@login_required
def api_medicaments_disponibles():
    """
    Récupère les médicaments depuis Google Sheets (via GHP)
    """
    from models import StructureMapping
    import requests
    
    # Récupérer le mapping GHP
    mapping = StructureMapping.query.filter_by(
        local_structure_id=current_user.id_structure,
        actif=True
    ).first()
    
    if not mapping:
        return jsonify([])
    
    try:
        # Appeler l'API de GHP pour récupérer les médicaments
        url = f"{mapping.api_url}/api/medicaments"
        params = {'token': mapping.api_key}
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return jsonify([])
        
        data = response.json()
        medicaments = data.get('medicaments', [])
        
        # Filtrer et formater pour le médecin
        result = []
        for m in medicaments:
            # ⭐ Le médecin voit seulement le nom et le stock
            result.append({
                'id': m.get('ID'),
                'nom': m.get('nom', ''),
                'quantite_stock': m.get('quantite_stock', 0)
            })
        
        # Trier par nom
        result.sort(key=lambda x: x['nom'])
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Erreur récupération médicaments: {e}")
        return jsonify([])

@app.route('/api/medicamentos/disponibles')
@login_required
def api_medicamentos_disponibles():
    """
    Récupère les médicaments disponibles depuis GHP
    Le médecin voit seulement : id, nom, quantite_stock
    """
    from models import StructureMapping
    import requests
    
    # Récupérer le mapping GHP
    mapping = StructureMapping.query.filter_by(
        local_structure_id=current_user.id_structure,
        actif=True
    ).first()
    
    if not mapping:
        print(f"⚠️ Aucun mapping GHP trouvé pour la structure {current_user.id_structure}")
        return jsonify([])
    
    try:
        # Appeler l'API de GHP pour récupérer les médicaments
        url = f"{mapping.api_url}/api/medicamentos"
        params = {'token': mapping.api_key}
        
        print(f"📡 Récupération des médicaments depuis: {url}")
        print(f"   Structure source: {mapping.source_structure_id}")
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Erreur GHP: {response.status_code} - {response.text[:100]}")
            return jsonify([])
        
        data = response.json()
        medicamentos = data.get('medicamentos', [])
        
        # Formater pour le médecin (seulement nom + stock)
        result = []
        for m in medicamentos:
            if m.get('nom'):
                result.append({
                    'id': m.get('ID'),
                    'nom': m.get('nom', ''),
                    'quantite_stock': m.get('quantite_stock', 0)
                })
        
        result.sort(key=lambda x: x['nom'])
        
        print(f"✅ {len(result)} médicaments disponibles chargés")
        return jsonify(result)
        
    except requests.exceptions.Timeout:
        print("❌ Timeout lors de la récupération des médicaments")
        return jsonify([])
    except requests.exceptions.ConnectionError:
        print("❌ Erreur de connexion à GHP")
        return jsonify([])
    except Exception as e:
        print(f"❌ Erreur récupération médicaments: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([])

@app.route('/api/sync/prescriptions', methods=['POST'])
@login_required
def api_sync_prescriptions_to_ghp():
    """
    Envoie les prescriptions vers GHP
    """
    from models import Prescription, Patient, StructureMapping
    from datetime import datetime
    import requests

    try:
        # ⭐ Récupérer le mapping GHP
        mapping = StructureMapping.query.filter_by(
            local_structure_id=current_user.id_structure,
            actif=True
        ).first()

        if not mapping:
            return jsonify({'success': False, 'message': 'Configuration GHP non trouvée'}), 400

        # ⭐ Récupérer les prescriptions non synchronisées — UNIQUEMENT
        # celles dont le patient appartient à la structure de cet
        # utilisateur (sinon, avec plusieurs structures actives sur ce
        # déploiement, on enverrait aussi les prescriptions des AUTRES
        # structures avec le mapping/token de celle-ci).
        prescriptions = (
            Prescription.query
            .join(Patient, Prescription.id_patient == Patient.id)
            .filter(
                Prescription.synced_at.is_(None),
                Prescription.statut == 'active',
                Patient.id_structure == current_user.id_structure,
            )
            .all()
        )
        
        if not prescriptions:
            return jsonify({'success': True, 'message': 'Aucune prescription à synchroniser'})
        
        # ⭐ Formater les données
        data = []
        for p in prescriptions:
            # 🔥 Déterminer le type automatiquement
            type_presc = 'medicament'  # Par défaut
            
            # Si c'est un acte (ex: contient des mots-clés)
            mots_actes = ['examen', 'radio', 'scan', 'echo', 'analyse', 'test', 'biopsie', 'radiographie', 'irm']
            if p.medicament and any(mot in p.medicament.lower() for mot in mots_actes):
                type_presc = 'acte'
            
            # Ou si c'est un médicament (par défaut)
            presc_data = {
                'id': p.id,
                'patient_id': p.id_patient,
                'patient_nom': p.patient.nom if p.patient else '',
                'patient_prenom': p.patient.prenom if p.patient else '',
                'medicament': p.medicament or '',
                'type_prescription': type_presc,  # 🔥 AJOUT DU TYPE
                'dosage': p.dosage or '',
                'forme': p.forme or '',
                'quantite': p.quantite or '1',
                'duree_jours': p.duree_jours or 0,
                'frequence': p.frequence or '',
                'instructions': p.instructions or '',
                'date_prescription': p.date_prescription.isoformat() if p.date_prescription else datetime.now().isoformat(),
                'prescripteur': p.prescripteur or ''
            }
            data.append(presc_data)
        
        # ⭐ Envoyer vers GHP
        url = f"{mapping.api_url}/api/prescriptions"
        params = {'token': mapping.api_key}
        
        print(f"📡 Envoi de {len(data)} prescriptions vers GHP")
        
        response = requests.post(
            url,
            json={'prescriptions': data},
            params=params,
            timeout=30
        )
        
        if response.status_code == 200:
            # ⭐ Marquer comme synchronisées
            for p in prescriptions:
                p.synced_at = datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'✅ {len(data)} prescriptions envoyées'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur GHP: {response.status_code}',
                'response': response.text[:500]
            }), 500
            
    except Exception as e:
        print(f"❌ Erreur sync prescriptions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ================================================================
# ════════════════════════════════════════════════════════════════
# SECTION : GESTION DES TEMPLATES (PROTOCOLES, ORDONNANCES, EXAMENS)
# ════════════════════════════════════════════════════════════════
# ================================================================

# ================================================================
# 1. DASHBOARD DES TEMPLATES
# ================================================================

@app.route('/templates')
@login_required
def templates_dashboard():
    """Dashboard des templates médicaux"""
    from models import ProtocoleSoins, OrdonnanceType, ExamenType
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    structure_id = current_user.id_structure
    
    # Statistiques
    nb_protocoles = ProtocoleSoins.query.filter_by(structure_id=structure_id, actif=True).count()
    nb_ordonnances = OrdonnanceType.query.filter_by(structure_id=structure_id, actif=True).count()
    nb_examens = ExamenType.query.filter_by(structure_id=structure_id, actif=True).count()
    nb_inactifs = ProtocoleSoins.query.filter_by(structure_id=structure_id, actif=False).count() + \
                  OrdonnanceType.query.filter_by(structure_id=structure_id, actif=False).count() + \
                  ExamenType.query.filter_by(structure_id=structure_id, actif=False).count()
    
    # Derniers templates créés
    derniers_protocoles = ProtocoleSoins.query.filter_by(structure_id=structure_id).order_by(
        ProtocoleSoins.created_at.desc()
    ).limit(5).all()
    
    return render_template('templates/dashboard.html',
                         nb_protocoles=nb_protocoles,
                         nb_ordonnances=nb_ordonnances,
                         nb_examens=nb_examens,
                         nb_inactifs=nb_inactifs,
                         derniers_protocoles=derniers_protocoles)


# ================================================================
# 2. PROTOCOLES DE SOINS - CRUD
# ================================================================

@app.route('/templates/protocoles')
@login_required
def liste_protocoles():
    """Liste des protocoles de soins"""
    from models import ProtocoleSoins
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    protocoles = ProtocoleSoins.query.filter_by(
        structure_id=current_user.id_structure
    ).order_by(ProtocoleSoins.nom).all()
    
    return render_template('templates/protocoles/liste.html', protocoles=protocoles)


@app.route('/templates/protocole/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_protocole():
    """Ajouter un nouveau protocole de soins"""
    from models import ProtocoleSoins, OrdonnanceType, ExamenType
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Récupérer les ordonnances et examens types pour les associations
    ordonnances = OrdonnanceType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    examens = ExamenType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        description = request.form.get('description', '').strip()
        ordonnance_type_id = request.form.get('ordonnance_type_id')
        examen_type_id = request.form.get('examen_type_id')
        
        if not nom or not description:
            flash('Le nom et la description sont obligatoires', 'danger')
            return redirect(url_for('ajouter_protocole'))
        
        protocole = ProtocoleSoins(
            structure_id=current_user.id_structure,
            nom=nom,
            description=description,
            ordonnance_type_id=int(ordonnance_type_id) if ordonnance_type_id else None,
            examen_type_id=int(examen_type_id) if examen_type_id else None,
            created_by=current_user.id,
            actif=True
        )
        
        db.session.add(protocole)
        db.session.commit()
        
        flash(f'Protocole "{nom}" créé avec succès', 'success')
        return redirect(url_for('liste_protocoles'))
    
    return render_template('templates/protocoles/ajouter.html',
                         ordonnances=ordonnances,
                         examens=examens)


@app.route('/templates/protocole/<int:id>/modifier', methods=['GET', 'POST'])
@login_required
def modifier_protocole(id):
    """Modifier un protocole de soins"""
    from models import ProtocoleSoins, OrdonnanceType, ExamenType
    
    protocole = ProtocoleSoins.query.get_or_404(id)
    
    if protocole.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_protocoles'))
    
    ordonnances = OrdonnanceType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    examens = ExamenType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    if request.method == 'POST':
        protocole.nom = request.form.get('nom', '').strip()
        protocole.description = request.form.get('description', '').strip()
        protocole.ordonnance_type_id = request.form.get('ordonnance_type_id', type=int) or None
        protocole.examen_type_id = request.form.get('examen_type_id', type=int) or None
        protocole.actif = request.form.get('actif') == 'on'
        protocole.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        flash(f'Protocole "{protocole.nom}" modifié avec succès', 'success')
        return redirect(url_for('liste_protocoles'))
    
    return render_template('templates/protocoles/modifier.html',
                         protocole=protocole,
                         ordonnances=ordonnances,
                         examens=examens)


@app.route('/templates/protocole/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_protocole(id):
    """Supprimer un protocole de soins"""
    from models import ProtocoleSoins
    
    protocole = ProtocoleSoins.query.get_or_404(id)
    
    if protocole.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_protocoles'))
    
    nom = protocole.nom
    db.session.delete(protocole)
    db.session.commit()
    
    flash(f'Protocole "{nom}" supprimé avec succès', 'success')
    return redirect(url_for('liste_protocoles'))


# ================================================================
# 3. ORDONNANCES TYPES - CRUD
# ================================================================

@app.route('/templates/ordonnances')
@login_required
def liste_ordonnances():
    """Liste des ordonnances types"""
    from models import OrdonnanceType
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    ordonnances = OrdonnanceType.query.filter_by(
        structure_id=current_user.id_structure
    ).order_by(OrdonnanceType.nom).all()
    
    return render_template('templates/ordonnances/liste.html', ordonnances=ordonnances)


@app.route('/templates/ordonnance/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_ordonnance():
    """Ajouter une nouvelle ordonnance type"""
    from models import OrdonnanceType
    import json
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        description = request.form.get('description', '').strip()
        medicaments_json = request.form.get('medicaments_json', '[]')
        
        if not nom:
            flash('Le nom est obligatoire', 'danger')
            return redirect(url_for('ajouter_ordonnance'))
        
        # Vérifier que le JSON est valide
        try:
            medicaments = json.loads(medicaments_json)
        except:
            flash('Format des médicaments invalide', 'danger')
            return redirect(url_for('ajouter_ordonnance'))
        
        ordonnance = OrdonnanceType(
            structure_id=current_user.id_structure,
            nom=nom,
            description=description,
            medicaments=medicaments_json,
            created_by=current_user.id,
            actif=True
        )
        
        db.session.add(ordonnance)
        db.session.commit()
        
        flash(f'Ordonnance "{nom}" créée avec succès', 'success')
        return redirect(url_for('liste_ordonnances'))
    
    return render_template('templates/ordonnances/ajouter.html')


@app.route('/templates/ordonnance/<int:id>/modifier', methods=['GET', 'POST'])
@login_required
def modifier_ordonnance(id):
    """Modifier une ordonnance type"""
    from models import OrdonnanceType
    import json
    
    ordonnance = OrdonnanceType.query.get_or_404(id)
    
    if ordonnance.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_ordonnances'))
    
    if request.method == 'POST':
        ordonnance.nom = request.form.get('nom', '').strip()
        ordonnance.description = request.form.get('description', '').strip()
        ordonnance.medicaments = request.form.get('medicaments_json', '[]')
        ordonnance.actif = request.form.get('actif') == 'on'
        ordonnance.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        flash(f'Ordonnance "{ordonnance.nom}" modifiée avec succès', 'success')
        return redirect(url_for('liste_ordonnances'))
    
    return render_template('templates/ordonnances/modifier.html', ordonnance=ordonnance)


@app.route('/templates/ordonnance/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_ordonnance(id):
    """Supprimer une ordonnance type"""
    from models import OrdonnanceType
    
    ordonnance = OrdonnanceType.query.get_or_404(id)
    
    if ordonnance.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_ordonnances'))
    
    nom = ordonnance.nom
    db.session.delete(ordonnance)
    db.session.commit()
    
    flash(f'Ordonnance "{nom}" supprimée avec succès', 'success')
    return redirect(url_for('liste_ordonnances'))


# ================================================================
# 4. EXAMENS TYPES - CRUD
# ================================================================

@app.route('/templates/examens')
@login_required
def liste_examens():
    """Liste des examens types"""
    from models import ExamenType
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    examens = ExamenType.query.filter_by(
        structure_id=current_user.id_structure
    ).order_by(ExamenType.nom).all()
    
    return render_template('templates/examens/liste.html', examens=examens)


@app.route('/templates/examen/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_examen():
    """Ajouter un nouvel examen type"""
    from models import ExamenType
    import json
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        nature = request.form.get('nature', '').strip()
        motif = request.form.get('motif', '').strip()
        description = request.form.get('description', '').strip()
        examens_json = request.form.get('examens_json', '[]')
        
        if not nom or not nature:
            flash('Le nom et la nature sont obligatoires', 'danger')
            return redirect(url_for('ajouter_examen'))
        
        try:
            examens = json.loads(examens_json)
        except:
            flash('Format des examens invalide', 'danger')
            return redirect(url_for('ajouter_examen'))
        
        examen = ExamenType(
            structure_id=current_user.id_structure,
            nom=nom,
            nature=nature,
            motif=motif,
            description=description,
            examens=examens_json,
            created_by=current_user.id,
            actif=True
        )
        
        db.session.add(examen)
        db.session.commit()
        
        flash(f'Examen type "{nom}" créé avec succès', 'success')
        return redirect(url_for('liste_examens'))
    
    return render_template('templates/examens/ajouter.html')


@app.route('/templates/examen/<int:id>/modifier', methods=['GET', 'POST'])
@login_required
def modifier_examen(id):
    """Modifier un examen type"""
    from models import ExamenType
    import json
    
    examen = ExamenType.query.get_or_404(id)
    
    if examen.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_examens'))
    
    if request.method == 'POST':
        examen.nom = request.form.get('nom', '').strip()
        examen.nature = request.form.get('nature', '').strip()
        examen.motif = request.form.get('motif', '').strip()
        examen.description = request.form.get('description', '').strip()
        examen.examens = request.form.get('examens_json', '[]')
        examen.actif = request.form.get('actif') == 'on'
        examen.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        flash(f'Examen type "{examen.nom}" modifié avec succès', 'success')
        return redirect(url_for('liste_examens'))
    
    return render_template('templates/examens/modifier.html', examen=examen)


@app.route('/templates/examen/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_examen(id):
    """Supprimer un examen type"""
    from models import ExamenType
    
    examen = ExamenType.query.get_or_404(id)
    
    if examen.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('liste_examens'))
    
    nom = examen.nom
    db.session.delete(examen)
    db.session.commit()
    
    flash(f'Examen type "{nom}" supprimé avec succès', 'success')
    return redirect(url_for('liste_examens'))

# ================================================================
# HOSPITALISATION - GESTION DU PROTOCOLE, ORDONNANCE ET EXAMENS
# ================================================================

@app.route('/hospitalisation/<int:id>/appliquer-protocole', methods=['POST'])
@login_required
def appliquer_protocole(id):
    """Appliquer un protocole de soins à une hospitalisation"""
    from models import Hospitalisation, ProtocoleSoins, OrdonnanceType, ExamenType, ExamenPrescrit
    import json
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    protocole_id = request.form.get('protocole_id', type=int)
    
    if not protocole_id:
        flash('Veuillez sélectionner un protocole', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    protocole = ProtocoleSoins.query.get_or_404(protocole_id)
    
    if protocole.structure_id != current_user.id_structure:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    try:
        # Appliquer le protocole
        hospitalisation.protocole_id = protocole.id
        hospitalisation.updated_at = datetime.utcnow()
        
        # Si le protocole a une ordonnance associée, la copier
        if protocole.ordonnance_type_id:
            ordonnance_type = OrdonnanceType.query.get(protocole.ordonnance_type_id)
            if ordonnance_type:
                hospitalisation.ordonnance_prescite = ordonnance_type.medicaments
        
        # Si le protocole a des examens associés, les créer
        if protocole.examen_type_id:
            examen_type = ExamenType.query.get(protocole.examen_type_id)
            if examen_type:
                # Créer l'examen prescrit
                examen_prescrit = ExamenPrescrit(
                    hospitalisation_id=hospitalisation.id,
                    patient_id=hospitalisation.patient_id,
                    medecin_id=current_user.id,
                    examen_type_id=examen_type.id,
                    nature=examen_type.nature,
                    motif=examen_type.motif,
                    description=examen_type.description,
                    examens=examen_type.examens,
                    statut='EN_ATTENTE',
                    date_prescription=datetime.utcnow()
                )
                db.session.add(examen_prescrit)
        
        db.session.commit()
        
        flash(f'Protocole "{protocole.nom}" appliqué avec succès', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur : {str(e)}', 'danger')
    
    return redirect(url_for('detail_hospitalisation', id=id))


@app.route('/hospitalisation/<int:id>/ordonnance/modifier', methods=['POST'])
@login_required
def modifier_ordonnance_hospitalisation(id):
    """Modifier une ordonnance existante (crée une nouvelle version)"""
    from models import Hospitalisation
    import json
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    if hospitalisation.statut != 'actif':
        flash('Impossible de modifier une hospitalisation clôturée', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    medicaments_json = request.form.get('medicaments_json', '[]')
    motif_modification = request.form.get('motif_modification', 'Modification')
    
    try:
        medicaments = json.loads(medicaments_json)
    except:
        flash('Format des médicaments invalide', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    if not medicaments:
        flash('Veuillez ajouter au moins un médicament', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    try:
        # Récupérer l'historique existant
        historique = []
        if hospitalisation.ordonnance_historique:
            try:
                historique = json.loads(hospitalisation.ordonnance_historique)
            except:
                historique = []
        
        # Sauvegarder l'ancienne ordonnance dans l'historique
        if hospitalisation.ordonnance_prescite:
            ancienne_version = json.loads(hospitalisation.ordonnance_prescite)
            historique.append({
                'version': hospitalisation.ordonnance_version or 1,
                'date': datetime.utcnow().isoformat(),
                'medicaments': ancienne_version,
                'prescrit_par': current_user.id,
                'prescrit_par_nom': f"{current_user.prenom} {current_user.nom}",
                'motif': motif_modification
            })
        
        # Sauvegarder l'historique
        hospitalisation.ordonnance_historique = json.dumps(historique, ensure_ascii=False)
        
        # Incrémenter la version
        hospitalisation.ordonnance_version = (hospitalisation.ordonnance_version or 0) + 1
        
        # Mettre à jour la nouvelle ordonnance
        hospitalisation.ordonnance_prescite = medicaments_json
        hospitalisation.updated_at = datetime.utcnow()
        hospitalisation.created_by = current_user.id
        
        db.session.commit()
        
        flash(f'✅ Ordonnance modifiée - Version {hospitalisation.ordonnance_version} créée', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erreur : {str(e)}', 'danger')
    
    return redirect(url_for('detail_hospitalisation', id=id))

@app.route('/hospitalisation/<int:id>/ordonnance/historique')
@login_required
def historique_ordonnances_hospitalisation(id):
    from models import Hospitalisation
    import json
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # Récupérer l'historique
    historique = []
    if hospitalisation.ordonnance_historique:
        try:
            historique = json.loads(hospitalisation.ordonnance_historique)
            # Formater les dates
            for v in historique:
                if 'date' in v and v['date']:
                    try:
                        dt = datetime.fromisoformat(v['date'].replace('Z', '+00:00'))
                        v['date_formatted'] = dt.strftime('%d/%m/%Y %H:%M')
                    except:
                        v['date_formatted'] = v['date']
                else:
                    v['date_formatted'] = '-'
        except:
            historique = []
    
    # Récupérer l'ordonnance actuelle
    ordonnance_actuelle_medicaments = []
    if hospitalisation.ordonnance_prescite:
        try:
            ordonnance_actuelle_medicaments = json.loads(hospitalisation.ordonnance_prescite)
        except:
            ordonnance_actuelle_medicaments = []
    
    return render_template('hospitalisations/historique_ordonnances.html',
                         hospitalisation=hospitalisation,
                         historique=historique,
                         ordonnance_prescite=hospitalisation.ordonnance_prescite,
                         ordonnance_actuelle_medicaments=ordonnance_actuelle_medicaments,
                         version_actuelle=hospitalisation.ordonnance_version or 1)

@app.route('/hospitalisation/<int:id>/ordonnance/version/<int:version>/imprimer')
@login_required
def imprimer_ordonnance_version(id, version):
    """Imprimer une version spécifique de l'ordonnance"""
    from models import Hospitalisation, Structure
    import json
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    structure = Structure.query.get(current_user.id_structure)
    
    # ⭐ RÉCUPÉRER LE PATIENT
    patient = hospitalisation.patient
    
    # ⭐ SI C'EST LA VERSION ACTUELLE
    if version == hospitalisation.ordonnance_version:
        medicaments = []
        if hospitalisation.ordonnance_prescite:
            try:
                medicaments = json.loads(hospitalisation.ordonnance_prescite)
            except:
                medicaments = []
        
        prescripteur = f"{hospitalisation.createur.prenom} {hospitalisation.createur.nom}" if hospitalisation.createur else current_user.prenom + " " + current_user.nom
        date_version = hospitalisation.updated_at.strftime('%d/%m/%Y %H:%M') if hospitalisation.updated_at else datetime.now().strftime('%d/%m/%Y %H:%M')
        
        return render_template('impressions/ordonnance_version.html',
                             hospitalisation=hospitalisation,
                             structure=structure,
                             patient=patient,
                             medicaments=medicaments,
                             version=version,
                             prescripteur=prescripteur,
                             date_version=date_version,
                             now=datetime.utcnow())
    
    # ⭐ SI C'EST UNE VERSION ANCIENNE
    historique = []
    if hospitalisation.ordonnance_historique:
        try:
            historique = json.loads(hospitalisation.ordonnance_historique)
        except:
            historique = []
    
    # Chercher la version
    version_data = None
    for v in historique:
        if v.get('version') == version:
            version_data = v
            break
    
    if not version_data:
        flash('Version non trouvée', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    medicaments = version_data.get('medicaments', [])
    prescripteur = version_data.get('prescrit_par_nom', 'Inconnu')
    date_version = version_data.get('date_formatted', version_data.get('date', datetime.now().strftime('%d/%m/%Y %H:%M')))
    
    return render_template('impressions/ordonnance_version.html',
                         hospitalisation=hospitalisation,
                         structure=structure,
                         patient=patient,
                         medicaments=medicaments,
                         version=version,
                         prescripteur=prescripteur,
                         date_version=date_version,
                         now=datetime.utcnow())

@app.route('/hospitalisation/<int:id>/ordonnance/creer', methods=['POST'])
@login_required
def creer_ordonnance_hospitalisation(id):
    """Créer une nouvelle ordonnance pour une hospitalisation"""
    from models import Hospitalisation
    import json
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    if hospitalisation.statut != 'actif':
        flash('Impossible de créer une ordonnance sur une hospitalisation clôturée', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    medicaments_json = request.form.get('medicaments_json', '[]')
    
    try:
        medicaments = json.loads(medicaments_json)
    except:
        flash('Format des médicaments invalide', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    if not medicaments:
        flash('Veuillez ajouter au moins un médicament', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    try:
        # ⭐ SAUVEGARDER L'ANCIENNE ORDONNANCE DANS L'HISTORIQUE (SI ELLE EXISTE)
        historique = []
        if hospitalisation.ordonnance_historique:
            try:
                historique = json.loads(hospitalisation.ordonnance_historique)
            except:
                historique = []
        
        # Si une ancienne ordonnance existe, la sauvegarder dans l'historique
        if hospitalisation.ordonnance_prescite:
            ancienne_version = json.loads(hospitalisation.ordonnance_prescite)
            historique.append({
                'version': hospitalisation.ordonnance_version or 1,
                'date': datetime.utcnow().isoformat(),
                'medicaments': ancienne_version,
                'prescrit_par': current_user.id,
                'prescrit_par_nom': f"{current_user.prenom} {current_user.nom}",
                'motif': 'Nouvelle prescription'
            })
        
        # Sauvegarder l'historique
        hospitalisation.ordonnance_historique = json.dumps(historique, ensure_ascii=False)
        
        # Incrémenter la version
        hospitalisation.ordonnance_version = (hospitalisation.ordonnance_version or 0) + 1
        
        # Mettre à jour la nouvelle ordonnance
        hospitalisation.ordonnance_prescite = medicaments_json
        hospitalisation.updated_at = datetime.utcnow()
        hospitalisation.created_by = current_user.id
        
        db.session.commit()
        
        flash(f'✅ Nouvelle prescription enregistrée (Version {hospitalisation.ordonnance_version})', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erreur : {str(e)}', 'danger')
    
    return redirect(url_for('detail_hospitalisation', id=id))

@app.route('/patient/<int:patient_id>/dossier/imprimer')
@login_required
def imprimer_dossier_patient(patient_id):
    from models import Patient, Consultation, Prescription, AntecedentPatient, Hospitalisation, AnalyseDemande, ExamenPhysique, Utilisateur, ExamenPrescrit, AvisExterne, EvolutionPatient, ConstanteVitale, HospitalisationMedecin, HospitalisationInfirmier, NoteAdmission, Engagement
    from datetime import datetime
    import json
    
    patient = Patient.query.get_or_404(patient_id)
    
    if current_user.role not in ['admin_structure', 'medecin', 'super_admin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('patient_detail', id=patient_id))
    
    # ============================================================ #
    # 1. CONSULTATIONS
    # ============================================================ #
    consultations = Consultation.query.filter_by(
        id_patient=patient.id
    ).order_by(Consultation.date_consultation.desc()).all()
    
    consultations_data = []
    for consultation in consultations:
        medecin = None
        if consultation.id_medecin:
            medecin = Utilisateur.query.get(consultation.id_medecin)
        
        prescriptions = Prescription.query.filter_by(
            id_patient=patient.id,
            id_consultation=consultation.id,
            type_prescription='medicament'
        ).all()
        
        examens_prescrits = ExamenPrescrit.query.filter_by(
            consultation_id=consultation.id,
            est_active=True
        ).all()
        
        analyses = AnalyseDemande.query.filter_by(
            consultation_id=consultation.id
        ).all()
        
        examen_physique = ExamenPhysique.query.filter_by(
            consultation_id=consultation.id
        ).first()
        
        consultations_data.append({
            'consultation': consultation,
            'medecin': medecin,
            'prescriptions': prescriptions,
            'examens_prescrits': examens_prescrits,
            'analyses': analyses,
            'examen_physique': examen_physique
        })
    
    # ============================================================ #
    # 2. HOSPITALISATIONS
    # ============================================================ #
    hospitalisations = Hospitalisation.query.filter_by(
        patient_id=patient.id
    ).order_by(Hospitalisation.date_debut.desc()).all()
    
    hospitalisations_data = []
    for hosp in hospitalisations:
        medecins = HospitalisationMedecin.query.filter_by(
            hospitalisation_id=hosp.id,
            actif=True
        ).all()
        
        infirmiers = HospitalisationInfirmier.query.filter_by(
            hospitalisation_id=hosp.id,
            actif=True
        ).all()
        
        constantes = ConstanteVitale.query.filter_by(
            hospitalisation_id=hosp.id
        ).order_by(ConstanteVitale.date_prise.desc()).limit(20).all()
        
        evolutions = EvolutionPatient.query.filter_by(
            hospitalisation_id=hosp.id
        ).order_by(EvolutionPatient.date_evolution.desc()).all()
        
        avis_externes = AvisExterne.query.filter_by(
            hospitalisation_id=hosp.id
        ).order_by(AvisExterne.date_demande.desc()).all()
        
        note_active = None
        if hosp.note_admission_active_id:
            note_active = NoteAdmission.query.get(hosp.note_admission_active_id)
        
        ordonnance_medicaments = []
        if hosp.ordonnance_prescite:
            try:
                ordonnance_medicaments = json.loads(hosp.ordonnance_prescite)
            except:
                ordonnance_medicaments = []
        
        examens_hosp = ExamenPrescrit.query.filter_by(
            hospitalisation_id=hosp.id,
            est_active=True
        ).all()
        
        hospitalisations_data.append({
            'hospitalisation': hosp,
            'medecins': medecins,
            'infirmiers': infirmiers,
            'constantes': constantes,
            'evolutions': evolutions,
            'avis_externes': avis_externes,
            'note_active': note_active,
            'ordonnance_medicaments': ordonnance_medicaments,
            'examens_prescrits': examens_hosp,
            'protocole': hosp.protocole
        })
    
    # ============================================================ #
    # 3. ENGAGEMENTS (DNR, REFUS_TRAITEMENT, SORTIE_AVIS, AUTRE)
    # ============================================================ #
    engagements = Engagement.query.filter_by(
        patient_id=patient.id
    ).order_by(Engagement.date_creation.desc()).all()
    
    # ============================================================ #
    # 4. ANTÉCÉDENTS
    # ============================================================ #
    antecedents = AntecedentPatient.query.filter_by(
        patient_id=patient.id,
        actif=True
    ).order_by(AntecedentPatient.date_recueil.desc()).all()
    
    age = None
    if patient.date_naissance:
        today = datetime.utcnow().date()
        age = today.year - patient.date_naissance.year - ((today.month, today.day) < (patient.date_naissance.month, patient.date_naissance.day))
    
    return render_template('impressions/dossier_patient.html',
                         patient=patient,
                         age=age,
                         consultations_data=consultations_data,
                         hospitalisations_data=hospitalisations_data,
                         engagements=engagements,
                         antecedents=antecedents,
                         now=datetime.utcnow())

@app.route('/hospitalisation/<int:id>/examen/ajouter', methods=['POST'])
@login_required
def ajouter_examen_prescrit(id):
    """Ajouter un examen prescrit à une hospitalisation"""
    from models import Hospitalisation, ExamenPrescrit, ExamenType, AnalyseDemande
    import json
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    examen_type_id = request.form.get('examen_type_id', type=int)
    nature = request.form.get('nature', '').strip()
    motif = request.form.get('motif', '').strip()
    description = request.form.get('description', '').strip()
    examens_json = request.form.get('examens_json', '[]')
    
    try:
        # Récupérer la liste des examens
        examens = json.loads(examens_json) if examens_json else []
        
        if not examens and not examen_type_id:
            flash('Veuillez ajouter au moins un examen', 'danger')
            return redirect(url_for('detail_hospitalisation', id=id))
        
        if examen_type_id:
            examen_type = ExamenType.query.get(examen_type_id)
            if examen_type:
                # Utiliser les données du template
                nature = examen_type.nature
                motif = examen_type.motif or motif
                description = examen_type.description or description
                examens = json.loads(examen_type.examens) if examen_type.examens else []
                examens_json = examen_type.examens
                
                examen_prescrit = ExamenPrescrit(
                    hospitalisation_id=hospitalisation.id,
                    patient_id=hospitalisation.patient_id,
                    medecin_id=current_user.id,
                    examen_type_id=examen_type.id,
                    version=1,
                    est_active=True,
                    nature=nature,
                    motif=motif,
                    description=description,
                    examens=examens_json,
                    statut='EN_ATTENTE',
                    date_prescription=datetime.utcnow()
                )
                db.session.add(examen_prescrit)
                db.session.flush()
        else:
            # Création manuelle
            examen_prescrit = ExamenPrescrit(
                hospitalisation_id=hospitalisation.id,
                patient_id=hospitalisation.patient_id,
                medecin_id=current_user.id,
                version=1,
                est_active=True,
                nature=nature,
                motif=motif,
                description=description,
                examens=examens_json,
                statut='EN_ATTENTE',
                date_prescription=datetime.utcnow()
            )
            db.session.add(examen_prescrit)
            db.session.flush()
        
        # ⭐⭐⭐ CRÉER LES ANALYSES DEMANDÉES (pour le laborantin) ⭐⭐⭐
        analyses_creees = 0
        try:
            for nom_analyse in examens:
                if nom_analyse and nom_analyse.strip():
                    analyse = AnalyseDemande(
                        hospitalisation_id=hospitalisation.id,
                        consultation_id=None,
                        patient_id=hospitalisation.patient_id,
                        structure_id=current_user.id_structure,
                        type_analyse=nature,  # BIOLOGIE, IMAGERIE, AUTRE
                        nom_analyse=nom_analyse.strip(),
                        description=description,
                        prescrit_par=current_user.id,
                        statut='EN_ATTENTE',
                        date_demande=datetime.utcnow()
                    )
                    db.session.add(analyse)
                    analyses_creees += 1
            print(f"✅ {analyses_creees} analyse(s) créée(s) pour le laborantin (hospitalisation)")
        except Exception as e:
            print(f"⚠️ Erreur création analyses: {e}")
        
        db.session.commit()
        flash(f'✅ Examen prescrit et {analyses_creees} analyse(s) envoyée(s) au laborantin', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erreur : {str(e)}', 'danger')
    
    return redirect(url_for('detail_hospitalisation', id=id))


@app.route('/hospitalisation/<int:id>/examen/<int:examen_id>/resultats', methods=['POST'])
@login_required
def saisir_resultats_examen(id, examen_id):
    """Saisir les résultats d'un examen prescrit"""
    from models import Hospitalisation, ExamenPrescrit, AnalyseDemande
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    examen = ExamenPrescrit.query.get_or_404(examen_id)
    
    # ⭐ PERMISSIONS : Laborantin, Radiologue, Medecin, Admin
    if current_user.role not in ['admin_structure', 'medecin', 'laborantin', 'radiologue']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    resultats = request.form.get('resultats', '').strip()
    statut = request.form.get('statut', 'TERMINE')
    
    if not resultats:
        flash('Veuillez saisir les résultats', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    # ⭐ METTRE À JOUR L'EXAMEN PRESCRIT
    examen.resultats = resultats
    examen.statut = statut
    examen.laborantin_id = current_user.id
    examen.date_resultats = datetime.utcnow()
    examen.updated_at = datetime.utcnow()
    
    # ⭐ METTRE À JOUR L'ANALYSE DEMANDÉE (si elle existe)
    analyse = AnalyseDemande.query.filter_by(
        hospitalisation_id=id,
        nom_analyse=examen.nature  # Ou un champ plus précis
    ).first()
    
    if analyse:
        analyse.resultats = resultats
        analyse.statut = statut
        analyse.date_resultats = datetime.utcnow()
        analyse.resultats_par = current_user.id
    
    # ⭐ METTRE À JOUR LES RÉSULTATS DANS L'HOSPITALISATION
    if statut == 'TERMINE':
        if examen.nature == 'BIOLOGIE':
            if hospitalisation.notes_admission:
                hospitalisation.notes_admission += f"\n\n--- RÉSULTATS BIOLOGIE ---\n{resultats}"
            else:
                hospitalisation.notes_admission = f"--- RÉSULTATS BIOLOGIE ---\n{resultats}"
        elif examen.nature == 'IMAGERIE':
            if hospitalisation.notes_admission:
                hospitalisation.notes_admission += f"\n\n--- RÉSULTATS IMAGERIE ---\n{resultats}"
            else:
                hospitalisation.notes_admission = f"--- RÉSULTATS IMAGERIE ---\n{resultats}"
    
    db.session.commit()
    
    flash('✅ Résultats enregistrés avec succès', 'success')
    return redirect(url_for('detail_hospitalisation', id=id))


@app.route('/hospitalisation/<int:id>/examen/<int:examen_id>/supprimer', methods=['POST'])
@login_required
def supprimer_examen_prescrit(id, examen_id):
    """Supprimer un examen prescrit"""
    from models import ExamenPrescrit
    
    examen = ExamenPrescrit.query.get_or_404(examen_id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    db.session.delete(examen)
    db.session.commit()
    
    flash('Examen supprimé avec succès', 'success')
    return redirect(url_for('detail_hospitalisation', id=id))


@app.route('/hospitalisation/<int:id>/ordonnance/imprimer')
@login_required
def imprimer_ordonnance(id):
    """Imprimer l'ordonnance médicale"""
    from models import Hospitalisation, Structure
    import json
    from datetime import datetime
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    structure = Structure.query.get(current_user.id_structure)
    
    if not hospitalisation.ordonnance_prescite:
        flash('Aucune ordonnance à imprimer', 'warning')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    medicaments = json.loads(hospitalisation.ordonnance_prescite) if hospitalisation.ordonnance_prescite else []
    
    return render_template('impressions/ordonnance.html',
                         hospitalisation=hospitalisation,
                         structure=structure,
                         patient=hospitalisation.patient,  # ⭐ PASSER LE PATIENT
                         medicaments=medicaments,
                         now=datetime.utcnow())


@app.route('/hospitalisation/<int:id>/examen/<int:examen_id>/imprimer')
@login_required
def imprimer_examen(id, examen_id):
    """Imprimer la demande d'examens"""
    from models import Hospitalisation, ExamenPrescrit, Structure
    import json
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    examen = ExamenPrescrit.query.get_or_404(examen_id)
    structure = Structure.query.get(current_user.id_structure)
    
    examens_list = json.loads(examen.examens) if examen.examens else []
    
    return render_template('impressions/examen.html',
                         hospitalisation=hospitalisation,
                         structure=structure,
                         examen=examen,
                         examens_list=examens_list,
                         now=datetime.utcnow())

# ================================================================
# API - TEMPLATES (pour sélection dynamique)
# ================================================================

@app.route('/api/protocole/<int:id>')
@login_required
def api_get_protocole(id):
    """Récupère les détails d'un protocole pour l'aperçu dynamique"""
    from models import ProtocoleSoins
    
    protocole = ProtocoleSoins.query.get_or_404(id)
    
    if protocole.structure_id != current_user.id_structure:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    return jsonify({
        'id': protocole.id,
        'nom': protocole.nom,
        'description': protocole.description,
        'ordonnance_type': protocole.ordonnance_type.nom if protocole.ordonnance_type else None,
        'examen_type': protocole.examen_type.nom if protocole.examen_type else None
    })


@app.route('/api/examen-type/<int:id>')
@login_required
def api_get_examen_type(id):
    """Récupère les détails d'un examen type pour le pré-remplissage"""
    from models import ExamenType
    import json
    
    examen_type = ExamenType.query.get_or_404(id)
    
    if examen_type.structure_id != current_user.id_structure:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    examens_list = json.loads(examen_type.examens) if examen_type.examens else []
    
    return jsonify({
        'id': examen_type.id,
        'nom': examen_type.nom,
        'nature': examen_type.nature,
        'motif': examen_type.motif,
        'description': examen_type.description,
        'examens': examens_list
    })


@app.route('/api/ordonnance-type/<int:id>')
@login_required
def api_get_ordonnance_type(id):
    """Récupère les détails d'une ordonnance type pour le pré-remplissage"""
    from models import OrdonnanceType
    import json
    
    ordonnance = OrdonnanceType.query.get_or_404(id)
    
    if ordonnance.structure_id != current_user.id_structure:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    medicaments = json.loads(ordonnance.medicaments) if ordonnance.medicaments else []
    
    return jsonify({
        'id': ordonnance.id,
        'nom': ordonnance.nom,
        'description': ordonnance.description,
        'medicaments': medicaments
    })


@app.route('/api/hospitalisation/<int:id>/examen/<int:examen_id>')
@login_required
def api_get_examen_prescrit(id, examen_id):
    """Récupère les détails d'un examen prescrit"""
    from models import Hospitalisation, ExamenPrescrit
    import json
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    examen = ExamenPrescrit.query.get_or_404(examen_id)
    
    if hospitalisation.patient.id_structure != current_user.id_structure:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    examens_list = json.loads(examen.examens) if examen.examens else []
    
    return jsonify({
        'id': examen.id,
        'nature': examen.nature,
        'motif': examen.motif,
        'description': examen.description,
        'examens': examens_list,
        'statut': examen.statut,
        'resultats': examen.resultats,
        'date_prescription': examen.date_prescription.strftime('%d/%m/%Y %H:%M') if examen.date_prescription else None
    })

# ================================================================
# CONSULTATION - ORDONNANCES (AVEC HISTORIQUE)
# ================================================================

@app.route('/consultation/<int:id>/ordonnance/creer', methods=['GET', 'POST'])
@login_required
def creer_ordonnance_consultation(id):
    """Créer une nouvelle ordonnance pour une consultation"""
    from models import Consultation, Ordonnance, OrdonnanceType, ProtocoleSoins
    import json
    
    consultation = Consultation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    # Récupérer les templates et protocoles disponibles
    ordonnances_types = OrdonnanceType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    protocoles = ProtocoleSoins.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    if request.method == 'POST':
        source_type = request.form.get('source_type', 'manuel')
        source_id = request.form.get('source_id', type=int)
        medicaments_json = request.form.get('medicaments_json', '[]')
        motif_modification = request.form.get('motif_modification', 'Création')
        
        # Valider le JSON
        try:
            medicaments = json.loads(medicaments_json)
        except:
            flash('Format des médicaments invalide', 'danger')
            return redirect(url_for('creer_ordonnance_consultation', id=id))
        
        if not medicaments:
            flash('Veuillez ajouter au moins un médicament', 'danger')
            return redirect(url_for('creer_ordonnance_consultation', id=id))
        
        # Compter les ordonnances existantes
        nb_ordonnances = consultation.ordonnances.count()
        nouvelle_version = nb_ordonnances + 1
        
        # Récupérer le nom de la source
        source_nom = None
        if source_type == 'template' and source_id:
            template = OrdonnanceType.query.get(source_id)
            if template:
                source_nom = template.nom
        elif source_type == 'protocole' and source_id:
            protocole = ProtocoleSoins.query.get(source_id)
            if protocole:
                source_nom = protocole.nom
                
                # Si c'est un protocole, appliquer aussi les examens
                if protocole.examen_type_id:
                    from models import ExamenPrescrit, ExamenType
                    examen_type = ExamenType.query.get(protocole.examen_type_id)
                    if examen_type:
                        examen_prescrit = ExamenPrescrit(
                            consultation_id=consultation.id,
                            patient_id=consultation.id_patient,
                            medecin_id=current_user.id,
                            examen_type_id=examen_type.id,
                            version=1,
                            est_active=True,
                            nature=examen_type.nature,
                            motif=examen_type.motif,
                            description=examen_type.description,
                            examens=examen_type.examens,
                            source_type='protocole',
                            source_id=protocole.id,
                            source_nom=protocole.nom,
                            statut='EN_ATTENTE',
                            date_prescription=datetime.utcnow()
                        )
                        db.session.add(examen_prescrit)
        
        # Désactiver les anciennes ordonnances
        consultation.ordonnances.update({'est_active': False})
        
        # Créer la nouvelle ordonnance
        ordonnance = Ordonnance(
            consultation_id=consultation.id,
            version=nouvelle_version,
            est_active=True,
            medicaments=medicaments_json,
            source_type=source_type,
            source_id=source_id,
            source_nom=source_nom,
            redige_par=current_user.id,
            date_redaction=datetime.utcnow(),
            motif_modification=motif_modification
        )
        
        db.session.add(ordonnance)
        db.session.flush()
        
        # Mettre à jour la consultation
        consultation.ordonnance_active_id = ordonnance.id
        
        # Si source_type est 'protocole', enregistrer le protocole
        if source_type == 'protocole' and source_id:
            consultation.protocole_applique_id = source_id
        
        db.session.commit()
        
        flash(f'✅ Ordonnance (version {nouvelle_version}) créée avec succès', 'success')
        return redirect(url_for('consultation_detail', id=id))
    
    return render_template('consultations/modals/ordonnance_creer.html',
                         consultation=consultation,
                         ordonnances_types=ordonnances_types,
                         protocoles=protocoles,
                         now=datetime.utcnow())


@app.route('/consultation/<int:id>/ordonnance/<int:ordonnance_id>/modifier', methods=['GET', 'POST'])
@login_required
def modifier_ordonnance_consultation(id, ordonnance_id):
    """Modifier une ordonnance existante (crée une nouvelle version)"""
    from models import Consultation, Ordonnance
    import json
    
    consultation = Consultation.query.get_or_404(id)
    ordonnance_old = Ordonnance.query.get_or_404(ordonnance_id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    if request.method == 'POST':
        medicaments_json = request.form.get('medicaments_json', '[]')
        motif_modification = request.form.get('motif_modification', 'Modification')
        
        try:
            medicaments = json.loads(medicaments_json)
        except:
            flash('Format des médicaments invalide', 'danger')
            return redirect(url_for('consultation_detail', id=id))
        
        if not medicaments:
            flash('Veuillez ajouter au moins un médicament', 'danger')
            return redirect(url_for('consultation_detail', id=id))
        
        # Compter les ordonnances existantes
        nb_ordonnances = consultation.ordonnances.count()
        nouvelle_version = nb_ordonnances + 1
        
        # Désactiver les anciennes ordonnances
        consultation.ordonnances.update({'est_active': False})
        
        # Créer la nouvelle ordonnance
        ordonnance = Ordonnance(
            consultation_id=consultation.id,
            version=nouvelle_version,
            est_active=True,
            medicaments=medicaments_json,
            source_type='modification',
            source_id=ordonnance_old.id,
            source_nom=f"Version {ordonnance_old.version}",
            redige_par=current_user.id,
            date_redaction=datetime.utcnow(),
            motif_modification=motif_modification
        )
        
        db.session.add(ordonnance)
        db.session.flush()
        
        # Mettre à jour la consultation
        consultation.ordonnance_active_id = ordonnance.id
        
        db.session.commit()
        
        flash(f'✅ Ordonnance modifiée (version {nouvelle_version})', 'success')
        return redirect(url_for('consultation_detail', id=id))
    
    return render_template('consultations/modals/ordonnance_modifier.html',
                         consultation=consultation,
                         ordonnance=ordonnance_old,
                         now=datetime.utcnow())


@app.route('/consultation/<int:id>/ordonnance/imprimer')
@login_required
def imprimer_ordonnance_consultation(id):
    """Imprimer l'ordonnance active"""
    from models import Consultation, Structure
    import json
    
    consultation = Consultation.query.get_or_404(id)
    structure = Structure.query.get(current_user.id_structure)
    patient = consultation.patient
    
    ordonnance_active = consultation.ordonnance_active
    
    if not ordonnance_active:
        flash('Aucune ordonnance active à imprimer', 'warning')
        return redirect(url_for('consultation_detail', id=id))
    
    medicaments = ordonnance_active.get_medicaments_list()
    
    return render_template('impressions/ordonnance_consultation.html',
                         consultation=consultation,
                         patient=patient,
                         structure=structure,
                         ordonnance=ordonnance_active,
                         medicaments=medicaments,
                         now=datetime.utcnow())


@app.route('/consultation/<int:id>/ordonnance/historique')
@login_required
def historique_ordonnances_consultation(id):
    from models import Consultation, Ordonnance  # ⭐ AJOUTE CET IMPORT
    
    consultation = Consultation.query.get_or_404(id)
    
    ordonnances = consultation.ordonnances.order_by(
        Ordonnance.version.desc()
    ).all()
    
    return render_template('consultations/historique_ordonnances.html',
                         consultation=consultation,
                         ordonnances=ordonnances)

# ================================================================
# CONSULTATION - EXAMENS PRESCRITS
# ================================================================

@app.route('/consultation/<int:id>/examen/ajouter', methods=['POST'])
@login_required
def ajouter_examen_prescrit_consultation(id):
    from models import Consultation, ExamenPrescrit, ExamenType
    import json
    
    consultation = Consultation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    examen_type_id = request.form.get('examen_type_id', type=int)
    nature = request.form.get('nature', '').strip()
    motif = request.form.get('motif', '').strip()
    description = request.form.get('description', '').strip()
    examens_json = request.form.get('examens_json', '[]')
    
    try:
        if examen_type_id:
            examen_type = ExamenType.query.get(examen_type_id)
            if examen_type:
                examen_prescrit = ExamenPrescrit(
                    # ⭐ hospitalisation_id = None pour consultation
                    hospitalisation_id=None,
                    consultation_id=consultation.id,
                    patient_id=consultation.id_patient,
                    medecin_id=current_user.id,
                    examen_type_id=examen_type.id,
                    nature=examen_type.nature,
                    motif=examen_type.motif,
                    description=examen_type.description,
                    examens=examen_type.examens,
                    statut='EN_ATTENTE',
                    date_prescription=datetime.utcnow()
                )
                db.session.add(examen_prescrit)
        else:
            # Création manuelle
            examens = json.loads(examens_json) if examens_json else []
            examen_prescrit = ExamenPrescrit(
                # ⭐ hospitalisation_id = None pour consultation
                hospitalisation_id=None,
                consultation_id=consultation.id,
                patient_id=consultation.id_patient,
                medecin_id=current_user.id,
                nature=nature,
                motif=motif,
                description=description,
                examens=examens_json,
                statut='EN_ATTENTE',
                date_prescription=datetime.utcnow()
            )
            db.session.add(examen_prescrit)
        
        db.session.commit()
        flash('Examen prescrit ajoute avec succès', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur : {str(e)}', 'danger')
    
    return redirect(url_for('consultation_detail', id=id))


@app.route('/consultation/<int:id>/examen/<int:examen_id>/supprimer', methods=['POST'])
@login_required
def supprimer_examen_prescrit_consultation(id, examen_id):
    """Supprimer un examen prescrit d'une consultation"""
    from models import ExamenPrescrit
    
    examen = ExamenPrescrit.query.get_or_404(examen_id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    db.session.delete(examen)
    db.session.commit()
    
    flash('✅ Examen supprimé avec succès', 'success')
    return redirect(url_for('consultation_detail', id=id))


# ================================================================
# CONSULTATION - EXAMENS PRESCRITS (AVEC HISTORIQUE)
# ================================================================

@app.route('/consultation/<int:id>/examen/creer', methods=['GET', 'POST'])
@login_required
def creer_examen_consultation(id):
    """Créer une nouvelle demande d'examens pour une consultation"""
    from models import Consultation, ExamenPrescrit, ExamenType, ProtocoleSoins, AnalyseDemande
    import json
    
    consultation = Consultation.query.get_or_404(id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    examens_types = ExamenType.query.filter_by(
        structure_id=current_user.id_structure,
        actif=True
    ).all()
    
    if request.method == 'POST':
        source_type = request.form.get('source_type', 'manuel')
        source_id = request.form.get('source_id', type=int)
        
        nature = request.form.get('nature', '').strip()
        motif = request.form.get('motif', '').strip()
        description = request.form.get('description', '').strip()
        examens_json = request.form.get('examens_json', '[]')
        
        try:
            examens = json.loads(examens_json)
        except:
            flash('Format des examens invalide', 'danger')
            return redirect(url_for('creer_examen_consultation', id=id))
        
        if not examens:
            flash('Veuillez ajouter au moins un examen', 'danger')
            return redirect(url_for('creer_examen_consultation', id=id))
        
        # Récupérer le nom de la source
        source_nom = None
        if source_type == 'template' and source_id:
            template = ExamenType.query.get(source_id)
            if template:
                source_nom = template.nom
                nature = template.nature
                motif = template.motif
                description = template.description
        elif source_type == 'protocole' and source_id:
            protocole = ProtocoleSoins.query.get(source_id)
            if protocole and protocole.examen_type_id:
                template = ExamenType.query.get(protocole.examen_type_id)
                if template:
                    source_nom = protocole.nom
                    nature = template.nature
                    motif = template.motif
                    description = template.description
        
        # Compter les examens existants
        nb_examens = consultation.examens_prescrits.count()
        nouvelle_version = nb_examens + 1
        
        # Créer l'examen prescrit
        examen_prescrit = ExamenPrescrit(
            consultation_id=consultation.id,
            patient_id=consultation.id_patient,
            medecin_id=current_user.id,
            version=nouvelle_version,
            est_active=True,
            nature=nature,
            motif=motif,
            description=description,
            examens=examens_json,
            source_type=source_type,
            source_id=source_id,
            source_nom=source_nom,
            statut='EN_ATTENTE',
            date_prescription=datetime.utcnow()
        )
        db.session.add(examen_prescrit)
        db.session.flush()  # Pour obtenir l'ID si besoin
        
        # ⭐⭐⭐ CRÉER LES ANALYSES DEMANDÉES (pour le laborantin) ⭐⭐⭐
        analyses_creees = 0
        try:
            for nom_analyse in examens:
                if nom_analyse.strip():
                    analyse = AnalyseDemande(
                        consultation_id=consultation.id,
                        patient_id=consultation.id_patient,
                        structure_id=current_user.id_structure,
                        type_analyse=nature,  # BIOLOGIE, IMAGERIE, AUTRE
                        nom_analyse=nom_analyse.strip(),
                        description=description,
                        prescrit_par=current_user.id,
                        statut='EN_ATTENTE',
                        date_demande=datetime.utcnow()
                    )
                    db.session.add(analyse)
                    analyses_creees += 1
            print(f"✅ {analyses_creees} analyse(s) créée(s) pour le laborantin")
        except Exception as e:
            print(f"⚠️ Erreur création analyses: {e}")
        
        db.session.commit()
        
        flash(f'✅ Demande d\'examens créée avec succès ({analyses_creees} analyse(s) envoyée(s) au laborantin)', 'success')
        return redirect(url_for('consultation_detail', id=id))
    
    return render_template('consultations/modals/examen_creer.html',
                         consultation=consultation,
                         examens_types=examens_types,
                         now=datetime.utcnow())

# ================================================================
# CONSULTATION - EXAMENS (AVEC HISTORIQUE)
# ================================================================

@app.route('/consultation/<int:id>/examen/<int:examen_id>/modifier', methods=['GET', 'POST'])
@login_required
def modifier_examen_consultation(id, examen_id):
    """Modifier un examen prescrit (crée une nouvelle version)"""
    from models import Consultation, ExamenPrescrit
    import json
    
    consultation = Consultation.query.get_or_404(id)
    examen_old = ExamenPrescrit.query.get_or_404(examen_id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('consultation_detail', id=id))
    
    if request.method == 'POST':
        nature = request.form.get('nature', '').strip()
        motif = request.form.get('motif', '').strip()
        description = request.form.get('description', '').strip()
        examens_json = request.form.get('examens_json', '[]')
        
        try:
            examens = json.loads(examens_json)
        except:
            flash('Format des examens invalide', 'danger')
            return redirect(url_for('consultation_detail', id=id))
        
        if not examens:
            flash('Veuillez ajouter au moins un examen', 'danger')
            return redirect(url_for('consultation_detail', id=id))
        
        # Compter les examens existants
        nb_examens = consultation.examens_prescrits.count()
        nouvelle_version = nb_examens + 1
        
        # Désactiver les anciens examens
        consultation.examens_prescrits.update({'est_active': False})
        
        # Creer le nouvel examen
        examen = ExamenPrescrit(
            consultation_id=consultation.id,
            patient_id=consultation.id_patient,
            medecin_id=current_user.id,
            version=nouvelle_version,
            est_active=True,
            nature=nature,
            motif=motif,
            description=description,
            examens=examens_json,
            source_type='modification',
            source_id=examen_old.id,
            source_nom=f"Version {examen_old.version}",
            statut='EN_ATTENTE',
            date_prescription=datetime.utcnow()
        )
        
        db.session.add(examen)
        db.session.commit()
        
        flash(f'Demande d\'examens modifiee (version {nouvelle_version})', 'success')
        return redirect(url_for('consultation_detail', id=id))
    
    return render_template('consultations/modals/examen_modifier.html',
                         consultation=consultation,
                         examen=examen_old)

@app.route('/consultation/<int:id>/examen/<int:examen_id>/imprimer')
@login_required
def imprimer_examen_consultation(id, examen_id):
    """Imprimer une demande d'examens"""
    from models import Consultation, ExamenPrescrit, Structure
    import json
    
    consultation = Consultation.query.get_or_404(id)
    examen = ExamenPrescrit.query.get_or_404(examen_id)
    structure = Structure.query.get(current_user.id_structure)
    patient = consultation.patient
    
    examens_list = examen.get_examens_list()
    
    return render_template('impressions/examen_consultation.html',
                         consultation=consultation,
                         patient=patient,
                         structure=structure,
                         examen=examen,
                         examens_list=examens_list,
                         now=datetime.utcnow())
@app.route('/hospitalisation/<int:id>/reference/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter_reference_hospitalisation(id):
    """Ajouter une référence depuis une hospitalisation"""
    from models import Hospitalisation, Reference, Patient
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    patient = Patient.query.get(hospitalisation.patient_id)
    
    if current_user.role not in ['admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    if request.method == 'POST':
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')
        centre_reference = request.form.get('centre_reference')
        service_reference = request.form.get('service_reference')
        medecin_referent = request.form.get('medecin_referent')
        resume_clinique = request.form.get('resume_clinique')
        examens_realises = request.form.get('examens_realises')
        traitements_en_cours = request.form.get('traitements_en_cours')
        
        if not motif or not centre_reference:
            flash('Le motif et le centre de référence sont obligatoires', 'danger')
            return redirect(url_for('ajouter_reference_hospitalisation', id=id))
        
        reference = Reference(
            patient_id=patient.id,
            hospitalisation_id=hospitalisation.id,
            structure_id=current_user.id_structure,
            motif=motif,
            diagnostic=diagnostic or hospitalisation.motif,
            centre_reference=centre_reference,
            service_reference=service_reference,
            medecin_referent=medecin_referent,
            derniere_tension=patient.tension_arterielle,
            derniere_temperature=patient.temperature_c,
            derniere_pulse=patient.pulse_bpm,
            derniere_saturation=patient.oxygene_saturation,
            dernier_poids=patient.poids_kg,
            derniere_taille=patient.taille_cm,
            dernier_imc=patient.imc,
            resume_clinique=resume_clinique,
            examens_realises=examens_realises,
            traitements_en_cours=traitements_en_cours,
            statut='ENVOYE',
            created_by=current_user.id
        )
        
        db.session.add(reference)
        db.session.commit()
        
        flash('✅ Référence créée avec succès', 'success')
        return redirect(url_for('imprimer_reference', id=reference.id))
    
    return render_template('hospitalisations/ajouter_reference.html',
                         hospitalisation=hospitalisation,
                         patient=patient)


if __name__ == '__main__':
    app.run(debug=True)