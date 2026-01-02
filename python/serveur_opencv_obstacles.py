

import cv2
import numpy as np
import json
import urllib.request
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except:
    print("⚠️ paho-mqtt non installé")
    MQTT_OK = False

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

MQTT_BROKER = "192.168.1.18"
MQTT_PORT = 1883
ESP32_CAM_IP = "192.168.1.32"
ESP32_CAM_PORT = 81
SEUIL_OCCUPATION = 30.0
MIN_CONTOUR_AREA = 1000
WEB_PORT = 8888  # ← CHANGÉ DE 8080 À 8888

# ═══════════════════════════════════════════════════════════════
# DONNÉES GLOBALES
# ═══════════════════════════════════════════════════════════════

PARKING_DATA = {
    'places': {},
    'timestamp': None,
    'total': 4,
    'available': 0,
    'occupied': 0
}

zones_parking = {
    "P1": [50, 50, 150, 100],
    "P2": [220, 50, 150, 100],
    "P3": [390, 50, 150, 100],
    "P4": [560, 50, 150, 100]
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
        print(f"✗ Erreur MQTT: {rc}")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        print(f"\n📨 MQTT: {data}")
        
        if msg.topic == "parking/sensor/vehicle" and data.get("detected"):
            print(f"🚗 VÉHICULE ! Distance: {data.get('distance_cm')}cm")
            analyser_parking()
    except:
        pass

def mqtt_publish(topic, data):
    if mqtt_connected:
        mqtt_client.publish(topic, json.dumps(data), qos=1, retain=True)

# ═══════════════════════════════════════════════════════════════
# CAPTURE
# ═══════════════════════════════════════════════════════════════

def capturer_image():
    url = f"http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}/capture"
    try:
        print(f"📷 {url}")
        urllib.request.urlretrieve(url, "parking_current.jpg")
        img = cv2.imread("parking_current.jpg")
        if img is None:
            print("✗ Image invalide")
            return None
        print(f"✓ {img.shape[1]}x{img.shape[0]} px")
        return img
    except Exception as e:
        print(f"✗ Erreur: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# DÉTECTION
# ═══════════════════════════════════════════════════════════════

def analyser_zone(img_current, zone, nom):
    global image_reference
    x, y, w, h = zone
    zone_current = img_current[y:y+h, x:x+w]
    
    resultat = {'occupe': False, 'pourcentage_diff': 0.0, 'contours': 0, 'aire': 0}
    
    if image_reference is not None:
        zone_ref = image_reference[y:y+h, x:x+w]
        gray_current = cv2.cvtColor(zone_current, cv2.COLOR_BGR2GRAY)
        gray_ref = cv2.cvtColor(zone_ref, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_ref, gray_current)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        kernel = np.ones((5,5), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        pixels_diff = cv2.countNonZero(thresh)
        pourcentage = (pixels_diff / (w * h)) * 100
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours_valides = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]
        aire = sum(cv2.contourArea(c) for c in contours_valides)
        resultat = {
            'occupe': pourcentage > SEUIL_OCCUPATION,
            'pourcentage_diff': pourcentage,
            'contours': len(contours_valides),
            'aire': int(aire)
        }
    else:
        gray = cv2.cvtColor(zone_current, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours_valides = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]
        aire = sum(cv2.contourArea(c) for c in contours_valides)
        seuil_aire = (w * h) * 0.20
        resultat = {
            'occupe': aire > seuil_aire,
            'pourcentage_diff': (aire / (w * h)) * 100,
            'contours': len(contours_valides),
            'aire': int(aire)
        }
    
    return resultat

def analyser_parking():
    global PARKING_DATA
    
    img = capturer_image()
    if img is None:
        return
    
    img_result = img.copy()
    resultats = {}
    
    print("\n" + "="*70)
    print("📊 ANALYSE")
    print("="*70)
    
    for nom, zone in zones_parking.items():
        x, y, w, h = zone
        analyse = analyser_zone(img, zone, nom)
        occupe = analyse['occupe']
        resultats[nom] = {'occupe': occupe, 'details': analyse}
        
        couleur = (0, 0, 255) if occupe else (0, 255, 0)
        cv2.rectangle(img_result, (x, y), (x+w, y+h), couleur, 3)
        texte = "OCCUPEE" if occupe else "LIBRE"
        cv2.putText(img_result, f"{nom}: {texte}", (x+10, y+30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, couleur, 2)
        cv2.putText(img_result, f"{analyse['pourcentage_diff']:.1f}%", 
                   (x+10, y+h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, couleur, 2)
        
        statut = "OCCUPÉE ✗" if occupe else "LIBRE ✓"
        print(f"   {nom}: {statut:12} | Diff: {analyse['pourcentage_diff']:5.1f}% | "
              f"Contours: {analyse['contours']:2} | Aire: {analyse['aire']:6}")
    
    cv2.imwrite("parking_annotated.jpg", img_result)
    
    disponibles = sum(1 for p in resultats.values() if not p['occupe'])
    total = len(resultats)
    occupees = total - disponibles
    
    print("="*70)
    print(f"📊 RÉSULTAT: {disponibles}/{total} libres")
    print("="*70)
    
    PARKING_DATA = {
        'places': resultats,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'total': total,
        'available': disponibles,
        'occupied': occupees
    }
    
    if mqtt_connected:
        mqtt_publish("parking/status", {
            'timestamp': PARKING_DATA['timestamp'],
            'total': total,
            'available': disponibles,
            'occupied': occupees,
            'places': {n: p['occupe'] for n, p in resultats.items()}
        })
        
        if disponibles > 0:
            print(f"🟢 BARRIÈRE OUVERTE ({disponibles})")
            mqtt_publish("parking/barrier/command", {"action": "open", "available": disponibles})
        else:
            print("🔴 BARRIÈRE FERMÉE")
            mqtt_publish("parking/barrier/command", {"action": "stay_closed"})

# ═══════════════════════════════════════════════════════════════
# WEB
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
<title>🚗 Smart Parking 3D</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff}
.container{max-width:1400px;margin:0 auto;padding:20px}
header{text-align:center;padding:30px;background:rgba(0,0,0,.3);border-radius:15px;margin-bottom:30px}
h1{font-size:3em;margin-bottom:10px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:30px}
.stat-card{background:rgba(255,255,255,.1);border-radius:15px;padding:25px;text-align:center}
.stat-number{font-size:3em;font-weight:bold;margin:10px 0}
.stat-label{font-size:1.1em;text-transform:uppercase}
.parking-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:30px;margin:30px 0}
.parking-spot{background:linear-gradient(145deg,#2a2a2a,#1a1a1a);border-radius:15px;padding:30px;text-align:center;border:3px solid #444}
.parking-spot.libre{background:linear-gradient(145deg,#4ade80,#22c55e);animation:pulse-green 2s infinite}
.parking-spot.occupe{background:linear-gradient(145deg,#f87171,#ef4444);animation:pulse-red 2s infinite}
@keyframes pulse-green{0%,100%{box-shadow:0 0 20px rgba(34,197,94,.5)}50%{box-shadow:0 0 40px rgba(34,197,94,.8)}}
@keyframes pulse-red{0%,100%{box-shadow:0 0 20px rgba(239,68,68,.5)}50%{box-shadow:0 0 40px rgba(239,68,68,.8)}}
.spot-name{font-size:3em;font-weight:bold;margin-bottom:15px}
.spot-icon{font-size:5em;margin:20px 0}
.spot-status{font-size:1.8em;font-weight:bold}
.spot-details{font-size:.9em;margin-top:15px;padding-top:15px;border-top:1px solid rgba(255,255,255,.3)}
button{background:linear-gradient(145deg,#3b82f6,#2563eb);color:#fff;border:none;padding:15px 40px;font-size:1.1em;border-radius:10px;cursor:pointer;margin:10px}
button:hover{transform:translateY(-2px)}
.camera-view{background:rgba(0,0,0,.4);border-radius:15px;padding:20px;text-align:center;margin-top:30px}
.camera-view img{max-width:100%;border-radius:10px}
</style>
</head>
<body>
<div class="container">
<header>
<h1>🚗 Smart Parking 3D</h1>
<p>Système Intelligent - Temps Réel</p>
</header>
<div class="stats">
<div class="stat-card"><div class="stat-label">Total</div><div class="stat-number" id="total">4</div></div>
<div class="stat-card" style="background:rgba(74,222,128,.2)"><div class="stat-label">Libres</div><div class="stat-number" id="libres" style="color:#4ade80">0</div></div>
<div class="stat-card" style="background:rgba(248,113,113,.2)"><div class="stat-label">Occupées</div><div class="stat-number" id="occupees" style="color:#f87171">0</div></div>
<div class="stat-card"><div class="stat-label">Taux</div><div class="stat-number" id="taux">0%</div></div>
</div>
<div style="text-align:center"><button onclick="refreshData()">🔄 Actualiser</button></div>
<div class="parking-grid" id="parking-grid"></div>
<div style="text-align:center;padding:15px;background:rgba(0,0,0,.2);border-radius:10px">
Dernière MàJ: <span id="timestamp">Jamais</span>
</div>
<div class="camera-view">
<h2>📹 Vue Caméra</h2>
<img id="camera-image" src="/image/parking_annotated.jpg">
</div>
</div>
<script>
const API='/api/status';
setInterval(refreshData,3000);
async function refreshData(){
try{
const r=await fetch(API);
const d=await r.json();
document.getElementById('total').textContent=d.total||4;
document.getElementById('libres').textContent=d.available||0;
document.getElementById('occupees').textContent=d.occupied||0;
document.getElementById('taux').textContent=Math.round((d.occupied/d.total)*100)+'%';
document.getElementById('timestamp').textContent=d.timestamp||'Jamais';
const g=document.getElementById('parking-grid');
g.innerHTML='';
const p=d.places||{};
Object.keys(p).sort().forEach(nom=>{
const pl=p[nom];
const o=pl.occupe;
const dt=pl.details||{};
const div=document.createElement('div');
div.className='parking-spot '+(o?'occupe':'libre');
div.innerHTML=`
<div class="spot-name">${nom}</div>
<div class="spot-icon">${o?'🚗':'✅'}</div>
<div class="spot-status">${o?'OCCUPÉE':'LIBRE'}</div>
<div class="spot-details">
Diff: ${(dt.pourcentage_diff||0).toFixed(1)}%<br>
Contours: ${dt.contours||0}
</div>
`;
g.appendChild(div);
});
document.getElementById('camera-image').src='/image/parking_annotated.jpg?'+Date.now();
}catch(e){console.error(e)}
}
window.addEventListener('load',refreshData);
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
        print(f"✗ Erreur web: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global mqtt_client, image_reference
    
    print("\n" + "="*70)
    print("  🚗 SMART PARKING - PC WINDOWS")
    print("="*70)
    print(f"\nConfig:")
    print(f"  MQTT:      {MQTT_BROKER}:{MQTT_PORT}")
    print(f"  ESP32-CAM: http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    print(f"  Seuil:     {SEUIL_OCCUPATION}%")
    print(f"  Web:       http://localhost:{WEB_PORT}")
    print("="*70)
    
    if MQTT_OK:
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            mqtt_client.on_connect = on_connect
            mqtt_client.on_message = on_message
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
        except Exception as e:
            print(f"⚠️ MQTT erreur: {e}")
    
    start_web()
    
    print("\n✓ Serveur démarré !")
    print("\nCommandes:")
    print("  a = analyser")
    print("  r = référence")
    print("  t = test capture")
    print("  s = seuil")
    print("  q = quitter\n")
    
    while True:
        try:
            cmd = input("> ").strip().lower()
            if cmd == 'q':
                break
            elif cmd == 'a':
                analyser_parking()
            elif cmd == 'r':
                print("\n📷 Référence (parking VIDE)")
                if input("OK? (o/n): ").lower() == 'o':
                    img = capturer_image()
                    if img is not None:
                        image_reference = img.copy()
                        cv2.imwrite("reference_vide.jpg", img)
                        print("✓ Sauvegardée")
            elif cmd == 't':
                capturer_image()
            elif cmd == 's':
                try:
                    v = float(input("Seuil (0-100): "))
                    if 0 <= v <= 100:
                        globals()['SEUIL_OCCUPATION'] = v
                        print(f"✓ {v}%")
                except:
                    print("✗ Invalide")
        except KeyboardInterrupt:
            break
    
    print("\n👋 Au revoir !\n")

if __name__ == "__main__":
    main()