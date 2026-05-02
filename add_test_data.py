from app import app, db
from models import Structure, Utilisateur, Patient, Consultation, Prescription
from datetime import datetime, timedelta
import random

with app.app_context():
    # 1. Créer une structure de test si elle n'existe pas
    structure = Structure.query.filter_by(email='test@cabinet.tg').first()
    if not structure:
        structure = Structure(
            nom='Cabinet Médical Test',
            email='test@cabinet.tg',
            telephone='+228 90000000',
            adresse='Lomé, Togo',
            statut='actif',
            date_activation=datetime.utcnow()
        )
        db.session.add(structure)
        db.session.commit()
        print(f"✅ Structure créée: {structure.nom} (ID: {structure.id})")
    
    # 2. Créer un médecin
    medecin = Utilisateur.query.filter_by(email='dr.test@cabinet.tg').first()
    if not medecin:
        medecin = Utilisateur(
            email='dr.test@cabinet.tg',
            nom='Dupont',
            prenom='Jean',
            role='medecin',
            id_structure=structure.id,
            actif=True
        )
        medecin.set_password('Medecin@2024')
        db.session.add(medecin)
        db.session.commit()
        print(f"✅ Médecin créé: {medecin.nom} {medecin.prenom}")
    
    # 3. Créer des patients de test
    assurances = ['AMU-CNSS', 'AMU-INAM', 'AUTRE_ASSURANCE', 'NON_ASSURÉ']
    statuts = ['PREMIERE_VISITE', 'EN_TRAITEMENT', 'GUERI']
    noms = ['Koffi', 'Diallo', 'Martin', 'Lawson', 'Gbadamassi', 'Tchakpede']
    prenoms = ['Jean', 'Marie', 'Amadou', 'Sophie', 'Kossi', 'Afi']
    
    for i in range(10):
        patient = Patient(
            id_structure=structure.id,
            id_medecin_referent=medecin.id,
            nom=random.choice(noms),
            prenom=random.choice(prenoms),
            date_naissance=datetime(1975 + random.randint(0, 30), random.randint(1, 12), random.randint(1, 28)),
            telephone=f'+228 {random.randint(90000000, 99999999)}',
            email=f'patient{i}@example.com',
            type_assurance=random.choice(assurances),
            statut_medical=random.choice(statuts),
            date_premiere_visite=datetime.utcnow() - timedelta(days=random.randint(1, 365)),
            archived=False
        )
        db.session.add(patient)
    print(f"✅ 10 patients créés")
    
    # 4. Créer des consultations
    patients = Patient.query.filter_by(id_structure=structure.id).all()
    for patient in patients[:5]:
        consultation = Consultation(
            id_patient=patient.id,
            id_medecin=medecin.id,
            date_consultation=datetime.utcnow() - timedelta(days=random.randint(1, 30)),
            motif='Consultation de routine',
            diagnostic='Patient en bonne santé',
            tension_arterielle=f"{random.randint(110, 140)}/{random.randint(70, 90)}",
            temperature_c=36.5 + random.random(),
            poids_kg=70 + random.randint(-15, 15),
            statut='termine'
        )
        db.session.add(consultation)
    print(f"✅ 5 consultations créées")
    
    # 5. Créer des prescriptions
    for patient in patients[:3]:
        prescription = Prescription(
            id_patient=patient.id,
            id_medecin=medecin.id,
            medicament=random.choice(['Paracétamol', 'Amoxicilline', 'Vitamine C', 'Ibuprofène']),
            dosage='500mg',
            duree_jours=5,
            instructions='Prendre matin et soir',
            renouvelable=False,
            statut='active'
        )
        db.session.add(prescription)
    print(f"✅ 3 prescriptions créées")
    
    db.session.commit()
    
    print("\n" + "="*50)
    print("📊 RÉCAPITULATIF:")
    print(f"Structure : {structure.nom}")
    print(f"Médecin : {medecin.nom} {medecin.prenom}")
    print(f"Patients : {Patient.query.filter_by(id_structure=structure.id).count()}")
    print(f"Consultations : {Consultation.query.count()}")
    print(f"Prescriptions : {Prescription.query.count()}")
    print("="*50)