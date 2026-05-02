import gspread
from google.oauth2.service_account import Credentials
from models import Patient, Consultation, Prescription, Structure, Utilisateur, db
from datetime import datetime
import re

class GoogleSheetsSync:
    def __init__(self, spreadsheet_id, credentials_file='credentials.json'):
        self.spreadsheet_id = spreadsheet_id
        self.credentials_file = credentials_file
        self.client = None
        self.sheet = None
        
    def get_sheet_name(self, structure_id, data_type):
        return f"STRUCT_{structure_id}_{data_type}"
    
    def get_or_create_worksheet(self, structure_id, data_type):
        sheet_name = self.get_sheet_name(structure_id, data_type)
        try:
            worksheet = self.sheet.worksheet(sheet_name)
        except:
            worksheet = self.sheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
            print(f"  📝 Création feuille: {sheet_name}")
        return worksheet
    
    def authenticate(self):
        try:
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_file(
                self.credentials_file, scopes=scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            print("✅ Authentification Google Sheets réussie")
            return True
        except Exception as e:
            print(f"❌ Erreur authentification: {e}")
            return False
    
    def ensure_structure_sheets(self, structure_id):
        """Crée les feuilles avec leurs entêtes même vides"""
        # PATIENTS
        ws = self.get_or_create_worksheet(structure_id, "PATIENTS")
        headers_patients = ['id', 'nom', 'prenom', 'date_naissance', 'telephone', 
                           'email', 'adresse', 'type_assurance', 'statut_medical', 
                           'medecin_referent', 'archived']
        ws.clear()
        ws.update(range_name='A1', values=[headers_patients])
        
        # CONSULTATIONS
        ws = self.get_or_create_worksheet(structure_id, "CONSULTATIONS")
        headers_consult = ['id', 'id_patient', 'patient_nom', 'patient_prenom', 
                          'date_consultation', 'motif', 'diagnostic', 'tension', 'temperature']
        ws.clear()
        ws.update(range_name='A1', values=[headers_consult])
        
        # PRESCRIPTIONS
        ws = self.get_or_create_worksheet(structure_id, "PRESCRIPTIONS")
        headers_presc = ['id', 'id_patient', 'patient_nom', 'patient_prenom', 
                        'medicament', 'dosage', 'duree_jours', 'instructions', 'statut', 'date_prescription']
        ws.clear()
        ws.update(range_name='A1', values=[headers_presc])
        
        print(f"  ✅ Feuilles créées avec entêtes pour structure ID {structure_id}")
    
    def sync_prescriptions_by_structure(self, structure_id, structure_nom):
        """Synchronise les prescriptions d'une structure spécifique"""
        from models import Patient, Prescription
        
        headers = ['id', 'id_patient', 'patient_nom', 'patient_prenom', 'medicament', 
                   'dosage', 'duree_jours', 'instructions', 'statut', 'date_prescription']
        
        # Récupérer toutes les prescriptions des patients de cette structure
        prescriptions = db.session.query(Prescription).join(
            Patient, Prescription.id_patient == Patient.id
        ).filter(Patient.id_structure == structure_id).all()
        
        print(f"    💊 Prescriptions trouvées pour {structure_nom}: {len(prescriptions)}")
        
        worksheet = self.get_or_create_worksheet(structure_id, "PRESCRIPTIONS")
        
        rows = [headers]
        for prescription in prescriptions:
            patient = db.session.get(Patient, prescription.id_patient)
            rows.append([
                prescription.id,
                prescription.id_patient,
                patient.nom if patient else '',
                patient.prenom if patient else '',
                prescription.medicament or '',
                prescription.dosage or '',
                prescription.duree_jours or '',
                prescription.instructions or '',
                prescription.statut or '',
                str(prescription.date_prescription) if prescription.date_prescription else ''
            ])
        
        # Effacer et remplacer les données
        worksheet.clear()
        worksheet.update(range_name='A1', values=rows)
        print(f"    ✅ PRESCRIPTIONS: {len(prescriptions)} lignes exportées")
    
    def sync_all(self):
        if not self.sheet:
            if not self.authenticate():
                return False
        
        print(f"\n🔄 SYNCHRONISATION - {datetime.now()}")
        print("=" * 50)
        
        # Récupérer TOUTES les structures
        structures = Structure.query.all()
        
        for structure in structures:
            print(f"\n📁 Structure: {structure.nom} (ID: {structure.id}) - Statut: {structure.statut}")
            self.ensure_structure_sheets(structure.id)
            
            # Remplir les données si structure active
            if structure.statut == 'actif':
                # Patients
                patients = Patient.query.filter_by(id_structure=structure.id, archived=False).all()
                if patients:
                    ws = self.get_or_create_worksheet(structure.id, "PATIENTS")
                    headers = ['id', 'nom', 'prenom', 'date_naissance', 'telephone', 
                              'email', 'adresse', 'type_assurance', 'statut_medical', 
                              'medecin_referent', 'archived']
                    rows = [headers]
                    for p in patients:
                        rows.append([p.id, p.nom or '', p.prenom or '', 
                                   str(p.date_naissance) if p.date_naissance else '',
                                   p.telephone or '', p.email or '', p.adresse or '',
                                   p.type_assurance or '', p.statut_medical or '',
                                   p.id_medecin_referent or '', 'Oui' if p.archived else 'Non'])
                    ws.clear()
                    ws.update(range_name='A1', values=rows)
                    print(f"    📋 PATIENTS: {len(patients)} lignes")
                
                # Consultations
                consultations = db.session.query(Consultation).join(Patient).filter(Patient.id_structure == structure.id).all()
                if consultations:
                    ws = self.get_or_create_worksheet(structure.id, "CONSULTATIONS")
                    headers = ['id', 'id_patient', 'patient_nom', 'patient_prenom', 
                              'date_consultation', 'motif', 'diagnostic', 'tension', 'temperature']
                    rows = [headers]
                    for c in consultations:
                        patient = db.session.get(Patient, c.id_patient)
                        rows.append([c.id, c.id_patient, patient.nom if patient else '', patient.prenom if patient else '',
                                   str(c.date_consultation) if c.date_consultation else '',
                                   c.motif or '', c.diagnostic or '', c.tension_arterielle or '', c.temperature_c or ''])
                    ws.clear()
                    ws.update(range_name='A1', values=rows)
                    print(f"    🏥 CONSULTATIONS: {len(consultations)} lignes")
                
                # Prescriptions
                self.sync_prescriptions_by_structure(structure.id, structure.nom)
        
        # Feuille récapitulative des structures
        print(f"\n📋 Mise à jour de la feuille ALL_STRUCTURES...")
        ws = self.get_or_create_worksheet("ALL", "STRUCTURES")
        headers = ['id', 'nom_structure', 'responsable_nom', 'responsable_prenom', 
                  'email', 'telephone', 'adresse', 'statut', 'date_demande', 'date_activation']
        rows = [headers]
        
        for structure in structures:
            responsable = Utilisateur.query.filter_by(id_structure=structure.id, role='admin_structure').first()
            rows.append([
                structure.id,
                structure.nom,
                responsable.nom if responsable else '',
                responsable.prenom if responsable else '',
                structure.email,
                structure.telephone or '',
                structure.adresse or '',
                structure.statut,
                str(structure.date_demande) if structure.date_demande else '',
                str(structure.date_activation) if structure.date_activation else ''
            ])
        
        ws.clear()
        ws.update(range_name='A1', values=rows)
        print(f"  ✅ ALL_STRUCTURES: {len(structures)} structures")
        
        print("\n" + "=" * 50)
        print("✅ Synchronisation terminée")
        return True

if __name__ == "__main__":
    import sys, os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from app import app
    with app.app_context():
        SPREADSHEET_ID = "1nCUArOaWgXVFszjEhH1GqNJXGCV7cF754W87vXvQ-lQ"
        syncer = GoogleSheetsSync(SPREADSHEET_ID)
        syncer.sync_all()