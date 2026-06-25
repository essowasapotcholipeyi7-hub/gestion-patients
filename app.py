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

load_dotenv()

# Initialisation de l'application
app = Flask(__name__)
app.config.from_object('config.Config')

# Initialisation de la base de données
from models import db
db.init_app(app)

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

@app.template_filter('nl2br')
def nl2br_filter(text):
    """Convertit les sauts de ligne en <br>"""
    if not text:
        return text
    return text.replace('\n', '<br>')

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
            
            # Redirection selon le rôle
            if user.role == 'super_admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'admin_structure':
                return redirect(url_for('structure_dashboard'))
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

@app.route('/dashboard')
@login_required
def dashboard():
    from models import Patient, Consultation, Prescription
    from datetime import date
    
    if current_user.role == 'super_admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'admin_structure':
        return redirect(url_for('structure_dashboard'))
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
                             today=date.today())
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
    
    if current_user.role == 'admin_structure':
        patients = Patient.query.filter_by(id_structure=current_user.id_structure, archived=False).all()
    elif current_user.role == 'medecin':
        patients = Patient.query.filter_by(id_structure=current_user.id_structure, 
                                          id_medecin_referent=current_user.id,
                                          archived=False).all()
    else:  # secretaire
        patients = Patient.query.filter_by(id_structure=current_user.id_structure, archived=False).all()
    
    return render_template('patients/list.html', patients=patients)

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
        
        # Assurance
        type_assurance = request.form.get('type_assurance')
        autre_assurance_nom = request.form.get('autre_assurance_nom')
        num_assure = request.form.get('num_assure')
        
        # Médecin référent
        id_medecin_referent = request.form.get('id_medecin_referent')
        
        # ⭐ CONSTANTES VITALES
        temperature = request.form.get('temperature')
        tension = request.form.get('tension')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        
        # Validation
        if not nom or not prenom:
            flash('Le nom et le prénom sont obligatoires', 'danger')
            return redirect(url_for('patient_ajouter'))
        
        # Création du patient
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
            type_assurance=type_assurance,
            autre_assurance_nom=autre_assurance_nom if type_assurance == 'AUTRE_ASSURANCE' else None,
            num_assure=num_assure,
            id_medecin_referent=int(id_medecin_referent) if id_medecin_referent else None,
            # ⭐ CONSTANTES DANS PATIENT
            temperature_c=float(temperature) if temperature else None,
            tension_arterielle=tension,
            pulse_bpm=int(pouls) if pouls else None,
            oxygene_saturation=int(saturation) if saturation else None,
            poids_kg=float(poids) if poids else None,
            taille_cm=float(taille) if taille else None,
            imc=float(imc) if imc else None,
            statut_medical='PREMIERE_VISITE',
            date_premiere_visite=datetime.utcnow(),
            archived=False
        )
        
        db.session.add(patient)
        db.session.flush()  # Pour obtenir l'ID du patient
        
        # ⭐ CRÉER UNE PREMIÈRE CONSULTATION AVEC LES CONSTANTES
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=current_user.id if current_user.role == 'medecin' else int(id_medecin_referent) if id_medecin_referent else None,
            motif="Première consultation - Enregistrement initial",
            # ⭐ CONSTANTES DANS CONSULTATION
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
        
        flash(f'Patient {prenom} {nom} ajouté avec succès avec ses constantes vitales', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    
    return render_template('patients/ajouter.html', medecins=medecins)

@app.route('/patient/<int:id>')
@login_required
@has_permission('PATIENTS')
def patient_detail(id):
    from models import Patient, Consultation, Prescription
    
    patient = Patient.query.get_or_404(id)
    
    if current_user.role == 'medecin' and patient.id_medecin_referent != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('patients_list'))
    
    consultations = Consultation.query.filter_by(id_patient=patient.id).order_by(Consultation.date_consultation.desc()).all()
    prescriptions = Prescription.query.filter_by(id_patient=patient.id).order_by(Prescription.date_prescription.desc()).all()
    
    return render_template('patients/detail.html', 
                         patient=patient, 
                         consultations=consultations,
                         prescriptions=prescriptions,
                         now=datetime.now())

# ==================== CONSULTATIONS ====================

@app.route('/consultation/ajouter', methods=['GET', 'POST'])
@login_required
def consultation_ajouter():
    from models import Patient, Consultation, AnalyseDemande
    from datetime import datetime
    
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
        
        # Antécédents
        allergies = request.form.get('allergies')
        traitements_en_cours = request.form.get('traitements_en_cours')
        antecedents_medicaux = request.form.get('antecedents_medicaux')
        antecedents_chirurgicaux = request.form.get('antecedents_chirurgicaux')
        
        # Création de la consultation
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
            date_consultation=datetime.utcnow(),
            allergies=allergies,
            traitements_en_cours=traitements_en_cours,
            antecedents_medicaux=antecedents_medicaux,
            antecedents_chirurgicaux=antecedents_chirurgicaux,
            cim10=cim10
        )
        
        db.session.add(consultation)
        db.session.flush()  # Pour obtenir l'ID de la consultation
        
        # ⭐⭐⭐ CRÉATION AUTOMATIQUE DES ANALYSES ⭐⭐⭐
        
        # Analyser les examens de biologie (une par ligne)
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
        
        # Analyser les examens d'imagerie (une par ligne)
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
        
        # Mise à jour du patient
        patient = Patient.query.get(id_patient)
        
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
        
        db.session.commit()
        
        flash('Consultation enregistrée avec succès', 'success')
        return redirect(url_for('patient_detail', id=id_patient))
    
    return render_template('consultations/ajouter.html', patients=patients)

@app.route('/consultation/<int:id>')
@login_required
def consultation_detail(id):
    from models import Consultation, Patient
    
    consultation = Consultation.query.get_or_404(id)
    patient = Patient.query.get(consultation.id_patient)
    
    return render_template('consultations/detail.html', consultation=consultation, patient=patient)


# ==================== PRESCRIPTIONS ====================

@app.route('/prescription/ajouter', methods=['GET', 'POST'])
@login_required
def prescription_ajouter():
    from models import Patient, Prescription
    
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
        medicament = request.form.get('medicament')
        dosage = request.form.get('dosage')
        duree_jours = request.form.get('duree_jours')
        instructions = request.form.get('instructions')
        
        prescription = Prescription(
            id_patient=int(id_patient),
            id_medecin=current_user.id,
            medicament=medicament,
            dosage=dosage,
            duree_jours=int(duree_jours) if duree_jours else None,
            instructions=instructions,
            date_prescription=datetime.utcnow(),
            statut='active'
        )
        
        db.session.add(prescription)
        db.session.commit()
        
        flash('Prescription enregistrée avec succès', 'success')
        return redirect(url_for('patient_detail', id=id_patient))
    
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
        patient.nom = request.form.get('nom')
        patient.prenom = request.form.get('prenom')
        patient.date_naissance = datetime.strptime(request.form.get('date_naissance'), '%Y-%m-%d') if request.form.get('date_naissance') else None
        patient.telephone = request.form.get('telephone')
        patient.email = request.form.get('email')
        patient.adresse = request.form.get('adresse')
        patient.type_assurance = request.form.get('type_assurance')
        patient.autre_assurance_nom = request.form.get('autre_assurance_nom') if request.form.get('type_assurance') == 'AUTRE_ASSURANCE' else None
        patient.num_assure = request.form.get('num_assure')
        patient.id_medecin_referent = int(request.form.get('id_medecin_referent')) if request.form.get('id_medecin_referent') else None
        patient.allergies = request.form.get('allergies')
        patient.antecedents_medicaux = request.form.get('antecedents')
        patient.notes = request.form.get('notes')
        
        db.session.commit()
        flash('Patient modifié avec succès', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    
    return render_template('patients/modifier.html', patient=patient, medecins=medecins)


# ==================== CONSULTATION AVEC PATIENT SPECIFIQUE ====================

@app.route('/patient/<int:id>/consultation/ajouter', methods=['GET', 'POST'])
@login_required
def consultation_ajouter_avec_patient(id):
    from models import Patient, Consultation, AnalyseDemande
    from datetime import datetime
    
    patient = Patient.query.get_or_404(id)
    
    if current_user.role == 'medecin' and patient.id_medecin_referent != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('patients_list'))
    
    if request.method == 'POST':
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')
        
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
        
        # Diagnostic et traitement
        traitement = request.form.get('traitement')
        notes = request.form.get('notes')
        cim10 = request.form.get('cim10')
        
        # Arrêt de travail
        arret_travail = request.form.get('arret_travail') == 'on'
        arret_jours = request.form.get('arret_jours')
        
        # Prochain RDV
        prochain_rdv = request.form.get('prochain_rdv')
        
        # Statut médical
        statut_medical = request.form.get('statut_medical')
        
        # Antécédents
        allergies = request.form.get('allergies')
        traitements_en_cours = request.form.get('traitements_en_cours')
        antecedents_medicaux = request.form.get('antecedents_medicaux')
        antecedents_chirurgicaux = request.form.get('antecedents_chirurgicaux')
        
        # Création de la consultation
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=current_user.id if current_user.role == 'medecin' else None,
            motif=motif,
            diagnostic=diagnostic,
            # Constantes
            tension_arterielle=tension,
            temperature_c=float(temperature) if temperature else None,
            pulse_bpm=int(pouls) if pouls else None,
            oxygene_saturation=int(saturation) if saturation else None,
            poids_kg=float(poids) if poids else None,
            taille_cm=float(taille) if taille else None,
            imc=float(imc) if imc else None,
            # Examens
            examens_cliniques=examens_cliniques,
            examens_biologie=examens_biologie,
            examens_imagerie=examens_imagerie,
            # Diagnostic et traitement
            traitement_prescrit=traitement,
            notes_cliniques=notes,
            cim10=cim10,
            # Arrêt de travail
            arret_travail=arret_travail,
            arret_jours=int(arret_jours) if arret_jours else None,
            # Prochain RDV
            prochain_rdv=datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None,
            date_consultation=datetime.utcnow(),
            # Antécédents
            allergies=allergies,
            traitements_en_cours=traitements_en_cours,
            antecedents_medicaux=antecedents_medicaux,
            antecedents_chirurgicaux=antecedents_chirurgicaux
        )
        
        db.session.add(consultation)
        db.session.flush()  # ⭐ Pour obtenir l'ID de la consultation
        
        # ⭐⭐⭐ CRÉATION AUTOMATIQUE DES ANALYSES ⭐⭐⭐
        
        # Analyser les examens de biologie (une par ligne)
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
        
        # Analyser les examens d'imagerie (une par ligne)
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
        
        # Mettre à jour les constantes dans Patient
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
        
        # Mettre à jour le statut médical
        if statut_medical:
            patient.statut_medical = statut_medical
            if statut_medical == 'GUERI':
                patient.date_guerison = datetime.utcnow()
        elif patient.statut_medical == 'PREMIERE_VISITE':
            patient.statut_medical = 'EN_TRAITEMENT'
        
        db.session.commit()
        
        flash(f'Consultation pour {patient.prenom} {patient.nom} enregistrée avec succès', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    
    return render_template('consultations/ajouter_avec_patient.html', patient=patient)

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
    """Créer une nouvelle hospitalisation"""
    from models import Patient, Utilisateur, Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, Service, Salle, Lit
    
    if current_user.role not in ['admin_structure', 'medecin', 'secretaire']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        patient_id = request.form.get('patient_id')
        motif = request.form.get('motif')
        service = request.form.get('service')
        chambre = request.form.get('chambre')
        lit = request.form.get('lit')  # ⭐ Gardé pour compatibilité
        lit_id = request.form.get('lit_id', type=int)  # ⭐ NOUVEAU
        notes_admission = request.form.get('notes_admission')
        medecins_ids = request.form.getlist('medecins_ids')
        infirmiers_ids = request.form.getlist('infirmiers_ids')
        
        # Validation
        if not patient_id or not motif or not service:
            flash('Le patient, le motif et le service sont obligatoires', 'danger')
            return redirect(url_for('nouvelle_hospitalisation'))
        
        # Créer l'hospitalisation
        hospitalisation = Hospitalisation(
            patient_id=int(patient_id),
            motif=motif,
            service=service,
            chambre=chambre,
            lit=lit,
            notes_admission=notes_admission,
            statut='actif',
            created_by=current_user.id
        )
        db.session.add(hospitalisation)
        db.session.flush()
        
        # ⭐ ASSIGNER LE LIT SI SÉLECTIONNÉ
        if lit_id:
            lit_obj = Lit.query.get(lit_id)
            if lit_obj and lit_obj.statut == 'disponible':
                lit_obj.occuper(hospitalisation.id)
                hospitalisation.lit_id = lit_obj.id
                # Mettre à jour chambre et lit dans hospitalisation
                hospitalisation.chambre = lit_obj.salle.nom
        
        # Assigner les médecins
        for medecin_id in medecins_ids:
            hm = HospitalisationMedecin(
                hospitalisation_id=hospitalisation.id,
                medecin_id=int(medecin_id)
            )
            db.session.add(hm)
        
        # Assigner les infirmiers
        for infirmier_id in infirmiers_ids:
            hi = HospitalisationInfirmier(
                hospitalisation_id=hospitalisation.id,
                infirmier_id=int(infirmier_id)
            )
            db.session.add(hi)
        
        db.session.commit()
        
        flash(f'Hospitalisation créée avec succès pour {hospitalisation.patient.nom} {hospitalisation.patient.prenom}', 'success')
        return redirect(url_for('detail_hospitalisation', id=hospitalisation.id))
    
    # GET: Afficher le formulaire
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
    
    # ⭐ Récupérer les services pour le formulaire
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
    """Détails d'une hospitalisation"""
    from models import Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, ConstanteVitale, EvolutionPatient
    
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
    
    # Récupérer les données associées
    medecins = hospitalisation.medecins.filter_by(actif=True).all()
    infirmiers = hospitalisation.infirmiers.filter_by(actif=True).all()
    constantes = hospitalisation.constantes.order_by(ConstanteVitale.date_prise.desc()).limit(50).all()
    evolutions = hospitalisation.evolutions.order_by(EvolutionPatient.date_evolution.desc()).all()
    
    return render_template('hospitalisations/detail.html',
                         hospitalisation=hospitalisation,
                         medecins=medecins,
                         infirmiers=infirmiers,
                         constantes=constantes,
                         evolutions=evolutions)


@app.route('/hospitalisation/<int:id>/evolution', methods=['GET', 'POST'])
@login_required
def ajouter_evolution(id):
    """Ajouter une évolution pour un patient hospitalisé"""
    from models import Hospitalisation, HospitalisationMedecin, HospitalisationInfirmier, EvolutionPatient
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # Vérifier les permissions
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
    
    if request.method == 'POST':
        etat_echelle = request.form.get('etat_echelle', type=int)
        temperature = request.form.get('temperature', type=float)
        pression = request.form.get('pression')
        fc = request.form.get('fc', type=int)
        symptomes = request.form.get('symptomes')
        traitement_administre = request.form.get('traitement_administre')
        observations = request.form.get('observations')
        prochaines_etapes = request.form.get('prochaines_etapes')
        
        if etat_echelle is None or etat_echelle < 0 or etat_echelle > 10:
            flash('L\'état doit être entre 0 et 10', 'danger')
            return redirect(url_for('ajouter_evolution', id=id))
        
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
            redige_par=current_user.id
        )
        db.session.add(evolution)
        db.session.commit()
        
        flash('Évolution enregistrée avec succès', 'success')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    return render_template('hospitalisations/evolution.html',
                         hospitalisation=hospitalisation)


@app.route('/hospitalisation/<int:id>/constante', methods=['GET', 'POST'])
@login_required
def ajouter_constante(id):
    """Ajouter des constantes vitales pour un patient hospitalisé"""
    from models import Hospitalisation, HospitalisationInfirmier, HospitalisationMedecin, ConstanteVitale
    
    hospitalisation = Hospitalisation.query.get_or_404(id)
    
    # Permissions
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
    
    if request.method == 'POST':
        temperature = request.form.get('temperature', type=float)
        pression_arterielle = request.form.get('pression_arterielle')
        frequence_cardiaque = request.form.get('frequence_cardiaque', type=int)
        frequence_respiratoire = request.form.get('frequence_respiratoire', type=int)
        saturation_oxygene = request.form.get('saturation_oxygene', type=float)
        glycemie = request.form.get('glycemie', type=float)
        poids = request.form.get('poids', type=float)
        taille = request.form.get('taille', type=float)
        
        # ⭐ NOUVEAUX CHAMPS
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
        
        imc = None
        if poids and taille and taille > 0:
            imc = round(poids / ((taille/100) ** 2), 1)
        
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
            # ⭐ NOUVEAUX CHAMPS
            diurese=diurese,
            emission_gaz=emission_gaz,
            selles=selles,
            vomissements=vomissements,
            douleur=douleur,
            conscience=conscience,
            pouls_peripherique=pouls_peripherique,
            temperature_cutanee=temperature_cutanee,
            autres_constantes=autres_constantes,
            notes=notes
        )
        db.session.add(constante)
        db.session.commit()
        
        flash('Constantes vitales enregistrées avec succès', 'success')
        return redirect(url_for('detail_hospitalisation', id=id))
    
    return render_template('hospitalisations/constante.html',
                         hospitalisation=hospitalisation)

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
    
    # ⭐ PERMISSIONS - Médecin, Laborantin, Admin, Super Admin
    if current_user.role not in ['super_admin', 'admin_structure', 'laborantin', 'medecin']:
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
    """Le laborantin saisit les résultats"""
    from models import AnalyseDemande, Consultation
    from datetime import datetime
    
    analyse = AnalyseDemande.query.get_or_404(id)
    
    if current_user.role not in ['laborantin', 'admin_structure', 'super_admin']:
        flash('Accès non autorisé - réservé au laborantin', 'danger')
        return redirect(url_for('dashboard'))
    
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
    
    # ⭐⭐⭐ METTRE À JOUR LES RÉSULTATS DE LA CONSULTATION ⭐⭐⭐
    consultation = Consultation.query.get(analyse.consultation_id)
    if consultation:
        # Ajouter les résultats dans le champ approprié selon le type
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
        
        # Mettre à jour la date des résultats
        consultation.date_resultats = datetime.utcnow()
    
    db.session.commit()
    
    flash('✅ Résultats enregistrés avec succès', 'success')
    return redirect(url_for('liste_analyses'))

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
    """Voir toutes les analyses d'un patient"""
    from models import Patient, AnalyseDemande
    
    patient = Patient.query.get_or_404(patient_id)
    
    # ⭐ PERMISSIONS
    if current_user.role not in ['super_admin', 'admin_structure', 'laborantin', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Vérifier la structure
    if current_user.role not in ['super_admin']:
        if patient.id_structure != current_user.id_structure:
            flash('Accès non autorisé - patient d\'une autre structure', 'danger')
            return redirect(url_for('liste_analyses'))
    
    # Récupérer les analyses
    analyses = AnalyseDemande.query.filter_by(
        patient_id=patient_id,
        structure_id=current_user.id_structure
    ).order_by(AnalyseDemande.date_demande.desc()).all()
    
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
    from models import Reference
    
    reference = Reference.query.get_or_404(id)
    
    if current_user.role not in ['super_admin', 'admin_structure', 'medecin']:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    if reference.structure_id != current_user.id_structure and current_user.role != 'super_admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    return render_template('references/imprimer.html', reference=reference)
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

if __name__ == '__main__':
    app.run(debug=True)