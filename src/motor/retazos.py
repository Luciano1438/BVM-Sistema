 motor/retazos.py
# Lógica de arbitraje de retazos BVM
# Sin Streamlit. Recibe datos, devuelve resultados.

MIN_ANCHO = 150  # mm
MIN_LARGO = 400  # mm


def es_retazo_util(largo: float, ancho: float) -> bool:
    """Valida si un retazo supera el mínimo BVM (150x400 en cualquier orientación)."""
    return (largo >= MIN_LARGO and ancho >= MIN_ANCHO) or \
           (largo >= MIN_ANCHO and ancho >= MIN_LARGO)


def pieza_entra_en_retazo(retazo: dict, pieza: dict) -> bool:
    """
    Verifica si una pieza entra en un retazo, considerando ambas orientaciones.
    retazo : dict con claves 'largo' y 'ancho'
    pieza  : dict con claves 'L' y 'A'
    """
    L, A = float(pieza["L"]), float(pieza["A"])
    rl, ra = float(retazo["largo"]), float(retazo["ancho"])
    return (rl >= L and ra >= A) or (rl >= A and ra >= L)


def calcular_ahorro_retazos(
    df_corte,           # pandas DataFrame con columnas L, A, Cant
    retazos: list,      # lista de dicts desde Supabase
    precio_placa: float,# precio por placa (5.03 m²)
) -> tuple[float, list]:
    """
    Cruza el despiece contra los retazos disponibles.

    Retorna
    -------
    ahorro_total : float  — ahorro en pesos
    matches      : list   — [{"pieza": str, "retazo_id": int, "ahorro": float}]
    """
    ahorro_total = 0.0
    matches = []

    retazos_utiles = [r for r in retazos if es_retazo_util(r["largo"], r["ancho"])]

    for _, row in df_corte.iterrows():
        for ret in retazos_utiles:
            if pieza_entra_en_retazo(ret, row):
                m2_pieza = (float(row["L"]) * float(row["A"])) / 1_000_000
                ahorro   = m2_pieza * (precio_placa / 5.03)
                ahorro_total += ahorro
                matches.append({
                    "pieza":     row["Pieza"],
                    "retazo_id": ret["id"],
                    "ahorro":    round(ahorro, 2),
                })
                break  # una pieza se asigna a un solo retazo

    return round(ahorro_total, 2), matches
