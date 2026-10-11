# Recherche API et choix de compatibilité

Recherche réalisée le 11 octobre 2026. Les pages publiques Freebox décrivent principalement les API v2/v4 : ces versions ne sont jamais codées en dur dans le client. La version majeure et la racine proviennent de /api_version, recontrôlé en HTTPS. Les schémas réels sont inventoriés à chaque succès.

## Sources primaires

- [Index Freebox OS et autorités TLS officielles](https://dev.freebox.fr/sdk/os/)
- [Authentification, HMAC et permissions](https://dev.freebox.fr/sdk/os/login/)
- [LAN et navigateur réseau](https://dev.freebox.fr/sdk/os/lan/)
- [Wi-Fi, stations et radar](https://dev.freebox.fr/sdk/os/wifi/)
- [Switch, tables MAC et compteurs](https://dev.freebox.fr/sdk/os/switch/)
- [WAN, FTTH et IPv6](https://dev.freebox.fr/sdk/os/connection/)
- [Système](https://dev.freebox.fr/sdk/os/system/)
- [DHCP](https://dev.freebox.fr/sdk/os/dhcp/)
- [NAT, DMZ et redirections](https://dev.freebox.fr/sdk/os/nat/)
- [Stockage](https://dev.freebox.fr/sdk/os/storage/)
- [VPN serveur](https://dev.freebox.fr/sdk/os/vpn/), [client](https://dev.freebox.fr/sdk/os/vpn_client/)
- [Téléchargements et statistiques](https://dev.freebox.fr/sdk/os/download/)
- [Contrôle parental](https://dev.freebox.fr/sdk/os/parental/)
- [Freeplug](https://dev.freebox.fr/sdk/os/freeplug/)
- [Bibliothèque Python asynchrone hacf-fr/freebox-api](https://github.com/hacf-fr/freebox-api) : revue des endpoints complémentaires (partages, UPnP AV/IGD, AirMedia, journaux de connexion). Son code GPL n’est pas incorporé ; le client est une implémentation indépendante des contrats publics. Les certificats proviennent de la documentation officielle Freebox.
- [Discussion Free sur le protocole WebSocket LAN](https://dev.freebox.fr/bugs/task/29900) et [implémentation publique par l’auteur de freeboxos-bash-api](https://github.com/freeboxos/freeboxos-bash-api). Le protocole ws/event et register est une extension publique dépendante du firmware. L’acceptation de l’abonnement est contrôlée ; un simple handshake ne vaut pas preuve de support.
- [Conventions Home Assistant](https://developers.home-assistant.io/), [config flows](https://developers.home-assistant.io/docs/core/integration/config_flow/), [mise à jour des données](https://developers.home-assistant.io/docs/integration_fetching_data/), [diagnostics](https://developers.home-assistant.io/docs/core/integration_diagnostics/).
- [Sources HA 2026.10.1](https://github.com/home-assistant/core/tree/2026.10.1) : validation réelle du suivi réseau BaseScannerEntity et des relations via_device_id introduites dans les versions récentes.

## Règles d’unités

WAN rate_down/up : octets/s ; bandwidth_down/up : bits/s. Convertis en Mbit/s décimaux. Compteurs bytes : octets, total_increasing.

Stations Wi-Fi rx_rate/tx_rate : octets/s ; rx/tx_bytes : octets ; last_rx/last_tx.bitrate : dixièmes de Mbit/s, -1 inconnu. Direction depuis le point de vue Freebox. Le champ signal est documenté comme une atténuation en dB : il n’est pas renommé RSSI dBm. noise_level est aussi documenté en dB ; aucun SNR n’est calculé sans preuve d’unités et de références compatibles.

Switch speed : Mbit/s (aucun plafond 1 Gbit/s). rx/tx_bytes_rate : octets/s, compteurs rx_good_bytes/tx_bytes en octets. Les compteurs de paquets/erreurs utilisent packets/events ; leurs unités ne deviennent pas du trafic Internet.

FTTH sfp_pwr_rx/tx : entiers documentés en centièmes de dBm, division par 100. Une option explicite permet un firmware vérifié retournant des dBm directs ; aucune heuristique sur la grandeur de la valeur. Absence de power report/module : aucune valeur de puissance exploitable.

Températures système temp_* et disques temp : °C. fans : rpm seulement pour le groupe fans ou type explicite. Les variantes sensors de type temp/temperature sont prises en charge, les autres valeurs restent sans unité vérifiée et désactivées par défaut.

## Limites connues

Aucune preuve de support universel des répéteurs, du MLO détaillé, du bruit de chaque station, des CPU/mémoire, des flux réseau actifs ou des journaux système généraux. Aucune route devinée pour ces fonctionnalités. Les points d’accès renvoyés par wifi/ap/ sont tous parcourus ; les booléens/références opérationnelles et les champs numériques nouveaux peuvent être exposés sans inventer d’unité.

Le GET radar lit le cache déjà disponible. Le POST neighbors/scan interromprait la radio et n’est jamais appelé. Les endpoints RRD historiques, appels/contacts, fichiers, certificats VPN, VM, caméras et contrôle domotique Freebox sont écartés de cette version pour conserver un périmètre réseau en lecture seule et ne pas collecter de contenu personnel. L’historique local d’automatisation complète le polling sans prétendre remplacer les logs natifs absents.

## Certificats legacy et Python 3.13+

La découverte réelle d’une Ultra V9 / API 16.0 sur HTTPS local a échoué avec Missing Authority Key Identifier, puis réussi avec le contexte dédié retirant VERIFY_X509_STRICT. [Python documente ce changement depuis 3.13](https://docs.python.org/3.14/library/ssl.html#ssl.create_default_context). La vérification de chaîne/signature/validité et de nom reste obligatoire. Cinq tests TLS de boucle locale reproduisent une chaîne sans AKI et vérifient le rejet des mauvais noms, autorités inconnues, certificats expirés et signatures invalides. La vérification matérielle inclut les deux GET /api_version, un appairage LCD accepté, une session challenge/HMAC, 45 endpoints lisibles et un abonnement WebSocket accepté. Les jetons de cette validation ont été conservés uniquement en mémoire.
