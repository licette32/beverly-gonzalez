import json
from pathlib import Path

from sistema.seguridad import detectar

ruta = Path(r"C:\Users\bever\Desktop\novit-curso\academia2026-tp\datos\voces\indice.json")
voces = json.loads(ruta.read_text(encoding="utf-8"))

for v in voces.values():
    cats = [d.categoria for d in detectar(v["texto"])]
    if cats:
        print(v["escenario"], v["nota_id"], cats, v["texto"])