import cv2
import os

print("Test référence\n")

# Vérifier fichier
if os.path.exists("reference_vide.jpg"):
    print("✓ reference_vide.jpg existe")
    
    # Charger
    img_ref = cv2.imread("reference_vide.jpg")
    
    if img_ref is not None:
        print(f"✓ Image chargée: {img_ref.shape[1]}x{img_ref.shape[0]}")
    else:
        print("✗ Impossible de charger l'image")
else:
    print("✗ reference_vide.jpg n'existe PAS")
    print("\nCréez-la avec:")
    print("  1. Enlevez toutes les voitures")
    print("  2. Dans serveur Python: tapez 'r'")
    print("  3. Tapez 'o' pour confirmer")