#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
SMART PARKING COMPLET - VÉRIFICATION PAIEMENT + NOTIFICATION PARKING FULL
Serveur unifié avec monitoring transactions Supabase
Version: 2.0 - Ajout notification parking complet vers ESP32/Mega
═══════════════════════════════════════════════════════════════
"""

import cv2
import numpy as np
import json
import urllib.request
import os
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import socket
import paho.mqtt.client as mqtt
from supabase import create_client, Client

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION SUPABASE
# ═══════════════════════════════════════════════════════════════

SUPABASE_URL = "https://hdxmsbldntwqkdlhicyw.supabase.co"
SUPABASE_KEY = "sb_publishable_IbbrwBTGthThypb6sxi8rA_Bw7J6Jj1"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION MQTT
# ═══════════════════════════════════════════════════════════════

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
UNIQUE_ID = "hachem_smartparking_2026"

# Topics MQTT
TOPIC_RFID = f"{UNIQUE_ID}/parking/rfid_card"
TOPIC_QR = f"{UNIQUE_ID}/parking/access_code"
TOPIC_STATUS = f"{UNIQUE_ID}/parking/status"
TOPIC_BARRIER = f"{UNIQUE_ID}/parking/barrier/command"
TOPIC_RFID_RESPONSE = f"{UNIQUE_ID}/parking/rfid_response"
TOPIC_QR_RESPONSE = f"{UNIQUE_ID}/parking/qr_response"
TOPIC_PARKING_FULL = f"{UNIQUE_ID}/parking/full_notification"  # ← NOUVEAU TOPIC

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION DÉTECTION
# ═══════════════════════════════════════════════════════════════

ESP32_CAM_IP = "192.168.7.20"
ESP32_CAM_PORT = 81
WEB_PORT = 8888

SEUIL_OCCUPATION = 25.0
MIN_CONTOUR_AREA = 800
NB_PLACES = 8
INTERVALLE_ANALYSE = 2

# Paramètres monitoring paiement
TIMEOUT_PAIEMENT = 300  # 5 minutes max pour payer
CHECK_INTERVAL_PAYMENT = 3  # Vérifier toutes les 3 secondes

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

zones_parking = {}
image_reference = None
mqtt_client = None
mqtt_connected = False
analyse_en_cours = False
doit_continuer = True

# Dictionnaire pour tracer les codes QR en attente
pending_qr_codes = {}  # {code: {'timestamp': datetime, 'thread': Thread}}

# Variable pour éviter spam notifications
last_parking_full_notification = 0
PARKING_FULL_NOTIFICATION_COOLDOWN = 30  # 30 secondes entre notifications

# ═══════════════════════════════════════════════════════════════
# FONCTIONS SUPABASE - RFID
# ═══════════════════════════════════════════════════════════════

def verify_rfid_card(card_uid):
    """Vérifier carte RFID dans Supabase"""
    try:
        response = supabase.table("rfid_cards")\
            .select("*")\
            .eq("card_uid", card_uid)\
            .execute()
        
        if response.data and len(response.data) > 0:
            card = response.data[0]
            is_active = card.get('is_active', False)
            owner_name = card.get('owner_name', 'Unknown')
            
            print(f"\n{'='*60}")
            print(f"📇 RFID: {card_uid}")
            print(f"   Propriétaire: {owner_name}")
            print(f"   Active: {is_active}")
            
            if is_active:
                print(f"✅ ACCÈS AUTORISÉ")
                log_access_attempt(card_uid, "rfid", "granted", owner_name)
                print(f"{'='*60}\n")
                return {
                    "status": "granted", 
                    "owner": owner_name, 
                    "valid": True,
                    "card_uid": card_uid
                }
            else:
                print(f"❌ ACCÈS REFUSÉ (Carte inactive)")
                log_access_attempt(card_uid, "rfid", "denied_inactive", owner_name)
                print(f"{'='*60}\n")
                return {
                    "status": "denied", 
                    "reason": "inactive", 
                    "valid": False
                }
        else:
            print(f"\n{'='*60}")
            print(f"📇 RFID: {card_uid}")
            print(f"❌ ACCÈS REFUSÉ (Carte inconnue)")
            log_access_attempt(card_uid, "rfid", "denied_unknown", None)
            print(f"{'='*60}\n")
            return {
                "status": "denied", 
                "reason": "not_found", 
                "valid": False
            }
            
    except Exception as e:
        print(f"✗ Erreur RFID: {e}")
        return {
            "status": "error", 
            "message": str(e), 
            "valid": False
        }

def log_access_attempt(identifier, access_type, status, owner_name=None):
    """Logger les tentatives d'accès"""
    try:
        data = {
            "identifier": identifier,
            "access_type": access_type,
            "status": status,
            "owner_name": owner_name,
            "timestamp": datetime.utcnow().isoformat()
        }
        supabase.table("access_logs").insert(data).execute()
        print(f"📝 Accès loggé: {access_type} - {status}")
    except Exception as e:
        print(f"✗ Erreur log: {e}")

# ═══════════════════════════════════════════════════════════════
# FONCTIONS SUPABASE - QR CODE AVEC MONITORING PAIEMENT
# ═══════════════════════════════════════════════════════════════

def insert_access_code_to_supabase(access_code):
    """Insérer nouveau QR code"""
    try:
        data = {
            "access_code": access_code,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active"
        }
        supabase.table("access_codes").insert(data).execute()
        print(f"✓ QR {access_code} inséré dans Supabase")
        return True
    except Exception as e:
        print(f"✗ Erreur insertion QR: {e}")
        return False

def check_payment_for_qr(access_code):
    """Vérifier si un paiement existe pour ce QR code"""
    try:
        response = supabase.table("transactions")\
            .select("*")\
            .eq("access_code", access_code)\
            .eq("status", "completed")\
            .execute()
        
        if response.data and len(response.data) > 0:
            transaction = response.data[0]
            return {
                "paid": True,
                "transaction": transaction
            }
        else:
            return {"paid": False}
            
    except Exception as e:
        print(f"✗ Erreur vérification paiement: {e}")
        return {"paid": False, "error": str(e)}

def monitor_payment_realtime(access_code):
    """
    Monitorer en temps réel le paiement d'un QR code
    Cette fonction tourne dans un thread séparé
    """
    print(f"\n🔍 MONITORING PAIEMENT: {access_code}")
    print(f"   Timeout: {TIMEOUT_PAIEMENT}s ({TIMEOUT_PAIEMENT//60} minutes)")
    
    start_time = datetime.utcnow()
    check_count = 0
    
    while True:
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        # Timeout atteint
        if elapsed > TIMEOUT_PAIEMENT:
            print(f"\n⏱️  TIMEOUT: QR {access_code}")
            print(f"   Aucun paiement reçu en {TIMEOUT_PAIEMENT//60} minutes")
            
            # Marquer comme expiré
            try:
                supabase.table("access_codes")\
                    .update({"status": "expired"})\
                    .eq("access_code", access_code)\
                    .execute()
                print(f"🗑️  QR {access_code} marqué comme expiré")
            except Exception as e:
                print(f"✗ Erreur expiration: {e}")
            
            # Retirer de la liste d'attente
            if access_code in pending_qr_codes:
                del pending_qr_codes[access_code]
            
            break
        
        # Vérifier le paiement
        check_count += 1
        result = check_payment_for_qr(access_code)
        
        if result.get("paid"):
            transaction = result.get("transaction")
            
            print(f"\n{'='*60}")
            print(f"💰 PAIEMENT REÇU !")
            print(f"{'='*60}")
            print(f"   QR Code: {access_code}")
            print(f"   Transaction ID: {transaction.get('id')}")
            print(f"   User ID: {transaction.get('user_id')}")
            print(f"   Montant: {transaction.get('amount')} TND")
            print(f"   Type: {transaction.get('transaction_type')}")
            print(f"   Timestamp: {transaction.get('timestamp')}")
            print(f"   Temps écoulé: {elapsed:.0f}s")
            print(f"{'='*60}\n")
            
            # Marquer comme payé
            try:
                supabase.table("access_codes")\
                    .update({"status": "paid"})\
                    .eq("access_code", access_code)\
                    .execute()
                print(f"✅ QR {access_code} marqué comme PAYÉ")
            except Exception as e:
                print(f"✗ Erreur update: {e}")
            
            # Logger l'accès
            log_access_attempt(
                access_code, 
                "qr", 
                "paid_waiting_scan", 
                transaction.get('user_id')
            )
            
            # Retirer de la liste d'attente
            if access_code in pending_qr_codes:
                del pending_qr_codes[access_code]
            
            # Notification MQTT (optionnel)
            if mqtt_connected:
                notification = {
                    "code": access_code,
                    "status": "paid",
                    "message": "Paiement reçu ! Scannez le QR pour accéder."
                }
                mqtt_client.publish(TOPIC_QR_RESPONSE, json.dumps(notification))
            
            break
        
        # Afficher progression toutes les 10 vérifications
        if check_count % 10 == 0:
            remaining = TIMEOUT_PAIEMENT - elapsed
            print(f"⏳ QR {access_code}: En attente... ({remaining:.0f}s restant)")
        
        # Attendre avant prochaine vérification
        time.sleep(CHECK_INTERVAL_PAYMENT)

def verify_qr_code_for_access(access_code):
    """
    Vérifier QR code lors du scan pour accès
    (après que l'utilisateur ait potentiellement payé)
    """
    try:
        # Vérifier dans access_codes
        response = supabase.table("access_codes")\
            .select("*")\
            .eq("access_code", access_code)\
            .execute()
        
        if not response.data or len(response.data) == 0:
            print(f"\n{'='*60}")
            print(f"🔢 QR Code: {access_code}")
            print(f"❌ ACCÈS REFUSÉ (Code invalide ou expiré)")
            print(f"{'='*60}\n")
            
            log_access_attempt(access_code, "qr", "denied_invalid", None)
            return {
                "status": "denied", 
                "reason": "invalid", 
                "valid": False
            }
        
        code_data = response.data[0]
        code_status = code_data.get("status")
        
        # Vérifier le statut
        if code_status == "used":
            print(f"\n{'='*60}")
            print(f"🔢 QR Code: {access_code}")
            print(f"❌ ACCÈS REFUSÉ (Code déjà utilisé)")
            print(f"{'='*60}\n")
            
            log_access_attempt(access_code, "qr", "denied_already_used", None)
            return {
                "status": "denied", 
                "reason": "already_used", 
                "valid": False
            }
        
        if code_status == "expired":
            print(f"\n{'='*60}")
            print(f"🔢 QR Code: {access_code}")
            print(f"❌ ACCÈS REFUSÉ (Code expiré)")
            print(f"{'='*60}\n")
            
            log_access_attempt(access_code, "qr", "denied_expired", None)
            return {
                "status": "denied", 
                "reason": "expired", 
                "valid": False
            }
        
        # Vérifier transaction
        tx_response = supabase.table("transactions")\
            .select("*")\
            .eq("access_code", access_code)\
            .eq("status", "completed")\
            .execute()
        
        if tx_response.data and len(tx_response.data) > 0:
            transaction = tx_response.data[0]
            
            print(f"\n{'='*60}")
            print(f"🔢 QR Code: {access_code}")
            print(f"✅ PAYÉ - ACCÈS AUTORISÉ")
            print(f"   Transaction ID: {transaction.get('id')}")
            print(f"   User ID: {transaction.get('user_id')}")
            print(f"   Montant: {transaction.get('amount')} TND")
            print(f"{'='*60}\n")
            
            log_access_attempt(access_code, "qr", "granted_paid", transaction.get('user_id'))
            
            # Marquer comme utilisé
            supabase.table("access_codes")\
                .update({"status": "used", "used_at": datetime.utcnow().isoformat()})\
                .eq("access_code", access_code)\
                .execute()
            
            return {
                "status": "granted", 
                "paid": True, 
                "valid": True,
                "transaction": transaction,
                "user_id": transaction.get('user_id')
            }
        else:
            print(f"\n{'='*60}")
            print(f"🔢 QR Code: {access_code}")
            print(f"❌ ACCÈS REFUSÉ (Non payé)")
            
            # Vérifier si toujours en attente
            if code_status == "active":
                if access_code in pending_qr_codes:
                    remaining_time = TIMEOUT_PAIEMENT - (datetime.utcnow() - pending_qr_codes[access_code]['timestamp']).total_seconds()
                    print(f"⏳ Paiement en attente ({remaining_time:.0f}s restant)")
                else:
                    print(f"⏳ Paiement en attente")
            
            print(f"{'='*60}\n")
            
            log_access_attempt(access_code, "qr", "denied_unpaid", None)
            return {
                "status": "denied", 
                "reason": "unpaid", 
                "valid": False
            }
            
    except Exception as e:
        print(f"✗ Erreur QR: {e}")
        return {
            "status": "error", 
            "message": str(e), 
            "valid": False
        }

# ═══════════════════════════════════════════════════════════════
# NOUVELLE FONCTION: NOTIFICATION PARKING COMPLET
# ═══════════════════════════════════════════════════════════════

def notify_parking_full():
    """Envoyer notification parking complet vers ESP32"""
    global last_parking_full_notification
    
    current_time = time.time()
    
    # Vérifier cooldown pour éviter spam
    if current_time - last_parking_full_notification < PARKING_FULL_NOTIFICATION_COOLDOWN:
        return
    
    last_parking_full_notification = current_time
    
    if mqtt_connected:
        notification = {
            "status": "full",
            "available": 0,
            "total": PARKING_DATA['total'],
            "message": "PARKING COMPLET - Revenez plus tard",
            "timestamp": datetime.now().isoformat()
        }
        
        mqtt_client.publish(TOPIC_PARKING_FULL, json.dumps(notification))
        
        print(f"\n{'🔴'*30}")
        print(f"🚨 NOTIFICATION PARKING COMPLET ENVOYÉE")
        print(f"   ESP32 va afficher message sur Mega")
        print(f"   Places: {PARKING_DATA['available']}/{PARKING_DATA['total']}")
        print(f"{'🔴'*30}\n")

# ═══════════════════════════════════════════════════════════════
# THREAD AFFICHAGE CODES EN ATTENTE
# ═══════════════════════════════════════════════════════════════

def display_pending_codes_status():
    """Afficher périodiquement les codes QR en attente de paiement"""
    while doit_continuer:
        time.sleep(30)  # Toutes les 30 secondes
        
        if pending_qr_codes:
            print(f"\n{'─'*60}")
            print(f"📊 CODES QR EN ATTENTE DE PAIEMENT: {len(pending_qr_codes)}")
            print(f"{'─'*60}")
            
            for code, info in pending_qr_codes.items():
                elapsed = (datetime.utcnow() - info['timestamp']).total_seconds()
                remaining = TIMEOUT_PAIEMENT - elapsed
                
                if remaining > 0:
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    print(f"   🔢 {code}: {minutes}m {seconds}s restant")
                else:
                    print(f"   ⏱️  {code}: EXPIRÉ")
            
            print(f"{'─'*60}\n")

# ═══════════════════════════════════════════════════════════════
# MQTT CALLBACKS
# ═══════════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        print("✓ MQTT Connecté à HiveMQ")
        mqtt_connected = True
        
        client.subscribe(TOPIC_RFID)
        client.subscribe(TOPIC_QR)
        
        print(f"✓ Abonné à:")
        print(f"  - {TOPIC_RFID}")
        print(f"  - {TOPIC_QR}")
    else:
        print(f"✗ MQTT erreur: {rc}")

def on_message(client, userdata, msg):
    """Callback réception messages MQTT"""
    try:
        message = msg.payload.decode('utf-8').strip()
        topic = msg.topic
        
        # ============ RFID CARD ============
        if topic == TOPIC_RFID:
            print(f"\n📨 RFID reçu: {message}")
            
            result = verify_rfid_card(message)
            
            # Envoyer réponse ESP32
            client.publish(TOPIC_RFID_RESPONSE, json.dumps(result))
            
            # Si valide ET places disponibles → Ouvrir barrière
            if result.get('valid') and PARKING_DATA['available'] > 0:
                ouvrir_barriere("RFID", result.get('owner', 'Utilisateur'))
            elif result.get('valid') and PARKING_DATA['available'] == 0:
                refuser_acces("PARKING COMPLET")
                notify_parking_full()  # ← NOTIFICATION PARKING COMPLET
            else:
                refuser_acces("CARTE INVALIDE")
        
        # ============ QR CODE ============
        elif topic == TOPIC_QR:
            print(f"\n📨 QR Code reçu: {message}")
            
            # Distinguer: nouveau code généré VS scan code existant
            if message.isdigit() and len(message) == 6:
                # ═══════════════════════════════════════════════════
                # NOUVEAU CODE GÉNÉRÉ PAR ESP32
                # ═══════════════════════════════════════════════════
                
                # ✅ VÉRIFIER PLACES DISPONIBLES AVANT GÉNÉRATION
                if PARKING_DATA['available'] <= 0:
                    print(f"\n{'='*60}")
                    print(f"🔴 GÉNÉRATION QR REFUSÉE")
                    print(f"   Raison: PARKING COMPLET (0/{PARKING_DATA['total']})")
                    print(f"   QR Code: {message}")
                    print(f"{'='*60}\n")
                    
                    # Réponse ESP32 - REFUS
                    response = {
                        "status": "rejected",
                        "code": message,
                        "reason": "parking_full",
                        "available": 0,
                        "total": PARKING_DATA['total'],
                        "message": "PARKING COMPLET - Génération QR impossible"
                    }
                    client.publish(TOPIC_QR_RESPONSE, json.dumps(response))
                    
                    # 🚨 ENVOYER NOTIFICATION PARKING COMPLET
                    notify_parking_full()
                    
                    # Ne PAS insérer dans Supabase
                    # Ne PAS démarrer monitoring
                    return
                
                # ✅ PLACES DISPONIBLES - GÉNÉRER QR
                if insert_access_code_to_supabase(message):
                    # Ajouter à la liste d'attente
                    pending_qr_codes[message] = {
                        'timestamp': datetime.utcnow(),
                        'thread': None,
                        'places_at_generation': PARKING_DATA['available']
                    }
                    
                    # Démarrer monitoring paiement dans thread séparé
                    monitor_thread = threading.Thread(
                        target=monitor_payment_realtime, 
                        args=(message,),
                        daemon=True
                    )
                    monitor_thread.start()
                    pending_qr_codes[message]['thread'] = monitor_thread
                    
                    # Réponse ESP32 - SUCCÈS
                    response = {
                        "status": "received",
                        "code": message,
                        "available": PARKING_DATA['available'],
                        "total": PARKING_DATA['total'],
                        "message": f"QR {message} généré - {PARKING_DATA['available']} places disponibles"
                    }
                    client.publish(TOPIC_QR_RESPONSE, json.dumps(response))
                    
                    print(f"\n{'='*60}")
                    print(f"✅ QR CODE GÉNÉRÉ")
                    print(f"   Code: {message}")
                    print(f"   Places disponibles: {PARKING_DATA['available']}/{PARKING_DATA['total']}")
                    print(f"   Timeout paiement: {TIMEOUT_PAIEMENT//60} minutes")
                    print(f"{'='*60}\n")
                    
                    print(f"🔄 Monitoring démarré pour QR {message}")
                    print(f"📱 L'utilisateur a {TIMEOUT_PAIEMENT//60} minutes pour payer")
            
            else:
                # ═══════════════════════════════════════════════════
                # CODE SCANNÉ POUR ACCÈS
                # ═══════════════════════════════════════════════════
                result = verify_qr_code_for_access(message)
                
                client.publish(TOPIC_QR_RESPONSE, json.dumps(result))
                
                if result.get('valid') and PARKING_DATA['available'] > 0:
                    user_id = result.get('user_id', f'QR-{message}')
                    ouvrir_barriere("QR", user_id)
                elif result.get('valid') and PARKING_DATA['available'] == 0:
                    refuser_acces("PARKING COMPLET")
                    notify_parking_full()  # ← NOTIFICATION PARKING COMPLET
                else:
                    reason = result.get('reason', 'invalide')
                    if reason == "unpaid":
                        refuser_acces("PAIEMENT REQUIS")
                    elif reason == "expired":
                        refuser_acces("CODE EXPIRÉ")
                    elif reason == "already_used":
                        refuser_acces("CODE UTILISÉ")
                    else:
                        refuser_acces("CODE INVALIDE")
        
    except Exception as e:
        print(f"✗ Erreur message MQTT: {e}")

def ouvrir_barriere(methode, utilisateur):
    """Envoyer commande ouverture barrière"""
    if mqtt_connected:
        commande = {
            "action": "open",
            "method": methode,
            "user": utilisateur,
            "available": PARKING_DATA['available'],
            "message": f"BIENVENUE {utilisateur}"
        }
        mqtt_client.publish(TOPIC_BARRIER, json.dumps(commande))
        print(f"🟢 BARRIÈRE OUVERTE - {methode} - {utilisateur}")

def refuser_acces(raison):
    """Envoyer commande refus"""
    if mqtt_connected:
        commande = {
            "action": "stay_closed",
            "reason": raison,
            "message": raison
        }
        mqtt_client.publish(TOPIC_BARRIER, json.dumps(commande))
        print(f"🔴 ACCÈS REFUSÉ - {raison}")

# ═══════════════════════════════════════════════════════════════
# DÉTECTION PARKING (code existant maintenu)
# ═══════════════════════════════════════════════════════════════

def charger_zones():
    global zones_parking
    try:
        with open("zones_parking.json", "r") as f:
            zones_parking = json.load(f)
        print(f"✓ {len(zones_parking)} zones chargées")
        return True
    except:
        print("✗ zones_parking.json introuvable")
        return False

def capturer_image():
    url = f"http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}/capture"
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'SmartParking/1.0')
        response = urllib.request.urlopen(req, timeout=5)
        
        with open("parking_current.jpg", "wb") as f:
            f.write(response.read())
        
        img = cv2.imread("parking_current.jpg")
        return img
    except Exception as e:
        return None

def analyser_zone(img_current, zone_coords, nom_place):
    global image_reference
    
    x, y, w, h = zone_coords
    zone_current = img_current[y:y+h, x:x+w]
    
    resultat = {'occupe': False, 'pourcentage_diff': 0.0}
    
    if image_reference is not None:
        try:
            zone_ref = image_reference[y:y+h, x:x+w]
            
            gray_current = cv2.cvtColor(zone_current, cv2.COLOR_BGR2GRAY)
            gray_ref = cv2.cvtColor(zone_ref, cv2.COLOR_BGR2GRAY)
            
            diff = cv2.absdiff(gray_ref, gray_current)
            _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
            
            kernel = np.ones((5,5), np.uint8)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            pixels_diff = cv2.countNonZero(thresh)
            pourcentage = (pixels_diff / (w * h)) * 100
            
            resultat = {
                'occupe': pourcentage > SEUIL_OCCUPATION,
                'pourcentage_diff': pourcentage
            }
        except:
            pass
    
    return resultat

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
        
        resultats[nom_place] = {'occupe': est_occupe, 'details': analyse}
        
        couleur = (0, 0, 255) if est_occupe else (0, 255, 0)
        cv2.rectangle(img_result, (x, y), (x+w, y+h), couleur, 3)
        cv2.putText(img_result, f"{nom_place}", (x+10, y+25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, couleur, 2)
    
    cv2.imwrite("parking_annotated.jpg", img_result)
    
    disponibles = sum(1 for p in resultats.values() if not p['occupe'])
    
    # Détecter changement de statut (plein → non plein ou vice-versa)
    ancien_disponibles = PARKING_DATA['available']
    
    PARKING_DATA = {
        'places': resultats,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'total': len(resultats),
        'available': disponibles,
        'occupied': len(resultats) - disponibles
    }
    
    # 🚨 SI PARKING DEVIENT COMPLET → NOTIFIER
    if ancien_disponibles > 0 and disponibles == 0:
        print(f"\n{'⚠️'*30}")
        print(f"🚨 ALERTE: PARKING VIENT DE DEVENIR COMPLET")
        print(f"{'⚠️'*30}\n")
        notify_parking_full()
    
    print(f"\r[{PARKING_DATA['timestamp']}] Libres: {disponibles}/{len(resultats)} ", end="", flush=True)
    
    if mqtt_connected:
        status_msg = {
            'timestamp': PARKING_DATA['timestamp'],
            'total': PARKING_DATA['total'],
            'available': disponibles,
            'occupied': PARKING_DATA['occupied'],
            'places': {nom: p['occupe'] for nom, p in resultats.items()}
        }
        mqtt_client.publish(TOPIC_STATUS, json.dumps(status_msg))
    
    analyse_en_cours = False

def thread_analyse_automatique():
    global doit_continuer
    print(f"\n🔄 Analyse parking auto {INTERVALLE_ANALYSE}s\n")
    while doit_continuer:
        analyser_parking()
        time.sleep(INTERVALLE_ANALYSE)

# ═══════════════════════════════════════════════════════════════
# SERVEUR WEB (code existant maintenu)
# ═══════════════════════════════════════════════════════════════

class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Smart Parking Web Interface")
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(PARKING_DATA).encode())

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
    print("║  🚗 SMART PARKING V2 - NOTIFICATION PARKING COMPLET".center(70) + "║")
    print("╚" + "="*68 + "╝")
    
    if not charger_zones():
        print("⚠️  Lancez: python calibration_8_places.py")
    
    if os.path.exists("reference_vide.jpg"):
        image_reference = cv2.imread("reference_vide.jpg")
        print("✓ Référence parking chargée")
    
    print(f"\n📋 Configuration:")
    print(f"   MQTT: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"   ESP32-CAM: http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    print(f"   Web: http://localhost:{WEB_PORT}")
    print(f"   Supabase: Connecté")
    print(f"   Timeout paiement: {TIMEOUT_PAIEMENT//60} minutes")
    print(f"   Check interval: {CHECK_INTERVAL_PAYMENT}s")
    print(f"   🆕 Notification parking complet: ACTIVÉE")
    print("="*70)
    
    # MQTT
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"✗ MQTT: {e}")
    
    # Web
    start_web()
    
    # Thread affichage codes en attente
    status_thread = threading.Thread(target=display_pending_codes_status, daemon=True)
    status_thread.start()
    
    print("\n✓ Serveur démarré !")
    print("📱 Les QR codes générés seront monitorés automatiquement")
    print("🚨 Notification PARKING COMPLET activée\n")
    
    # Analyse parking auto
    if zones_parking:
        thread_analyse = threading.Thread(target=thread_analyse_automatique, daemon=True)
        thread_analyse.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹  Arrêt...")
        doit_continuer = False
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
    
    print("\n👋 Au revoir !\n")

if __name__ == "__main__":
    main()
