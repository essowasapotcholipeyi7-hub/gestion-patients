from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import logging
import os

logger = logging.getLogger(__name__)

# ⭐ Une seule instance du scheduler
scheduler = None

def scheduled_sync_ghp():
    """Synchronisation automatique des patients depuis GHP"""
    from app import app
    from models import db, StructureMapping
    
    env = os.getenv('FLASK_ENV', 'development')
    
    with app.app_context():
        try:
            mappings = StructureMapping.query.filter_by(actif=True).all()
            
            if not mappings:
                return
            
            logger.info(f"🔄 Sync GHP - {len(mappings)} structure(s) - Env: {env}")
            
            for mapping in mappings:
                try:
                    from app import sync_patients_from_ghp
                    resultat = sync_patients_from_ghp(mapping)
                    
                    if resultat.get('cree', 0) > 0:
                        logger.info(f"✅ {resultat['cree']} nouveaux patients depuis GHP")
                    elif resultat.get('mis_a_jour', 0) > 0:
                        logger.info(f"📝 {resultat['mis_a_jour']} patients mis à jour")
                    
                except Exception as e:
                    logger.error(f"❌ Erreur sync GHP: {e}")
            
        except Exception as e:
            logger.error(f"❌ Erreur synchronisation GHP: {e}")


def scheduled_sync_prescriptions():
    """
    Synchronisation automatique des prescriptions toutes les 5 minutes
    (rattrapage si l'envoi automatique a échoué)
    """
    try:
        from tasks import sync_prescriptions_to_ghp
        result = sync_prescriptions_to_ghp()
        if result.get('success'):
            logger.info(f"🔄 Sync prescriptions: {result.get('message')}")
    except Exception as e:
        logger.error(f"❌ Erreur sync prescriptions: {e}")


def start_scheduler():
    """Démarre le planificateur de tâches"""
    global scheduler
    
    env = os.getenv('FLASK_ENV', 'development')
    
    if scheduler is None:
        scheduler = BackgroundScheduler()
        
        # ---- 1. SYNCHRONISATION GHP (toutes les 3 minutes) ----
        scheduler.add_job(
            func=scheduled_sync_ghp,
            trigger=IntervalTrigger(minutes=3),
            id='ghp_sync',
            replace_existing=True
        )
        logger.info("🔄 GHP: Synchronisation automatique toutes les 3 minutes")
        
        # ---- 2. SYNCHRONISATION GHP (sécurité horaire) ----
        scheduler.add_job(
            func=scheduled_sync_ghp,
            trigger=CronTrigger(minute=0),
            id='ghp_sync_hourly',
            replace_existing=True
        )
        logger.info("🔄 GHP: Synchronisation horaire (sécurité)")
        
        # ---- 3. SYNCHRONISATION PRESCRIPTIONS (toutes les 5 minutes) ----
        scheduler.add_job(
            func=scheduled_sync_prescriptions,
            trigger=IntervalTrigger(minutes=5),
            id='sync_prescriptions',
            replace_existing=True
        )
        logger.info("🔄 Prescriptions: Synchronisation toutes les 5 minutes")
        
        # ---- DÉMARRAGE ----
        scheduler.start()
        logger.info(f"✅ Scheduler démarré - Mode: {env}")
        
    else:
        logger.info("ℹ️ Scheduler déjà en cours d'exécution")


def stop_scheduler():
    """Arrête le planificateur"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        scheduler = None
        logger.info("⏹️ Scheduler arrêté")