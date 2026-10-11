# Freebox HA — Freebox Ultra Ultimate

Intégration personnalisée Home Assistant locale pour Freebox OS, domaine **freebox_ultra_ultimate**. Version 1.0.0. Configuration intégralement graphique, installation HACS ou manuelle. Supervision en lecture seule : aucune modification de réseau, aucun redémarrage de box, aucun scan Wi-Fi actif.

**Compatibilité validée en tests : Home Assistant 2026.10.1 et Python 3.14 sous Linux. Minimum déclaré : HA 2026.10.0.** Les tests utilisent des contrats API anonymisés et de vraies plateformes HA. Un appairage LCD réel, une session challenge/HMAC et les collecteurs ont aussi été validés sur une Ultra V9 avec API 16.0 : 45 endpoints lisibles et 71 appareils identifiés. Le retéléchargement HACS et l’état absent d’un téléphone hors Wi-Fi ont été vérifiés dans HA OS ; les scénarios prolongés restent à valider. Les capteurs sont créés d’après les champs présents, sans simuler les fonctionnalités absentes.

## Profil Essentiel et téléphones

Le profil par défaut privilégie les automatisations et le monitoring de base : **un seul device_tracker actif par appareil**, état et débits Internet, lien et puissance RX fibre, températures et uptime, lien/vitesse/trafic Ethernet, radios actives et nombre de clients. Les 14 événements restent publiés sur le bus HA ; leurs entités event sont optionnelles.

**Les appareils portant le même nom sont regroupés par défaut**, conformément au choix de cette intégration. Les trois identités d’un téléphone peuvent ainsi partager un appareil HA et un seul suivi de présence. La comparaison ignore la casse et les espaces répétés. Les appareils sans nom restent séparés. Le tracker conservé est celui de l’identité la plus ancienne de l’inventaire ; ses alias MAC sont persistés, donc un changement de bande ou de MAC déjà connue ne recrée pas de tracker. Avec cette option, deux équipements distincts portant le même nom seraient aussi regroupés : garde des noms distincts ou désactive le regroupement.

Pour les clients déjà observés en Wi-Fi, la présence repose sur les **stations associées aux radios**, et non sur les champs LAN `active/reachable`, qui peuvent rester vrais après le départ. Le groupe reste présent tant qu’au moins une de ses identités figure dans une liste Wi-Fi valide. Son absence est confirmée par deux collectes complètes de toutes les radios, avec un délai Wi-Fi de **10 secondes** par défaut. À un polling de 10 secondes, cela prend généralement 10 à 20 secondes **après que la Freebox retire la station de sa liste** ; l’intégration ne peut pas rendre son API plus rapide. Le statut LAN reste le repli pour les équipements jamais observés en Wi-Fi ou lorsque la collecte Wi-Fi est désactivée. Les attributs du tracker donnent **connection_type, wifi_band, wifi_bands, access_point, access_points** et, si l’exposition d’identité est autorisée, **ssid/ssids**. Les listes couvrent les associations multiples ; un champ singulier reste vide quand plusieurs valeurs sont présentes. Les informations Wi-Fi disparaissent lorsqu’aucune association exploitable n’est observée. L’absence de réponse API reste une indisponibilité, pas une preuve de départ.

Pour une automatisation, utilise l’état du **device_tracker** : `home` = connecté, `not_home` = absence confirmée, `unavailable` = collecte insuffisante. Le capteur binaire « Connected », optionnel, partage cette décision. Les attributs `connection_evidence` (`wifi_association`, `wifi_absence`, `lan_status`, `api_unavailable`), `presence_observed_at`, `connected_observed` et `presence_pending` expliquent la dernière observation et sa confirmation. Avec une association Wi-Fi valide, `wifi_signal`/`wifi_signal_unit`, `wifi_inactive_seconds` et `wifi_traffic_active` fournissent les données radio/activité disponibles. Pour un groupe multiradio, le signal le plus fort et l’inactivité minimale sont retenus. Signal et trafic sont des indices complémentaires : un signal ancien, un bail DHCP ou une IP ne prouvent pas une connexion ; zéro trafic ou une longue inactivité ne prouvent pas un départ. Ces attributs ne provoquent aucun scan ni ping actif.

Les collections réseau vides renvoyées avec succès sous forme `[]`, `{}` ou `null` sont acceptées pour les listes d’hôtes LAN et de stations Wi-Fi. Sur API 16.0, un succès sans champ `result` est aussi accepté comme collection vide uniquement pour ces deux types de listes, comportement identifié sur la box de l’utilisateur. Les autres endpoints sans `result`, les erreurs et les objets non vides de forme inattendue restent rejetés. Les informations mémorisées (nom, MAC, IP connue, première/dernière détection) restent disponibles après départ et panne API, avec `data_source: inventory` et, pour les informations de connexion, `last_known: true` lorsque l’équipement n’est pas présent. Les valeurs radio sans mesure courante peuvent devenir indisponibles.

Les autres capteurs disponibles des familles essentielles sont enregistrés **désactivés par défaut**. Ils peuvent être activés individuellement dans la liste des entités de l’appareil. Les statistiques techniques Wi-Fi nécessitent **Familles et détails → Statistiques détaillées par client** ; les métriques techniques globales et entités event utilisent **Activer les métriques techniques et de diagnostic**. DHCP, stockage, services, routage, VPN et autres catégories sont optionnels et ne sont pas collectés tant qu’ils ne sont pas sélectionnés. Leur sélection active leurs métriques opérationnelles reconnues ; les champs numériques non vérifiés restent désactivés.

Une installation antérieure adopte ce profil et regroupe son inventaire au chargement, sans nouvel appairage. Les entités secondaires des identités fusionnées sont retirées uniquement de cette intégration ; les autres intégrations sont préservées. Adapte les automatisations qui utilisaient un tracker secondaire au tracker conservé. **Configurer → Appliquer le profil Essentiel** permet de réappliquer ces valeurs ; les entités désactivées manuellement restent désactivées. Une activation individuelle ordinaire est conservée au rechargement.

## Installation via HACS

1. Ouvre HACS → menu → **Dépôts personnalisés**.
2. Ajoute **https://github.com/FOEDI/FreeboxHA**, catégorie **Intégration**.
3. Télécharge **Freebox HA**, puis redémarre Home Assistant.
4. Paramètres → Appareils et services → Ajouter une intégration → **Freebox HA**. Une découverte mDNS peut aussi proposer la box automatiquement.
5. Indique l’adresse locale de la Freebox (ou mafreebox.freebox.fr) et le port HTTPS local, **443** par défaut.
6. Accepte **Freebox HA** sur l’écran de la Freebox dans les deux minutes.

Le dépôt est un dépôt HACS personnalisé ; cela ne signifie pas qu’il est inclus dans le catalogue HACS officiel.

## Installation manuelle sur Home Assistant OS

Télécharge l’archive de la release et copie le dossier **custom_components/freebox_ultra_ultimate** dans **/config/custom_components/** avec Samba, Studio Code Server ou ton outil de fichiers habituel. La structure finale doit être **/config/custom_components/freebox_ultra_ultimate/manifest.json**. Ne copie pas un second niveau custom_components dans ce dossier.

Redémarre HA, puis ajoute **Freebox HA** depuis Appareils et services et accepte l’appairage sur l’écran. Aucune configuration YAML, installation pip sur HA OS ou service externe n’est nécessaire.

Pour une mise à jour manuelle, remplace le dossier de l’intégration et redémarre HA. Le jeton et l’inventaire sont stockés par HA et conservent les identifiants. Supprimer/recréer l’entrée change l’identifiant d’application ; privilégie Reconfigurer ou la réauthentification proposée par HA.

## HTTPS et permissions

Seule la découverte publique **/api_version** utilise HTTP, sans jeton. L’identité est ensuite recontrôlée en HTTPS. Toutes les requêtes authentifiées sont envoyées à l’adresse locale avec le nom TLS api_domain annoncé par la Freebox. Les deux autorités officielles Freebox et les autorités système sont validées. La signature, la période de validité, la chaîne de confiance et le nom TLS sont vérifiés. Le contexte dédié retire VERIFY_X509_STRICT, activé par défaut depuis Python 3.13, car la chaîne Freebox peut omettre une extension Authority Key Identifier ; aucune option SSL non vérifié n’est proposée. Le https_port annoncé peut être un port d’accès distant : il n’est pas substitué au port local 443.

L’intégration emploie le jeton d’application, challenge HMAC-SHA1 et un jeton de session en mémoire. Les sessions expirées sont renouvelées sous verrou, avec une nouvelle tentative limitée. Elle ne demande pas l’autorisation settings et ne réalise aucun PUT/DELETE ; les seuls POST servent à autoriser, ouvrir ou fermer une session. Freebox attribue les permissions par défaut : il n’existe pas de liste de permissions demandées dans le POST authorize documenté. La lecture des réglages est autorisée sans settings.

Les familles **Téléchargements** et **Contrôle parental** peuvent exiger respectivement downloader et parental, à autoriser dans Freebox OS → Paramètres → Gestion des accès → Applications. Elles sont désactivées par défaut. Un refus est reporté dans les diagnostics et n’interrompt pas les autres familles. Aucune permission explorer, appels, contacts ou PVR n’est demandée par le code.

Le jeton persistant est conservé dans le stockage standard des config entries HA ; ce stockage n’est pas une promesse de chiffrement au repos. Protège l’accès au système et aux sauvegardes HA. Le jeton de session n’est jamais persisté. L’inventaire local conserve les identités réseau nécessaires au suivi ; les diagnostics exportés ne les divulguent pas.

## Familles implémentées et intervalles

| Famille | Routes relatives au préfixe API découvert | Défaut |
|---|---|---|
| WAN | connection/ | 10 s |
| Stations Wi-Fi | wifi/ap/, wifi/ap/{id}/stations/ | 10 s |
| Ethernet | switch/status/, switch/port/{id}, switch/port/{id}/stats | 15 s |
| Présence LAN | lan/browser/interfaces/, lan/browser/{interface}/ | 20 s |
| Système | system/ | 30 s |
| Fibre | connection/ftth/ | 30 s |
| Radios et SSID | wifi/ap/, wifi/ap/{id}/, wifi/bss/, wifi/config/ | 30 s |
| Stockage | storage/disk/, storage/partition/, storage/config/ | 30 s, désactivé |
| VPN | vpn/, vpn/connection/, vpn/ip_pool/, vpn_client/status | 30 s, désactivé |
| Freeplug | freeplug/ | 30 s, désactivé |
| DHCP | dhcp/dynamic_lease/, dhcp/static_lease/, dhcp/config/ | 120 s, désactivé |
| LAN, DNS, IPv6 | lan/config/, connection/config/, connection/ipv6/config/ | 300 s, désactivé |
| Services | ftp/config/, netshare/samba/, netshare/afp/, upnpav/config/, airmedia/config/ | 300 s, désactivé |
| Routage et UPnP | fw/redir/, fw/dmz/, fw/incoming/, upnpigd/config/, upnpigd/redir/ | 300 s, désactivé |
| Radar Wi-Fi en cache | wifi/ap/{id}/channel_usage/, wifi/ap/{id}/neighbors/ | 300 s, désactivé |
| Téléchargements | downloads/, downloads/stats | 30 s, désactivé |
| Contrôle parental | parental/config/, parental/filter/ | 120 s, désactivé |
| Journaux WAN | connection/logs/ | 120 s, désactivé |

« Implémentée » signifie que le collecteur effectue la lecture, valide la forme, découvre les champs et expose les scalaires opérationnels pris en charge. La disponibilité réelle de chaque route dépend du matériel, du firmware et des droits. Les réponses d’erreur restent visibles ; aucune disponibilité sur une Ultra réelle n’est revendiquée sur la seule base du catalogue.

Le coordinateur vérifie les échéances toutes les 5 secondes, avec quatre requêtes simultanées au maximum, timeout de 8 secondes, corps limités à 1 Mio, cache par endpoint et une seule découverte AP par cycle. Une erreur temporaire applique un backoff exponentiel plafonné à 300 secondes ; absence/refus est réessayé après 15 minutes et après redémarrage observé. Les familles conservent des échéances indépendantes.

## Configuration graphique

Dans l’intégration, choisis **Configurer** :

- **Profil Essentiel** : réapplique les familles et entités de base aux installations existantes.
- **Familles et détails** : active/désactive les 18 familles, les détails clients, les métriques techniques, le regroupement par nom et l’essai WebSocket.
- **Intervalles** : de 5 à 3 600 secondes par famille. Les métriques lentes n’exigent pas les intervalles des débits.
- **Événements et seuils** : anti-rebond, délai de déconnexion, délai des alertes, hystérésis, seuils et unité source des puissances fibre.
- **Confidentialité et diagnostics** : identités dans les capteurs/événements, suivi des nouveaux appareils, historique borné de 0 à 100 événements par appareil, champs numériques non vérifiés et journalisation temporaire de 0 à 60 minutes.
- **Capacités détectées** : résumé de disponibilité ; le diagnostic JSON donne le détail des endpoints et champs.

**Défauts d’événements** : absence Wi-Fi 10 s, déconnexion LAN 40 s, autres transitions 10 s, alertes 30 s. Deux observations fraîches sont toujours nécessaires, même avec un délai à zéro. Seuil signal Wi-Fi -70 dB (hystérésis 5), température 80 °C (5), fibre RX -28 dBm (2). Adapte les seuils à ton installation et à ton module optique : ils ne représentent pas des limites universelles Freebox.

Les champs numériques nouveaux n’ont ni unité ni statistiques tant que leur sémantique n’est pas vérifiée. L’option correspondante crée des entités **désactivées par défaut**, avec source_field et unit_verified=false. Les champs inconnus sont listés dans les diagnostics même si cette option reste désactivée.

## Appareils et identifiants

La Freebox est le hub. WAN, fibre, radios AP, BSS, ports et stockage sont rattachés au hub. Chaque identité réseau LAN/Wi-Fi/DHCP dispose de ses propres entités et de son appareil HA lorsque des données exploitables sont présentes.

La clé d’origine utilise le MAC normalisé ou, sans MAC, l’identifiant Freebox contextualisé par interface. Le regroupement par nom conserve la clé d’origine la plus ancienne et mémorise les autres clés comme alias. L’adresse IP n’est jamais une clé d’identité. Plusieurs interfaces et MAC regroupées complètent ce même appareil. Le type Ethernet est indiqué uniquement si la table MAC d’un port le confirme. Le LAN seul ne permet pas d’inventer un port physique ou un type de liaison.

Les MAC localement administrées sont signalées. Une nouvelle MAC portant le même nom est rattachée au groupe lorsque le regroupement est actif. Si le nom change aussi et qu’aucun alias n’est connu, l’intégration ne peut pas déduire cette relation. Avec le regroupement désactivé, les MAC distinctes restent des appareils distincts.

La déconnexion ne supprime jamais l’appareil. L’inventaire est sauvegardé à la première collecte puis par points de contrôle toutes les 60 secondes et à la décharge. Les premiers états après chargement, perte d’API ou reboot reconstituent une référence silencieuse : il n’y a pas de vague de déconnexions/reconnexions fictives. Une coupure survenue pendant une indisponibilité API ne peut pas être reconstituée avec certitude.

## Entités et unités

| Données | Entités / unités |
|---|---|
| Présence | device_tracker home/not_home actif ; binary_sensor Connected confirmé optionnel |
| Identité | capteurs hostname, MAC, IPv4/IPv6, DHCP et indicateur MAC privée |
| Historique local | première observation, dernière observation/activité, connexions/déconnexions confirmées en timestamp |
| Stations Wi-Fi | octets RX/TX en B, trafic RX/TX en Mbit/s, durée/inactivité en s, débit PHY RX/TX en Mbit/s, largeur en MHz, MCS/flags disponibles |
| Radios | état, bande, canaux/largeur, clients associés ; radar en cache : bruit dB, occupation %, nombre de voisins |
| Ethernet | lien, duplex/mode, vitesse négociée Mbit/s, trafic Mbit/s, compteurs octets B et paquets/erreurs |
| Internet | connecté, état, média, IPv4/IPv6 publics, trafic Mbit/s, bande passante déclarée Mbit/s, totaux B |
| Fibre | lien/module/alimentation/signal, modèle du module, puissance RX/TX dBm si le rapport optique existe |
| Matériel | modèle/firmware, uptime s, dernier démarrage calculé, températures °C et ventilateurs rpm présents |
| Stockage | état, taille/libre/utilisé en B et température °C |
| Autres familles | compteurs d’objets et booléens/états opérationnels des services, règles, VPN, téléchargements et profils ; scalaires reconnus réellement présents |
| Diagnostic | appareils suivis, entités créées, endpoints accessibles/refusés/absents, version API, reboots observés, état WebSocket et disponibilité par famille |
| Automatisations | 14 événements sur le bus HA ; entités event optionnelles |

La direction RX/TX est celle de la **Freebox/AP/port**, pas celle du téléphone. Le trafic Wi-Fi/Ethernet local n’est pas assimilé à la consommation Internet. Le débit PHY est une vitesse de liaison, pas un débit utile mesuré. Les Mbit/s sont décimaux. Les -1 PHY/MCS sont inconnus et ne deviennent pas une mesure négative.

Le champ Wi-Fi **signal** est documenté en **dB d’atténuation** ; il n’est pas présenté comme un RSSI dBm vérifié. Aucune SNR n’est calculée à partir de grandeurs dont les références ne sont pas garanties compatibles. Les flags Wi-Fi 7/EHT sont exposés s’ils existent ; ils ne prouvent pas le standard négocié ou le MLO actif. Les informations MCS/flux supplémentaires et champs inconnus restent soumis à la disponibilité et à la vérification des unités.

FTTH sfp_pwr_rx/tx est documenté en **centièmes de dBm** : division par 100 par défaut. Si une lecture de ton firmware prouve des dBm directs, sélectionne cette unité dans les options. L’intégration ne choisit pas une unité en devinant selon l’amplitude.

Les données chiffrées appropriées utilisent measurement ou total_increasing et les classes HA data_rate, data_size, temperature, duration, timestamp, signal_strength. Les compteurs de trafic remis à zéro peuvent alimenter les statistiques longue durée. Les textes, MCS et valeurs de sémantique inconnue n’ont pas de state_class inventée. Les états sont bornés à 255 caractères ; aucun objet API complet n’est publié.

Selon le nombre d’appareils et les options, le volume Recorder peut devenir important. Désactive les détails inutiles, augmente leurs intervalles ou exclus les entités de dernière observation/diagnostic du Recorder si tu n’utilises pas leur historique. Les métriques absentes/disparues sont indisponibles, jamais remplacées par zéro.

## Événements

Tous les noms suivants sont utilisables dans un déclencheur HA event :

- freebox_ultra_device_discovered
- freebox_ultra_device_connected
- freebox_ultra_device_disconnected
- freebox_ultra_device_ip_changed
- freebox_ultra_device_connection_changed
- freebox_ultra_wifi_signal_low
- freebox_ultra_wifi_band_changed
- freebox_ultra_wifi_client_roamed
- freebox_ultra_ethernet_link_down
- freebox_ultra_ethernet_link_up
- freebox_ultra_wan_disconnected
- freebox_ultra_wan_reconnected
- freebox_ultra_fibre_signal_warning
- freebox_ultra_system_temperature_high

Champs communs : **device_id** (clé stable de l’intégration, et non UUID du registre HA), **entry_id**, **old_value**, **new_value**, **timestamp** UTC. Pour un client, MAC/nom peuvent être inclus selon l’option de confidentialité. Pour les alertes : metric, threshold, unit. Les IP utilisent deux collections : IPv4 puis IPv6. Les ports utilisent une clé telle que port:1 ; la Freebox utilise wan, fibre ou box selon l’événement.

Un changement doit persister pendant le délai avec au moins deux observations réussies. Les alertes restent verrouillées jusqu’au retour au-delà de l’hystérésis. L’apparition d’un appareil est distincte du passage connecté. La première photographie de lancement est silencieuse pour les nouveaux appareils et transitions ; une alerte métrique persistante peut être confirmée après deux lectures. Une perte d’API rend les entités concernées indisponibles et réinitialise les candidats, sans événement de déconnexion réseau.

Les event entities sous la Freebox affichent le dernier événement de chaque type ; elles sont complémentaires du bus. Les capteurs se prêtent aussi aux déclencheurs state/numeric_state habituels. L’intégration n’envoie pas de notification elle-même : tes automatisations choisissent les actions.

## Exemples d’automatisations

Le fichier [examples/automations.yaml](examples/automations.yaml) contient neuf exemples, dont une variante utilisant le SSID du tracker regroupé : nouvel appareil, connexion précise, présence du téléphone, équipement critique absent, fibre déconnectée, signal Wi-Fi bas, port Ethernet et changement d’IP. Remplace les identifiants d’entités et les MAC d’exemple par ceux de ton installation. Les entity_id sont attribués par HA et peuvent varier ; les unique_id restent stables.

Exemple nouvel appareil :

~~~yaml
alias: Freebox — nouvel équipement
triggers:
  - trigger: event
    event_type: freebox_ultra_device_discovered
actions:
  - action: persistent_notification.create
    data:
      title: Nouvel appareil réseau
      message: "{{ trigger.event.data.get('name', 'Identité inconnue') }} — {{ trigger.event.data.device_id }}"
~~~

Exemple d’équipement précis : ajoute event_data: {device_id: 'mac:02:00:00:00:00:01'} au déclencheur freebox_ultra_device_connected. Pour une alerte de coupure physique fibre, utilise le binary_sensor de lien fibre plutôt que confondre une session WAN interrompue avec la perte optique.

## Temps réel

L’abonnement ws/event utilise les événements LAN publics lan_host_l3addr_reachable et lan_host_l3addr_unreachable. La réponse register doit confirmer le succès avant que le diagnostic indique subscribed. Les notifications ne forcent pas directement les états : elles demandent une lecture LAN, au maximum une indication toutes les deux secondes, puis le moteur valide la transition. Les événements non disponibles sur un firmware restent couverts par le polling. Un firmware refusant le WebSocket reste parfaitement utilisable via les lectures régulières.

## Diagnostics et dépannage

Dans l’intégration → menu → **Télécharger les diagnostics** : version, familles, endpoints pseudonymisés, statut supported/unsupported/forbidden/error, champs connus/nouveaux, dernières tentatives/réussites, latences et limites. Le JSON ne contient jamais le jeton, les réponses brutes, noms des clients, MAC/IP, SSID ou chemins de fichiers. Les identifiants dynamiques de routes sont pseudonymisés.

- **Erreur de certificat** : vérifie les horaires de HA et le port HTTPS local 443. Le contexte TLS inclut les autorités Freebox et la compatibilité des chaînes legacy, sans désactiver la validation.
- **Connexion impossible** : HA doit joindre la box sur le réseau local et son port HTTPS. Vérifie la segmentation réseau, le DNS et les horaires système. N’active pas un mode TLS non vérifié.
- **Appairage refusé/expiré** : accepte sur l’écran dans les deux minutes, puis recommence l’ajout si nécessaire. Vérifie que les nouvelles applications sont autorisées dans Freebox OS.
- **Jeton révoqué** : HA propose la réauthentification. Un nouveau POST authorize crée une nouvelle application ; supprime éventuellement l’ancienne dans Freebox OS après validation.
- **Forbidden / insufficient_rights** : vérifie la permission de la famille concernée ; laisse settings désactivé pour cette intégration en lecture seule.
- **Endpoint absent** : limitation de firmware/matériel ; consulte le diagnostic. Une catégorie ne fait pas planter les autres.
- **Capteur absent** : aucun champ exploitable correspondant n’a été reçu ; active les métriques inconnues si tu veux préparer une contribution, puis vérifie leur signification avant emploi.
- **Compteurs remis à zéro** : normal après reboot ou nouvelle session réseau ; total_increasing traite les resets.
- **Présence inconnue/indisponible** : ce n’est pas une confirmation d’absence. Un bail DHCP seul ne prouve jamais qu’un appareil est connecté.
- **Signal optique incohérent** : contrôle l’unité source avec la doc locale Freebox OS avant de changer l’option.

Le mode debug temporaire des options journalise seulement des compteurs, sans secrets ni identités. La journalisation de débogage standard HA peut aussi être activée depuis l’intégration ; le code ne logue aucun payload. Évite de publier un dump personnel de Freebox OS : utilise le diagnostic anonymisé.

## Limites et validation sur ta Freebox

Les fonctionnalités suivantes ne sont pas garanties par l’API publique : bruit/SNR individuels, MIMO/flux spatiaux négociés, détails MLO, métriques CPU/mémoire, débits SFP+ distincts du WAN, relations derrière des switches externes, répéteurs hors liste AP, connexions TCP/UDP actives et journaux système généraux. Elles ne sont pas simulées. Les champs nouveaux sont recensés et les scalaires sûrs peuvent être inspectés. Les scans, boutons de contrôle, fichiers, appels/contacts, VM et modifications de configuration ne font pas partie de cette version.

Déjà vérifiés sur ton Ultra : découverte HTTP/HTTPS avec certificat validé, appairage LCD, session HMAC, lectures de 45 endpoints et acceptation de l’abonnement WebSocket. L’installation HACS et le passage à absent d’un téléphone hors Wi-Fi sont aussi vérifiés dans HA OS. Restent à vérifier : couverture complète des entités, renouvellement de session en durée, reboot physique, réception des notifications, comportement des événements et seuils. Le support MLO et les métriques de routes refusées ne sont pas revendiqués. La documentation locale **Freebox OS → Développer / doc/** peut être plus récente que la documentation publique.

Le code complet et les détails des sources sont disponibles dans ce dépôt et [docs/api-research.md](docs/api-research.md). L’état de validation est décrit dans [docs/validation.md](docs/validation.md).

## Développement et tests

Sous Linux, Python 3.14 :

~~~sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
python scripts/validate.py
python scripts/build_release.py
~~~

**La validation locale et les limites de la vérification matérielle sont détaillées dans [docs/validation.md](docs/validation.md).** Les tests couvrent transport/authentification/TLS, sessions concurrentes, versions nouvelles, endpoints absents/refusés, parsing, unités, identités et MAC privées, événements temporisés/hystérésis, interruptions/reboots, découverte dynamique, configuration et options, diagnostics et vrais setup/unload/reload HA. Le réseau de la box est doublé dans les tests ; ils n’effectuent pas d’écriture sur une Freebox. CI exécute pytest, Ruff, mypy, hassfest et le validateur HACS. L’absence d’une marque dans le catalogue Home Assistant est explicitement ignorée par HACS ; le dépôt personnalisé reste installable.

Licence MIT. Projet indépendant, sans affiliation avec Free ou Home Assistant.
