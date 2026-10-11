# Validation de Freebox HA 1.0.0

Validation exécutée le 12 octobre 2026 sous Linux : Python 3.14.8, Home Assistant 2026.10.1, pytest-homeassistant-custom-component 0.13.372, aiohttp 3.14.4.

## Contrôles automatisés

Résultats locaux : **162 tests automatisés**, dont 18 régressions du profil Essentiel et du regroupement et 15 régressions de présence Wi-Fi, ainsi que 19 contrôles de collections vides et de conservation des métadonnées, Ruff sans défaut, 40 fichiers conformes au format, mypy sans défaut sur 19 modules, compileall réussi ; hassfest officiel : une intégration et zéro invalide. Les deux tests de distribution vérifient le contenu public et la reproductibilité de l’archive.

La commande reproductible est **python scripts/validate.py**. Elle exécute Ruff, le contrôle de format, mypy sur les 19 modules de l’intégration, compileall et pytest avec un timeout par test. La CI ajoute les validateurs officiels hassfest et HACS ainsi que la construction de l’archive installable.

Les tests chargent réellement les plateformes sensor, binary_sensor, device_tracker et event dans HA, avec une API doublée. Ils couvrent ajout graphique, découverte mDNS, appairage, identifiants, renouvellement et concurrence des sessions, erreurs API, unités, ajout dynamique d’entités, confidentialité, événements temporisés, setup/unload/reload et options. Les fixtures publiques sont synthétiques et anonymisées d’après les contrats documentés ; elles ne sont pas une capture des appareils de l’utilisateur.

Les tests TLS ouvrent un serveur HTTPS de boucle locale. Une chaîne legacy sans Authority Key Identifier est acceptée ; les mauvais noms TLS, autorités inconnues, certificats expirés et signatures invalides restent refusés. Un test impose aussi un identifiant d’application court, conservé dans la config entry après appairage.

Les régressions supplémentaires vérifient la fusion de trois appareils homonymes dans les vrais registres HA, les alias après redémarrage, le maintien de présence lors d’un changement de MAC, le profil Essentiel, les activations individuelles et la séparation optionnelle des identités. Le regroupement réel des téléphones de l’utilisateur doit encore être observé dans son instance.

Les régressions vérifient les enfants d’endpoints devenus indisponibles, les sources LAN/Wi-Fi partielles, les candidats d’alertes après panne et la sauvegarde d’inventaire. Une réponse partielle ne doit pas établir une déconnexion.

Les tests de présence Wi-Fi couvrent le statut LAN retardé, les cycles entre deux pollings, les alias, le redémarrage, le roaming, l’inactivité sans trafic, les entrées radio malformées et les collectes partielles. Dans le harnais HA avec une API doublée, ils vérifient les états home/not_home/unavailable et les attributs de confirmation. Le délai effectif sur les téléphones réels dépend encore de la mise à jour des listes de stations par le firmware.

Un diagnostic anonymisé téléchargé depuis HA OS le 12 octobre a confirmé des erreurs invalid_shape sur deux listes de stations et une liste LAN. Le harnais HA vérifie maintenant les variantes vides {}, null et [] : Presence passe à not_home, Connected à off, et les métadonnées restent disponibles. Après un premier correctif, ces mêmes endpoints ont signalé invalid_envelope : ils renvoient un succès sans champ result. Cette variante est maintenant acceptée uniquement sur ces listes réseau ; le passage à absent a ensuite été observé dans HA OS, après retéléchargement HACS et redémarrage. Connected affiche Déconnecté et Presence Absent pour le téléphone hors Wi-Fi, tandis que nom, MAC et IP connues restent disponibles. Les métadonnées ont déjà été vérifiées disponibles dans HA OS après redémarrage, avec le téléphone déconnecté.

## Vérification matérielle réelle

L’utilisateur a accepté **Freebox HA validation V1** sur l’écran de sa Freebox Ultra V9. Le client aiohttp et les collecteurs du projet ont ensuite exécuté les étapes suivantes en lecture seule :

| Contrôle | Résultat observé |
|---|---|
| Découverte HTTP et HTTPS | API 16.0, modèle FreeboxServer9,1, HTTPS local 443 |
| Certificat | Chaîne et nom TLS vérifiés |
| Autorisation LCD | Acceptée |
| Authentification challenge/HMAC | Session ouverte puis fermée |
| Endpoints | 45 lectures réussies ; 7 erreurs isolées |
| Inventaire | 71 identités réseau |
| Modèle de métriques | 3 178 métriques candidates, avant enregistrement HA |
| WAN | Bande passante déclarée 8 000 Mbit/s dans chaque direction |
| Fibre | RX -18,76 dBm ; TX 5,8 dBm après conversion documentée |
| WebSocket | Réponse register avec success=true |

Des lectures ont réussi dans les familles WAN, fibre, présence LAN, stations Wi-Fi, Ethernet, système, radios Wi-Fi, DHCP, réseau, stockage, services, routage et VPN. Cela ne signifie pas que chaque endpoint de chacune de ces familles est supporté. Aucun résultat lisible n’a été obtenu pour Freeplug. Les familles coûteuses désactivées par défaut n’ont pas été validées lors de cette collecte.

Les 3 178 métriques correspondent au modèle des collecteurs, **pas à des entités créées dans l’instance HA OS de l’utilisateur**. L’acceptation WebSocket confirme l’abonnement, pas la réception d’un événement de connectivité. Les sept erreurs n’interrompent pas les autres lectures ; leur cause précise n’a pas été exportée pendant cette session. Aucun jeton ni payload personnel n’a été conservé dans le dépôt ou les rapports publics.

## Validation restant à effectuer sur HA OS

L’installation et le retéléchargement HACS ainsi que l’état absent d’un téléphone hors Wi-Fi ont été observés dans l’instance. Restent à vérifier : appairage depuis HA OS, qualité des noms et volume des entités, fonctionnement prolongé et renouvellement de session, reboot physique, interruptions réseau, réception des notifications WebSocket et déclenchement des automatisations sur des transitions réelles. Les tests automatisés vérifient ces contrats avec des doubles explicites ; ils ne remplacent pas cette observation matérielle.

Les résultats de la [CI publique](https://github.com/FOEDI/FreeboxHA/actions) sont consultables par commit. Le dépôt est installable comme dépôt HACS personnalisé ; il n’est pas annoncé comme inclus dans le catalogue officiel.
