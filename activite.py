"""⭐ Dernière activité d'un utilisateur (2026-10-12 : heures de calcul Neon).

Neon facture les heures pendant lesquelles la base est allumée ; elle s'endort
après 5 minutes sans requête. Les synchronisations automatiques (toutes les 3
et 5 minutes) l'interrogeaient jour et nuit, même clinique fermée : la base ne
dormait jamais (≈ 24 h/24 facturées), et chaque passage réveillait aussi la
base de GHP. Elles ne tournent désormais que si quelqu'un a utilisé
l'application récemment — sinon, il n'y a rien de nouveau à synchroniser.

Partagé entre les processus du serveur (plusieurs workers, chacun avec son
planificateur) par la date de modification d'un petit fichier temporaire ;
écrit au plus une fois par minute.
"""
import os
import tempfile
import time

FICHIER = os.path.join(tempfile.gettempdir(), 'medilogic_activite_' +
                       os.path.basename(os.path.dirname(os.path.abspath(__file__))))
DELAI_ACTIVITE_MINUTES = 15
_derniere_ecriture = [0.0]


def noter_activite():
    maintenant = time.time()
    if maintenant - _derniere_ecriture[0] < 60:
        return
    _derniere_ecriture[0] = maintenant
    try:
        with open(FICHIER, 'a'):
            pass
        os.utime(FICHIER, (maintenant, maintenant))
    except OSError:
        pass


def activite_recente(minutes=DELAI_ACTIVITE_MINUTES):
    try:
        return time.time() - os.path.getmtime(FICHIER) < minutes * 60
    except OSError:
        return False
