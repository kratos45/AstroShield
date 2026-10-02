# Évaluation des sources — AstroShield

## Source A — NASA NeoWs (source principale, RETENUE)

- **Producteur** : Jet Propulsion Laboratory (NASA)
- **URL** : https://api.nasa.gov/neo/rest/v1/feed (documentation officielle)
- **Mode d'accès** : API REST, clé gratuite `DEMO_KEY` (30 req/min, 50 req/jour)
- **Format** : JSON (feed des approches, 7 jours max par requête)
- **Mise à jour** : quotidienne
- **Clé/identifiant** : `neo_reference_id`
- **Licence** : données publiques NASA, crédit demandé ; aucun scraping
- **Risques** : quotas de DEMO_KEY ; `element_count` par fenêtre
- **Données personnelles** : aucune
- **Pourquoi retenue** : répond directement à la question (approches, distances,
  diamètres estimés, statut PHA), accès documenté et stable, reproductible.

## Source B — JPL Small-Body Database (enrichissement, RETENUE)

- **Producteur** : NASA JPL (Small-Body Database Search Engine)
- **URL** : https://ssd-api.jpl.nasa.gov/sbdb.api
- **Mode d'accès** : API REST publique, sans clé
- **Format** : JSON (orbites, paramètres physiques)
- **Mise à jour** : continue
- **Licence** : données publiques JPL
- **Risques** : réponses volumineuses, gabarit orbitale (keplerienne) à parser
- **Complémentarité réelle** : éléments orbitaux (a, e, i, q, ad) et albedo
  absents de NeoWs → indispensable aux modèles ML et à la famille spectrale.

## Sources écartées

| Source | Motif |
|---|---|
| Wikipedia / scraping générique | Conditions d'utilisation, non structuré, redondant avec JPL |
| Données de tirs/télescopes réels | Nécessitent des accès authentifiés non disponibles → simulateur cohérent |

## Conclusion

Collecte 100 % légale via API officielles, aucun secret dans le dépôt
(clé en variable d'environnement), aucune donnée personnelle.
