from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
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
    
    type_prescription = db.Column(db.String(20), default='medicament')  # 'medicament' ou 'acte
    # Détails du médicament
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
    
    # Suivi
    prescripteur = db.Column(db.String(100))
    statut = db.Column(db.String(50), default='active')
    date_debut = db.Column(db.Date)
    date_fin = db.Column(db.Date)
    date_prescription = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    
    # ⭐ Champs pour la synchronisation
    source_id = db.Column(db.String(50), nullable=True)
    source_medicament_id = db.Column(db.Integer, nullable=True)
    stock_disponible = db.Column(db.Integer, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)
    synced_from = db.Column(db.String(20), default='consultation')
    
    # ⭐ Relations avec des noms UNIQUES
    patient = db.relationship('Patient', foreign_keys=[id_patient], backref='prescriptions_list')
    consultation = db.relationship('Consultation', foreign_keys=[id_consultation], backref='prescriptions_consultation_list')
    medecin = db.relationship('Utilisateur', foreign_keys=[id_medecin], backref='prescriptions_redigees')


# ==================== ACTES POSÉS ====================
# ⭐ Distinct de Prescription (type='acte') : un ACTE POSÉ est réalisé
# directement par le médecin/infirmier sur place (pansement, injection,
# suture, petit soin...), pas un examen PRESCRIT à faire réaliser ailleurs
# (labo/radio — ça reste Prescription). Synchronisé vers GHP pour
# facturation, comme les prescriptions (même pipeline /api/prescriptions).

class ActeType(db.Model):
    """Catalogue des actes posés, par structure — recherché par nom au
    moment de consigner un acte ; complété à la volée (comme pour les
    médicaments) si l'acte n'existe pas encore dans la liste."""
    __tablename__ = 'actes_types'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    nom = db.Column(db.String(200), nullable=False)
    actif = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActePose(db.Model):
    """Un acte réellement effectué, consigné pour un patient donné — que ce
    soit via le journal de soins (dossier patient / consultation) ou saisi
    manuellement dans l'onglet "Actes posés"."""
    __tablename__ = 'actes_poses'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=True)
    acte_type_id = db.Column(db.Integer, db.ForeignKey('actes_types.id'), nullable=True)

    # ⭐ Dénormalisé, toujours rempli (même principe que Prescription.medicament)
    # — permet d'envoyer le libellé à GHP sans jointure, et de garder une
    # trace même si le catalogue est modifié/supprimé ensuite.
    nom = db.Column(db.String(200), nullable=False)
    quantite = db.Column(db.String(50), default='1')
    notes = db.Column(db.Text, nullable=True)

    # ⭐ Détail du soin — pertinent surtout pour injections/perfusions,
    # laissé vide pour les actes qui n'en ont pas besoin.
    produit_administre = db.Column(db.String(200), nullable=True)

    date_pose = db.Column(db.DateTime, default=datetime.utcnow)  # porte aussi l'heure réelle du soin
    pose_par_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    statut = db.Column(db.String(20), default='actif')  # 'actif' | 'annule'

    # ⭐ Étape de vérification avant envoi à GHP : un soin tout juste
    # consigné (dossier patient, consultation, ou saisie manuelle) arrive en
    # "brouillon" dans l'onglet Actes posés — la caissière/l'infirmier(-ère)
    # responsable y vérifie/ajuste la quantité puis valide, ce qui déclenche
    # la synchronisation. Rien ne part vers GHP sans validation explicite.
    valide = db.Column(db.Boolean, default=False, nullable=False)
    valide_par_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    date_validation = db.Column(db.DateTime, nullable=True)

    synced_at = db.Column(db.DateTime, nullable=True)

    patient = db.relationship('Patient', foreign_keys=[patient_id], backref='actes_poses')
    consultation = db.relationship('Consultation', foreign_keys=[consultation_id], backref='actes_poses_consultation')
    hospitalisation = db.relationship('Hospitalisation', foreign_keys=[hospitalisation_id], backref='actes_poses_hospitalisation')
    acte_type = db.relationship('ActeType', foreign_keys=[acte_type_id])
    pose_par = db.relationship('Utilisateur', foreign_keys=[pose_par_id], backref='actes_poses_realises')
    valide_par = db.relationship('Utilisateur', foreign_keys=[valide_par_id])


# ==================== CONSULTATIONS ====================
class Consultation(db.Model):
    __tablename__ = 'consultations'
    
    id = db.Column(db.Integer, primary_key=True)
    id_patient = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    id_medecin = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    id_consultation_precedente = db.Column(db.Integer, db.ForeignKey('consultations.id'))
    
    type_consultation = db.Column(db.String(20))
    motif = db.Column(db.String(200))
    symptomes = db.Column(db.Text)
    type_prescription = db.Column(db.String(20), default='acte')
    
    temperature_c = db.Column(db.Float)
    tension_arterielle = db.Column(db.String(20))
    pulse_bpm = db.Column(db.Integer)
    oxygene_saturation = db.Column(db.Integer)
    poids_kg = db.Column(db.Float)
    taille_cm = db.Column(db.Float)
    imc = db.Column(db.Float)
    
    examens_cliniques = db.Column(db.Text)
    examens_biologie = db.Column(db.Text)
    examens_imagerie = db.Column(db.Text)
    resultats_biologie = db.Column(db.Text)
    resultats_imagerie = db.Column(db.Text)
    date_resultats = db.Column(db.DateTime)

    diagnostic = db.Column(db.Text)
    examens_realises = db.Column(db.Text)
    notes_cliniques = db.Column(db.Text)
    traitement_prescrit = db.Column(db.Text)
    ordonnance_prescite = db.Column(db.Text, nullable=True)
    
    # Lien vers l'ordonnance active
    ordonnance_active_id = db.Column(db.Integer, db.ForeignKey('ordonnances.id'), nullable=True)
    protocole_applique_id = db.Column(db.Integer, db.ForeignKey('protocoles_soins.id'), nullable=True)
    
    cim10 = db.Column(db.Text, nullable=True)
    
    allergies = db.Column(db.Text)
    antecedents_medicaux = db.Column(db.Text)
    antecedents_chirurgicaux = db.Column(db.Text)
    traitements_en_cours = db.Column(db.Text)
    
    arret_travail = db.Column(db.Boolean, default=False)
    arret_jours = db.Column(db.Integer)
    date_retour = db.Column(db.Date)
    
    prochain_rdv = db.Column(db.DateTime)
    statut = db.Column(db.String(50), default='en_cours')
    date_consultation = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer)
    
    # ⭐ HISTOIRE DE LA MALADIE (HPI)
    # Partie structurée (infirmier)
    hpi_date_debut = db.Column(db.Date, nullable=True)
    hpi_debut_type = db.Column(db.String(20), nullable=True)
    hpi_circonstances = db.Column(db.Text, nullable=True)
    hpi_evolution = db.Column(db.Text, nullable=True)
    hpi_facteurs = db.Column(db.Text, nullable=True)
    hpi_traitements = db.Column(db.Text, nullable=True)
    hpi_signes = db.Column(db.Text, nullable=True)

    # ⭐ AJOUTER CES CHAMPS POUR LES SIGNES ASSOCIÉS
    hpi_fievre = db.Column(db.Boolean, default=False)
    hpi_nausees = db.Column(db.Boolean, default=False)
    hpi_douleur = db.Column(db.Boolean, default=False)
    hpi_cephalées = db.Column(db.Boolean, default=False)
    hpi_vertiges = db.Column(db.Boolean, default=False)
    hpi_dyspnee = db.Column(db.Boolean, default=False)

    
    # Champs spécifiques (traumatisme)
    hpi_trauma_mecanisme = db.Column(db.Text, nullable=True)
    hpi_trauma_heure = db.Column(db.DateTime, nullable=True)
    hpi_trauma_pc = db.Column(db.String(20), nullable=True)
    hpi_trauma_description = db.Column(db.Text, nullable=True)
    
    # Champs spécifiques (morsure)
    hpi_morsure_type = db.Column(db.String(30), nullable=True)
    hpi_morsure_espece = db.Column(db.String(50), nullable=True)
    hpi_morsure_siege = db.Column(db.String(50), nullable=True)
    hpi_morsure_signes = db.Column(db.Text, nullable=True)
    
    # Champs spécifiques (intoxication)
    hpi_intox_substance = db.Column(db.String(100), nullable=True)
    hpi_intox_heure = db.Column(db.DateTime, nullable=True)
    hpi_intox_circonstances = db.Column(db.Text, nullable=True)
    
    # Autres champs
    hpi_autres_signes = db.Column(db.String(200), nullable=True)
    hpi_autre_infos = db.Column(db.Text, nullable=True)
    
    # Partie libre (médecin)
    hpi_complements_medecin = db.Column(db.Text, nullable=True)
    
    # Synthèse finale
    histoire_maladie = db.Column(db.Text, nullable=True)
    is_temporary = db.Column(db.Boolean, default=False)

    
    # ⭐ RELATIONS (UNE SEULE FOIS CHAQUE)
    consultation_precedente = db.relationship('Consultation', remote_side=[id])
    protocole_applique = db.relationship('ProtocoleSoins', foreign_keys=[protocole_applique_id], backref='consultations')
    ordonnance_active = db.relationship('Ordonnance', foreign_keys=[ordonnance_active_id])
    
    # ⭐ RELATION VERS ORDONNANCES (SANS backref vers Consultation)
    ordonnances = db.relationship(
        'Ordonnance',
        foreign_keys='Ordonnance.consultation_id',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    
    # ⭐ RELATION VERS EXAMENS PRESCRITS
    examens_prescrits = db.relationship(
        'ExamenPrescrit',
        foreign_keys='ExamenPrescrit.consultation_id',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

# ==================== PATIENT ====================
class Patient(db.Model):
    __tablename__ = 'patients'
    
    id = db.Column(db.Integer, primary_key=True)
    id_structure = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    id_medecin_referent = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))

    # ⭐ NOUVEAUX CHAMPS DE SYNCHRONISATION
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    source_structure_id = db.Column(db.Integer, nullable=True)  # ID dans GHP
    patient_source_id = db.Column(db.Integer, nullable=True)    # ID du patient dans GHP
    source_name = db.Column(db.String(50), nullable=True)       # 'ghp'
    synced_at = db.Column(db.DateTime, nullable=True)
    synced_from = db.Column(db.String(50), nullable=True)
    # ⭐ CHAMPS MANQUANTS (à ajouter)
    numero_assure = db.Column(db.String(50), nullable=True)
    assurance2_nom = db.Column(db.String(100), nullable=True)
    taux_prise_charge = db.Column(db.String(50))  # ou db.Float()
    taux_assurance2 = db.Column(db.Float, nullable=True)
    numero_assure2 = db.Column(db.String(50), nullable=True)
    personne_a_prevenir_nom = db.Column(db.String(100), nullable=True)
    personne_a_prevenir_telephone = db.Column(db.String(50), nullable=True)
    personne_a_prevenir_relation = db.Column(db.String(50), nullable=True)
    # ⭐ HABITUDES DE VIE
    tabac = db.Column(db.String(20))        # Non, Oui, Ancien
    alcool = db.Column(db.String(20))       # Non, Oui, Occasionnel
    allaitement = db.Column(db.Boolean, default=False)
    grossesse = db.Column(db.Boolean, default=False)

    # ⭐ INFORMATIONS MÉDICALES
    groupe_sanguin = db.Column(db.String(10))  # A+, A-, B+, B-, AB+, AB-, O+, O-
    mutuelle = db.Column(db.String(100))
    medecin_traitant = db.Column(db.String(100))

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

    # ⭐ NOUVEAUX CHAMPS POUR LA PRÉ-CONSULTATION
    motif_pre_consultation = db.Column(db.Text, nullable=True)
    pre_consultation_faite = db.Column(db.Boolean, default=False)
    pre_consultation_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    pre_consultation_date = db.Column(db.DateTime, nullable=True)
    
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
    medecin_referent = db.relationship('Utilisateur', foreign_keys=[id_medecin_referent], backref='patients_suivis')
    # Relation avec l'infirmier qui a fait la pré-consultation
    pre_consultation_infirmier = db.relationship('Utilisateur', foreign_keys=[pre_consultation_par])


class StructureMapping(db.Model):
    __tablename__ = 'structure_mappings'
    
    id = db.Column(db.Integer, primary_key=True)
    local_structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    source_structure_id = db.Column(db.Integer, nullable=False)  # ID dans GHP
    source_name = db.Column(db.String(50), default='ghp')
    api_url = db.Column(db.String(255), nullable=True)
    api_key = db.Column(db.String(255), nullable=True)
    last_sync = db.Column(db.DateTime, nullable=True)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='mappings_ghp')

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
    
    # ⭐ CHAMPS POUR LE LIT - CORRIGÉS (comme avant)
    lit = db.Column(db.String(20), nullable=True)  # Stocke le numéro du lit "A", "B", "101"
    lit_id = db.Column(db.Integer, db.ForeignKey('lits.id'), nullable=True)
    
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
    
    # ⭐ NOUVEAU : Lien vers la note active
    note_admission_active_id = db.Column(db.Integer, db.ForeignKey('notes_admission.id', ondelete='SET NULL'), nullable=True)
    
    # ⭐ RELATIONS EXISTANTES (sans la relation lit qui pose problème)
    patient = db.relationship('Patient', backref='hospitalisations')
    medecins = db.relationship('HospitalisationMedecin', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')
    infirmiers = db.relationship('HospitalisationInfirmier', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')
    evolutions = db.relationship('EvolutionPatient', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')
    constantes = db.relationship('ConstanteVitale', backref='hospitalisation', lazy='dynamic', cascade='all, delete-orphan')


    # Protocole de soins
    protocole_id = db.Column(db.Integer, db.ForeignKey('protocoles_soins.id'), nullable=True)
    
    # Ordonnance prescrite (stockée en JSON, copie de l'ordonnance_type)
    ordonnance_prescite = db.Column(db.Text, nullable=True)  # JSON avec les médicaments

    ordonnance_historique = db.Column(db.Text, nullable=True)  # Historique des ordonnances (JSON)
    ordonnance_version = db.Column(db.Integer, default=1)       
    
    # Relations
    protocole = db.relationship('ProtocoleSoins', foreign_keys=[protocole_id], backref='hospitalisations')
    
    # ⭐ RELATION AVEC NOTE ADMISSION
    notes_admission_list = db.relationship(
        'NoteAdmission',
        foreign_keys='NoteAdmission.hospitalisation_id',
        backref='hospitalisation_ref',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    
    # ⭐ RELATION AVEC LA NOTE ACTIVE
    note_admission_active = db.relationship(
        'NoteAdmission',
        foreign_keys=[note_admission_active_id],
        primaryjoin='Hospitalisation.note_admission_active_id == NoteAdmission.id',
        uselist=False,
        post_update=True
    )

    createur = db.relationship('Utilisateur', foreign_keys=[created_by], backref='hospitalisations_crees')


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
    
    # Constantes vitales de base
    temperature = db.Column(db.Float, nullable=True)
    pression_arterielle = db.Column(db.String(20), nullable=True)
    frequence_cardiaque = db.Column(db.Integer, nullable=True)
    frequence_respiratoire = db.Column(db.Integer, nullable=True)
    saturation_oxygene = db.Column(db.Float, nullable=True)
    glycemie = db.Column(db.Float, nullable=True)
    poids = db.Column(db.Float, nullable=True)
    taille = db.Column(db.Float, nullable=True)
    imc = db.Column(db.Float, nullable=True)
    
    # ⭐ NOUVEAUX CHAMPS
    diurese = db.Column(db.String(50), nullable=True)          # Ex: 1200 mL/24h
    emission_gaz = db.Column(db.String(50), nullable=True)    # Oui/Non, Normal
    selles = db.Column(db.String(50), nullable=True)          # Ex: Normale, Constipation, Diarrhée
    vomissements = db.Column(db.String(50), nullable=True)    # Oui/Non, Fréquence
    douleur = db.Column(db.Integer, nullable=True)             # Échelle 0-10
    conscience = db.Column(db.String(50), nullable=True)      # Alerte, Obnubilé, Coma
    pouls_peripherique = db.Column(db.String(50), nullable=True) # Présent, Absent
    temperature_cutanee = db.Column(db.String(50), nullable=True) # Normale, Froide, Chaude
    evolution_par_rapport = db.Column(db.String(20), nullable=True)  # amelioration, aggravation, stable

    
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
    evolution_par_rapport = db.Column(db.String(20), nullable=True)  # amelioration, aggravation, stable, fluctuant

    
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

class AnalyseDemande(db.Model):
    __tablename__ = 'analyses_demandes'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # ⭐ MODIFIER consultation_id pour qu'il soit nullable
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=True)
    
    # ⭐ AJOUTER hospitalisation_id
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=True)
    
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Type d'analyse
    type_analyse = db.Column(db.String(50), nullable=False)  # BIOLOGIE, IMAGERIE, AUTRE
    nom_analyse = db.Column(db.String(255), nullable=False)  # NFS, Glycémie, Radio...
    description = db.Column(db.Text, nullable=True)
    
    # Prescription
    prescrit_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    date_prescription = db.Column(db.DateTime, default=datetime.utcnow)
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Résultats
    resultats = db.Column(db.Text, nullable=True)
    date_resultats = db.Column(db.DateTime, nullable=True)
    resultats_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    
    # Statut
    statut = db.Column(db.String(20), default='EN_ATTENTE')
    
    # Fichiers joints
    fichiers = db.Column(db.Text, nullable=True)
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # ⭐ RELATIONS
    consultation = db.relationship('Consultation', backref='analyses_demandees')
    hospitalisation = db.relationship('Hospitalisation', backref='analyses_demandees')  # ⭐ AJOUTER
    patient = db.relationship('Patient', backref='analyses_demandees')
    structure = db.relationship('Structure', backref='analyses_demandees')
    prescripteur = db.relationship('Utilisateur', foreign_keys=[prescrit_par], backref='analyses_prescrites')
    responsable = db.relationship('Utilisateur', foreign_keys=[resultats_par], backref='analyses_resultats')

class Reference(db.Model):
    __tablename__ = 'references'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=True)  
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Informations de référence
    motif = db.Column(db.Text, nullable=False)
    diagnostic = db.Column(db.Text, nullable=True)
    centre_reference = db.Column(db.String(200), nullable=False)
    service_reference = db.Column(db.String(100), nullable=True)
    medecin_referent = db.Column(db.String(100), nullable=True)
    
    # Dernières constantes (copiées au moment de la référence)
    derniere_tension = db.Column(db.String(20), nullable=True)
    derniere_temperature = db.Column(db.Float, nullable=True)
    derniere_pulse = db.Column(db.Integer, nullable=True)
    derniere_saturation = db.Column(db.Integer, nullable=True)
    dernier_poids = db.Column(db.Float, nullable=True)
    derniere_taille = db.Column(db.Float, nullable=True)
    dernier_imc = db.Column(db.Float, nullable=True)
    
    # Résumé
    resume_clinique = db.Column(db.Text, nullable=True)
    examens_realises = db.Column(db.Text, nullable=True)
    traitements_en_cours = db.Column(db.Text, nullable=True)
    
    # Suivi
    statut = db.Column(db.String(20), default='ENVOYE')  # ENVOYE, ACCEPTE, REFUSE, EN_ATTENTE
    date_reference = db.Column(db.DateTime, default=datetime.utcnow)
    date_retour = db.Column(db.DateTime, nullable=True)
    retour_info = db.Column(db.Text, nullable=True)
    
    # Métadonnées
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    patient = db.relationship('Patient', backref='references')
    consultation = db.relationship('Consultation', backref='references')
    hospitalisation = db.relationship('Hospitalisation', backref='references')
    structure = db.relationship('Structure', backref='references')
    createur = db.relationship('Utilisateur', backref='references_crees')

class PermissionTemp(db.Model):
    __tablename__ = 'permissions_temp'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Permission accordée
    permission = db.Column(db.String(50), nullable=False)  # ANALYSES, REFERENCE, HOSPITALISATION, STATISTIQUES, etc.
    
    # Durée
    date_debut = db.Column(db.DateTime, default=datetime.utcnow)
    date_fin = db.Column(db.DateTime, nullable=False)
    
    # Motif
    motif = db.Column(db.String(255), nullable=True)
    
    # Statut
    actif = db.Column(db.Boolean, default=True)
    date_revocation = db.Column(db.DateTime, nullable=True)
    revoked_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    motif_revocation = db.Column(db.String(255), nullable=True)
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    user = db.relationship('Utilisateur', foreign_keys=[user_id], backref='permissions_temp')
    grantor = db.relationship('Utilisateur', foreign_keys=[granted_by], backref='permissions_temp_donnees')
    revoker = db.relationship('Utilisateur', foreign_keys=[revoked_by], backref='permissions_temp_revoquees')
    structure = db.relationship('Structure', backref='permissions_temp')


# ==================== GESTION DES SALLES ====================

class Service(db.Model):
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='services')
    salles = db.relationship('Salle', backref='service_associe', lazy='dynamic', cascade='all, delete-orphan', overlaps="salles_list")


class Salle(db.Model):
    __tablename__ = 'salles'

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    nom = db.Column(db.String(50), nullable=False)
    type_salle = db.Column(db.String(50), nullable=False)
    nombre_lits = db.Column(db.Integer, nullable=False, default=1)
    prix_journalier = db.Column(db.Float, nullable=True)
    description = db.Column(db.Text, nullable=True)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ⭐ FACTURATION HOSPITALISATION — mapping vers le catalogue d'actes GHP
    # de la structure. Le nom doit correspondre EXACTEMENT à un acte du
    # catalogue Sheets côté GHP (P160 Hospitalisation ... Premiere Semaine /
    # 8e jour au 14e jour / 15 jours et plus) pour que le prix/PBR soit
    # retrouvé à l'affichage dans "Prescriptions reçues". Configurable par
    # salle depuis l'écran Paramétrages (les tarifs dépendent de la salle).
    acte_ghp_semaine1 = db.Column(db.String(255), nullable=True)   # jours 1-7
    acte_ghp_semaine2 = db.Column(db.String(255), nullable=True)   # jours 8-14
    acte_ghp_semaine3 = db.Column(db.String(255), nullable=True)   # jour 15+
    
    # Relations - Utiliser des noms uniques
    service = db.relationship('Service', backref='salles_list', overlaps="salles")
    lits = db.relationship('Lit', backref='salle_associee', lazy='dynamic', cascade='all, delete-orphan', overlaps="lits_list")
    
    def lits_disponibles(self):
        return self.lits.filter_by(statut='disponible').count()
    
    def lits_occupes(self):
        return self.lits.filter_by(statut='occupe').count()


class Lit(db.Model):
    __tablename__ = 'lits'
    
    id = db.Column(db.Integer, primary_key=True)
    salle_id = db.Column(db.Integer, db.ForeignKey('salles.id'), nullable=False)
    numero = db.Column(db.String(10), nullable=False)
    statut = db.Column(db.String(20), default='disponible')
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations - Utiliser des noms uniques
    salle = db.relationship('Salle', backref='lits_list', overlaps="lits")
    hospitalisation = db.relationship('Hospitalisation', foreign_keys=[hospitalisation_id], backref='lit_occupe')
    
    def liberer(self):
        self.statut = 'disponible'
        self.hospitalisation_id = None
        self.updated_at = datetime.utcnow()
    
    def occuper(self, hospitalisation_id):
        self.statut = 'occupe'
        self.hospitalisation_id = hospitalisation_id
        self.updated_at = datetime.utcnow()


# ==================== FACTURATION HOSPITALISATION (AMU) ====================

class ParametrageAMU(db.Model):
    """Paramétrage AMU hospitalisation, par structure. Les paliers de jours
    (semaine 1 / semaine 2 / 15j et plus) déterminent comment les jours
    d'hospitalisation sont répartis vers les actes GHP correspondants
    (voir Salle.acte_ghp_semaine1/2/3). Le taux n'est utilisé que pour
    l'ESTIMATION affichée à la clôture — le calcul définitif est fait par
    GHP au moment de la vente, avec le taux réel du patient et le PBR du
    catalogue à cet instant (même moteur que pour toute vente normale)."""
    __tablename__ = 'parametrages_amu'

    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False, unique=True)

    seuil_jours_semaine1 = db.Column(db.Integer, nullable=False, default=7)   # fin du palier 1
    seuil_jours_semaine2 = db.Column(db.Integer, nullable=False, default=14)  # fin du palier 2
    taux_amu_info = db.Column(db.Float, nullable=False, default=90.0)         # informatif uniquement

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    structure = db.relationship('Structure', backref=db.backref('parametrage_amu', uselist=False))

    @classmethod
    def get_ou_defaut(cls, structure_id):
        """Retourne le paramétrage de la structure, ou un paramétrage par
        défaut (non persisté) si elle n'en a pas encore configuré."""
        p = cls.query.filter_by(structure_id=structure_id).first()
        if p:
            return p
        return cls(structure_id=structure_id, seuil_jours_semaine1=7, seuil_jours_semaine2=14, taux_amu_info=90.0)


class HospitalisationFacturation(db.Model):
    """Une ligne de facturation d'hospitalisation envoyée à GHP (une par
    palier réellement utilisé — jusqu'à 3 par hospitalisation clôturée).
    Miroir du même principe que Prescription/ActePose : synced_at permet au
    scheduler de rattraper un envoi qui aurait échoué (structure GHP
    injoignable au moment de la clôture)."""
    __tablename__ = 'hospitalisation_facturations'

    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)

    palier = db.Column(db.String(20), nullable=False)       # 'semaine1' | 'semaine2' | 'semaine3plus'
    acte_nom = db.Column(db.String(255), nullable=False)     # nom exact catalogue GHP envoyé
    nombre_jours = db.Column(db.Integer, nullable=False)
    prix_unitaire_estime = db.Column(db.Float, nullable=True)  # snapshot pour historique/affichage local

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    synced_at = db.Column(db.DateTime, nullable=True)

    hospitalisation = db.relationship('Hospitalisation', backref='facturations')
    patient = db.relationship('Patient')


# ==================== ANTÉCÉDENTS PATIENT ====================

class AntecedentPatient(db.Model):
    __tablename__ = 'antecedents_patient'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    
    # Type d'antécédent
    type_antecedent = db.Column(db.String(50), nullable=False)  # MEDICAL, CHIRURGICAL, PSYCHOLOGIQUE, OBSTETRIQUE, ALLERGIE, AUTRE
    type_precision = db.Column(db.String(100))  # Pour le type "AUTRE"
    
    # Description
    description = db.Column(db.Text, nullable=False)
    
    # Dates
    date_debut = db.Column(db.Date)
    date_fin = db.Column(db.Date)
    
    # Sévérité
    severite = db.Column(db.String(20))  # LEGERE, MODEREE, SEVERE
    
    # Traitement associé
    traitement = db.Column(db.String(255))
    
    # Notes
    notes = db.Column(db.Text)
    
    # Statut
    actif = db.Column(db.Boolean, default=True)
    
    # Qui a recueilli l'information
    recueilli_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    date_recueil = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Métadonnées
    modified_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    modified_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relations
    patient = db.relationship('Patient', backref='antecedents')
    recueillant = db.relationship('Utilisateur', foreign_keys=[recueilli_par], backref='antecedents_recueillis')
    modificateur = db.relationship('Utilisateur', foreign_keys=[modified_by], backref='antecedents_modifies')

# ==================== EXAMEN PHYSIQUE ====================

class ExamenPhysique(db.Model):
    __tablename__ = 'examens_physiques'
    
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id'), nullable=False)
    
    # Stockage des sections modifiées (JSON)
    sections_modifiees = db.Column(db.Text, nullable=True)
    
    # Texte complet de l'examen
    examen_complet = db.Column(db.Text, nullable=True)
    
    # Métadonnées
    version = db.Column(db.String(10), default='fr')
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    modified_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    
    # Relations
    consultation = db.relationship('Consultation', backref='examen_physique')
    createur = db.relationship('Utilisateur', backref='examens_physiques')


class SectionExamenPhysique(db.Model):
    __tablename__ = 'sections_examen_physique'
    
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    icone = db.Column(db.String(50), nullable=True)
    
    # Texte par langue
    texte_fr = db.Column(db.Text, nullable=False)
    texte_en = db.Column(db.Text, nullable=False)
    
    ordre = db.Column(db.Integer, default=0)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Engagement(db.Model):
    __tablename__ = 'engagements'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    medecin_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    # Type d'engagement
    type_engagement = db.Column(db.String(50), nullable=False)
    # 'DNR', 'REFUS_TRAITEMENT', 'SORTIE_AVIS', 'AUTRE'
    
    # Contenu généré
    contenu = db.Column(db.Text, nullable=False)
    
    # Champs spécifiques
    traitement_refuse = db.Column(db.Text, nullable=True)
    motif_refus = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    
    # Témoins
    temoin1_nom = db.Column(db.String(100), nullable=True)
    temoin1_signature = db.Column(db.String(100), nullable=True)
    temoin2_nom = db.Column(db.String(100), nullable=True)
    temoin2_signature = db.Column(db.String(100), nullable=True)
    
    # Représentant légal
    representant_nom = db.Column(db.String(100), nullable=True)
    representant_lien = db.Column(db.String(50), nullable=True)
    representant_signature = db.Column(db.String(100), nullable=True)
    
    # Signatures
    signe_par_patient = db.Column(db.Boolean, default=False)
    signe_par_medecin = db.Column(db.Boolean, default=False)
    date_signature_patient = db.Column(db.DateTime, nullable=True)
    date_signature_medecin = db.Column(db.DateTime, nullable=True)
    
    # Métadonnées
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_impression = db.Column(db.DateTime, nullable=True)
    numero_dossier = db.Column(db.String(50), nullable=True)
    
    # Relations
    patient = db.relationship('Patient', backref='engagements')
    medecin = db.relationship('Utilisateur', backref='engagements_crees')
    
    def __repr__(self):
        return f'<Engagement {self.id} - {self.type_engagement} - Patient {self.patient_id}>'
    
    def get_type_label(self):
        labels = {
            'DNR': 'Ordre de Non-Réanimation',
            'REFUS_TRAITEMENT': 'Refus de traitement',
            'SORTIE_AVIS': 'Sortie contre avis médical',
            'AUTRE': 'Autre engagement'
        }
        return labels.get(self.type_engagement, self.type_engagement)
    
    def get_type_badge_color(self):
        colors = {
            'DNR': 'danger',
            'REFUS_TRAITEMENT': 'warning',
            'SORTIE_AVIS': 'info',
            'AUTRE': 'secondary'
        }
        return colors.get(self.type_engagement, 'secondary')
    
    def to_dict(self):
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'medecin_id': self.medecin_id,
            'type_engagement': self.type_engagement,
            'type_label': self.get_type_label(),
            'contenu': self.contenu,
            'traitement_refuse': self.traitement_refuse,
            'motif_refus': self.motif_refus,
            'observations': self.observations,
            'temoin1_nom': self.temoin1_nom,
            'temoin2_nom': self.temoin2_nom,
            'representant_nom': self.representant_nom,
            'representant_lien': self.representant_lien,
            'signe_par_patient': self.signe_par_patient,
            'signe_par_medecin': self.signe_par_medecin,
            'date_creation': self.date_creation.strftime('%d/%m/%Y %H:%M'),
            'date_signature_patient': self.date_signature_patient.strftime('%d/%m/%Y %H:%M') if self.date_signature_patient else None,
            'date_signature_medecin': self.date_signature_medecin.strftime('%d/%m/%Y %H:%M') if self.date_signature_medecin else None,
            'numero_dossier': self.numero_dossier
        }

class NoteAdmission(db.Model):
    __tablename__ = 'notes_admission'
    
    id = db.Column(db.Integer, primary_key=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id', ondelete='CASCADE'), nullable=False)
    
    # Version
    version = db.Column(db.Integer, nullable=False, default=1)
    est_initial = db.Column(db.Boolean, nullable=False, default=False)
    est_verrouillee = db.Column(db.Boolean, nullable=False, default=False)
    
    # Contenu
    motif_admission = db.Column(db.Text, nullable=True)
    contexte_admission = db.Column(db.Text, nullable=True)
    examen_clinique_admission = db.Column(db.Text, nullable=True)
    diagnostic_admission = db.Column(db.Text, nullable=True)
    examens_admission = db.Column(db.Text, nullable=True)
    traitement_admission = db.Column(db.Text, nullable=True)
    evolution_prevue = db.Column(db.Text, nullable=True)
    conclusion_admission = db.Column(db.Text, nullable=True)
    constantes_admission = db.Column(db.Text, nullable=True)
    
    # Métadonnées
    redige_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id', ondelete='SET NULL'), nullable=False)
    date_redaction = db.Column(db.DateTime, default=datetime.utcnow)
    valide_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id', ondelete='SET NULL'), nullable=True)
    date_validation = db.Column(db.DateTime, nullable=True)
    
    # ⭐ RELATIONS UNIQUEMENT VERS UTILISATEUR
    redacteur = db.relationship(
        'Utilisateur',
        foreign_keys=[redige_par],
        backref=db.backref('notes_redigees', lazy='dynamic')
    )
    validateur = db.relationship(
        'Utilisateur',
        foreign_keys=[valide_par],
        backref=db.backref('notes_validees', lazy='dynamic')
    )
    
    # ⭐ PAS DE RELATION DIRECTE VERS HOSPITALISATION ICI
    # La relation est définie DANS Hospitalisation avec backref='hospitalisation_ref'
    
    # Contraintes
    __table_args__ = (
        db.UniqueConstraint('hospitalisation_id', 'version', name='uq_hospitalisation_version'),
        db.Index('idx_note_admission_hospitalisation', 'hospitalisation_id'),
        db.Index('idx_note_admission_active', 'est_verrouillee'),
    )

# ==================== PROTOCOLES DE SOINS ====================
class ProtocoleSoins(db.Model):
    __tablename__ = 'protocoles_soins'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)  # Étapes détaillées du protocole
    actif = db.Column(db.Boolean, default=True)
    
    # Associations optionnelles
    ordonnance_type_id = db.Column(db.Integer, db.ForeignKey('ordonnances_types.id'), nullable=True)
    examen_type_id = db.Column(db.Integer, db.ForeignKey('examens_types.id'), nullable=True)
    
    # Métadonnées
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='protocoles')
    createur = db.relationship('Utilisateur', foreign_keys=[created_by], backref='protocoles_crees')
    ordonnance_type = db.relationship('OrdonnanceType', foreign_keys=[ordonnance_type_id], backref='protocoles_associes')
    examen_type = db.relationship('ExamenType', foreign_keys=[examen_type_id], backref='protocoles_associes')
    
    def __repr__(self):
        return f'<ProtocoleSoins {self.nom}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'description': self.description,
            'actif': self.actif,
            'ordonnance_type_id': self.ordonnance_type_id,
            'examen_type_id': self.examen_type_id,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'createur': f"{self.createur.prenom} {self.createur.nom}" if self.createur else None
        }


# ==================== ORDONNANCES TYPES ====================
class OrdonnanceType(db.Model):
    __tablename__ = 'ordonnances_types'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    nom = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Stocké en JSON : [{"medicament": "Paracétamol", "dosage": "1g", "posologie": "3x/jour", "duree": "7 jours", "quantite": "2 boîtes"}]
    medicaments = db.Column(db.Text, nullable=False, default='[]')
    
    actif = db.Column(db.Boolean, default=True)
    
    # Métadonnées
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='ordonnances_types')
    createur = db.relationship('Utilisateur', foreign_keys=[created_by], backref='ordonnances_crees')
    
    def __repr__(self):
        return f'<OrdonnanceType {self.nom}>'
    
    def get_medicaments_list(self):
        """Retourne la liste des médicaments depuis le JSON"""
        import json
        try:
            return json.loads(self.medicaments) if self.medicaments else []
        except:
            return []
    
    def set_medicaments_list(self, medicaments_list):
        """Sauvegarde la liste des médicaments en JSON"""
        import json
        self.medicaments = json.dumps(medicaments_list, ensure_ascii=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'description': self.description,
            'medicaments': self.get_medicaments_list(),
            'actif': self.actif,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'createur': f"{self.createur.prenom} {self.createur.nom}" if self.createur else None
        }

# ==================== ORDONNANCES ====================
class Ordonnance(db.Model):
    __tablename__ = 'ordonnances'
    
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id', ondelete='CASCADE'), nullable=False)
    
    # Versionnement
    version = db.Column(db.Integer, nullable=False, default=1)
    est_active = db.Column(db.Boolean, default=True)
    
    # Contenu (JSON)
    medicaments = db.Column(db.Text, nullable=False, default='[]')
    
    # Provenance
    source_type = db.Column(db.String(30), nullable=True)
    source_id = db.Column(db.Integer, nullable=True)
    source_nom = db.Column(db.String(200), nullable=True)
    
    # Métadonnées
    redige_par = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    date_redaction = db.Column(db.DateTime, default=datetime.utcnow)
    motif_modification = db.Column(db.String(255), nullable=True)
    
    # ⭐ SUPPRIME cette ligne (c'est elle qui cause le conflit)
    # consultation = db.relationship('Consultation', foreign_keys=[consultation_id], backref='ordonnances')
    
    # ⭐ GARDE UNIQUEMENT
    redacteur = db.relationship('Utilisateur', foreign_keys=[redige_par], backref='ordonnances_redigees')


    def get_medicaments_list(self):
        """Retourne la liste des médicaments depuis le JSON"""
        import json
        try:
            return json.loads(self.medicaments) if self.medicaments else []
        except:
            return []



# ==================== EXAMENS TYPES ====================
class ExamenType(db.Model):
    __tablename__ = 'examens_types'
    
    id = db.Column(db.Integer, primary_key=True)
    structure_id = db.Column(db.Integer, db.ForeignKey('structures.id'), nullable=False)
    
    nom = db.Column(db.String(200), nullable=False)
    nature = db.Column(db.String(50), nullable=False)  # BIOLOGIE, IMAGERIE, AUTRE
    motif = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    
    # Stocké en JSON : ["NFS", "CRP", "Glycémie", ...]
    examens = db.Column(db.Text, nullable=False, default='[]')
    
    actif = db.Column(db.Boolean, default=True)
    
    # Métadonnées
    created_by = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    structure = db.relationship('Structure', backref='examens_types')
    createur = db.relationship('Utilisateur', foreign_keys=[created_by], backref='examens_types_crees')
    
    def __repr__(self):
        return f'<ExamenType {self.nom}>'
    
    def get_examens_list(self):
        """Retourne la liste des examens depuis le JSON"""
        import json
        try:
            return json.loads(self.examens) if self.examens else []
        except:
            return []
    
    def set_examens_list(self, examens_list):
        """Sauvegarde la liste des examens en JSON"""
        import json
        self.examens = json.dumps(examens_list, ensure_ascii=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'nature': self.nature,
            'motif': self.motif,
            'description': self.description,
            'examens': self.get_examens_list(),
            'actif': self.actif,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'createur': f"{self.createur.prenom} {self.createur.nom}" if self.createur else None
        }


# ==================== EXAMENS PRESCRITS (déjà existant, à adapter) ====================
class ExamenPrescrit(db.Model):
    __tablename__ = 'examens_prescrits'
    
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultations.id', ondelete='CASCADE'), nullable=True)
    hospitalisation_id = db.Column(db.Integer, db.ForeignKey('hospitalisations.id', ondelete='CASCADE'), nullable=True)
    
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    medecin_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    examen_type_id = db.Column(db.Integer, db.ForeignKey('examens_types.id'), nullable=True)
    
    # Versionnement
    version = db.Column(db.Integer, nullable=False, default=1)
    est_active = db.Column(db.Boolean, default=True)
    
    nature = db.Column(db.String(50), nullable=False)
    motif = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    examens = db.Column(db.Text, nullable=False, default='[]')
    
    # Provenance
    source_type = db.Column(db.String(30), nullable=True)  # 'template', 'protocole', 'manuel'
    source_id = db.Column(db.Integer, nullable=True)
    source_nom = db.Column(db.String(200), nullable=True)
    
    # Suivi
    statut = db.Column(db.String(20), default='EN_ATTENTE')
    resultats = db.Column(db.Text, nullable=True)
    laborantin_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    date_resultats = db.Column(db.DateTime, nullable=True)
    
    date_prescription = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ⭐ RELATIONS AVEC BACKREFS UNIQUES
    consultation = db.relationship(
        'Consultation',
        foreign_keys=[consultation_id],
        backref='examens_prescrits_consultation',  # ⭐ NOUVEAU NOM UNIQUE
        lazy='joined'
    )
    
    hospitalisation = db.relationship(
        'Hospitalisation',
        foreign_keys=[hospitalisation_id],
        backref='examens_prescrits_hospitalisation',  # ⭐ NOUVEAU NOM UNIQUE
        lazy='joined'
    )
    
    patient = db.relationship('Patient', foreign_keys=[patient_id], backref='examens_prescrits')
    medecin = db.relationship('Utilisateur', foreign_keys=[medecin_id], backref='examens_prescrits_medecin')
    laborantin = db.relationship('Utilisateur', foreign_keys=[laborantin_id], backref='examens_prescrits_laborantin')
    examen_type = db.relationship('ExamenType', foreign_keys=[examen_type_id], backref='examens_prescrits')
    
    def __repr__(self):
        return f'<ExamenPrescrit {self.id} - {self.nature}>'
    
    def get_examens_list(self):
        """Retourne la liste des examens depuis le JSON"""
        import json
        try:
            return json.loads(self.examens) if self.examens else []
        except:
            return []
    
    def set_examens_list(self, examens_list):
        """Sauvegarde la liste des examens en JSON"""
        import json
        self.examens = json.dumps(examens_list, ensure_ascii=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nature': self.nature,
            'motif': self.motif,
            'description': self.description,
            'examens': self.get_examens_list(),
            'statut': self.statut,
            'resultats': self.resultats,
            'date_prescription': self.date_prescription.strftime('%d/%m/%Y %H:%M') if self.date_prescription else None,
            'date_resultats': self.date_resultats.strftime('%d/%m/%Y %H:%M') if self.date_resultats else None
        }
