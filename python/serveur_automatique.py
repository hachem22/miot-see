#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
SMART PARKING - SERVEUR AUTOMATIQUE PC/RASPBERRY
Analyse toutes les 2 secondes
Détection obstacles OpenCV
Barrière automatique
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
import socket

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except:
    MQTT_OK = False
    print("⚠️  pip install paho-mqtt")

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Détection automatique IP (PC ou Raspberry)
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

MQTT_BROKER = get_local_ip()  # Auto-détecte IP locale
MQTT_PORT = 1883
ESP32_CAM_IP = "192.168.131.20"
ESP32_CAM_PORT = 81
WEB_PORT = 8888

# Paramètres détection
SEUIL_OCCUPATION = 25.0
MIN_CONTOUR_AREA = 800
NB_PLACES = 8
INTERVALLE_ANALYSE = 2  # secondes

# ═══════════════════════════════════════════════════════════════
# ZONES PARKING
# ═══════════════════════════════════════════════════════════════

zones_parking = {}

def charger_zones():
    global zones_parking
    try:
        with open("zones_parking.json", "r") as f:
            zones_parking = json.load(f)
        print(f"✓ {len(zones_parking)} zones chargées")
        return True
    except:
        print("✗ zones_parking.json introuvable")
        print("  Lancez: python calibration_8_places.py")
        return False

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
analyse_en_cours = False
doit_continuer = True

# ═══════════════════════════════════════════════════════════════
# MQTT
# ═══════════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        print("✓ MQTT Connecté")
        mqtt_connected = True
    else:
        print(f"✗ MQTT erreur: {rc}")

def mqtt_publish(topic, data):
    if mqtt_connected:
        try:
            mqtt_client.publish(topic, json.dumps(data), qos=1, retain=True)
        except Exception as e:
            print(f"✗ MQTT: {e}")

# ═══════════════════════════════════════════════════════════════
# CAPTURE IMAGE
# ═══════════════════════════════════════════════════════════════

def capturer_image():
    url = f"http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}/capture"
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'SmartParking/1.0')
        response = urllib.request.urlopen(req, timeout=5)
        
        with open("parking_current.jpg", "wb") as f:
            f.write(response.read())
        
        img = cv2.imread("parking_current.jpg")
        if img is None:
            return None
        
        return img
        
    except Exception as e:
        print(f"✗ Capture: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# DÉTECTION OBSTACLES
# ═══════════════════════════════════════════════════════════════

def analyser_zone(img_current, zone_coords, nom_place):
    global image_reference
    
    x, y, w, h = zone_coords
    zone_current = img_current[y:y+h, x:x+w]
    
    resultat = {
        'occupe': False,
        'pourcentage_diff': 0.0,
        'contours': 0,
        'aire': 0
    }
    
    if image_reference is not None:
        try:
            zone_ref = image_reference[y:y+h, x:x+w]
            
            gray_current = cv2.cvtColor(zone_current, cv2.COLOR_BGR2GRAY)
            gray_ref = cv2.cvtColor(zone_ref, cv2.COLOR_BGR2GRAY)
            
            diff = cv2.absdiff(gray_ref, gray_current)
            _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
            
            kernel = np.ones((5,5), np.uint8)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            
            pixels_diff = cv2.countNonZero(thresh)
            total_pixels = w * h
            pourcentage = (pixels_diff / total_pixels) * 100
            
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contours_valides = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]
            aire_totale = sum(cv2.contourArea(c) for c in contours_valides)
            
            resultat = {
                'occupe': pourcentage > SEUIL_OCCUPATION,
                'pourcentage_diff': pourcentage,
                'contours': len(contours_valides),
                'aire': int(aire_totale)
            }
            
        except Exception as e:
            print(f"✗ Zone {nom_place}: {e}")
    
    return resultat

# ═══════════════════════════════════════════════════════════════
# ANALYSE COMPLÈTE
# ═══════════════════════════════════════════════════════════════

def analyser_parking():
    global PARKING_DATA, analyse_en_cours
    
    if analyse_en_cours:
        return
    
    analyse_en_cours = True
    
    img = capturer_image()
    if img is None:
        analyse_en_cours = False
        return
    
    img_result = img.copy()
    resultats = {}
    
    for nom_place in sorted(zones_parking.keys()):
        zone_coords = zones_parking[nom_place]
        x, y, w, h = zone_coords
        
        analyse = analyser_zone(img, zone_coords, nom_place)
        est_occupe = analyse['occupe']
        
        resultats[nom_place] = {
            'occupe': est_occupe,
            'details': analyse
        }
        
        couleur = (0, 0, 255) if est_occupe else (0, 255, 0)
        cv2.rectangle(img_result, (x, y), (x+w, y+h), couleur, 3)
        
        texte_statut = "OCCUPEE" if est_occupe else "LIBRE"
        cv2.putText(img_result, f"{nom_place}", 
                   (x+10, y+25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, couleur, 2)
        cv2.putText(img_result, texte_statut, 
                   (x+10, y+50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, couleur, 2)
        cv2.putText(img_result, f"{analyse['pourcentage_diff']:.1f}%", 
                   (x+10, y+h-10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, couleur, 1)
    
    cv2.imwrite("parking_annotated.jpg", img_result)
    
    disponibles = sum(1 for p in resultats.values() if not p['occupe'])
    total = len(resultats)
    occupees = total - disponibles
    
    PARKING_DATA = {
        'places': resultats,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'total': total,
        'available': disponibles,
        'occupied': occupees
    }
    
    print(f"\r[{PARKING_DATA['timestamp']}] Libres: {disponibles}/{total} ", end="", flush=True)
    
    if mqtt_connected:
        status_msg = {
            'timestamp': PARKING_DATA['timestamp'],
            'total': total,
            'available': disponibles,
            'occupied': occupees,
            'places': {nom: p['occupe'] for nom, p in resultats.items()}
        }
        mqtt_publish("parking/status", status_msg)
        
        if disponibles > 0:
            mqtt_publish("parking/barrier/command", {
                "action": "open",
                "available": disponibles,
                "message": "BARRIERE OUVERTE"
            })
        else:
            mqtt_publish("parking/barrier/command", {
                "action": "stay_closed",
                "message": "PARKING COMPLET"
            })
    
    analyse_en_cours = False

# ═══════════════════════════════════════════════════════════════
# THREAD AUTOMATIQUE
# ═══════════════════════════════════════════════════════════════

def thread_analyse_automatique():
    global doit_continuer
    
    print(f"\n🔄 Analyse auto {INTERVALLE_ANALYSE}s")
    print("   Ctrl+C pour arrêter\n")
    
    while doit_continuer:
        analyser_parking()
        time.sleep(INTERVALLE_ANALYSE)

# ═══════════════════════════════════════════════════════════════
# WEB SERVER
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
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🚗 Smart Parking Auto</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;min-height:100vh}
.container{max-width:1600px;margin:0 auto;padding:20px}
header{text-align:center;padding:40px;background:rgba(0,0,0,.3);border-radius:20px;margin-bottom:30px;box-shadow:0 10px 40px rgba(0,0,0,.3)}
h1{font-size:3.5em;margin-bottom:10px;text-shadow:2px 2px 4px rgba(0,0,0,.5)}
.subtitle{font-size:1.3em;opacity:.9}
.badge{display:inline-block;background:#4ade80;color:#000;padding:10px 20px;border-radius:20px;font-weight:bold;margin-top:10px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px}
.stat-card{background:rgba(255,255,255,.1);backdrop-filter:blur(10px);border-radius:15px;padding:30px;text-align:center;transition:transform .3s;border:1px solid rgba(255,255,255,.2)}
.stat-card:hover{transform:translateY(-5px)}
.stat-number{font-size:3.5em;font-weight:bold;margin:10px 0}
.stat-label{font-size:1.1em;text-transform:uppercase;letter-spacing:2px}
.parking-3d{background:rgba(0,0,0,.4);border-radius:20px;padding:40px;margin-bottom:30px}
.parking-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:25px}
.parking-spot{background:linear-gradient(145deg,#2a2a2a,#1a1a1a);border-radius:15px;padding:25px;text-align:center;border:3px solid #444;transition:all .5s;min-height:200px;display:flex;flex-direction:column;justify-content:center}
.parking-spot.libre{background:linear-gradient(145deg,#4ade80,#22c55e);animation:pulse-green 2s infinite}
.parking-spot.occupe{background:linear-gradient(145deg,#f87171,#ef4444);animation:pulse-red 2s infinite}
@keyframes pulse-green{0%,100%{box-shadow:0 0 20px rgba(34,197,94,.5)}50%{box-shadow:0 0 40px rgba(34,197,94,.8)}}
@keyframes pulse-red{0%,100%{box-shadow:0 0 20px rgba(239,68,68,.5)}50%{box-shadow:0 0 40px rgba(239,68,68,.8)}}
.spot-name{font-size:2.5em;font-weight:bold;margin-bottom:10px}
.spot-icon{font-size:4em;margin:15px 0}
.spot-status{font-size:1.5em;font-weight:bold}
.spot-details{font-size:.85em;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.3)}
.timestamp{text-align:center;padding:20px;background:rgba(0,0,0,.2);border-radius:10px;margin-bottom:30px}
.camera-view{background:rgba(0,0,0,.4);border-radius:20px;padding:30px;text-align:center}
.camera-view h2{margin-bottom:25px;font-size:2.5em}
.camera-view img{max-width:100%;border-radius:15px;box-shadow:0 15px 50px rgba(0,0,0,.5)}
@media (max-width:1200px){.parking-grid{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="container">
<header>
<h1>🚗 Smart Parking Auto</h1>
<p class="subtitle">8 Places - Temps Réel</p>
<div class="badge">🔄 Auto 2s</div>
</header>
<div class="stats">
<div class="stat-card">
<div class="stat-label">Total</div>
<div class="stat-number" id="total">8</div>
</div>
<div class="stat-card" style="background:rgba(74,222,128,.2)">
<div class="stat-label">Libres</div>
<div class="stat-number" id="libres" style="color:#4ade80">0</div>
</div>
<div class="stat-card" style="background:rgba(248,113,113,.2)">
<div class="stat-label">Occupées</div>
<div class="stat-number" id="occupees" style="color:#f87171">0</div>
</div>
<div class="stat-card">
<div class="stat-label">Taux</div>
<div class="stat-number" id="taux">0%</div>
</div>
</div>
<div class="parking-3d">
<h2 style="text-align:center;margin-bottom:30px">🅿️ 8 Places</h2>
<div class="parking-grid" id="parking-grid"></div>
</div>
<div class="timestamp">
MàJ: <span id="timestamp">...</span>
</div>
<div class="camera-view">
<h2>📹 Caméra</h2>
<img id="camera-image" src="/image/parking_annotated.jpg">
</div>
</div>
<script>
setInterval(async()=>{
try{
const r=await fetch('/api/status');
const d=await r.json();
document.getElementById('total').textContent=d.total||8;
document.getElementById('libres').textContent=d.available||0;
document.getElementById('occupees').textContent=d.occupied||0;
document.getElementById('taux').textContent=Math.round((d.occupied/d.total)*100)+'%';
document.getElementById('timestamp').textContent=d.timestamp||'...';
const g=document.getElementById('parking-grid');
g.innerHTML='';
const p=d.places||{};
Object.keys(p).sort().forEach(nom=>{
const pl=p[nom];
const o=pl.occupe;
const dt=pl.details||{};
const div=document.createElement('div');
div.className='parking-spot '+(o?'occupe':'libre');
div.innerHTML=`<div class="spot-name">${nom}</div><div class="spot-icon">${o?'🚗':'✅'}</div><div class="spot-status">${o?'OCCUPÉE':'LIBRE'}</div><div class="spot-details">Diff: ${(dt.pourcentage_diff||0).toFixed(1)}%<br>Contours: ${dt.contours||0}</div>`;
g.appendChild(div);
});
document.getElementById('camera-image').src='/image/parking_annotated.jpg?'+Date.now();
}catch(e){}
},2000);
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
        print(f"✓ Web: http://localhost:{WEB_PORT}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except Exception as e:
        print(f"✗ Web: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global mqtt_client, image_reference
    
    print("\n" + "╔" + "="*68 + "╗")
    print("║" + " "*68 + "║")
    print("║" + "  🚗 SMART PARKING AUTO - 8 PLACES".center(68) + "║")
    print("║" + "  PC ou Raspberry Pi".center(68) + "║")
    print("║" + " "*68 + "║")
    print("╚" + "="*68 + "╝")
    
    if not charger_zones():
        return
    
    if os.path.exists("reference_vide.jpg"):
        image_reference = cv2.imread("reference_vide.jpg")
        if image_reference is not None:
            print("✓ Référence chargée")
        else:
            print("⚠️  Référence invalide")
    else:
        print("⚠️  Pas de référence")
        print("   Créez reference_vide.jpg (parking vide)")
    
    print(f"\n📋 Config:")
    print(f"   IP:        {MQTT_BROKER}")
    print(f"   MQTT:      {MQTT_BROKER}:{MQTT_PORT}")
    print(f"   ESP32-CAM: http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    print(f"   Web:       http://localhost:{WEB_PORT}")
    print("="*70)
    
    if MQTT_OK:
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            mqtt_client.on_connect = on_connect
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
        except Exception as e:
            print(f"⚠️  MQTT: {e}")
    
    start_web()
    
    print("\n✓ Serveur démarré !")
    
    thread_analyse = threading.Thread(target=thread_analyse_automatique, daemon=True)
    thread_analyse.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹  Arrêt...")
        doit_continuer = False
        if mqtt_client and mqtt_connected:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
    
    print("\n👋 Au revoir !\n")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ Erreur: {e}\n")