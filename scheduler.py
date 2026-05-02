from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import logging

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Variable pour stocker le scheduler
scheduler = None

def scheduled_sync_to_sheets():
    """Fonction exécutée automatiquement toutes les 24h"""
    from app import app
    from sheets_sync import GoogleSheetsSync
    
    with app.app_context():
        try:
            logger.info(f"🔄 Début synchronisation Sheets - {datetime.now()}")
            SPREADSHEET_ID = "1nCUArOaWgXVFszjEhH1GqNJXGCV7cF754W87vXvQ-lQ"
            syncer = GoogleSheetsSync(SPREADSHEET_ID)
            syncer.sync_all()
            logger.info(f"✅ Synchronisation Sheets terminée - {datetime.now()}")
        except Exception as e:
            logger.error(f"❌ Erreur synchronisation Sheets: {e}")

def start_scheduler():
    """Démarre le planificateur de tâches"""
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler()
        # Planifier toutes les 24 heures (86400 secondes)
        scheduler.add_job(
            func=scheduled_sync_to_sheets,
            trigger=IntervalTrigger(seconds=86400),  # 24h
            id='daily_sheets_sync',
            name='Synchronisation Google Sheets',
            replace_existing=True
        )
        scheduler.start()
        logger.info("✅ Scheduler démarré - Synchronisation toutes les 24h")
        
        # Option: exécuter une première synchronisation au démarrage
        # scheduled_sync_to_sheets()

def stop_scheduler():
    """Arrête le planificateur"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        logger.info("⏹️ Scheduler arrêté")