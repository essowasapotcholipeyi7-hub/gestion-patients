from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib

db = SQLAlchemy()

# ==================== STRUCTURES ====================
class Structure(db.Model):
    __tablename__ = 'structures'
    
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    adresse = db.Column(db.Text)
    telephone = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True)
    statut = db.Column(db.String(20), default='en_attente')
    logo_url = db.Column(db.String(500))
    primary_color = db.Column(db.String(7), default='#0d6efd')
    secondary_color = db.Column(db.String(7), default='#6c757d')
    reset_question = db.Column(db.String(255))
    reset_answer_hash = db.Column(db.String(255))
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    date_activation = db.Column(db.DateTime)
    
    utilisateurs = db.relationship('Utilisateur', backref='structure', lazy=True)
    patients = db.relationship('Patient', backref='structure', lazy=True)


# ==================== UTILISATEURS ====================
class Utilisateur(UserMixin, db.Model):
    __tablename__ = 'utilisateurs'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nom = db.Column(db.String(100))
    prenom = db.Column(db.String(100))
    role = db.Column(db.String(50), default='medecin')
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'))
    actif = db.Column(db.Boolean, default=True)
    reset_token = db.Column(db.String(255))
    reset_token_expiry = db.Column(db.DateTime)
    reset_question = db.Column(db.String(255))
    reset_answer_hash = db.Column(db.String(255))
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


# ==================== PRESCRIPTIONS (AVANT PATIENT) ====================
class Prescription(db.Model):
    __tablename__ = 'prescriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    id_patient = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    id_consultation = db.Column(db.Integer, db.ForeignKey('consultations.id'))
    id_medecin = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    medicament = db.Column(db.String(100), nullable=False)
    dosage = db.Column(db.String(50))
    forme = db.Column(db.String(50))
    quantite = db.Column(db.String(50))
    duree_jours = db.Column(db.Integer)
    frequence = db.Column(db.String(100))
    instructions = db.Column(db.Text)
    renouvelable = db.Column(db.Boolean, default=False)
    nombre_renouvellements = db.Column(db.Integer, default=0)
    prescripteur = db.Column(db.String(100))
    statut = db.Column(db.String(50), default='active')
    date_debut = db.Column(db.Date)
    date_fin = db.Column(db.Date)
    date_prescription = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)


# ==================== CONSULTATIONS (AVANT PATIENT) ====================
class Consultation(db.Model):
    __tablename__ = 'consultations'
    
    id = db.Column(db.Integer, primary_key=True)
    id_patient = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    id_medecin = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    id_consultation_precedente = db.Column(db.Integer, db.ForeignKey('consultations.id'))
    
    type_consultation = db.Column(db.String(20))
    motif = db.Column(db.String(200))
    symptomes = db.Column(db.Text)
    
    # Constantes vitales
    temperature_c = db.Column(db.Float)
    tension_arterielle = db.Column(db.String(20))
    pulse_bpm = db.Column(db.Integer)
    oxygene_saturation = db.Column(db.Integer)
    poids_kg = db.Column(db.Float)
    taille_cm = db.Column(db.Float)
    imc = db.Column(db.Float)
    
    # Examens
    examens_cliniques = db.Column(db.Text)

    # ⭐ EXAMENS PARAMÉDICAUX (biologie + imagerie)
    examens_biologie = db.Column(db.Text)          # NFS, glycémie, bilan hépatique, etc.
    examens_imagerie = db.Column(db.Text)          # Radio, échographie, scanner, IRM, etc.

    # ⭐ RÉSULTATS
    resultats_biologie = db.Column(db.Text)        # Résultats des analyses biologiques
    resultats_imagerie = db.Column(db.Text)        # Résultats de l'imagerie
    date_resultats = db.Column(db.DateTime)

    # Diagnostic et traitement
    diagnostic = db.Column(db.Text)
    examens_realises = db.Column(db.Text)
    notes_cliniques = db.Column(db.Text)
    traitement_prescrit = db.Column(db.Text)
    
    # ⭐ ANTÉCÉDENTS (NOUVEAU)
    allergies = db.Column(db.Text)
    antecedents_medicaux = db.Column(db.Text)
    antecedents_chirurgicaux = db.Column(db.Text)
    traitements_en_cours = db.Column(db.Text)
    
    # Arrêt de travail
    arret_travail = db.Column(db.Boolean, default=False)
    arret_jours = db.Column(db.Integer)
    date_retour = db.Column(db.Date)
    
    # Suivi
    prochain_rdv = db.Column(db.DateTime)
    statut = db.Column(db.String(50), default='en_cours')
    
    date_consultation = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer)
    
    # Relations
    prescriptions = db.relationship('Prescription', backref='consultation', lazy=True)
    consultation_precedente = db.relationship('Consultation', remote_side=[id])


# ==================== PATIENT ====================
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
    sexe = db.Column(db.String(10))
    telephone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    adresse = db.Column(db.Text)
    code_postal = db.Column(db.String(20))
    ville = db.Column(db.String(100))
    profession = db.Column(db.String(100))
    
    # Assurance
    type_assurance = db.Column(db.String(50))
    autre_assurance_nom = db.Column(db.String(100))
    num_assure = db.Column(db.String(50))
    
    # ⭐ CONSTANTES VITALES DANS PATIENT
    temperature_c = db.Column(db.Float)
    tension_arterielle = db.Column(db.String(20))
    pulse_bpm = db.Column(db.Integer)
    oxygene_saturation = db.Column(db.Integer)
    poids_kg = db.Column(db.Float)
    taille_cm = db.Column(db.Float)
    imc = db.Column(db.Float)
    
    # ⚠️ ANTÉCÉDENTS SUPPRIMÉS (déplacés vers Consultation)
    
    # Autres informations
    mutuelle = db.Column(db.String(100))
    medecin_traitant = db.Column(db.String(100))
    personne_a_prevenir = db.Column(db.String(100))
    tel_personne_prevenir = db.Column(db.String(50))
    tabac = db.Column(db.String(10))
    alcool = db.Column(db.String(10))
    allaitement = db.Column(db.Boolean, default=False)
    grossesse = db.Column(db.Boolean, default=False)
    groupe_sanguin = db.Column(db.String(5))
    
    # Suivi médical
    statut_medical = db.Column(db.String(50), default='PREMIERE_VISITE')
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


# ==================== AUTRES CLASSES ====================
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
    
    expediteur = db.relationship('Utilisateur', foreign_keys=[id_expediteur], backref='messages_envoyes')
    destinataire = db.relationship('Utilisateur', foreign_keys=[id_destinataire], backref='messages_recus')


class Log(db.Model):
    __tablename__ = 'logs'
    
    id = db.Column(db.Integer, primary_key=True)
    id_utilisateur = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'))
    action = db.Column(db.String(50))
    table_name = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    old_values = db.Column(db.Text)
    new_values = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    date_action = db.Column(db.DateTime, default=datetime.utcnow)


# ==================== HOSPITALISATION ====================
class Hospitalisation(db.Model):
    __tablename__ = 'hospitalisations'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    date_debut = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_fin = db.Column(db.DateTime, nullable=True)
    motif = db.Column(db.Text, nullable=False)
    service = db.Column(db.String(100), nullable=False)
    chambre = db.Column(db.String(20), nullable=True)
    lit = db.Column(db.String(20), nullable=True)
    statut = db.Column(db.String(20), default='actif')
    centre_transfert = db.Column(db.String(200), nullable=True)
    motif_transfert = db.Column(db.Text, nullable=True)
    date_transfert = db.Column(db.DateTime, nullable=True)
    avis_externes = db.Column(db.Text, nullable=True)
    medecins_externes = db.Column(db.Text, nullable=True)
    demandes_avis = db.Column(db.Text, nullable=True)
    notes_admission = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    
    patient = db.relationship('Patient', backref='hospitalisations')
    medecins = db.relationship('HospitalisationMedecin', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')
    infirmiers = db.relationship('HospitalisationInfirmier', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')
    evolutions = db.relationship('EvolutionPatient', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')
    constantes = db.relationship('ConstanteVitale', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')


class HospitalisationMedecin(db.Model):
    __tablename__ = 'hospitalisation_medecins'
    
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=False)
    medecin_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    role = db.Column(db.String(50), default='medecin_traitant')
    date_assignation = db.Column(db.DateTime, default=datetime.utcnow)
    actif = db.Column(db.Boolean, default=True)
    
    medecin = db.relationship('Utilisateur', backref='hospitalisations_assignees')


class HospitalisationInfirmier(db.Model):
    __tablename__ = 'hospitalisation_infirmiers'
    
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=False)
    infirmier_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    date_assignation = db.Column(db.DateTime, default=datetime.utcnow)
    actif = db.Column(db.Boolean, default=True)
    
    infirmier = db.relationship('Utilisateur', backref='hospitalisations_surveillees')


class ConstanteVitale(db.Model):
    __tablename__ = 'constantes_vitales'
    
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=False)
    infirmier_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    date_prise = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    temperature = db.Column(db.Float, nullable=True)
    pression_arterielle = db.Column(db.String(20), nullable=True)
    frequence_cardiaque = db.Column(db.Integer, nullable=True)
    frequence_respiratoire = db.Column(db.Integer, nullable=True)
    saturation_oxygene = db.Column(db.Float, nullable=True)
    glycemie = db.Column(db.Float, nullable=True)
    poids = db.Column(db.Float, nullable=True)
    taille = db.Column(db.Float, nullable=True)
    imc = db.Column(db.Float, nullable=True)
    autres_constantes = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    infirmier = db.relationship('Utilisateur', backref='constantes_prises')


class EvolutionPatient(db.Model):
    __tablename__ = 'evolutions_patient'
    
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=False)
    date_evolution = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    etat_echelle = db.Column(db.Integer, nullable=False)
    temperature = db.Column(db.Float, nullable=True)
    pression = db.Column(db.String(20), nullable=True)
    fc = db.Column(db.Integer, nullable=True)
    symptomes = db.Column(db.Text, nullable=True)
    traitement_administre = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    prochaines_etapes = db.Column(db.Text, nullable=True)
    redige_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    redacteur = db.relationship('Utilisateur', backref='evolutions_redigees')


class AvisExterne(db.Model):
    __tablename__ = 'avis_externes'
    
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=False)
    medecin_nom = db.Column(db.String(200), nullable=False)
    specialite = db.Column(db.String(100), nullable=True)
    etablissement = db.Column(db.String(200), nullable=True)
    demande_avis = db.Column(db.Text, nullable=True)
    avis_recu = db.Column(db.Text, nullable=False)
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    date_reception = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    hospitalisation = db.relationship('Hospitalisation', backref='avis_externes_list')
    createur = db.relationship('Utilisateur', backref='avis_externes_crees')