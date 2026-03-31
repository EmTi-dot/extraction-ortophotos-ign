# Documentation de extract_ortophotosIGN.py

## Objectif
Ce script automatise l'extraction d'orthophotos historiques depuis l'IGN en utilisant un service WMS accessible via `https://data.geopf.fr/wms-r`.

Il est conçu pour produire des tuiles TIFF par commune à partir d'un shapefile de polygones d'emprises communales, en testant plusieurs couches temporelles afin de trouver la meilleure couverture disponible pour chaque zone.

Le script :
- identifie les couches IGN ORTHOPHOTOS disponibles,
- teste la couverture de chaque couche sur la zone communale,
- télécharge des images via `gdal_translate`,
- vérifie la qualité finale en rejetant les images trop blanches et en évitant les erreurs liées au serveur ou au téléchargement
- organise la sortie en deux périodes (`Before` et `After`).

## Prérequis
- Python 3
- bibliothèques Python : `geopandas`, `requests`, `Pillow`, `numpy` (peuvent nécessiter un `pip install` si elles ne sont pas déjà présentes)
- GDAL présent sur le système, comme c'est le cas avec une installation QGIS complète
- l'exécutable `gdal_translate` doit être accessible via `gdal_path`

## Données ciblées
Le script travaille spécifiquement avec les orthophotos IGN de la famille `ORTHOIMAGERY.ORTHOPHOTOS*`.

Ces orthophotos sont des images aériennes géoréférencées produites et diffusées par l'IGN, généralement issues de campagnes photographiques françaises réalisées par avion.
Elles offrent une résolution fine adaptée aux analyses territoriales et d'aménagement, et sont disponibles en différentes années/millésimes.

Le script cherche à extraire des versions historiques de ces images pour deux périodes distinctes :
- `Before` : couvre 2014 à 2017 (avant le lancement du programme ACV)
- `After` : couvre 2022 à 2024 (après ACV)

## Principaux paramètres du script
- `villes_shp` : chemin vers le shapefile des communes à traiter.
- `output_root` : dossier de sortie pour les images extraites.
- `gdal_path` : chemin vers l'exécutable `gdal_translate`.
- `wms_url` : URL de base du service WMS utilisé.

## Comportement général
1. Le script charge les communes depuis `villes_shp` et les reprojette en EPSG:2154.
2. Il interroge le service WMS pour lister les couches ORTHOPHOTOS disponibles.
3. Il sépare les couches en deux périodes : `Before` (2014-2017) et `After` (2022-2024).
4. Pour chaque commune et chaque période, il tente plusieurs couches jusqu'à obtenir une image valide.
5. Il utilise `gdal_translate` pour créer un TIFF, puis vérifie que le fichier existe et qu'il n'est pas majoritairement blanc.

## Fonctions clés
- `is_too_white(filepath, threshold=0.90)` : analyse une miniature de l'image TIFF. Retourne `True` si plus de 90 % des pixels sont blancs, indiquant une image inutilisable.
- `get_available_layers(bbox_2154)` : récupère et trie les noms de couches disponibles du service WMS.
- `is_covered_by_layer(layer, xmin, ymin, xmax, ymax)` : effectue une pré-vérification par requêtes WMS `GetMap` sur une grille 3x3. Si la zone produit une image non blanche, la couche est considérée comme couvrante.
- `inspect_raw_response(layer, x, y, periode_label)` : utilitaire de débogage qui permet d'inspecter la réponse brute du serveur WMS.

## Détails d'exécution
- Les fichiers temporaires de configuration WMS sont écrits dans `temp_config.xml`.
- Le script construit une commande `gdal_translate` avec des options de compression JPEG et un blocage en tuiles (`TILED=YES`).
- Si une image est jugée blanche ou si une erreur survient, le script tente la couche suivante.
- Les erreurs classiques `502`, `503`, `504`, `IReadBlock failed` ou `ServiceExceptionReport` déclenchent une suppression du cache `gdalwmscache` pour repartir sur une extraction propre.

## Limites
- Le serveur IGN peut parfois être lent ou instable, ce qui allonge les temps de téléchargement.
- Des images partiellement corrompues peuvent apparaître, notamment sous la forme de carrés noirs ou de zones manquantes.
- Dans ce cas, supprimez manuellement le fichier TIFF concerné puis relancez le script pour que l'extraction soit retentée.

## Remarques
- Le script suppose que les communes sont en Lambert 93 (EPSG:2154).
- Si un TIFF existe déjà et dépasse 1 Mo, il est considéré comme valide et la commune est sautée.
- La logique de période dépend des années présentes dans les noms de couches IGN.

## Utilisation
1. Ajuster les chemins `villes_shp`, `output_root` et `gdal_path` dans `extract_ortophotosIGN.py`.
2. Installer les dépendances Python.
3. Lancer le fichier (depuis VSCode par exemple):
   ```bash
   python C:\\...\\Chemin\\...\\extract_ortophotosIGN.py
   ```

## Fichiers associés
- `temp_config.xml` : fichier temporaire de configuration GDAL/WMS créé à chaque exécution.
- `gdalwmscache/` : cache de GDAL pouvant être supprimé automatiquement en cas d'erreur réseau ou serveur.
