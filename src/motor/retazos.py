# motor/retazos.py

MIN_ANCHO = 150
MIN_LARGO = 400


def es_retazo_util(largo, ancho):
    return (largo >= MIN_LARGO and ancho >= MIN_ANCHO) or \
           (largo >= MIN_ANCHO and ancho >= MIN_LARGO)


def pieza_entra_en_retazo(retazo, pieza):
    L = float(pieza["L"])
    A = float(pieza["A"])
    rl = float(retazo["largo"])
    ra = float(retazo["ancho"])
    return (rl >= L and ra >= A) or (rl >= A and ra >= L)


def calcular_ahorro_retazos(df_corte, retazos, precio_placa):
    ahorro_total = 0.0
    matches = []

    if df_corte.empty or not retazos:
        return ahorro_total, matches

    retazos_utiles = [r for r in retazos if es_retazo_util(r["largo"], r["ancho"])]

    for _, row in df_corte.iterrows():
        for ret in retazos_utiles:
            if pieza_entra_en_retazo(ret, row):
                m2_pieza = (float(row["L"]) * float(row["A"])) / 1_000_000
                ahorro = m2_pieza * (precio_placa / 5.03)
                ahorro_total += ahorro
                matches.append({
                    "pieza": row["Pieza"],
                    "retazo_id": ret["id"],
                    "ahorro": round(ahorro, 2),
                })
                break

    return round(ahorro_total, 2), matches
