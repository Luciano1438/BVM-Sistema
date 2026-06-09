# motor/despiece.py
# Motor de Despiece Geométrico BVM

CONFIG_TECNICA = {
    "ranura_profundidad": 10.0,
    "ranura_distancia_borde": 10.0,
    "retazo_min_ancho": 150,
    "retazo_min_largo": 400,
}


def obtener_veta_automatica(nombre_pieza: str, material_seleccionado: str) -> str:
    if "blanco" in material_seleccionado.lower():
        return "Libre (Cualquier sentido)"
    nombre_lower = nombre_pieza.lower()
    if any(x in nombre_lower for x in ["lateral exterior", "puerta", "tapa de cajon", "fondo"]):
        return "Vertical (Hacia Arriba)"
    return "Horizontal (Izquierda a Derecha)"


def calcular_medida_frente(ancho_hueco, alto_hueco, tipo_montaje="Superpuesto", es_doble=False):
    if tipo_montaje == "Superpuesto":
        return ancho_hueco - 4, alto_hueco - 4
    else:
        alto_real = alto_hueco - 6
        ancho_real = (ancho_hueco - 5) if es_doble else (ancho_hueco - 6)
        return ancho_real, alto_real



def generar_despiece_bvm(
    tipo, ancho_m, alto_m, prof_m, esp_real,
    tiene_parante=False, tipo_parante="Corto (100mm)", distancia_parante=0,
    cant_cajones=0, tipo_tapa="Superpuesta", tipo_base="Nada", altura_base=0,
    luz_entre_tapas=3.0, luz_perimetral_tapa=4.0, alto_frentin_emb=0,
    aire_trasero=30, esp_corredera=13, distribucion_tapas="Iguales",
    cant_puertas=2, tiene_cenefa=False, alto_cenefa=0.0,
    estantes_fijos=0, estantes_moviles=0,
    tipo_estante_manual="Completo",
    sin_fondo=False,
    tiene_parante_medio=False,
    # Parámetros exclusivos de Placard
    division_placard="Sin división",
    zona_izq="Solo estantes",
    zona_der="Solo estantes",
    zona_unica="Solo estantes",
    altura_tubo=1200,
    cant_estantes_izq_fijos=0, cant_estantes_izq_moviles=0,
    cant_estantes_der_fijos=0, cant_estantes_der_moviles=0,
    cant_estantes_unica_fijos=1, cant_estantes_unica_moviles=0,
    cant_cajones_placard=0,
    # Parámetros exclusivos de Panel a Medida
    cant_paneles=1,
    **kwargs,
):
    despiece = []
    ancho_interno_total = ancho_m - (esp_real * 2)

    # -----------------------------------------------------------------------
    # BAJO MESADA
    # -----------------------------------------------------------------------
    if tipo == "Bajo Mesada":
        despiece.append({"Pieza": "Base Módulo",      "Cant": 1, "L": ancho_m,       "A": prof_m, "Tipo": "Cuerpo"})
        altura_lateral = alto_m - esp_real
        despiece.append({"Pieza": "Lateral Exterior", "Cant": 2, "L": altura_lateral, "A": prof_m, "Tipo": "Cuerpo"})

        if tipo_tapa == "Superpuesta":
            despiece.append({"Pieza": "Frentín Frontal",    "Cant": 1, "L": ancho_interno_total, "A": 50, "Tipo": "Cuerpo"})
            alto_puerta = alto_m - 30
        elif tipo_tapa == "Gola BVM":
            despiece.append({"Pieza": "Frentín Gola L (A)", "Cant": 1, "L": ancho_interno_total, "A": 40, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Frentín Gola L (B)", "Cant": 1, "L": ancho_interno_total, "A": 50, "Tipo": "Cuerpo"})
            alto_puerta = alto_m - 30
        else:  # Embutida
            despiece.append({"Pieza": "Frentín Embutido",   "Cant": 1, "L": ancho_interno_total, "A": 40, "Tipo": "Cuerpo"})
            alto_puerta = alto_m - esp_real - 46

        despiece.append({"Pieza": "Travesaño Trasero (100)", "Cant": 1, "L": ancho_interno_total, "A": 100, "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Trasero (60)",  "Cant": 1, "L": ancho_interno_total, "A": 60,  "Tipo": "Cuerpo"})

        if not sin_fondo:
            alto_fondo = alto_m - 80 - esp_real
            despiece.append({"Pieza": "Fondo Mueble", "Cant": 1, "L": alto_fondo, "A": ancho_m - 20, "Tipo": "Fondo"})

        prof_est = prof_m - 20
        if tipo_estante_manual == "Medio":
            etiqueta_est    = "Medio Estante"
            ancho_est_final = (ancho_interno_total - esp_real) / 2
            mult_cant       = 2
        else:
            etiqueta_est    = "Estante Completo"
            ancho_est_final = ancho_interno_total
            mult_cant       = 1

        if estantes_fijos > 0:
            despiece.append({"Pieza": f"{etiqueta_est} FIJO",  "Cant": int(estantes_fijos * mult_cant),  "L": round(ancho_est_final, 1),     "A": prof_est, "Tipo": "Cuerpo"})
        if estantes_moviles > 0:
            despiece.append({"Pieza": f"{etiqueta_est} MÓVIL", "Cant": int(estantes_moviles * mult_cant), "L": round(ancho_est_final - 2, 1), "A": prof_est, "Tipo": "Cuerpo"})

        if tiene_parante_medio:
            ancho_par_medio = prof_m if tipo_parante == "Largo (Fondo Lateral)" else 100
            despiece.append({"Pieza": "Parante Medio", "Cant": 1, "L": altura_lateral, "A": ancho_par_medio, "Tipo": "Cuerpo"})

        if tiene_parante:
            ancho_par = prof_m if tipo_parante == "Largo (Fondo Lateral)" else 100
            despiece.append({"Pieza": "Parante Divisor", "Cant": 1, "L": altura_lateral, "A": ancho_par, "Tipo": "Cuerpo"})
            ancho_p = (ancho_m - (esp_real * 3) - 16) / 3 if tipo_tapa == "Embutida" else (ancho_m - 12) / 3
            despiece.append({"Pieza": "Puerta", "Cant": 3, "L": alto_puerta, "A": round(ancho_p, 1), "Tipo": "Frente"})
        else:
            ancho_p = (ancho_m - (esp_real * 2) - 10) / 2 if tipo_tapa == "Embutida" else (ancho_m - 8) / 2
            despiece.append({"Pieza": "Puerta", "Cant": 2, "L": alto_puerta, "A": round(ancho_p, 1), "Tipo": "Frente"})

    # -----------------------------------------------------------------------
    # CAJONERA
    # -----------------------------------------------------------------------
    elif tipo == "Cajonera":
        altura_caja_real = alto_m
        if tipo_base in ["Banquina de Obra", "Patas Plásticas"]:
            altura_caja_real = alto_m - altura_base

        despiece.append({"Pieza": "Base Módulo",        "Cant": 1, "L": ancho_m,             "A": prof_m,       "Tipo": "Cuerpo"})
        altura_lateral_bvm = alto_m - esp_real
        despiece.append({"Pieza": "Lateral Exterior",   "Cant": 2, "L": altura_lateral_bvm,  "A": prof_m,       "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_interno_total, "A": 100,          "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Trasero",  "Cant": 1, "L": ancho_interno_total, "A": 60,           "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Frentín Frontal",    "Cant": 1, "L": ancho_interno_total, "A": 50,           "Tipo": "Cuerpo"})

        if not sin_fondo:
            despiece.append({"Pieza": "Fondo Mueble", "Cant": 1, "L": alto_m - 20, "A": ancho_m - 20, "Tipo": "Fondo"})

        if tipo_base == "Zócalo de Madera":
            despiece.append({"Pieza": "Zócalo Frontal", "Cant": 2, "L": altura_base, "A": ancho_interno_total, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Zócalo Lateral", "Cant": 2, "L": altura_base, "A": prof_m - 50,         "Tipo": "Cuerpo"})

        if tiene_parante:
            altura_interna = altura_caja_real - (esp_real * 2)
            despiece.append({"Pieza": "Parante Divisor", "Cant": 1, "L": altura_interna, "A": prof_m - 20, "Tipo": "Cuerpo"})

        if cant_cajones > 0:
            if "Superpuesta" in tipo_tapa:
                espacio_util_total = alto_m - 30 - ((cant_cajones - 1) * luz_entre_tapas)
                ancho_tapa_bvm     = ancho_m - luz_perimetral_tapa
                largo_lateral_caja = prof_m - aire_trasero
            elif tipo_tapa == "Embutida":
                espacio_util_total = alto_m - alto_frentin_emb - esp_real - ((cant_cajones + 1) * luz_entre_tapas)
                ancho_tapa_bvm     = ancho_interno_total - 6
                largo_lateral_caja = prof_m - 30 - esp_real
            else:  # Gola
                espacio_util_total = alto_m - 60 - ((cant_cajones - 1) * luz_entre_tapas)
                ancho_tapa_bvm     = ancho_m - luz_perimetral_tapa
                largo_lateral_caja = prof_m - aire_trasero
                despiece.append({"Pieza": "Frentín Gola L (A)", "Cant": 2, "L": 40, "A": ancho_interno_total, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Frentín Gola L (B)", "Cant": 2, "L": 50, "A": ancho_interno_total, "Tipo": "Cuerpo"})

            if distribucion_tapas == "Proporcional (20/35/45)" and cant_cajones == 3:
                alturas_tapas = [espacio_util_total * 0.20, espacio_util_total * 0.35, espacio_util_total * 0.45]
            else:
                divisor = cant_cajones if cant_cajones > 0 else 1
                alturas_tapas = [espacio_util_total / divisor] * int(cant_cajones)

            for i, alto_tapa in enumerate(alturas_tapas):
                despiece.append({"Pieza": f"Tapa de Cajón {i+1}", "Cant": 1, "L": round(alto_tapa, 1), "A": ancho_tapa_bvm, "Tipo": "Frente"})

            ancho_caja_total = ancho_interno_total - (esp_corredera * 2)
            ancho_frente_int = ancho_caja_total - (esp_real * 2)
            despiece.append({"Pieza": "Lateral Cajón",        "Cant": int(cant_cajones * 2), "L": 150, "A": largo_lateral_caja,                 "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Frente/Fondo Interno", "Cant": int(cant_cajones * 2), "L": 150, "A": ancho_frente_int,                   "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Piso Cajón",           "Cant": int(cant_cajones),     "L": round(largo_lateral_caja - 20, 1), "A": round(ancho_caja_total - 20, 1), "Tipo": "Piso"})

    # -----------------------------------------------------------------------
    # ALACENA
    # -----------------------------------------------------------------------
    elif tipo == "Alacena":
        ancho_base = ancho_m - (esp_real * 2)

        despiece.append({"Pieza": "Piso (Base)",        "Cant": 1, "L": ancho_base,        "A": prof_m,       "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Techo",              "Cant": 1, "L": ancho_m,           "A": prof_m,       "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Lateral",            "Cant": 2, "L": alto_m - esp_real, "A": prof_m,       "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_base,        "A": 100,          "Tipo": "Cuerpo"})

        if not sin_fondo:
            despiece.append({"Pieza": "Fondo", "Cant": 1, "L": alto_m - 10, "A": ancho_m - 10, "Tipo": "Fondo"})

        if cant_puertas in [3, 4]:
            despiece.append({"Pieza": "Parante Intermedio", "Cant": 1, "L": alto_m - (esp_real * 2), "A": prof_m - 20, "Tipo": "Cuerpo"})

        prof_est = prof_m - 30
        if cant_puertas == 2:
            ancho_est_ref = ancho_base
            ancho_est_ref_grande = ancho_est_ref
            ancho_est_ref_chico  = ancho_est_ref
        elif cant_puertas == 3:
            ancho_est_ref_grande = round(((ancho_m / 3) * 2) - (esp_real * 2), 1)
            ancho_est_ref_chico  = round((ancho_m / 3) - (esp_real * 1.5), 1)
            ancho_est_ref        = ancho_est_ref_grande
        else:
            ancho_est_ref = round((ancho_m / 2) - (esp_real * 1.5), 1)
            ancho_est_ref_grande = ancho_est_ref
            ancho_est_ref_chico  = ancho_est_ref

        if estantes_fijos > 0:
            if cant_puertas == 3:
                despiece.append({"Pieza": "Estante Fijo (V2/3)", "Cant": int(estantes_fijos), "L": ancho_est_ref_grande, "A": prof_est, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Estante Fijo (V1/3)", "Cant": int(estantes_fijos), "L": ancho_est_ref_chico,  "A": prof_est, "Tipo": "Cuerpo"})
            else:
                despiece.append({"Pieza": "Estante Fijo", "Cant": int(estantes_fijos), "L": ancho_est_ref, "A": prof_est, "Tipo": "Cuerpo"})

        if estantes_moviles > 0:
            if cant_puertas == 3:
                despiece.append({"Pieza": "Estante Móvil (V2/3)", "Cant": int(estantes_moviles), "L": ancho_est_ref_grande - 2, "A": prof_est, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Estante Móvil (V1/3)", "Cant": int(estantes_moviles), "L": ancho_est_ref_chico - 2,  "A": prof_est, "Tipo": "Cuerpo"})
            else:
                despiece.append({"Pieza": "Estante Móvil", "Cant": int(estantes_moviles), "L": ancho_est_ref - 2, "A": prof_est, "Tipo": "Cuerpo"})

        if "Uñero" in tipo_tapa or "Unero" in tipo_tapa:
            alto_p = alto_m + 20
            if tiene_cenefa:
                despiece.append({"Pieza": "Cenefa", "Cant": 1, "L": ancho_m, "A": alto_cenefa if alto_cenefa > 0 else 50, "Tipo": "Frente"})
        elif "Embutida" in tipo_tapa:
            alto_p = alto_m - (esp_real * 2) - 6
        else:
            alto_p = alto_m - 4

        if "Embutida" in tipo_tapa:
            if cant_puertas == 2:   ancho_p = (ancho_base - 10) / 2
            elif cant_puertas == 3: ancho_p = (ancho_m - (esp_real * 3) - 16) / 3
            else:                   ancho_p = (ancho_m - (esp_real * 3) - 20) / 4
        else:
            if cant_puertas == 2:   ancho_p = (ancho_m - 8) / 2
            elif cant_puertas == 3: ancho_p = (ancho_m - 12) / 3
            else:                   ancho_p = (ancho_m - 16) / 4

        despiece.append({"Pieza": "Puerta", "Cant": cant_puertas, "L": alto_p, "A": round(ancho_p, 1), "Tipo": "Frente"})

    # -----------------------------------------------------------------------
    # PLACARD
    # -----------------------------------------------------------------------
    elif tipo == "Placard":
        # ── CAJA ESTRUCTURAL ──────────────────────────────────────────────
        # Igual que Alacena: techo tapa los laterales, piso va entre laterales
        ancho_interno = ancho_m - (esp_real * 2)
        alto_lateral  = alto_m - esp_real          # lateral = alto total - 1 espesor (techo lo tapa)

        despiece.append({"Pieza": "Techo",    "Cant": 1, "L": ancho_m,      "A": prof_m, "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Piso",     "Cant": 1, "L": ancho_interno, "A": prof_m, "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Lateral",  "Cant": 2, "L": alto_lateral,  "A": prof_m, "Tipo": "Cuerpo"})

        # Fondo opcional
        if not sin_fondo:
            despiece.append({"Pieza": "Fondo", "Cant": 1, "L": alto_m - 10, "A": ancho_m - 10, "Tipo": "Fondo"})

        # Frentin superior opcional (mismo que bajo mesada: ancho interno x 50mm)
        if tiene_parante:  # reutilizamos tiene_parante como flag "lleva frentín"
            despiece.append({"Pieza": "Frentín Superior", "Cant": 1, "L": ancho_interno, "A": 50, "Tipo": "Cuerpo"})

        # ── DIVISIÓN CENTRAL ──────────────────────────────────────────────
        # division_placard: "Sin división" | "Una división central" | "Dos divisiones"
        tiene_division = division_placard != "Sin división"
        cant_divisiones = 0
        if division_placard == "Una división central":
            cant_divisiones = 1
        elif division_placard == "Dos divisiones":
            cant_divisiones = 2

        if cant_divisiones > 0:
            # Parante vertical: alto_lateral x prof_m (igual que lateral)
            # Mismo criterio que alacena: alto - 2 espesores (piso y techo lo contienen)
            alto_parante = alto_m - (esp_real * 2)
            despiece.append({
                "Pieza": "Parante Divisor",
                "Cant":  cant_divisiones,
                "L":     alto_parante,
                "A":     prof_m,
                "Tipo":  "Cuerpo"
            })

        # ── CÁLCULO DE ANCHOS DE ZONA ─────────────────────────────────────
        # Con 1 división → zona izquierda y zona derecha, ancho = ancho_interno / 2
        # Con 2 divisiones → tres zonas, ancho = ancho_interno / 3
        # Sin división → una sola zona, ancho = ancho_interno
        if cant_divisiones == 0:
            ancho_zona = ancho_interno
            zonas = [("", zona_unica, cant_estantes_unica_fijos, cant_estantes_unica_moviles)]
        elif cant_divisiones == 1:
            ancho_zona = (ancho_interno - esp_real) / 2
            zonas = [
                ("Izq", zona_izq, cant_estantes_izq_fijos, cant_estantes_izq_moviles),
                ("Der", zona_der, cant_estantes_der_fijos, cant_estantes_der_moviles),
            ]
        else:  # 2 divisiones → 3 zonas
            ancho_zona = (ancho_interno - esp_real * 2) / 3
            zonas = [
                ("Izq",  zona_izq,   cant_estantes_izq_fijos,   cant_estantes_izq_moviles),
                ("Med",  zona_unica, cant_estantes_unica_fijos, cant_estantes_unica_moviles),
                ("Der",  zona_der,   cant_estantes_der_fijos,   cant_estantes_der_moviles),
            ]

        prof_est = prof_m - 30   # profundidad de estantes: mismo criterio que alacena

        for sufijo, zona_tipo, est_fijos, est_moviles in zonas:
            label = f" {sufijo}" if sufijo else ""

            if zona_tipo == "Solo estantes":
                if est_fijos > 0:
                    despiece.append({"Pieza": f"Estante Fijo{label}",  "Cant": int(est_fijos),  "L": round(ancho_zona, 1),     "A": prof_est, "Tipo": "Cuerpo"})
                if est_moviles > 0:
                    despiece.append({"Pieza": f"Estante Móvil{label}", "Cant": int(est_moviles), "L": round(ancho_zona - 2, 1), "A": prof_est, "Tipo": "Cuerpo"})

            elif zona_tipo == "Ropa colgada":
                # Estante superior encima del tubo (mismo ancho que estante fijo)
                despiece.append({"Pieza": f"Estante Superior{label}", "Cant": 1, "L": round(ancho_zona, 1), "A": prof_est, "Tipo": "Cuerpo"})
                # El tubo no es una pieza de madera → se anota como referencia
                despiece.append({"Pieza": f"Tubo Ropero{label} (ref.)", "Cant": 1, "L": round(ancho_zona, 1), "A": 35, "Tipo": "Herraje"})
                # Estantes adicionales debajo del tubo si los hay
                if est_fijos > 0:
                    despiece.append({"Pieza": f"Estante Fijo inf.{label}",  "Cant": int(est_fijos),  "L": round(ancho_zona, 1),     "A": prof_est, "Tipo": "Cuerpo"})
                if est_moviles > 0:
                    despiece.append({"Pieza": f"Estante Móvil inf.{label}", "Cant": int(est_moviles), "L": round(ancho_zona - 2, 1), "A": prof_est, "Tipo": "Cuerpo"})

            elif zona_tipo == "Cajones":
                # Los cajones ocupan solo una parte del alto del placard (zona inferior).
                # El carpintero define la altura de la cajonera mediante altura_cajonera_placard.
                # Por defecto: 600mm (aprox. 3 cajones de 150mm c/u + separaciones).
                cant_caj = int(cant_cajones_placard) if cant_cajones_placard > 0 else 3
                alto_cajonera = kwargs.get("altura_cajonera_placard", 600)  # alto real de la zona de cajones
                ancho_int_zona = ancho_zona - (esp_real * 2)

                # Tapas: se calculan sobre el alto de la cajonera, NO el alto del placard
                esp_util      = alto_cajonera - 30 - ((cant_caj - 1) * luz_entre_tapas)
                alto_tapa_caj = max(50, esp_util / cant_caj)  # mínimo 50mm por tapa
                ancho_tapa_caj = ancho_zona - luz_perimetral_tapa

                for i in range(cant_caj):
                    despiece.append({"Pieza": f"Tapa Cajón{label} {i+1}", "Cant": 1, "L": round(alto_tapa_caj, 1), "A": round(ancho_tapa_caj, 1), "Tipo": "Frente"})

                # Estructura interna de los cajones (laterales, fondos, pisos)
                ancho_caja_caj   = ancho_int_zona - (esp_corredera * 2)
                ancho_frente_caj = ancho_caja_caj - (esp_real * 2)
                largo_lat_caj    = prof_m - aire_trasero
                alto_caja_caj    = 150  # altura estándar del cajón interno

                despiece.append({"Pieza": f"Lateral Cajón{label}",     "Cant": cant_caj * 2, "L": alto_caja_caj, "A": largo_lat_caj,                           "Tipo": "Cuerpo"})
                despiece.append({"Pieza": f"Frente/Fondo Int.{label}", "Cant": cant_caj * 2, "L": alto_caja_caj, "A": round(ancho_frente_caj, 1),               "Tipo": "Cuerpo"})
                despiece.append({"Pieza": f"Piso Cajón{label}",        "Cant": cant_caj,     "L": round(largo_lat_caj - 20, 1), "A": round(ancho_caja_caj - 20, 1), "Tipo": "Piso"})

    # -----------------------------------------------------------------------
    # PANEL A MEDIDA
    # -----------------------------------------------------------------------
    elif tipo == "Pieza Suelta":
        # Sin lógica automática — el carpintero ingresa L, A y cantidad.
        # La descripción (nota_pieza) se usa como nombre en la planilla.
        _nombre_pieza = kwargs.get("nota_pieza", "").strip() or "Pieza Suelta"
        despiece.append({
            "Pieza": _nombre_pieza,
            "Cant":  int(cant_paneles) if cant_paneles > 0 else 1,
            "L":     ancho_m,
            "A":     alto_m,
            "Tipo":  "Cuerpo",
        })

    return despiece
    
