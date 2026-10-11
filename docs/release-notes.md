# Freebox HA v1.0.0

Première version stable de l’intégration locale Home Assistant pour Freebox OS, avec profil Essentiel par défaut. Installation HACS personnalisée ou manuelle ; configuration graphique en français et en anglais.

- Appairage natif LCD, identifiant d’application court, session challenge/HMAC et HTTPS avec validation de certificat.
- Découverte dynamique de la version API et des capacités ; 18 familles de collecte configurables, erreurs et permissions isolées.
- Inventaire persistant, regroupement automatique par nom avec alias MAC, un seul suivi de présence actif par appareil.
- Compatibilité des collections LAN/Wi-Fi vides ; conservation des métadonnées d’appareil après déconnexion ou perte d’API.
- Monitoring de base actif ; familles supplémentaires, capteurs détaillés et entités event optionnels.
- Migration des installations existantes, retrait des doublons de cette intégration et conservation des activations individuelles.
- WAN, fibre, matériel, LAN, DHCP, Wi-Fi, switch, services et catégories complémentaires disponibles selon le firmware.
- Présence Wi-Fi fondée sur les associations radio, priorité sur le statut LAN retardé, délai Wi-Fi configurable de 10 secondes et indices radio/activité sur le tracker.
- 14 événements d’automatisation, anti-rebond, seuils et hystérésis ; reprise silencieuse après perte d’API.
- Polling asynchrone par famille, limites de concurrence et backoff ; abonnement WebSocket LAN avec repli sur polling.
- Diagnostics anonymisés, documentation des unités et huit exemples d’automatisations.

Validation matérielle : appairage accepté sur une Ultra V9 / API 16.0, session HMAC ouverte, 45 endpoints lus, 71 identités réseau et abonnement WebSocket accepté. Sept erreurs d’endpoints ont été isolées. L’installation et les événements dans l’instance HA OS de l’utilisateur restent à vérifier. Aucun support MLO ou métrique non exposée n’est simulé.

Installation : ajouter https://github.com/FOEDI/FreeboxHA comme dépôt personnalisé HACS de catégorie Intégration, télécharger Freebox HA et redémarrer HA. Ajouter l’intégration avec l’adresse locale et le port HTTPS 443, puis accepter sur l’écran de la Freebox. En manuel, copier custom_components/freebox_ultra_ultimate de l’archive dans /config/custom_components et redémarrer.

Voir README.md pour les entités, options et limites ; docs/validation.md pour les contrôles réellement exécutés.
