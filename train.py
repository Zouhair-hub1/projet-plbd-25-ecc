from ultralytics import YOLO

# Charger le modèle YOLOv8 nano (le plus léger)
model = YOLO('yolov8n.pt')

# Lancer l'entraînement
model.train(
    data=r'C:\Users\Zouhire\Desktop\plbd mauvaise herbe\data.yaml',
    epochs=50,
    imgsz=640,
    batch=8,
    device='cpu',
    project=r'C:\Users\Zouhire\Desktop\plbd mauvaise herbe',
    name='experience_5',
    verbose=True
)

print("✅ Entraînement terminé !")