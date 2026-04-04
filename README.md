# prove_it
Competitia ProveIT 2026 by BEST Iasi - Proba Tremend

---

## Idei de proiecte AI

### 1. Optimizarea reducerilor de produse cu AI
**Problema:** Retailerii aplică reduceri "la ochi" sau după reguli fixe, pierzând profit sau stoc.  
**Solutia:** Model ML (XGBoost / regresie) antrenat pe istoricul vânzărilor, sezonalitate, stoc rămas, elasticitate preț și comportamentul concurenței. Outputul: recomandare automată de perioadă și procent de reducere care maximizează profitul net.  
**Date necesare:** istoricul tranzacțiilor, prețuri concurență (scraping), date demografice  
**Impact:** direct financiar, ușor de demonstrat cu cifre  
**Dificultate tehnică:** medie — există dataset-uri publice (Kaggle retail)

---

### 2. Prevenție burnout personal medical
**Problema:** Burnout-ul în sistemul medical este o criză globală — afectează calitatea actului medical și crește rata de erori.  
**Solutia:** Sistem de monitorizare pasivă (ture, ore suplimentare, wearables, ton în comunicări interne) + model de predicție timpurie a riscului de burnout per angajat + dashboard pentru manageri cu alerte și recomandări.  
**Date necesare:** date anonimizate HR, wearables, programări  
**Impact:** uman și financiar (costul înlocuirii unui medic este enorm)  
**Dificultate tehnică:** ridicată — date sensibile, GDPR, necesită parteneriat cu o instituție medicală

---

### 3. AI analiză TIR forestier pentru legalitate
**Problema:** Tăierile ilegale de pădure sunt o problemă majoră în România — controalele manuale sunt rare și ușor de eludat.  
**Solutia:** Computer vision pe imagini de cameră (drone / camere fixe la puncte de control) pentru detectarea și estimarea volumului de lemn dintr-un TIR + corelarea cu avizul de transport (OCR pe documente) + alertă automată la neconcordanțe.  
**Date necesare:** imagini TIR-uri, baza de date SUMAL (sistemul național de urmărire a lemnului)  
**Impact:** mediu, foarte relevant în context românesc  
**Dificultate tehnică:** ridicată (computer vision), dar impresionantă vizual pentru juriu

---

### 4. AI tutor adaptiv pentru elevi
**Problema:** Sistemul educațional nu poate personaliza predarea pentru fiecare elev în parte.  
**Solutia:** AI care detectează golurile de cunoștințe ale unui elev și generează exerciții personalizate în timp real.  
**Dificultate tehnică:** medie

---

### 5. Predicție boli culturi agricole
**Problema:** Fermierii detectează bolile culturilor prea târziu, după ce pagubele sunt deja mari.  
**Solutia:** Analiză imagini de dronă cu computer vision + recomandare tratament minim necesar.  
**Dificultate tehnică:** medie-ridicată

---

### 6. Detectare gropi în drumuri
**Problema:** Infrastructura rutieră degradată este greu de monitorizat sistematic.  
**Solutia:** Detectare gropi/degradări din imagini de cameră de bord + prioritizare automată a reparațiilor pe hartă.  
**Dificultate tehnică:** medie

---

### 7. Optimizare consum energetic clădiri publice
**Problema:** Clădirile publice consumă ineficient energia — fără corelație cu ocuparea reală sau condițiile meteo.  
**Solutia:** AI care optimizează consumul energetic în timp real pe baza ocupării și prognozei meteo.  
**Dificultate tehnică:** medie

---

### 8. Detectare clauze abuzive în contracte
**Problema:** Consumatorii semnează contracte fără să înțeleagă clauzele dezavantajoase.  
**Solutia:** AI (NLP) care analizează un contract și evidențiază clauzele abuzive sau riscante pentru utilizator.  
**Dificultate tehnică:** medie — modele LLM existente pot fi fine-tuned pe legislație românească
