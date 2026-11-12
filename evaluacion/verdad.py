"""Evaluacion offline del parte contra la verdad de una corrida.

Uso:
    python evaluacion/verdad.py correccion/corridas/etapa-final/martes-tranquilo.json

Se corre DESPUES de una corrida y nunca se importa desde el agente (D14: el
agente no lee /api/verdad ni /api/correccion en ejecucion). La verdad sale del
campo "verdad" del JSON de la corrida; lo que hizo el sistema sale de los
mensajes publicados en "sistema/tablet" dentro de "registro".
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

TOPICO_TABLET = "sistema/tablet"
SIN_EQUIPO = "SIN-EQUIPO"
TOLERANCIA = 1e-3


def cargar(ruta: str) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def mensajes_tablet(corrida: dict) -> list[dict]:
    return [
        e["payload"]
        for e in corrida.get("registro", [])
        if e.get("topico") == TOPICO_TABLET and e.get("valido", True) and e.get("payload")
    ]


def es_pregunta(msg: dict) -> bool:
    # Supuesto: una pregunta de desambiguacion espera respuesta y trae opciones.
    pantalla = msg.get("pantalla") or {}
    return bool(msg.get("espera_respuesta")) and bool(pantalla.get("opciones"))


def borrador_final(msgs: list[dict], nota_id: str) -> dict | None:
    final = None
    for m in msgs:
        filas = (m.get("pantalla") or {}).get("filas")
        if nota_id in (m.get("nota_ids") or []) and filas:
            final = m  # el ultimo borrador con filas es el estado final
    return final


def tag_norm(tag):
    return None if tag in (None, "", SIN_EQUIPO) else str(tag)


def mismo_valor(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) < TOLERANCIA
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def evaluar(corrida: dict) -> dict:
    msgs = mensajes_tablet(corrida)
    campos = defaultdict(lambda: [0, 0])  # campo -> [aciertos, total]
    fallos: list[str] = []
    sin_borrador: list[str] = []
    preguntaron: dict[str, bool] = {}
    con_ambiguedad: dict[str, bool] = {}

    for nota in (n for n in corrida.get("verdad", []) if "nota_id" in n):
        nid = nota["nota_id"]
        borr = borrador_final(msgs, nid)
        filas = ((borr or {}).get("pantalla") or {}).get("filas") or []
        if borr is None and nota.get("items"):
            sin_borrador.append(nid)
        preguntaron[nid] = any(
            es_pregunta(m) and nid in (m.get("nota_ids") or []) for m in msgs
        )
        con_ambiguedad[nid] = bool(nota.get("ambiguedades"))

        for item in nota.get("items", []):
            tag = tag_norm(item.get("tag"))
            var = item.get("variable")
            del_equipo = [f for f in filas if tag_norm(f.get("tag")) == tag]
            exacta = next((f for f in del_equipo if f.get("variable") == var), None)

            resultados = {
                "equipo": bool(del_equipo),
                "variable": exacta is not None,
                "valor": exacta is not None and mismo_valor(exacta.get("valor"), item.get("valor")),
                "unidad": exacta is not None and mismo_valor(exacta.get("unidad"), item.get("unidad")),
            }
            for campo, ok in resultados.items():
                campos[campo][1] += 1
                campos[campo][0] += int(ok)
            if not all(resultados.values()):
                malos = [c for c, ok in resultados.items() if not ok]
                fallos.append(
                    f"{nid} {tag}/{var}: fallan {malos}; verdad valor={item.get('valor')} "
                    f"unidad={item.get('unidad')}; sistema={exacta}"
                )
    return {
        "campos": campos,
        "fallos": fallos,
        "sin_borrador": sin_borrador,
        "preguntaron": preguntaron,
        "con_ambiguedad": con_ambiguedad,
    }


def informe(res: dict) -> str:
    out = ["=== Evaluacion offline contra la verdad ==="]
    for campo in ("equipo", "variable", "valor", "unidad"):
        a, t = res["campos"].get(campo, [0, 0])
        pct = 100 * a / t if t else 0.0
        out.append(f"{campo:9} {a}/{t} ({pct:.1f} %)")
    amb = [n for n, v in res["con_ambiguedad"].items() if v]
    sin_amb = [n for n, v in res["con_ambiguedad"].items() if not v]
    preg_amb = [n for n in amb if res["preguntaron"][n]]
    preg_sin = [n for n in sin_amb if res["preguntaron"][n]]
    out.append("")
    out.append(f"Notas con ambiguedad en la verdad: {len(amb)}; el sistema pregunto en {len(preg_amb)}: {preg_amb}")
    out.append(f"Notas sin ambiguedad donde igual pregunto: {len(preg_sin)}: {preg_sin}")
    out.append(f"Notas con items en la verdad y sin borrador publicado: {res['sin_borrador']}")
    out.append("")
    out.append("Detalle de fallos:")
    out.extend(f"  - {f}" for f in res["fallos"]) if res["fallos"] else out.append("  (ninguno)")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluacion offline contra la verdad de una corrida")
    ap.add_argument("corrida", help="ruta al JSON de la corrida")
    args = ap.parse_args()
    print(informe(evaluar(cargar(args.corrida))))


if __name__ == "__main__":
    main()
