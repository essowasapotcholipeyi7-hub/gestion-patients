from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib

db = SQLAlchemy()

# Table des structures (cabinets/cliniques)
class Structure(db.Model):
    __tablename__ = 'structures'
    
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    adresse = db.Column(db.Text)
    telephone = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True)
    statut = db.Column(db.String(20), default='en_attente')  # en_attente, actif, refuse
    
    # Logo et personnalisation
    logo_url = db.Column(db.String(500))
    primary_color = db.Column(db.String(7), default='#0d6efd')
    secondary_color = db.Column(db.String(7), default='#6c757d')
    
    # Questions secrètes pour réinitialisation
    reset_question = db.Column(db.String(255))
    reset_answer_hash = db.Column(db.String(255))
    
    # Dates
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    date_activation = db.Column(db.DateTime)
    
    # Relations
    utilisateurs = db.relationship('Utilisateur', backref='structure', lazy=True)
    patients = db.relationship('Patient', backref='structure', lazy=True)

# Table des utilisateurs
class Utilisateur(UserMixin, db.Model):
    __tablename__ = 'utilisateurs'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nom = db.Column(db.String(100))
    prenom = db.Column(db.String(100))
    
    # Rôle et structure
    role = db.Column(db.String(50), default='medecin')  # super_admin, admin_structure, medecin, secretaire
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'))
    
    # Statut
    actif = db.Column(db.Boolean, default=True)
    
    # Réinitialisation mot de passe
    reset_token = db.Column(db.String(255))
    reset_token_expiry = db.Column(db.DateTime)
    reset_question = db.Column(db.String(255))
    reset_answer_hash = db.Column(db.String(255))
    
    # Dates
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_connexion = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def set_reset_answer(self, answer):
        self.reset_answer_hash = hashlib.sha256(answer.lower().strip().encode()).hexdigest()
    
    def check_reset_answer(self, answer):
        return self.reset_answer_hash == hashlib.sha256(answer.lower().strip().encode()).hexdigest()

# Table des patients
class Patient(db.Model):
    __tablename__ = 'patients'
    
    id = db.Column(db.Integer, primary_key=True)
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    id_medecin_referent = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    
    # Identité
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    date_naissance = db.Column(db.Date)
    lieu_naissance = db.Column(db.String(100))
    sexe = db.Column(db.String(10))  # M, F, Autre
    telephone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    adresse = db.Column(db.Text)
    code_postal = db.Column(db.String(20))
    ville = db.Column(db.String(100))
    profession = db.Column(db.String(100))
    
    # Assurance (spécifique Togo)
    type_assurance = db.Column(db.String(50))  # AMU-CNSS, AMU-INAM, AUTRE_ASSURANCE, NON_ASSURÉ
    autre_assurance_nom = db.Column(db.String(100))
    num_assure = db.Column(db.String(50))
    
    # Médical
    mutuelle = db.Column(db.String(100))
    medecin_traitant = db.Column(db.String(100))
    personne_a_prevenir = db.Column(db.String(100))
    tel_personne_prevenir = db.Column(db.String(50))
    allergies = db.Column(db.Text)
    antecedents_medicaux = db.Column(db.Text)
    antecedents_chirurgicaux = db.Column(db.Text)
    traitements_en_cours = db.Column(db.Text)
    tabac = db.Column(db.String(10))
    alcool = db.Column(db.String(10))
    allaitement = db.Column(db.Boolean, default=False)
    grossesse = db.Column(db.Boolean, default=False)
    groupe_sanguin = db.Column(db.String(5))
    taille_cm = db.Column(db.Float)
    poids_kg = db.Column(db.Float)
    
    # Suivi médical
    statut_medical = db.Column(db.String(50), default='PREMIERE_VISITE')  # PREMIERE_VISITE, EN_TRAITEMENT, GUERI, TRANSFERE, DECEDE, PERDU_VUE
    date_premiere_visite = db.Column(db.DateTime, default=datetime.utcnow)
    date_derniere_consultation = db.Column(db.DateTime)
    date_guerison = db.Column(db.DateTime)
    
    # Archivage
    archived = db.Column(db.Boolean, default=False)
    archived_at = db.Column(db.DateTime)
    archived_by = db.Column(db.Integer)
    archive_reason = db.Column(db.String(255))
    
    # Métadonnées
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_modification = db.Column(db.DateTime, onupdate=datetime.utcnow)
    notes = db.Column(db.Text)
    
    # Relations
    consultations = db.relationship('Consultation', backref='patient', lazy=True, cascade='all, delete-orphan')
    prescriptions = db.relationship('Prescription', backref='patient', lazy=True)
    medecin_referent = db.relationship('Utilisateur', foreign_keys=[id_medecin_referent], backref='patients_suivis')

# Table des consultations
class Consultation(db.Model):
    __tablename__ = 'consultations'
    
    id = db.Column(db.Integer, primary_key=True)
    id_patient = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    id_medecin = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    id_consultation_precedente = db.Column(db.Integer, db.ForeignKey('consultations.id'))
    
    # Type et motif
    type_consultation = db.Column(db.String(20))  # NOUVELLE, SUIVI, URGENCE, CONTROLE
    motif = db.Column(db.String(200))
    symptomes = db.Column(db.Text)
    
    # Signes vitaux
    temperature_c = db.Column(db.Float)
    tension_arterielle = db.Column(db.String(20))
    pulse_bpm = db.Column(db.Integer)
    oxygene_saturation = db.Column(db.Integer)
    poids_kg = db.Column(db.Float)
    taille_cm = db.Column(db.Float)      # 👈 NOUVEAU
    imc = db.Column(db.Float)             # 👈 NOUVEAU
    
    # Examens
    examens_medicaux = db.Column(db.Text)        # 👈 NOUVEAU
    examens_paramedicaux = db.Column(db.Text)    # 👈 NOUVEAU
    
    # Diagnostic et traitement
    diagnostic = db.Column(db.Text)
    examens_realises = db.Column(db.Text)
    notes_cliniques = db.Column(db.Text)
    traitement_prescrit = db.Column(db.Text)
    
    # Arrêt de travail
    arret_travail = db.Column(db.Boolean, default=False)
    arret_jours = db.Column(db.Integer)
    date_retour = db.Column(db.Date)
    
    # Suivi
    prochain_rdv = db.Column(db.DateTime)
    statut = db.Column(db.String(50), default='en_cours')
    
    # Métadonnées
    date_consultation = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer)
    
    # Relations
    prescriptions = db.relationship('Prescription', backref='consultation', lazy=True)
    consultation_precedente = db.relationship('Consultation', remote_side=[id])

# Table des prescriptions
class Prescription(db.Model):
    __tablename__ = 'prescriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    id_patient = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    id_consultation = db.Column(db.Integer, db.ForeignKey('consultations.id'))
    id_medecin = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    
    # Médicament
    medicament = db.Column(db.String(100), nullable=False)
    dosage = db.Column(db.String(50))
    forme = db.Column(db.String(50))
    quantite = db.Column(db.String(50))
    duree_jours = db.Column(db.Integer)
    frequence = db.Column(db.String(100))
    instructions = db.Column(db.Text)
    
    # Renouvellement
    renouvelable = db.Column(db.Boolean, default=False)
    nombre_renouvellements = db.Column(db.Integer, default=0)
    prescripteur = db.Column(db.String(100))
    
    # Statut
    statut = db.Column(db.String(50), default='active')  # active, terminee, annulee
    date_debut = db.Column(db.Date)
    date_fin = db.Column(db.Date)
    
    # Métadonnées
    date_prescription = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    id_expediteur = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    id_destinataire = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    sujet = db.Column(db.String(200), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    lu = db.Column(db.Boolean, default=False)
    lu_at = db.Column(db.DateTime)
    
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    expediteur = db.relationship('Utilisateur', foreign_keys=[id_expediteur], backref='messages_envoyes')
    destinataire = db.relationship('Utilisateur', foreign_keys=[id_destinataire], backref='messages_recus')

# Table des logs (audit trail)
class Log(db.Model):
    __tablename__ = 'logs'
    
    id = db.Column(db.Integer, primary_key=True)
    id_utilisateur = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'))
    action = db.Column(db.String(50))  # CREATE, UPDATE, ARCHIVE, DELETE, LOGIN, RESET_PWD
    table_name = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    old_values = db.Column(db.Text)
    new_values = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    date_action = db.Column(db.DateTime, default=datetime.utcnow)