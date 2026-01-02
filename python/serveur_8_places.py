#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
SMART PARKING - 8 PLACES - DÉTECTION OBSTACLES OPENCV
Version Finale - Tous les bugs corrigés
═══════════════════════════════════════════════════════════════
"""

import cv2
import numpy as np
import json
import urllib.request
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except:
    MQTT_OK = False
    print("⚠️  pip install paho-mqtt")

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION - MODIFIEZ ICI
# ═══════════════════════════════════════════════════════════════

MQTT_BROKER = "192.168.1.18"       # Votre IP PC
MQTT_PORT = 1883
ESP32_CAM_IP = "192.168.1.32"      # IP ESP32-CAM
ESP32_CAM_PORT = 81
WEB_PORT = 8888

# Paramètres détection
SEUIL_OCCUPATION = 25.0            # % de différence pour détecter obstacle
MIN_CONTOUR_AREA = 800             # Aire minimale contour (pixels²)
NB_PLACES = 8                      # Nombre total de places

# ═══════════════════════════════════════════════════════════════
# ZONES DES 8 PLACES (À CALIBRER SELON VOTRE MAQUETTE)
# ═══════════════════════════════════════════════════════════════

# Format : [x, y, largeur, hauteur]
# Ajustez selon la position de vos places dans l'image
zones_parking = {
    # Rangée du haut (4 places)
    "P1": [30, 40, 120, 90],
    "P2": [170, 40, 120, 90],
    "P3": [310, 40, 120, 90],
    "P4": [450, 40, 120, 90],
    
    # Rangée du bas (4 places)
    "P5": [30, 160, 120, 90],
    "P6": [170, 160, 120, 90],
    "P7": [310, 160, 120, 90],
    "P8": [450, 160, 120, 90],
}

# ═══════════════════════════════════════════════════════════════
# DONNÉES GLOBALES
# ═══════════════════════════════════════════════════════════════

PARKING_DATA = {
    'places': {},
    'timestamp': None,
    'total': NB_PLACES,
    'available': 0,
    'occupied': 0
}

image_reference = None
mqtt_client = None
mqtt_connected = False

# ═══════════════════════════════════════════════════════════════
# MQTT
# ═══════════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        print("✓ MQTT Connecté")
        mqtt_connected = True
        client.subscribe("parking/sensor/vehicle")
        print("✓ Abonné à parking/sensor/vehicle")
    else:
        print(f"✗ MQTT erreur code: {rc}")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        print(f"\n📨 MQTT: {data}")
        
        if msg.topic == "parking/sensor/vehicle" and data.get("detected"):
            print(f"🚗 VÉHICULE DÉTECTÉ ! Distance: {data.get('distance_cm')}cm")
            print("⏳ Analyse automatique dans 1 seconde...")
            time.sleep(1)  # Petite pause pour stabiliser
            analyser_parking()
    except Exception as e:
        print(f"✗ Erreur message MQTT: {e}")

def mqtt_publish(topic, data):
    if mqtt_connected:
        try:
            mqtt_client.publish(topic, json.dumps(data), qos=1, retain=True)
        except Exception as e:
            print(f"✗ Erreur publication MQTT: {e}")

# ═══════════════════════════════════════════════════════════════
# CAPTURE IMAGE ESP32-CAM
# ═══════════════════════════════════════════════════════════════

def capturer_image():
    url = f"http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}/capture"
    try:
        print(f"📷 Capture: {url}")
        urllib.request.urlretrieve(url, "parking_current.jpg")
        img = cv2.imread("parking_current.jpg")
        
        if img is None:
            print("✗ Image invalide ou corrompue")
            return None
        
        print(f"✓ Image capturée: {img.shape[1]}x{img.shape[0]} pixels")
        return img
        
    except urllib.error.URLError as e:
        print(f"✗ Impossible de contacter ESP32-CAM: {e}")
        print(f"  Vérifiez que http://{ESP32_CAM_IP}:{ESP32_CAM_PORT} est accessible")
        return None
    except Exception as e:
        print(f"✗ Erreur capture: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# DÉTECTION OBSTACLES PAR OPENCV
# ═══════════════════════════════════════════════════════════════

def analyser_zone(img_current, zone_coords, nom_place):
    """
    Analyse une zone pour détecter un obstacle (voiture)
    
    Méthode 1 (avec référence) : Compare avec image parking vide
    Méthode 2 (sans référence) : Détecte contours/obstacles
    
    Returns:
        dict avec 'occupe', 'pourcentage_diff', 'contours', 'aire'
    """
    global image_reference
    
    x, y, w, h = zone_coords
    zone_current = img_current[y:y+h, x:x+w]
    
    resultat = {
        'occupe': False,
        'pourcentage_diff': 0.0,
        'contours': 0,
        'aire': 0,
        'methode': 'Aucune'
    }
    
    # ═════ MÉTHODE 1 : AVEC IMAGE DE RÉFÉRENCE ═════
    if image_reference is not None:
        try:
            zone_ref = image_reference[y:y+h, x:x+w]
            
            # Conversion niveaux de gris
            gray_current = cv2.cvtColor(zone_current, cv2.COLOR_BGR2GRAY)
            gray_ref = cv2.cvtColor(zone_ref, cv2.COLOR_BGR2GRAY)
            
            # Différence absolue
            diff = cv2.absdiff(gray_ref, gray_current)
            
            # Binarisation avec seuil adaptatif
            _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
            
            # Morphologie pour nettoyer le bruit
            kernel = np.ones((5,5), np.uint8)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            
            # Calculer pourcentage de pixels différents
            pixels_diff = cv2.countNonZero(thresh)
            total_pixels = w * h
            pourcentage = (pixels_diff / total_pixels) * 100
            
            # Détection de contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filtrer contours trop petits
            contours_valides = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]
            
            # Aire totale des obstacles détectés
            aire_totale = sum(cv2.contourArea(c) for c in contours_valides)
            
            resultat = {
                'occupe': pourcentage > SEUIL_OCCUPATION,
                'pourcentage_diff': pourcentage,
                'contours': len(contours_valides),
                'aire': int(aire_totale),
                'methode': 'Différence avec référence'
            }
            
        except Exception as e:
            print(f"✗ Erreur analyse {nom_place}: {e}")
    
    # ═════ MÉTHODE 2 : SANS RÉFÉRENCE (DÉTECTION CONTOURS) ═════
    else:
        try:
            # Conversion niveaux de gris
            gray = cv2.cvtColor(zone_current, cv2.COLOR_BGR2GRAY)
            
            # Flou pour réduire bruit
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Détection de bords (Canny)
            edges = cv2.Canny(blur, 50, 150)
            
            # Détection de contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filtrer contours
            contours_valides = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]
            
            # Aire totale
            aire_totale = sum(cv2.contourArea(c) for c in contours_valides)
            
            # Heuristique : si aire > 20% de la zone = obstacle présent
            seuil_aire = (w * h) * 0.20
            
            resultat = {
                'occupe': aire_totale > seuil_aire,
                'pourcentage_diff': (aire_totale / (w * h)) * 100,
                'contours': len(contours_valides),
                'aire': int(aire_totale),
                'methode': 'Détection contours (sans référence)'
            }
            
        except Exception as e:
            print(f"✗ Erreur analyse {nom_place}: {e}")
    
    return resultat

# ═══════════════════════════════════════════════════════════════
# ANALYSE COMPLÈTE DU PARKING
# ═══════════════════════════════════════════════════════════════

def analyser_parking():
    global PARKING_DATA
    
    # Capture image
    img = capturer_image()
    if img is None:
        print("✗ Impossible d'analyser sans image")
        return
    
    # Image pour annotation
    img_result = img.copy()
    resultats = {}
    
    print("\n" + "="*80)
    print("📊 ANALYSE DU PARKING (8 PLACES)")
    print("="*80)
    
    # Analyser chaque place
    for nom_place in sorted(zones_parking.keys()):
        zone_coords = zones_parking[nom_place]
        x, y, w, h = zone_coords
        
        # Analyser la zone
        analyse = analyser_zone(img, zone_coords, nom_place)
        
        # Déterminer occupation
        est_occupe = analyse['occupe']
        
        # Stocker résultat
        resultats[nom_place] = {
            'occupe': est_occupe,
            'details': analyse
        }
        
        # Couleur selon statut
        couleur = (0, 0, 255) if est_occupe else (0, 255, 0)  # Rouge/Vert
        
        # Dessiner rectangle
        cv2.rectangle(img_result, (x, y), (x+w, y+h), couleur, 3)
        
        # Texte statut
        texte_statut = "OCCUPEE" if est_occupe else "LIBRE"
        cv2.putText(img_result, f"{nom_place}", 
                   (x+10, y+25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, couleur, 2)
        cv2.putText(img_result, texte_statut, 
                   (x+10, y+50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, couleur, 2)
        
        # Pourcentage
        cv2.putText(img_result, f"{analyse['pourcentage_diff']:.1f}%", 
                   (x+10, y+h-10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, couleur, 1)
        
        # Affichage console
        statut_text = "OCCUPÉE ✗" if est_occupe else "LIBRE ✓  "
        print(f"   {nom_place}: {statut_text:12} | "
              f"Diff: {analyse['pourcentage_diff']:5.1f}% | "
              f"Contours: {analyse['contours']:2} | "
              f"Aire: {analyse['aire']:6} px²")
    
    # Sauvegarder image annotée
    cv2.imwrite("parking_annotated.jpg", img_result)
    print("="*80)
    print(f"✓ Image annotée sauvegardée: parking_annotated.jpg")
    
    # Calculer statistiques
    disponibles = sum(1 for p in resultats.values() if not p['occupe'])
    total = len(resultats)
    occupees = total - disponibles
    taux_occupation = (occupees / total * 100) if total > 0 else 0
    
    print("\n" + "="*80)
    print(f"📊 RÉSULTAT GLOBAL:")
    print(f"   Total:           {total} places")
    print(f"   Disponibles:     {disponibles} places ({100-taux_occupation:.1f}%)")
    print(f"   Occupées:        {occupees} places ({taux_occupation:.1f}%)")
    print("="*80)
    
    # Mise à jour données web
    PARKING_DATA = {
        'places': resultats,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'total': total,
        'available': disponibles,
        'occupied': occupees
    }
    
    # Publication MQTT
    if mqtt_connected:
        # Statut parking
        status_msg = {
            'timestamp': PARKING_DATA['timestamp'],
            'total': total,
            'available': disponibles,
            'occupied': occupees,
            'places': {nom: p['occupe'] for nom, p in resultats.items()}
        }
        mqtt_publish("parking/status", status_msg)
        print("✓ Statut publié sur MQTT: parking/status")
        
        # Commande barrière
        if disponibles > 0:
            print(f"\n🟢 BARRIÈRE: OUVERTURE ({disponibles} place(s) disponible(s))")
            commande = {"action": "open", "available": disponibles}
        else:
            print("\n🔴 BARRIÈRE: RESTE FERMÉE (Parking complet)")
            commande = {"action": "stay_closed"}
        
        mqtt_publish("parking/barrier/command", commande)
        print("✓ Commande barrière publiée sur MQTT: parking/barrier/command")
    
    print()

# ═══════════════════════════════════════════════════════════════
# SERVEUR WEB 3D
# ═══════════════════════════════════════════════════════════════

class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        if self.path == '/':
            self.send_html()
        elif self.path == '/api/status':
            self.send_json(PARKING_DATA)
        elif self.path == '/image/parking_annotated.jpg':
            self.send_image('parking_annotated.jpg')
        else:
            self.send_error(404)
    
    def send_html(self):
        html = '''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🚗 Smart Parking 8 Places - 3D</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    min-height: 100vh;
}
.container { max-width: 1600px; margin: 0 auto; padding: 20px; }
header {
    text-align: center;
    padding: 40px;
    background: rgba(0,0,0,0.3);
    border-radius: 20px;
    margin-bottom: 30px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
}
h1 { font-size: 3.5em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.5); }
.subtitle { font-size: 1.3em; opacity: 0.9; }
.stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin-bottom: 30px;
}
.stat-card {
    background: rgba(255,255,255,0.1);
    backdrop-filter: blur(10px);
    border-radius: 15px;
    padding: 30px;
    text-align: center;
    transition: transform 0.3s;
    border: 1px solid rgba(255,255,255,0.2);
}
.stat-card:hover { transform: translateY(-5px); box-shadow: 0 15px 40px rgba(0,0,0,0.4); }
.stat-number { font-size: 3.5em; font-weight: bold; margin: 10px 0; }
.stat-label { font-size: 1.1em; text-transform: uppercase; letter-spacing: 2px; }
.controls {
    background: rgba(0,0,0,0.3);
    border-radius: 15px;
    padding: 25px;
    margin-bottom: 30px;
    text-align: center;
}
button {
    background: linear-gradient(145deg, #3b82f6, #2563eb);
    color: white;
    border: none;
    padding: 15px 40px;
    font-size: 1.1em;
    border-radius: 10px;
    cursor: pointer;
    margin: 0 10px;
    box-shadow: 0 5px 15px rgba(37,99,235,0.4);
    transition: all 0.3s;
}
button:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(37,99,235,0.6); }
.parking-3d {
    background: rgba(0,0,0,0.4);
    border-radius: 20px;
    padding: 40px;
    margin-bottom: 30px;
}
.parking-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 25px;
    perspective: 1000px;
}
.parking-spot {
    background: linear-gradient(145deg, #2a2a2a, #1a1a1a);
    border-radius: 15px;
    padding: 25px;
    text-align: center;
    border: 3px solid #444;
    transform-style: preserve-3d;
    transition: all 0.5s;
    min-height: 200px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.parking-spot:hover { transform: rotateY(10deg) rotateX(5deg); }
.parking-spot.libre {
    background: linear-gradient(145deg, #4ade80, #22c55e);
    border-color: #16a34a;
    animation: pulse-green 2s infinite;
}
.parking-spot.occupe {
    background: linear-gradient(145deg, #f87171, #ef4444);
    border-color: #dc2626;
    animation: pulse-red 2s infinite;
}
@keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 20px rgba(34,197,94,0.5); }
    50% { box-shadow: 0 0 40px rgba(34,197,94,0.8); }
}
@keyframes pulse-red {
    0%, 100% { box-shadow: 0 0 20px rgba(239,68,68,0.5); }
    50% { box-shadow: 0 0 40px rgba(239,68,68,0.8); }
}
.spot-name { font-size: 2.5em; font-weight: bold; margin-bottom: 10px; }
.spot-icon { font-size: 4em; margin: 15px 0; }
.spot-status { font-size: 1.5em; font-weight: bold; text-transform: uppercase; }
.spot-details {
    font-size: 0.85em;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.3);
}
.timestamp {
    text-align: center;
    padding: 20px;
    background: rgba(0,0,0,0.2);
    border-radius: 10px;
    font-size: 1.1em;
    margin-bottom: 30px;
}
.camera-view {
    background: rgba(0,0,0,0.4);
    border-radius: 20px;
    padding: 30px;
    text-align: center;
}
.camera-view h2 { margin-bottom: 25px; font-size: 2.5em; }
.camera-view img {
    max-width: 100%;
    border-radius: 15px;
    box-shadow: 0 15px 50px rgba(0,0,0,0.5);
}
@media (max-width: 1200px) {
    .parking-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
    .parking-grid { grid-template-columns: 1fr; }
    h1 { font-size: 2.5em; }
}
</style>
</head>
<body>
<div class="container">
<header>
<h1>🚗 Smart Parking 8 Places</h1>
<p class="subtitle">Système de Gestion Intelligent avec Détection d'Obstacles</p>
</header>

<div class="stats">
<div class="stat-card">
<div class="stat-label">Places Totales</div>
<div class="stat-number" id="total">8</div>
</div>
<div class="stat-card" style="background: rgba(74,222,128,0.2);">
<div class="stat-label">Places Libres</div>
<div class="stat-number" id="libres" style="color: #4ade80;">0</div>
</div>
<div class="stat-card" style="background: rgba(248,113,113,0.2);">
<div class="stat-label">Places Occupées</div>
<div class="stat-number" id="occupees" style="color: #f87171;">0</div>
</div>
<div class="stat-card">
<div class="stat-label">Taux d'Occupation</div>
<div class="stat-number" id="taux">0%</div>
</div>
</div>

<div class="controls">
<button onclick="refreshData()">🔄 Actualiser Maintenant</button>
</div>

<div class="parking-3d">
<h2 style="text-align: center; margin-bottom: 30px; font-size: 2.5em;">
🅿️ Vue 3D du Parking (8 Places)
</h2>
<div class="parking-grid" id="parking-grid">
<!-- Les places seront générées ici -->
</div>
</div>

<div class="timestamp">
<span style="opacity: 0.8;">Dernière mise à jour: </span>
<span id="timestamp" style="font-weight: bold;">Jamais</span>
</div>

<div class="camera-view">
<h2>📹 Vue Caméra en Temps Réel</h2>
<img id="camera-image" src="/image/parking_annotated.jpg" 
     onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22800%22 height=%22600%22%3E%3Crect fill=%22%23333%22 width=%22800%22 height=%22600%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 fill=%22white%22 font-size=%2224%22%3EImage non disponible%3C/text%3E%3C/svg%3E'">
</div>
</div>

<script>
const API_URL = '/api/status';
const REFRESH_INTERVAL = 3000; // 3 secondes

let autoRefreshInterval;

function startAutoRefresh() {
    autoRefreshInterval = setInterval(refreshData, REFRESH_INTERVAL);
}

function stopAutoRefresh() {
    clearInterval(autoRefreshInterval);
}

async function refreshData() {
    try {
        const response = await fetch(API_URL);
        const data = await response.json();
        updateUI(data);
    } catch (error) {
        console.error('Erreur:', error);
    }
}

function updateUI(data) {
    // Stats
    document.getElementById('total').textContent = data.total || 8;
    document.getElementById('libres').textContent = data.available || 0;
    document.getElementById('occupees').textContent = data.occupied || 0;
    
    const taux = data.total > 0 ? Math.round((data.occupied / data.total) * 100) : 0;
    document.getElementById('taux').textContent = taux + '%';
    
    // Timestamp
    if (data.timestamp) {
        document.getElementById('timestamp').textContent = data.timestamp;
    }
    
    // Places de parking
    const grid = document.getElementById('parking-grid');
    grid.innerHTML = '';
    
    const places = data.places || {};
    const nomPlaces = Object.keys(places).sort();
    
    nomPlaces.forEach(nom => {
        const place = places[nom];
        const estOccupe = place.occupe;
        const details = place.details || {};
        
        const spotDiv = document.createElement('div');
        spotDiv.className = `parking-spot ${estOccupe ? 'occupe' : 'libre'}`;
        
        const icon = estOccupe ? '🚗' : '✅';
        const status = estOccupe ? 'OCCUPÉE' : 'LIBRE';
        const pourcentage = details.pourcentage_diff !== undefined ? 
            details.pourcentage_diff.toFixed(1) + '%' : 'N/A';
        const contours = details.contours || 0;
        
        spotDiv.innerHTML = `
            <div class="spot-name">${nom}</div>
            <div class="spot-icon">${icon}</div>
            <div class="spot-status">${status}</div>
            <div class="spot-details">
                <div>Différence: ${pourcentage}</div>
                <div>Contours détectés: ${contours}</div>
            </div>
        `;
        
        grid.appendChild(spotDiv);
    });
    
    // Rafraîchir image
    document.getElementById('camera-image').src = 
        '/image/parking_annotated.jpg?' + Date.now();
}

// Initialisation
window.addEventListener('load', () => {
    refreshData();
    startAutoRefresh();
});

// Pause auto-refresh quand page cachée
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopAutoRefresh();
    } else {
        startAutoRefresh();
    }
});
</script>
</body>
</html>'''
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def send_image(self, filename):
        if os.path.exists(filename):
            self.send_response(200)
            self.send_header('Content-type', 'image/jpeg')
            self.end_headers()
            with open(filename, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404)

def start_web():
    try:
        server = HTTPServer(('0.0.0.0', WEB_PORT), WebHandler)
        print(f"✓ Serveur web: http://localhost:{WEB_PORT}")
        print(f"  Accès réseau: http://{MQTT_BROKER}:{WEB_PORT}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except Exception as e:
        print(f"✗ Erreur serveur web: {e}")

# ═══════════════════════════════════════════════════════════════
# PROGRAMME PRINCIPAL
# ═══════════════════════════════════════════════════════════════

def main():
    global mqtt_client, image_reference
    
    print("\n" + "╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "  🚗 SMART PARKING - 8 PLACES - DÉTECTION OBSTACLES".center(78) + "║")
    print("║" + "  Version Finale - OpenCV + MQTT + Interface Web 3D".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")
    
    print(f"\n📋 Configuration:")
    print(f"   MQTT Broker:  {MQTT_BROKER}:{MQTT_PORT}")
    print(f"   ESP32-CAM:    http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    print(f"   Seuil détect: {SEUIL_OCCUPATION}%")
    print(f"   Places:       {NB_PLACES}")
    print(f"   Web Server:   http://localhost:{WEB_PORT}")
    print("="*80)
    
    # Connexion MQTT
    if MQTT_OK:
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            mqtt_client.on_connect = on_connect
            mqtt_client.on_message = on_message
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
        except Exception as e:
            print(f"⚠️  MQTT non disponible: {e}")
    else:
        print("⚠️  MQTT désactivé (paho-mqtt non installé)")
    
    # Démarrer serveur web
    start_web()
    
    print("\n✓ Serveur démarré avec succès !")
    print("\n╔════════════════════════════════════════════════════════════════╗")
    print("║  COMMANDES DISPONIBLES:                                        ║")
    print("╠════════════════════════════════════════════════════════════════╣")
    print("║  a  →  Analyser le parking maintenant                          ║")
    print("║  r  →  Capturer image de référence (parking VIDE)              ║")
    print("║  t  →  Test capture d'image                                    ║")
    print("║  s  →  Changer le seuil de détection                           ║")
    print("║  z  →  Afficher les zones configurées                          ║")
    print("║  w  →  Afficher l'URL de l'interface web                       ║")
    print("║  q  →  Quitter le serveur                                      ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    # Boucle interactive
    while True:
        try:
            commande = input("> ").strip().lower()
            
            if not commande:
                continue
            
            elif commande in ['q', 'quit', 'exit']:
                print("\n⏹  Arrêt du serveur...")
                break
            
            elif commande == 'a':
                analyser_parking()
            
            elif commande == 'r':
                print("\n📷 CAPTURE IMAGE DE RÉFÉRENCE")
                print("   Assurez-vous que TOUTES les 8 places sont VIDES !")
                confirm = input("   Continuer? (o/n): ").strip().lower()
                if confirm in ['o', 'oui', 'y', 'yes']:
                    img = capturer_image()
                    if img is not None:
                        image_reference = img.copy()
                        cv2.imwrite("reference_vide.jpg", img)
                        print("✓ Image de référence sauvegardée: reference_vide.jpg")
                else:
                    print("   Annulé")
            
            elif commande == 't':
                capturer_image()
            
            elif commande == 's':
                try:
                    valeur = float(input("   Nouveau seuil (0-100): "))
                    if 0 <= valeur <= 100:
                        globals()['SEUIL_OCCUPATION'] = valeur
                        print(f"✓ Seuil changé: {valeur}%")
                    else:
                        print("✗ Le seuil doit être entre 0 et 100")
                except ValueError:
                    print("✗ Valeur invalide")
            
            elif commande == 'z':
                print("\n📐 ZONES CONFIGURÉES (8 places):")
                print("="*80)
                for nom in sorted(zones_parking.keys()):
                    x, y, w, h = zones_parking[nom]
                    print(f"   {nom}: x={x:3}, y={y:3}, largeur={w:3}, hauteur={h:3}")
                print("="*80)
            
            elif commande == 'w':
                print(f"\n🌐 Interface Web 3D:")
                print(f"   http://localhost:{WEB_PORT}")
                print(f"   http://{MQTT_BROKER}:{WEB_PORT}")
            
            else:
                print(f"✗ Commande inconnue: '{commande}'")
                print("   Tapez 'a' pour analyser, 'q' pour quitter")
        
        except KeyboardInterrupt:
            print("\n\n⏹  Interruption détectée...")
            break
        except Exception as e:
            print(f"\n✗ Erreur: {e}")
    
    # Arrêt propre
    if mqtt_client and mqtt_connected:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("✓ Déconnecté du broker MQTT")
    
    print("\n👋 Au revoir !\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹  Programme interrompu\n")
    except Exception as e:
        print(f"\n✗ Erreur fatale: {e}\n")
        import traceback
        traceback.print_exc()