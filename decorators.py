from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user
from datetime import datetime
from models import PermissionTemp

def has_permission(permission):
    """Vérifie si l'utilisateur a une permission (permanente ou temporaire)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Vérifier le rôle de base
            role_permissions = {
                'admin_structure': ['ANALYSES', 'REFERENCE', 'HOSPITALISATION', 'STATISTIQUES', 'PATIENTS'],
                'medecin': ['PATIENTS', 'REFERENCE', 'HOSPITALISATION', 'STATISTIQUES'],
                'infirmier': ['PATIENTS', 'HOSPITALISATION'],
                'laborantin': ['ANALYSES'],
                'secretaire': ['PATIENTS']
            }
            
            base_permissions = role_permissions.get(current_user.role, [])
            
            if permission in base_permissions:
                return f(*args, **kwargs)
            
            # Vérifier les permissions temporaires
            temp_perm = PermissionTemp.query.filter(
                PermissionTemp.user_id == current_user.id,
                PermissionTemp.permission == permission,
                PermissionTemp.actif == True,
                PermissionTemp.date_fin > datetime.utcnow()
            ).first()
            
            if temp_perm:
                return f(*args, **kwargs)
            
            # Super Admin a tout
            if current_user.role == 'super_admin':
                return f(*args, **kwargs)
            
            flash('Accès non autorisé - Vous n\'avez pas la permission nécessaire', 'danger')
            return redirect(url_for('dashboard'))
        return decorated_function
    return decorator