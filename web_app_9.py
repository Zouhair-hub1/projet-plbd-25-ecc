from flask import Flask, Response, render_template, jsonify, make_response, request
import cv2
import numpy as np
import socket
import struct
import threading
import os
import json
from ultralytics import YOLO
from datetime import datetime
import time

from google.genai import Client
from google.genai import types

app = Flask(__name__)

# --- CONFIGURATIONS ROBOT & YOLO (STRICTEMENT INCHANGÉES) ---
LIVE_DIR   = r'C:\Users\Zouhire\Desktop\live robot'
MODEL_PATH = r'C:\Users\Zouhire\Desktop\plbd mauvaise herbe\experience_5\weights\best.pt'
HOST = '0.0.0.0'
PORT = 9999

os.makedirs(LIVE_DIR, exist_ok=True)

FRAME_W = 640
FRAME_H = 480
REAL_W_CM = 23.0
REAL_H_CM = 17.0

# --- Suivi GPS téléphone ---
robot_position = {"latitude": 33.5892, "longitude": -7.6042}

def pixels_to_cm(px, py):
    cx_cm = round((px / FRAME_W) * REAL_W_CM, 1)
    cy_cm = round((py / FRAME_H) * REAL_H_CM, 1)
    return cx_cm, cy_cm

current_frame = None
detections_list = []
compteur = 1
frame_lock = threading.Lock()

ibvs_mode = False
premier_screenshot_fait = False
ibvs_lock = threading.Lock()

print("Chargement du modele YOLOv8...")
model = YOLO(MODEL_PATH)
print("Modele charge !")

# --- CONNEXION SOCKET ET TRAITEMENT (STRICTEMENT INCHANGÉ) ---
def recevoir_frames():
    global current_frame, detections_list, compteur
    global ibvs_mode, premier_screenshot_fait

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print("En attente du robot...")

    conn, addr = server.accept()
    print(f"Robot connecte : {addr}")

    while True:
        try:
            raw_size = conn.recv(4)
            if not raw_size:
                break
            size = struct.unpack('>I', raw_size)[0]

            data = b''
            while len(data) < size:
                packet = conn.recv(4096)
                if not packet:
                    break
                data += packet

            img_array = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if frame is None:
                conn.sendall(b'0\n')
                continue

            results = model(frame, conf=0.5, verbose=False)
            boxes = results[0].boxes
            annotated = results[0].plot()

            with frame_lock:
                current_frame = annotated.copy()

            if len(boxes) > 0:
                best_box = None
                best_dist = float('inf')

                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    box_area = (x2-x1) * (y2-y1)
                    if box_area > FRAME_W * FRAME_H * 0.7:
                        continue
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    dist_centre = abs(cx - FRAME_W//2) + abs(cy - FRAME_H//2)
                    if dist_centre < best_dist:
                        best_dist = dist_centre
                        best_box = box
                        best_cx = cx
                        best_cy = cy

                if best_box is None:
                    conn.sendall(b'0\n')
                    continue

                x1, y1, x2, y2 = best_box.xyxy[0].tolist()
                conf = float(best_box.conf[0])
                cx_cm, cy_cm = pixels_to_cm(best_cx, best_cy)
                hauteur_box_px = y2 - y1
                hauteur_herbe_cm = round((hauteur_box_px / FRAME_H) * REAL_H_CM, 1)

                with ibvs_lock:
                    faire_screenshot = not premier_screenshot_fait
                    if faire_screenshot:
                        premier_screenshot_fait = True
                        ibvs_mode = True

                if faire_screenshot:
                    screenshot_frame = frame.copy()
                    overlay = screenshot_frame.copy()
                    x1i,y1i,x2i,y2i = int(x1),int(y1),int(x2),int(y2)
                    cv2.rectangle(overlay, (x1i,y1i), (x2i,y2i), (0,0,255), -1)
                    cv2.addWeighted(overlay, 0.4, screenshot_frame, 0.6, 0, screenshot_frame)
                    cv2.rectangle(screenshot_frame, (x1i,y1i), (x2i,y2i), (0,0,255), 3)
                    cv2.putText(screenshot_frame,
                                f"Herbe {conf:.0%} H={hauteur_herbe_cm}cm",
                                (x1i, y1i-10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (0,0,255), 2)

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    nom = f"live_{compteur:03d}_{timestamp}.jpg"
                    cv2.imwrite(os.path.join(LIVE_DIR, nom), screenshot_frame)

                    detection = {
                        'id': compteur,
                        'image': nom,
                        'timestamp': datetime.now().strftime("%H:%M:%S"),
                        'coords': [{'x_cm': cx_cm, 'y_cm': cy_cm, 'conf': round(conf*100)}],
                        'hauteur_cm': hauteur_herbe_cm,
                        'conseil': f"Herbe a X={cx_cm}cm Y={cy_cm}cm hauteur={hauteur_herbe_cm}cm"
                    }
                    detections_list.insert(0, detection)
                    if len(detections_list) > 20:
                        detections_list.pop()
                    compteur += 1

                print(f"Envoi cx={best_cx} cy={best_cy}")
                msg = f"{best_cx},{best_cy},{hauteur_herbe_cm}\n".encode()
                conn.sendall(msg)

            else:
                conn.sendall(b'0\n')

        except Exception as e:
            print(f"Erreur : {e}")
            break

def generate_stream():
    global current_frame
    while True:
        with frame_lock:
            frame = current_frame
        if frame is None:
            time.sleep(0.1)
            continue
        _, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')
        time.sleep(0.05)

# --- ROUTES FLASK ---
@app.route('/')
def index():
    resp = make_response(render_template('index_9.html'))
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route('/video_feed')
def video_feed():
    return Response(generate_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/detections')
def get_detections():
    return jsonify(detections_list)

@app.route('/screenshot/<nom>')
def screenshot(nom):
    chemin = os.path.join(LIVE_DIR, nom)
    with open(chemin, 'rb') as f:
        return Response(f.read(), mimetype='image/jpeg')

@app.route('/activer_detection')
def activer_detection():
    global ibvs_mode, premier_screenshot_fait
    with ibvs_lock:
        ibvs_mode = False
        premier_screenshot_fait = False
    print("Detection reactivee !")
    return "OK"

VERIF_DIR = r'C:\Users\Zouhire\Desktop\verification zone'
os.makedirs(VERIF_DIR, exist_ok=True)
server_start_time = datetime.now()

@app.route('/save_verification', methods=['POST'])
def save_verification():
    data = request.data
    nom = f"verif_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    with open(os.path.join(VERIF_DIR, nom), 'wb') as f:
        f.write(data)
    print(f"Photo verification sauvegardee : {nom}")
    return "OK"

@app.route('/verifications')
def list_verifications():
    photos = []
    if os.path.exists(VERIF_DIR):
        files = sorted([f for f in os.listdir(VERIF_DIR) if f.endswith('.jpg')], reverse=True)
        for f in files:
            timestamp = f.replace('verif_', '').replace('.jpg', '')
            try:
                dt = datetime.strptime(timestamp, '%Y%m%d_%H%M%S')
                if dt < server_start_time:
                    continue
                time_str = dt.strftime('%H:%M:%S')
            except:
                continue
            photos.append({'name': f, 'time': time_str})
    return jsonify(photos)

@app.route('/verification_img/<nom>')
def verification_img(nom):
    chemin = os.path.join(VERIF_DIR, nom)
    if os.path.exists(chemin):
        with open(chemin, 'rb') as f:
            return Response(f.read(), mimetype='image/jpeg')
    return "Not found", 404

# --- ROUTES GPS (depuis web_app.py) ---
@app.route('/partage-gps')
def partage_gps():
    return '''
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Émetteur GPS - Robot</title>
        <style>
            body { font-family: sans-serif; text-align: center; background-color: #e8f5e9; padding: 30px; margin: 0; }
            .card { background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 400px; margin: auto; }
            h2 { color: #2e7d32; }
            #status { font-size: 1.1em; color: #555; font-weight: bold; margin-top: 15px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>📡 Émetteur GPS Actif</h2>
            <p>Gardez cette page ouverte sur votre téléphone à côté du robot.</p>
            <div id="status">Recherche du signal GPS de l'appareil...</div>
        </div>
        <script>
            function envoyerGps() {
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(position => {
                        const lat = position.coords.latitude;
                        const lng = position.coords.longitude;
                        fetch('/api/update_from_phone', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ latitude: lat, longitude: lng })
                        })
                        .then(response => response.json())
                        .then(data => {
                            document.getElementById('status').innerHTML = 
                                "✅ Position envoyée au PC !<br><span style='font-size:0.8em; color:#777;'>Lat: " + lat.toFixed(5) + " | Lng: " + lng.toFixed(5) + "</span>";
                        });
                    }, 
                    error => {
                        document.getElementById('status').innerHTML = "❌ Erreur : activez le GPS de votre téléphone.";
                    }, 
                    { enableHighAccuracy: true, timeout: 5000 });
                } else {
                    document.getElementById('status').innerText = "❌ Ce téléphone ne supporte pas la géolocalisation.";
                }
            }
            setInterval(envoyerGps, 2000);
            envoyerGps();
        </script>
    </body>
    </html>
    '''

@app.route('/api/update_from_phone', methods=['POST'])
def update_from_phone():
    global robot_position
    data = request.get_json()
    if data and 'latitude' in data and 'longitude' in data:
        robot_position['latitude'] = float(data['latitude'])
        robot_position['longitude'] = float(data['longitude'])
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "error", "message": "Données invalides"}), 400

@app.route('/api/get_robot_location', methods=['GET'])
def get_robot_location():
    return jsonify(robot_position)


# --- CONFIGURATION ET ROUTE DU CHATBOT (STRICTEMENT INCHANGÉE) ---
GEMINI_API_KEY = "AQ.Ab8RN6LzdZGh-vV2uaEryytTYf4SOboS7ZRSag62rm2ZCYfPjg"
client_gemini = Client(api_key=GEMINI_API_KEY)

@app.route('/chat', methods=['POST'])
def chat():
    msg = request.json.get('message', '')
    timestamp_actuel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with open("historique_mess.txt", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp_actuel}] Utilisateur : {msg}\n")
    except Exception as e:
        print(f"Erreur ecriture historique : {e}")
    
    contenu_json_projet = ""
    try:
        with open("donnees_projet.json", "r", encoding="utf-8") as json_file:
            donnees = json.load(json_file)
            contenu_json_projet = json.dumps(donnees, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erreur lors du chargement du fichier JSON : {e}")
        contenu_json_projet = "Erreur d'accès à la base de connaissances JSON."

    contexte_systeme = f"""
    Tu es l'assistant virtuel officiel de l'application Spark (Robot PiCar AgriBot), projet LBD au sein de l'Ecole Centrale Casablanca.
    Ton rôle exclusif est de répondre aux questions des utilisateurs ou du jury d'examen en s'appuyant rigoureusement sur les données réelles fournies.
    
    Consignes strictes de réponse :
    1. Réponds TOUJOURS en français.
    2. Sois concis, clair et professionnel (maximum 2 à 3 phrases par réponse).
    3. Ne coupe jamais tes phrases et formule des énoncés complets et fluides.
    4. Base-toi uniquement sur la structure JSON technique ci-dessous pour répondre. Ne devine rien d'autre.
    
    BASE DE CONNAISSANCES STRUCTUREE DU PROJET (JSON) :
    {contenu_json_projet}
    
    Si la question de l'utilisateur n'a aucun lien logique ou technique avec les informations du projet Spark contenues dans ce JSON, réponds poliment que tu es un module de support dédié uniquement au projet AgriBot Spark et invite l'utilisateur à se recentrer sur l'IA, le bras robotique, l'asservissement visuel (IBVS) ou l'équipe projet.
    """
    
    try:
        response = client_gemini.models.generate_content(
            model='gemini-2.5-flash',
            contents=msg,
            config=types.GenerateContentConfig(
                system_instruction=contexte_systeme,
                max_output_tokens=300,
                temperature=0.2
            )
        )
        
        reponse_finale = response.text.strip()
        
        with open("historique_mess.txt", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp_actuel}] Gemini : {reponse_finale}\n\n")
            
    except Exception as e:
        print(f"--- ERREUR CHATBOT --- : {e}")
        reponse_finale = "Désolé, j'ai rencontré une micro-coupure de connexion avec mon serveur d'intelligence artificielle. Reposez-moi votre question !"

    return jsonify({'reponse': reponse_finale})


if __name__ == '__main__':
    t = threading.Thread(target=recevoir_frames)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
