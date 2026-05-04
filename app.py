from flask import Flask, render_template, redirect, url_for, flash, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
import os
from dotenv import load_dotenv
from scheduler import start_scheduler, stop_scheduler
from datetime import datetime, timedelta

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
    from models import Utilisateur
    return Utilisateur.query.get(int(user_id))

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
def patient_ajouter():
    from models import Patient, Utilisateur
    
    # Récupérer la liste des médecins pour la structure (si admin_structure ou secretaire)
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
        # Récupérer les données
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        date_naissance = request.form.get('date_naissance')
        telephone = request.form.get('telephone')
        email = request.form.get('email')
        adresse = request.form.get('adresse')
        type_assurance = request.form.get('type_assurance')
        autre_assurance_nom = request.form.get('autre_assurance_nom') if type_assurance == 'AUTRE_ASSURANCE' else None
        num_assure = request.form.get('num_assure')
        id_medecin_referent = request.form.get('id_medecin_referent')
        allergies = request.form.get('allergies')
        antecedents = request.form.get('antecedents')
        notes = request.form.get('notes')
        
        # Validation
        if not nom or not prenom:
            flash('Le nom et le prénom sont obligatoires', 'danger')
            return redirect(url_for('patient_ajouter'))
        
        # Création du patient
        from datetime import datetime
        patient = Patient(
            id_structure=current_user.id_structure if current_user.id_structure else 1,
            nom=nom,
            prenom=prenom,
            date_naissance=datetime.strptime(date_naissance, '%Y-%m-%d') if date_naissance else None,
            telephone=telephone,
            email=email,
            adresse=adresse,
            type_assurance=type_assurance,
            autre_assurance_nom=autre_assurance_nom,
            num_assure=num_assure,
            id_medecin_referent=int(id_medecin_referent) if id_medecin_referent else None,
            allergies=allergies,
            antecedents_medicaux=antecedents,
            notes=notes,
            statut_medical='PREMIERE_VISITE',
            date_premiere_visite=datetime.utcnow(),
            archived=False
        )
        
        db.session.add(patient)
        db.session.commit()
        
        flash(f'Patient {prenom} {nom} ajouté avec succès', 'success')
        
        # Rediriger vers la fiche du patient
        return redirect(url_for('patient_detail', id=patient.id))
    
    return render_template('patients/ajouter.html', medecins=medecins)


from datetime import datetime

@app.route('/patient/<int:id>')
@login_required
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
    from models import Patient, Consultation
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
        tension = request.form.get('tension')
        temperature = request.form.get('temperature')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        examens_medicaux = request.form.get('examens_medicaux')
        examens_paramedicaux = request.form.get('examens_paramedicaux')
        traitement = request.form.get('traitement')
        notes = request.form.get('notes')
        prochain_rdv = request.form.get('prochain_rdv')
        arret_travail = request.form.get('arret_travail') == 'on'
        arret_jours = request.form.get('arret_jours')
        statut_medical = request.form.get('statut_medical')  # 👈 NOUVEAU
        
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
            examens_medicaux=examens_medicaux,
            examens_paramedicaux=examens_paramedicaux,
            traitement_prescrit=traitement,
            notes_cliniques=notes,
            arret_travail=arret_travail,
            arret_jours=int(arret_jours) if arret_jours else None,
            prochain_rdv=datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None,
            date_consultation=datetime.utcnow()
        )
        
        db.session.add(consultation)
        
        # Mettre à jour le patient
        patient = Patient.query.get(id_patient)
        patient.date_derniere_consultation = datetime.utcnow()
        
        # 👈 NOUVEAU : Mettre à jour le statut si changé
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
    from models import Patient, Consultation
    from datetime import datetime
    
    patient = Patient.query.get_or_404(id)
    
    if current_user.role == 'medecin' and patient.id_medecin_referent != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('patients_list'))
    
    if request.method == 'POST':
        motif = request.form.get('motif')
        diagnostic = request.form.get('diagnostic')
        tension = request.form.get('tension')
        temperature = request.form.get('temperature')
        pouls = request.form.get('pouls')
        saturation = request.form.get('saturation')
        poids = request.form.get('poids')
        taille = request.form.get('taille')
        imc = request.form.get('imc')
        examens_medicaux = request.form.get('examens_medicaux')
        examens_paramedicaux = request.form.get('examens_paramedicaux')
        traitement = request.form.get('traitement')
        notes = request.form.get('notes')
        prochain_rdv = request.form.get('prochain_rdv')
        arret_travail = request.form.get('arret_travail') == 'on'
        arret_jours = request.form.get('arret_jours')
        statut_medical = request.form.get('statut_medical')  # 👈 NOUVEAU
        
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
            examens_medicaux=examens_medicaux,
            examens_paramedicaux=examens_paramedicaux,
            traitement_prescrit=traitement,
            notes_cliniques=notes,
            arret_travail=arret_travail,
            arret_jours=int(arret_jours) if arret_jours else None,
            prochain_rdv=datetime.strptime(prochain_rdv, '%Y-%m-%d') if prochain_rdv else None,
            date_consultation=datetime.utcnow()
        )
        
        db.session.add(consultation)
        
        # Mettre à jour le patient
        patient.date_derniere_consultation = datetime.utcnow()
        
        # 👈 NOUVEAU : Mettre à jour le statut si changé
        if statut_medical:
            patient.statut_medical = statut_medical
            if statut_medical == 'GUERI':
                patient.date_guerison = datetime.utcnow()
        elif patient.statut_medical == 'PREMIERE_VISITE':
            patient.statut_medical = 'EN_TRAITEMENT'
        
        db.session.commit()
        
        flash(f'Consultation pour {patient.prenom} {patient.nom} enregistrée', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    
    return render_template('consultations/ajouter_avec_patient.html', patient=patient)

# ==================== STATISTIQUES ====================

@app.route('/statistiques')
@login_required
def statistiques():
    from models import Patient, Consultation, Utilisateur
    from datetime import datetime, timedelta
    from sqlalchemy import func, extract
    
    # Récupérer les filtres
    date_debut = request.args.get('date_debut', '')
    date_fin = request.args.get('date_fin', '')
    periode = request.args.get('periode', 'mois')
    medecin_id = request.args.get('medecin_id', '')
    type_assurance = request.args.get('type_assurance', '')
    
    # ========== Construction de la requête de base correctement ==========
    # Commencer par une requête sur Consultation avec jointure à Patient
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
        
    else:  # année
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
        Consultation.diagnostic != ''
    ).group_by(Consultation.diagnostic).order_by(func.count(Consultation.id).desc()).limit(10).all()
    
    # ========== Répartition assurances ==========
    assurances = db.session.query(
        Patient.type_assurance,
        func.count(Patient.id).label('total')
    ).join(Consultation, Patient.id == Consultation.id_patient).filter(
        Consultation.id.in_(base_query.with_entities(Consultation.id))
    ).group_by(Patient.type_assurance).all()
    
    # ========== Statistiques par médecin (admin structure uniquement) ==========
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
    
    # ========== Évolution quotidienne (graphique) ==========
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
    
    # Types d'assurance pour le filtre
    types_assurance = ['AMU-CNSS', 'AMU-INAM', 'AUTRE_ASSURANCE', 'NON_ASSURÉ']
    
    return render_template('statistiques.html',
                         total_consultations=total_consultations,
                         total_patients=total_patients,
                         patients_par_periode=patients_par_periode,
                         top_pathologies=top_pathologies,
                         assurances=assurances,
                         stats_medecins=stats_medecins,
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

if __name__ == '__main__':
    app.run(debug=True)