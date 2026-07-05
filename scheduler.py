# scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import os

logger = logging.getLogger(__name__)
scheduler = None

def scheduled_sync_ghp():
    """Synchronisation automatique des patients depuis GHP"""
    from app import app
    from models import db, StructureMapping
    
    # ⭐ Vérifier si on est en production (Render)
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

def start_scheduler():
    """Démarre le planificateur de tâches"""
    global scheduler
    
    # ⭐ Ne pas démarrer le scheduler en production si inutile
    env = os.getenv('FLASK_ENV', 'development')
    if env == 'production':
        logger.info("🔄 Mode production - Scheduler démarré")
    
    if scheduler is None:
        scheduler = BackgroundScheduler()
        
        # Synchronisation GHP toutes les 3 minutes
        scheduler.add_job(
            func=scheduled_sync_ghp,
            trigger=IntervalTrigger(minutes=3),
            id='ghp_sync',
            replace_existing=True
        )
        logger.info("🔄 GHP: Synchronisation automatique toutes les 3 minutes")
        
        scheduler.start()
        logger.info("✅ Scheduler GHP démarré")

def stop_scheduler():
    """Arrête le planificateur"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        logger.info("⏹️ Scheduler GHP arrêté")