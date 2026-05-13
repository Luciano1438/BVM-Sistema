# motor/despiece.py
# Motor de Despiece Geométrico BVM
# Lógica pura de taller — sin Streamlit, sin Supabase.
# Entrada: medidas y parámetros. Salida: lista de piezas lista para corte.

# --- PARÁMETROS TÉCNICOS DE TALLER ---
CONFIG_TECNICA = {
    "ranura_profundidad": 10.0,
    "ranura_distancia_borde": 10.0,
    "retazo_min_ancho": 150,
    "retazo_min_largo": 400,
}


def obtener_veta_automatica(nombre_pieza: str, material_seleccionado: str) -> str:
    """
    Regla BVM de orientación de veta:
    - Blanco: libre (no desperdiciamos placa con orientaciones fijas).
    - Enchapados/colores: vertical para laterales, puertas y tapas; horizontal para el resto.
    """
    if "blanco" in material_seleccionado.lower():
        return "Libre (Cualquier sentido)"

    nombre_lower = nombre_pieza.lower()
    if any(x in nombre_lower for x in ["lateral exterior", "puerta", "tapa de cajon", "fondo"]):
        return "Vertical (Hacia Arriba)"
    return "Horizontal (Izquierda a Derecha)"


def calcular_medida_frente(
    ancho_hueco: float,
    alto_hueco: float,
    tipo_montaje: str = "Superpuesto",
    es_doble: bool = False,
) -> tuple[float, float]:
    """
    Calcula la medida real de la placa para un frente según tipo de montaje.
    Retorna (ancho_real, alto_real).
    """
    if tipo_montaje == "Superpuesto":
        return ancho_hueco - 4, alto_hueco - 4
    else:  # Embutido
        alto_real = alto_hueco - 6
        ancho_real = (ancho_hueco - 5) if es_doble else (ancho_hueco - 6)
        return ancho_real, alto_real


# ---------------------------------------------------------------------------
# MOTOR PRINCIPAL
# ---------------------------------------------------------------------------

def generar_despiece_bvm(
    tipo: str,
    ancho_m: float,
    alto_m: float,
    prof_m: float,
    esp_real: float,
    tiene_parante: bool,
    tipo_parante: str,
    distancia_parante: float,
    cant_cajones: int,
    tipo_tapa: str,
    tipo_base: str,
    altura_base: float,
    luz_entre_tapas: float,
    luz_perimetral_tapa: float,
    alto_frentin_emb: float,
    aire_trasero: float,
    esp_corredera: float,
    distribucion_tapas: str,
    cant_puertas: int = 0,
    tiene_cenefa: bool = False,
    alto_cenefa: float = 0.0,
    estantes_fijos: int = 0,
    estantes_moviles: int = 0,
    tipo_estante_manual: str = "Completo",
) -> list[dict]:
    """
    Genera la planilla de corte para un módulo de mueble.

    Parámetros
    ----------
    tipo              : "Bajo Mesada" | "Cajonera" | "Alacena"
    ancho_m / alto_m / prof_m : dimensiones externas del módulo en mm
    esp_real          : espesor real de la placa en mm (normalmente 18)
    tipo_estante_manual: "Completo" | "Medio"  (solo para Bajo Mesada)

    Retorna
    -------
    Lista de dicts con claves: Pieza, Cant, L, A, Tipo
    """
    despiece = []
    ancho_interno_total = ancho_m - (esp_real * 2)

    # -----------------------------------------------------------------------
    # BAJO MESADA
    # -----------------------------------------------------------------------
    if tipo == "Bajo Mesada":

        # 1. Base y laterales
        despiece.append({"Pieza": "Base Módulo",      "Cant": 1, "L": ancho_m,              "A": prof_m,  "Tipo": "Cuerpo"})
        altura_lateral = alto_m - esp_real
        despiece.append({"Pieza": "Lateral Exterior", "Cant": 2, "L": altura_lateral,        "A": prof_m,  "Tipo": "Cuerpo"})

        # 2. Frentines y estilos
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

        # 3. Refuerzos traseros
        despiece.append({"Pieza": "Travesaño Trasero (100)", "Cant": 1, "L": ancho_interno_total, "A": 100, "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Trasero (60)",  "Cant": 1, "L": ancho_interno_total, "A": 60,  "Tipo": "Cuerpo"})

        # 4. Fondo
        alto_fondo = alto_m - 80 - esp_real
        despiece.append({"Pieza": "Fondo Mueble", "Cant": 1, "L": alto_fondo, "A": ancho_m - 20, "Tipo": "Fondo"})

        # 5. Estantes
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
            despiece.append({
                "Pieza": f"{etiqueta_est} FIJO",
                "Cant": int(estantes_fijos * mult_cant),
                "L": round(ancho_est_final, 1),
                "A": prof_est,
                "Tipo": "Cuerpo",
            })
        if estantes_moviles > 0:
            despiece.append({
                "Pieza": f"{etiqueta_est} MÓVIL",
                "Cant": int(estantes_moviles * mult_cant),
                "L": round(ancho_est_final - 2, 1),
                "A": prof_est,
                "Tipo": "Cuerpo",
            })

        # 6. Parante y puertas
        if tiene_parante:
            ancho_par = prof_m if tipo_parante == "Largo (Fondo Lateral)" else 100
            despiece.append({"Pieza": "Parante Divisor", "Cant": 1, "L": altura_lateral, "A": ancho_par, "Tipo": "Cuerpo"})
            ancho_p = (
                (ancho_m - (esp_real * 3) - 16) / 3
                if tipo_tapa == "Embutida"
                else (ancho_m - 12) / 3
            )
            despiece.append({"Pieza": "Puerta", "Cant": 3, "L": alto_puerta, "A": round(ancho_p, 1), "Tipo": "Frente"})
        else:
            ancho_p = (
                (ancho_m - (esp_real * 2) - 10) / 2
                if tipo_tapa == "Embutida"
                else (ancho_m - 8) / 2
            )
            despiece.append({"Pieza": "Puerta", "Cant": 2, "L": alto_puerta, "A": round(ancho_p, 1), "Tipo": "Frente"})

    # -----------------------------------------------------------------------
    # CAJONERA
    # -----------------------------------------------------------------------
    elif tipo == "Cajonera":
        altura_caja_real = alto_m
        if tipo_base in ["Banquina de Obra", "Patas Plásticas"]:
            altura_caja_real = alto_m - altura_base

        despiece.append({"Pieza": "Base Módulo",         "Cant": 1, "L": ancho_m,              "A": prof_m,   "Tipo": "Cuerpo"})
        altura_lateral_bvm = alto_m - esp_real
        despiece.append({"Pieza": "Lateral Exterior",    "Cant": 2, "L": altura_lateral_bvm,   "A": prof_m,   "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Superior",  "Cant": 1, "L": ancho_interno_total,  "A": 100,      "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Travesaño Trasero",   "Cant": 1, "L": ancho_interno_total,  "A": 60,       "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Frentín Frontal",     "Cant": 1, "L": ancho_interno_total,  "A": 50,       "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Fondo Mueble",        "Cant": 1, "L": alto_m - 20,          "A": ancho_m - 20, "Tipo": "Fondo"})

        if tipo_base == "Zócalo de Madera":
            despiece.append({"Pieza": "Zócalo Frontal", "Cant": 2, "L": altura_base,       "A": ancho_interno_total, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Zócalo Lateral", "Cant": 2, "L": altura_base,       "A": prof_m - 50,         "Tipo": "Cuerpo"})

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
                alturas_tapas = [
                    espacio_util_total * 0.20,
                    espacio_util_total * 0.35,
                    espacio_util_total * 0.45,
                ]
            else:
                divisor = cant_cajones if cant_cajones > 0 else 1
                alturas_tapas = [espacio_util_total / divisor] * int(cant_cajones)

            for i, alto_tapa in enumerate(alturas_tapas):
                despiece.append({"Pieza": f"Tapa de Cajón {i+1}", "Cant": 1, "L": round(alto_tapa, 1), "A": ancho_tapa_bvm, "Tipo": "Frente"})

            ancho_caja_total   = ancho_interno_total - (esp_corredera * 2)
            ancho_frente_int   = ancho_caja_total - (esp_real * 2)
            despiece.append({"Pieza": "Lateral Cajón",        "Cant": int(cant_cajones * 2), "L": 150, "A": largo_lateral_caja,              "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Frente/Fondo Interno", "Cant": int(cant_cajones * 2), "L": 150, "A": ancho_frente_int,                "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Piso Cajón",           "Cant": int(cant_cajones),     "L": round(largo_lateral_caja - 20, 1), "A": round(ancho_caja_total - 20, 1), "Tipo": "Piso"})

    # -----------------------------------------------------------------------
    # ALACENA
    # -----------------------------------------------------------------------
    elif tipo == "Alacena":
        ancho_base = ancho_m - (esp_real * 2)

        # 1. Estructura
        despiece.append({"Pieza": "Piso (Base)",        "Cant": 1, "L": ancho_base,         "A": prof_m,      "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Techo",              "Cant": 1, "L": ancho_m,            "A": prof_m,      "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Lateral",            "Cant": 2, "L": alto_m - esp_real,  "A": prof_m,      "Tipo": "Cuerpo"})
        despiece.append({"Pieza": "Fondo",              "Cant": 1, "L": alto_m - 10,        "A": ancho_m - 10,"Tipo": "Fondo"})
        despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_base,         "A": 100,         "Tipo": "Cuerpo"})

        # 2. Parante intermedio
        if cant_puertas in [3, 4]:
            despiece.append({"Pieza": "Parante Intermedio", "Cant": 1, "L": alto_m - (esp_real * 2), "A": prof_m - 20, "Tipo": "Cuerpo"})

        # 3. Estantes dinámicos
        prof_est = prof_m - 30

        if cant_puertas == 2:
            ancho_est_ref = ancho_base
            ancho_est_ref_grande = ancho_est_ref  # alias para uso unificado abajo
            ancho_est_ref_chico  = ancho_est_ref
            puertas_con_particion = False
        elif cant_puertas == 3:
            ancho_est_ref_grande = round(((ancho_m / 3) * 2) - (esp_real * 2), 1)
            ancho_est_ref_chico  = round((ancho_m / 3) - (esp_real * 1.5), 1)
            ancho_est_ref        = ancho_est_ref_grande  # fallback
            puertas_con_particion = True
        else:  # 4 puertas
            ancho_est_ref = round((ancho_m / 2) - (esp_real * 1.5), 1)
            ancho_est_ref_grande = ancho_est_ref
            ancho_est_ref_chico  = ancho_est_ref
            puertas_con_particion = False

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

        # 4. Puertas y frentes
        if "Uñero" in tipo_tapa:
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

    return despiece
