# =====================
# EXTRACTION DES ORTHOPHOTOS HISTORIQUES DE L'IGN VIA WMS
# =====================

# =====================
# IMPORTS
# =====================
import geopandas as gpd
import os
import subprocess
import time
import shutil
from PIL import Image
import numpy as np
import requests
from io import BytesIO
from xml.etree import ElementTree as ET

# =====================
# PARAMÈTRES
# =====================
villes_shp = "C:/FAC/MASTER/M2/Thèse/Night_Lights/3Avril/GIS/Data_Com/SHP/Controles.shp" # Chemin vers le shapefile des villes (polygones)
output_root = "C:/FAC/MASTER/M2/Thèse/Night_Lights/3Avril/GIS/TESTControles" # Dossier de sortie pour les images extraites
gdal_path = "C:/FAC/MASTER/M1/Semestre 2/SIG/Logiciel/bin/gdal_translate" # Chemin vers l'exécutable gdal_translate (ajustez selon votre installation)


wms_url = "https://data.geopf.fr/wms-r" # URL de base pour les requêtes WMS. Notez que nous utiliserons des paramètres spécifiques dans le XML de configuration GDAL pour cibler les couches et les zones d'intérêt.

# =====================
#FONCTIONS
# =====================

##Pour éviter les images blanches
def is_too_white(filepath, threshold=0.90):
    """Analyse une miniature de l'image pour éviter les crashs RAM.
    Si plus de threshold (90%) des pixels sont blancs, on considère que c'est une image corrompue.
    filepath : chemin vers le fichier à analyser
    threshold : ratio de pixels blancs au-delà duquel on rejette l'image
    Retourne True si l'image est trop blanche, False sinon.
    """
    try:
        # On force PIL à accepter l'image même si elle est immense
        Image.MAX_IMAGE_PIXELS = None 
        
        with Image.open(filepath) as img:
            # On ne charge qu'une version minuscule (1000x1000 pixels max)
            img.thumbnail((1000, 1000))
            bw_img = img.convert('L') 
            bw_data = np.array(bw_img)
            
            # Un pixel blanc est proche de 255. On compte ceux > 245.
            white_pixels = np.sum(bw_data > 245)
            total_pixels = bw_data.size
            ratio = white_pixels / total_pixels
            
            print(f"      [DEBUG] Ratio de blanc : {ratio:.2%}")
            return ratio > threshold
    except Exception as e:
        print(f"      [!] Erreur analyse : {e}")
        return True # En cas d'erreur, on considère que c'est mauvais par sécurité


def get_available_layers(bbox_2154):
    """Retourne les couches ORTHOPHOTOS millésimées disponibles pour une zone.
    param bbox_2154 : (xmin, ymin, xmax, ymax) en EPSG:2154. Si None, on liste toutes les couches disponibles."""
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetCapabilities"
    }
    r = requests.get(wms_url, params=params, timeout=30)
    root = ET.fromstring(r.content)
    ns = {"wms": "http://www.opengis.net/wms"} # Namespace WMS standard
    
    available = []
    for layer in root.findall(".//wms:Layer/wms:Name", ns):
        name = layer.text or ""
        if "ORTHOIMAGERY.ORTHOPHOTOS2" in name:
            available.append(name)
    return sorted(available, reverse=True)  # Du plus récent au plus ancien


def is_covered_by_layer(layer, xmin, ymin, xmax, ymax):
    """Vérifie sur une grille de points si la couche couvre la zone.
    On teste une grille 3x3 (9 points) répartis sur la commune. Si au moins un point retourne une image non blanche, on considère que la couche couvre la zone.
    param layer : nom de la couche à tester
    param xmin, ymin, xmax, ymax : bornes de la zone à tester en EPSG:2154
    Retourne True si la couche couvre la zone, False sinon."""

    # Grille 3x3 = 9 points répartis sur toute la commune
    test_points = [
        (xmin + (xmax-xmin)*px, ymin + (ymax-ymin)*py)
        for px in [0.25, 0.5, 0.75]
        for py in [0.25, 0.5, 0.75]
    ]
    
    for x, y in test_points:
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": layer,
            "STYLES": "",
            "CRS": "EPSG:2154",
            "BBOX": f"{x-500},{y-500},{x+500},{y+500}",  # Zone plus large : 1km x 1km
            "WIDTH": 20, "HEIGHT": 20,                    # Un peu plus de pixels
            "FORMAT": "image/jpeg"
        }
        try:
            r = requests.get(wms_url, params=params, timeout=10)
            if r.status_code != 200:
                continue
            img = Image.open(BytesIO(r.content))
            bw = np.array(img.convert('L'))
            ratio_blanc = np.sum(bw > 245) / bw.size
            #print(f"  [PRE-CHECK] ratio blanc : {ratio_blanc:.2%}")
            
            if ratio_blanc < 0.90:
                return True  # Un seul point valide suffit
                
        except Exception as e:
            continue
    
    return False  # Aucun point valide = couche non couverte, on passe à la suivante

def inspect_raw_response(layer, x, y, periode_label):
    """Fonction de debug pour inspecter la réponse brute du serveur WMS avant de lancer GDAL.
    Cela permet de vérifier si le serveur répond correctement à nos requêtes et d'ajuster les paramètres si nécessaire."""
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": "EPSG:2154",
        "BBOX": f"{x-500},{y-500},{x+500},{y+500}",
        "WIDTH": 100, "HEIGHT": 100,
        "FORMAT": "image/jpeg"
    }
    r = requests.get(wms_url, params=params, timeout=10)
    print(f"  [INSPECT] Statut HTTP : {r.status_code}")
    print(f"  [INSPECT] Content-Type : {r.headers.get('Content-Type')}")
    print(f"  [INSPECT] Début contenu : {r.content[:300]}")  # Les 300 premiers octets
    
# =====================
# CHARGEMENT DES COUCHES DISPONIBLES
# =====================
ALL_LAYERS = get_available_layers(None)

BEFORE_LAYERS = sorted(
    [l for l in ALL_LAYERS 
     if any(y in l for y in ["2014","2015","2016","2017"])
     and "-" not in l.replace("ORTHOIMAGERY.ORTHOPHOTOS", "")],  # Exclut les plages
    reverse=True
)

AFTER_LAYERS = sorted(
    [l for l in ALL_LAYERS if any(y in l for y in ["2022","2023","2024"])
    and "-" not in l.replace("ORTHOIMAGERY.ORTHOPHOTOS", "")],
    reverse=True
)

config_periodes = {
    "Before": {
        "targets": [l.replace("ORTHOIMAGERY.ORTHOPHOTOS", "") for l in BEFORE_LAYERS],
        "layers": BEFORE_LAYERS
    },
    "After": {
        "targets": [l.replace("ORTHOIMAGERY.ORTHOPHOTOS", "") for l in AFTER_LAYERS],
        "layers": AFTER_LAYERS
    }
}


# =====================
# CHARGEMENT ET PREP
# =====================
villes = gpd.read_file(villes_shp)
villes = villes.to_crs(2154) # reprojection Lambert93 pour être sûr que les coordonnées correspondent au WMS de l'IGN

# =====================
# BOUCLE PRINCIPALE
# =====================
for periode_label, config in config_periodes.items():
    
    # Création du dossier Parent (Before ou After)
    parent_dir = os.path.join(output_root, periode_label)
    os.makedirs(parent_dir, exist_ok=True)

    for idx, row in villes.iterrows():
        ville_nom = str(row["nom_COM"]).replace(" ", "_").replace("'", "_") #le paramètres "nom_com" est à adapter selon le champ de votre shapefile qui contient le nom de la ville.
        xmin, ymin, xmax, ymax = row.geometry.bounds
        center_x, center_y = (xmin + xmax) / 2, (ymin + ymax) / 2
        success = False

        for i in range(len(config["layers"])):
            if success: break

            current_layer = config["layers"][i]
            
            current_year=config["targets"][i]

            filename = f"{ville_nom}_{current_year}.tif"
            output_file = os.path.join(parent_dir, filename)

            #Vérification d'existence pour gagner du temps en cas de relance
            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000000:
                print(f"  [v] {filename} déjà présent. Succès validé.")
                success = True  # On marque le succès
                break           # On sort de la boucle des années (2017, 2016...) pour passer à la suite
        
            if not is_covered_by_layer(current_layer, xmin, ymin, xmax, ymax):
                print(f"  [-] Pre-check : zone non couverte par {current_layer} pour {ville_nom}. Tentative suivante...")
                continue
            
            print(f"\n--- Tentative {periode_label} : {ville_nom} avec la couche {current_layer} ---")

            server_url = "https://data.geopf.fr/wms-r?SERVICE=WMS&amp;REQUEST=GetMap"

            # =====================
            # XML DE CONFIGURATION GDAL WMS
            # =====================
            wmts_xml = f"""<GDAL_WMS>
                <Service name="WMS">
                    <Version>1.3.0</Version>
                    <ServerUrl>{server_url}</ServerUrl>
                    <Layers>{current_layer}</Layers>
                    <CRS>EPSG:2154</CRS>
                    <ImageFormat>image/jpeg</ImageFormat>
                    <Transparent>FALSE</Transparent>
                </Service>
                <DataWindow>
                    <UpperLeftX>0.0</UpperLeftX><UpperLeftY>7117201.0</UpperLeftY>
                    <LowerRightX>1313651.0</LowerRightX><LowerRightY>6004030.0</LowerRightY>
                    <SizeX>5000000</SizeX><SizeY>5000000</SizeY>
                </DataWindow>
                <BlockSizeX>512</BlockSizeX>
                <BlockSizeY>512</BlockSizeY>
                <MaxConnections>2</MaxConnections>
                <Timeout>120</Timeout>
                <Retries>5</Retries>
                <RetryDelay>10</RetryDelay>
                <ZeroBlockHttpCodes>400,404,502,503,504</ZeroBlockHttpCodes>
                <ZeroBlockOnServerException>true</ZeroBlockOnServerException>
            </GDAL_WMS>"""

            with open("temp_config.xml", "w") as f: f.write(wmts_xml)

            # =====================
            # DEBUG : INSPECTION DE LA RÉPONSE BRUTE AVANT GDAL (commentée pour accélérer les tests une fois la config validée)
            # =====================

            #inspect_raw_response(current_layer, center_x, center_y, periode_label) 
            #print(f"  [XML URL] {server_url}")
            #with open("temp_config.xml", "r") as f: 
                #print(f.read())
            #with open("temp_config.xml", "r") as f: 
            #    print(f"  [FICHIER REEL] {f.read()}")

            # =====================
            # COMMANDE GDAL
            # =====================
            cmd = [
                gdal_path,
                "-projwin", str(xmin), str(ymax), str(xmax), str(ymin),
                "-tr", "0.3", "0.3",
                "-of", "GTiff",
                "-co", "COMPRESS=JPEG",
                "-co", "PHOTOMETRIC=YCBCR",
                "-co", "TILED=YES",
                "-co", "BLOCKXSIZE=512",
                "-co", "BLOCKYSIZE=512",
                "-co", "JPEG_QUALITY=85",
                "--config", "GDAL_HTTP_RETRY_DELAY", "30",
                "--config", "GDAL_HTTP_MAX_RETRY", "15",
                "--config", "GDAL_HTTP_RETRY_CODES", "502,503,504",
                "temp_config.xml", # SOURCE en avant-dernier
                output_file        # DESTINATION en dernier
            ]

            # =====================
            # EXÉCUTION DE LA COMMANDE AVEC GESTION DES ERREURS ET VALIDATION DE L'IMAGE
            # =====================
            try:
                result = subprocess.run(cmd, stdout=None, stderr=subprocess.PIPE, text=True)
                print(f"  [STDERR] {result.stderr[-500:]}")
            

                # 1. On vérifie d'abord si le fichier a été créé et s'il a une taille cohérente
                if os.path.exists(output_file) and os.path.getsize(output_file) > 500000:
                    
                    # 2. ANALYSE : Est-ce que l'image est blanche ?
                    if is_too_white(output_file):
                        print(f"  [-] Rejet : {filename} est une image blanche. Tentative année suivante...")
                        os.remove(output_file) # On supprime pour que la boucle continue
                    
                    else:
                        # 3. SUCCÈS : L'image existe et elle n'est pas blanche
                        print(f"  [+] SUCCÈS : {filename} généré et validé.")
                        success = True
                        break # ON SORT de la boucle des années pour passer à la VILLE suivante
                
                else:
                    # Échec du téléchargement (fichier absent ou trop petit)
                    if os.path.exists(output_file):
                        os.remove(output_file)
                    
                    # ON AJOUTE "ServiceExceptionReport" ICI pour vider le cache et continuer
                    if "IReadBlock failed" in result.stderr or "502" in result.stderr or "ServiceExceptionReport" in result.stderr:
                         if os.path.exists("gdalwmscache"):
                             shutil.rmtree("gdalwmscache")
                             os.makedirs("gdalwmscache", exist_ok=True)
                    
                    print(f"  [-] Échec/Saut pour {current_year}. (Erreur IGN ou donnée manquante)")
                    # Le code continue naturellement vers l'année suivante car success est toujours False
                    
            except Exception as e:
                print(f"Erreur système lors du traitement : {e}")

print("\n--- Extraction terminée ---")