# Contribuer à Freebox HA

Le développement et les tests Home Assistant sont exécutés sous Linux avec Python 3.14. Les dépendances de test sont épinglées dans requirements-test.txt.

~~~sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
python scripts/validate.py
python scripts/build_release.py
~~~

La CI exécute également les validateurs officiels hassfest et HACS. Elle constitue la procédure de validation de structure reproductible ; aucun checkout de recherche local n’est nécessaire.

Pour un bug : joindre la version réellement affichée dans le formulaire, la version HA, le firmware Freebox, le diagnostic anonymisé et le code d’erreur. Ne joindre aucun jeton, réponse API brute, nom réseau privé ou identifiant de client. Les fixtures publiques doivent rester anonymisées, les métriques nouvelles accompagnées d’une référence d’unité et d’une régression représentative.

L’intégration est en lecture seule. Les seuls POST sont ceux d’appairage/session. Un endpoint absent ou refusé doit rester isolé, et une collecte incomplète ne peut pas établir une déconnexion.
