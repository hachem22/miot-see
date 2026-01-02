import cv2
import json
import sys

# Utiliser l'image existante
print("="*60)
print("  📐 CALIBRATION MANUELLE")
print("="*60)

img_path = "calibration.jpg"
print(f"\n📂 Chargement de {img_path}...")

img = cv2.imread(img_path)
if img is None:
    print(f"✗ Fichier introuvable: {img_path}")
    print("\nAssurez-vous d'avoir sauvegardé l'image depuis:")
    print("http://192.168.16.20:81/capture")
    sys.exit(1)

h, w = img.shape[:2]
print(f"✓ Image chargée: {w}x{h} pixels\n")

zones = {}
current_place = ["P1", "P2", "P3", "P4"]
place_index = 0
points = []

def click_event(event, x, y, flags, params):
    global points, place_index, img, zones
    
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x, y))
        img_copy = img.copy()
        
        for pt in points:
            cv2.circle(img_copy, pt, 5, (0, 255, 0), -1)
        cv2.imshow("Calibration", img_copy)
        
        if len(points) == 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            
            x_min = min(x1, x2)
            y_min = min(y1, y2)
            width = abs(x2 - x1)
            height = abs(y2 - y1)
            
            place_name = current_place[place_index]
            zones[place_name] = (x_min, y_min, width, height)
            
            img_copy = img.copy()
            for pname, (px, py, pw, ph) in zones.items():
                cv2.rectangle(img_copy, (px, py), (px + pw, py + ph), (0, 255, 0), 2)
                cv2.putText(img_copy, pname, (px + 10, py + 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            cv2.imshow("Calibration", img_copy)
            img = img_copy.copy()
            
            print(f"✓ {place_name}: x={x_min}, y={y_min}, largeur={width}, hauteur={height}")
            
            points = []
            place_index += 1
            
            if place_index >= len(current_place):
                print("\n" + "="*60)
                print("✓ CALIBRATION TERMINÉE !")
                print("="*60)
                
                with open("zones_parking.json", "w") as f:
                    json.dump(zones, f, indent=2)
                print("\n✓ Sauvegardé: zones_parking.json")
                
                cv2.waitKey(2000)
                cv2.destroyAllWindows()
                sys.exit(0)
            else:
                print(f"\n📍 {current_place[place_index]}: Cliquez HAUT-GAUCHE puis BAS-DROITE")

print("INSTRUCTIONS:")
print("  1. Cliquez en HAUT-GAUCHE de chaque place")
print("  2. Puis cliquez en BAS-DROITE")
print("  3. Les zones doivent contenir les lettres 'P'\n")
print(f"📍 {current_place[0]}: Cliquez HAUT-GAUCHE puis BAS-DROITE\n")

cv2.imshow("Calibration", img)
cv2.setMouseCallback("Calibration", click_event)

while True:
    if cv2.waitKey(1) & 0xFF == 27:
        break

cv2.destroyAllWindows()