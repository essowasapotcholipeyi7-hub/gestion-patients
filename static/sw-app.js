// static/sw-app.js
// ============================================================
// Service worker de MediLogicConsult — condition technique pour que
// Chrome/Edge proposent l'installation (bouton "Installer") et que
// Android/PC créent une icône d'appli. Voir base.html pour
// l'enregistrement (navigator.serviceWorker.register), uniquement pour
// les pages où une session existe.
//
// ⭐ Les données ici sont des dossiers patients, des ordonnances, des
// résultats — jamais de valeur périmée affichée depuis un cache. Seuls
// le manifest et les icônes (immuables) sont mis en cache ; tout le
// reste passe TOUJOURS par le réseau d'abord, le cache ne sert qu'en
// dernier recours hors-ligne.
// ============================================================

const CACHE_NAME = 'medilogicconsult-app-v1';
const ASSETS_STATIQUES = [
    '/app-manifest.json',
    '/static/images/app-icon-192.png',
    '/static/images/app-icon-512.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS_STATIQUES))
            .catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cles) => Promise.all(
            cles.filter((cle) => cle !== CACHE_NAME).map((cle) => caches.delete(cle))
        ))
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const estAssetStatique = ASSETS_STATIQUES.some((url) => request.url.endsWith(url));
    if (estAssetStatique) {
        // Rapide, change rarement : cache d'abord, réseau en secours.
        event.respondWith(
            caches.match(request).then((reponse) => reponse || fetch(request))
        );
        return;
    }

    // Tout le reste (pages, API) : réseau d'abord — la version qui vient
    // d'être déployée est donc visible dès le prochain chargement de page,
    // sans étape supplémentaire. Cache uniquement si hors-ligne.
    event.respondWith(
        fetch(request)
            .then((reponse) => {
                if (reponse && reponse.ok) {
                    const copie = reponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, copie)).catch(() => {});
                }
                return reponse;
            })
            .catch(() => caches.match(request))
    );
});
