# 🌾 SPARK (Smart Pratics Removal Automatique Kits)

<p align="right">
  <img src="images/detection-logo.png" width="220" alt="Logo Détection SPARK">
</p>

**SPARK** est un système robotique agricole de précision de pointe conçu pour optimiser la gestion des cultures de tomates en automatisant l'élimination ciblée des mauvaises herbes. Ce projet a été développé dans le cadre du module *Learning by Doing (LBD)* au sein de l'**École Centrale Casablanca**.

---

## 👥 Équipe du Projet (PLBD 25)
* **Membres de l'équipe :** Zouhair Imad, Ilyas Dali, Fatima Ezzahra Melouki, Mohmed Chebabe, Inas Dridi
* **Encadrant :** Dr. Adil Ahidare
* **Institution :** École Centrale Casablanca
* **Année universitaire :** 2026

---

## 🤖 Présentation Matérielle du Robot
Le robot SPARK s'appuie sur la plateforme matérielle **Adeept PiCar Pro V2 Smart Robot**. Il élimine la flore nuisible de manière ciblée grâce à une approche séquentielle en deux étapes :
1. **La détection :** Identification en temps réel via une caméra HD embarquée.
2. **L'action :** Élimination physique localisée de la mauvaise herbe à l'aide d'une pince montée sur son bras articulé.

<p align="center">
  <img src="images/robot-picar.png" width="550" alt="Robot SPARK PiCar Pro V2">
</p>

---

## ⚙️ Démarche Chronologique & Algorithmique du Trajet

### 🏁 Phase 1 : Initialisation et calibration
Avant d'effectuer le moindre mouvement, le robot configure l'ensemble de ses périphériques matériels :
* **Mise en position zéro :** Tous les servomoteurs (de 0 à 7) sont positionnés à leur angle neutre de 90°.
* **Extinction des actionneurs :** Tous les relais ou interrupteurs électroniques (`sw.set_all_switch_off()`) sont désactivés par sécurité.
* **Établissement des connexions :** Le Raspberry Pi ouvre un canal de communication TCP/IP (Socket) avec le PC distant (`PC_IP:9999`) et initialise le flux de sa caméra en résolution $640 \times 480$ pixels.

### 🛣️ Phase 2 : Exécution du parcours géométrique théorique
Une fois connecté, le robot lance son fil conducteur principal dans un thread séparé (`t_trajet`). Ce trajet est une boucle ouverte temporelle qui simule un parcours en "S" ou en boucle dans le champ de tomates :
* **Déploiement du bras (Position de travail) :** Le robot oriente son bras articulé vers le sol pour préparer la caméra embarquée à filmer la piste :
  * Le Servo 1 (axe horizontal) bascule à 145°.
  * Le Servo 2 (axe vertical) s'abaisse à 130°.
* **Premier segment rectiligne :** Le robot active ses moteurs de propulsion pour avancer de 75 cm.
* **Premier virage :** Les roues directrices s'orientent à gauche (Servo 0 à 45°) et le robot effectue une rotation continue pendant 19 secondes.
* **Deuxième segment rectiligne :** Le robot se remet en ligne droite et avance de 60 cm.
* **Deuxième virage :** Le robot tourne à nouveau à gauche pendant 19 secondes.
* **Troisième segment rectiligne :** Le robot avance de 70 cm pour terminer sa boucle.

### 👁️ Phase 3 : L'Interruption Prioritaire (Détection d'une mauvaise herbe)
Pendant que le robot avance sur les segments rectilignes de la Phase 2, une boucle d'écoute infinie surveille en continu le retour des analyses du modèle YOLOv8 envoyé par le PC. Si le PC renvoie des coordonnées valides (la plante est détectée), la démarche du robot change instantanément :
#### Zoom sur la boucle de correction fine (IBVS) :
Lorsque la mauvaise herbe est interceptée, le robot fige ses roues et engage la boucle de rétroaction visuelle (`boucle_ibvs`) pour amener l'outil d'arrachage pile au-dessus de la cible :
* **Mesure de l'écart :** Le robot calcule la distance en pixels entre le centre de la mauvaise herbe dans l'image ($cx, cy$) et le centre optique idéal de la caméra ($320, 240$).
* **Ajustement proportionnel :**
  * Si la cible est trop à droite, le Servo 1 compense.
  * Si la cible est trop basse, le Servo 2 s'abaisse pour rapprocher l'outil.
  * Le Servo 3 s'ajuste en profondeur pour parfaire l'approche.
* **Pause de stabilisation :** Le robot attend 0,6 seconde à chaque micro-déplacement pour stabiliser l'image avant de demander une nouvelle coordonnée. Ce cycle se répète jusqu'à un maximum de 15 fois.

### 🛠️ Phase 4 : L'action mécanique d'élimination
Dès que l'erreur visuelle passe sous le seuil de tolérance requis ($SEUIL_X = 30$, $SEUIL_Y = 30$), la fonction `arracher()` prend le relais :
* **Alerte sonore :** Le buzzer émet un signal (note C4 pendant 1 seconde) pour notifier l'action.
* **Actionnement des pinces :** Le Servo 4 s'ouvre à 130° (ouverture des dents) puis se referme à 80° pour saisir l'herbe.
* **Activation de l'outil d'extraction :** Les interrupteurs électriques 1 et 2 (`sw.switch`) s'allument pendant 0,8 seconde pour alimenter l'outil physique d'élimination, puis se coupent.
* **Repli de sécurité :** Le bras se relève et se repositionne en configuration de sécurité pour ne pas racler le sol pendant le déplacement.
* **Signal de reprise :** Le robot envoie une requête HTTP `/activer_detection` à l'application web pour vider la mémoire de capture de l'écran, les moteurs redémarrent, et le robot reprend son trajet initial.

### 🏁 Phase 5 : Fin de mission
Une fois les distances théoriques épuisées (les 70 cm du dernier segment accomplis), le script appelle `position_initiale()` : les moteurs s'arrêtent définitivement, le bras se remet au repos complet (tous les servos à 90°) et le terminal affiche `"Mission terminee !"`.

---

## 📐 Le principe de l'Asservissement Visuel (IBVS)

Contrairement à un automatisme classique où l'on donnerait des coordonnées géométriques fixes, l'asservissement visuel utilise la caméra comme un **capteur de position en temps réel**. Le robot ajuste ses mouvements en fonction de ce qu'il voit à l'écran jusqu'à ce que l'image observée corresponde parfaitement à l'objectif visé.

### 🔄 La boucle de rétroaction appliquée au robot

Le programme connaît le centre idéal de votre image (qui correspond à l'alignement parfait de l'outil d'arrachage), soit $CX = 320$ et $CY = 240$ pixels. Dès que YOLOv8 détecte une herbe à une position ($cx, cy$), l'écart (l'erreur visuelle) est calculé :

$$\text{Erreur}_X = cx - 320$$

$$\text{Erreur}_Y = cy - 240$$

Pour annuler cette erreur, le Raspberry Pi applique des gains qui traduisent l'écart en pixels en un angle de rotation pour les moteurs :
* **Servo 1 (Axe Horizontal) :** Si l'herbe est trop à droite ($\text{Erreur}_X > 0$), l'angle du Servo 1 augmente proportionnellement pour faire pivoter le bras vers la droite.
* **Servo 2 (Axe Vertical) :** Si l'herbe est trop basse sur l'image ($\text{Erreur}_Y > 0$), le Servo 2 s'abaisse pour rapprocher la caméra et l'outil du sol.
* **Servo 3 (Profondeur) :** Il aide à ajuster l'extension du bras pour parfaire l'approche spatiale.

Ce processus itératif se répète (jusqu'à 15 fois maximum) jusqu'à ce que l'erreur devienne inférieure à 30 pixels (seuil de **convergence**).

<p align="center">
  <img src="images/courbe-convergence.png" width="550" alt="Courbe de convergence IBVS">
</p>

---

## 🖥️ Tableau de Bord Web & Supervision Intelligente

L'application Flask (`web_app_2.py`) génère une interface web de contrôle robuste et structurée :

<p align="center">
  <img src="images/interface-web.png" width="600" alt="Interface Web de Supervision SPARK">
</p>

### 🤖 L'Assistant Virtuel Intelligent (Chatbot AgriBot)
Intégré directement sur l'interface et relié à la route `/chat`, ce composant permet à l'utilisateur ou aux membres du jury d'échanger en temps réel :
* **Zone de saisie et d'historique :** Permet de poser des questions en langage naturel.
* **Boutons de suggestions rapides (Quick Replies) :** Boutons d'accès direct (`Detection`, `Robot`, `Coordonnées`, `Trajet`) pour interroger le système en un seul clic.
* **Intelligence Artificielle contextuelle :** Ce chatbot est propulsé par l'API **Gemini 2.5 Flash**. Il agit comme l'expert technique officiel de l'application Spark en lisant dynamiquement la base de connaissances du fichier `donnes_projet.json` pour répondre de façon concise et professionnelle en français.

---

## 🎬 Simulation du Trajet du Robot

Voici l'aperçu dynamique du comportement cinématique et du suivi de trajectoire simulé de notre robot lors de l'application de sa patrouille :

<p align="center">
  <img src="images/simulation-trajet.gif" width="500" alt="Simulation du trajet du robot SPARK">
</p>