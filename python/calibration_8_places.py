
import cv2
import json
import urllib.request
import sys
import os

# Configuration
ESP32_CAM_IP = "192.168.131.20"
ESP32_CAM_PORT = 81

zones = {}
drawing = False
start_point = None
current_place = 1
img = None
img_copy = None

def mouse_callback(event, x, y, flags, param):
    global drawing, start_point, img_copy, current_place, zones, img
    
    if current_place > 8:
        return
    
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        start_point = (x, y)
        print(f"\n🖱️  Coin 1 de P{current_place}: ({x}, {y})")
    
    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            img_copy = img.copy()
            
            # Dessiner zones terminées
            for nom, (zx, zy, zw, zh) in zones.items():
                cv2.rectangle(img_copy, (zx, zy), (zx+zw, zy+zh), (0, 255, 0), 2)
                cv2.putText(img_copy, nom, (zx+10, zy+30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            # Rectangle en cours
            cv2.rectangle(img_copy, start_point, (x, y), (0, 255, 255), 2)
            cv2.putText(img_copy, f"P{current_place}", 
                       (start_point[0]+10, start_point[1]+30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            
            cv2.imshow("Calibration 8 Places", img_copy)
    
    elif event == cv2.EVENT_LBUTTONUP:
        if drawing:
            drawing = False
            end_point = (x, y)
            print(f"🖱️  Coin 2 de P{current_place}: ({x}, {y})")
            
            x_min = min(start_point[0], end_point[0])
            y_min = min(start_point[1], end_point[1])
            largeur = abs(end_point[0] - start_point[0])
            hauteur = abs(end_point[1] - start_point[1])
            
            if largeur < 30 or hauteur < 30:
                print("⚠️  Zone trop petite ! Minimum 30x30 pixels")
                print(f"   Recommencez P{current_place}")
                return
            
            nom_place = f"P{current_place}"
            zones[nom_place] = [x_min, y_min, largeur, hauteur]
            
            print(f"✓ {nom_place}: x={x_min}, y={y_min}, w={largeur}, h={hauteur}")
            
            # Redessiner avec nouvelle zone
            img_copy = img.copy()
            for nom, (zx, zy, zw, zh) in zones.items():
                cv2.rectangle(img_copy, (zx, zy), (zx+zw, zy+zh), (0, 255, 0), 2)
                cv2.putText(img_copy, nom, (zx+10, zy+30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            cv2.imshow("Calibration 8 Places", img_copy)
            
            current_place += 1
            
            if current_place <= 8:
                print(f"\n📍 Dessinez P{current_place}")
            else:
                print("\n✅ 8 PLACES DÉFINIES !")
                print("Appuyez sur une touche pour sauvegarder...")

def capturer_image():
    url = f"http://{ESP32_CAM_IP}:{ESP32_CAM_PORT}/capture"
    try:
        print(f"📷 Capture: {url}")
        urllib.request.urlretrieve(url, "calibration.jpg")
        img = cv2.imread("calibration.jpg")
        if img is None:
            print("✗ Image invalide")
            return None
        print(f"✓ Image: {img.shape[1]}x{img.shape[0]} px")
        return img
    except Exception as e:
        print(f"✗ Erreur: {e}")
        return None

def main():
    global img, img_copy
    
    print("\n" + "="*70)
    print("  🎯 CALIBRATION 8 PLACES")
    print("="*70)
    
    # Capture
    img = capturer_image()
    if img is None:
        print("\n✗ Impossible de capturer l'image")
        sys.exit(1)
    
    img_copy = img.copy()
    
    print("\n📋 INSTRUCTIONS:")
    print("="*70)
    print("1. Cliquez et glissez pour dessiner chaque place")
    print("2. Ordre: P1→P2→P3→P4 (haut), P5→P6→P7→P8 (bas)")
    print("3. ESC = Annuler")
    print("4. Après P8, appuyez sur touche pour sauvegarder")
    print("="*70)
    print(f"\n📍 Dessinez P1")
    
    # Créer fenêtre
    cv2.namedWindow("Calibration 8 Places")
    cv2.setMouseCallback("Calibration 8 Places", mouse_callback)
    
    # Instructions sur image
    info_img = img.copy()
    cv2.putText(info_img, "Cliquez et glissez pour P1", 
               (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imshow("Calibration 8 Places", info_img)
    
    print("\n⏳ Fenêtre ouverte ! Si vous ne la voyez pas, cherchez-la dans la barre des tâches.")
    
    # Boucle
    while True:
        key = cv2.waitKey(1) & 0xFF
        
        if key == 27:  # ESC
            print("\n⚠️  Annulé")
            cv2.destroyAllWindows()
            sys.exit(0)
        
        if len(zones) == 8 and key != 255:
            break
    
    cv2.destroyAllWindows()
    
    # Sauvegarder
    try:
        with open("zones_parking.json", "w") as f:
            json.dump(zones, f, indent=2)
        
        print("\n✅ zones_parking.json créé !")
        print("\nContenu:")
        print(json.dumps(zones, indent=2))
        
        # Image finale
        final_img = img.copy()
        for nom in sorted(zones.keys()):
            x, y, w, h = zones[nom]
            cv2.rectangle(final_img, (x, y), (x+w, y+h), (0, 255, 0), 3)
            cv2.putText(final_img, nom, (x+10, y+35), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        
        cv2.imwrite("zones_visualisation.jpg", final_img)
        print("✓ zones_visualisation.jpg créé")
        
        print("\n" + "="*70)
        print("✅ CALIBRATION TERMINÉE !")
        print("="*70)
        print("\n📁 Fichiers:")
        print("   • zones_parking.json")
        print("   • zones_visualisation.jpg")
        print("   • calibration.jpg")
        
        print("\n📋 Prochaine étape:")
        print("   python serveur_8_places.py")
        print("   Puis commande 'r' pour référence")
        print()
        
        # Afficher résultat
        cv2.namedWindow("Zones Finales")
        cv2.imshow("Zones Finales", final_img)
        print("Appuyez sur une touche pour fermer...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        
    except Exception as e:
        print(f"✗ Erreur: {e}")
    
    print("\n👋 Terminé !\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrompu\n")
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"\n✗ Erreur: {e}\n")
        import traceback
        traceback.print_exc()