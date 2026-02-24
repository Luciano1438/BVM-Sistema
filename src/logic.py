import hashlib
def hash_pass(password):
    return hashlib.sha256(str.encode(password)).hexdigest()
  def obtener_veta_automatica(nombre_pieza, material_seleccionado):
    """
    Si es Blanco, la veta es libre. Si es enchapado, sigue la regla de BVM.
    """
    material_lower = material_seleccionado.lower()
    
    # REGLA DE EFICIENCIA: Si es blanco, no desperdiciamos placa con orientaciones fijas
    if "blanco" in material_lower:
        return "Libre (Cualquier sentido)"
    
    # Regla de tu viejo para materiales con veta (enchapados/colores)
    nombre_lower = nombre_pieza.lower()
    if any(x in nombre_lower for x in ["lateral exterior", "puerta", "tapa de cajon", "fondo"]):
        return "Vertical (Hacia Arriba)"
    return "Horizontal (Izquierda a Derecha)"
def calcular_medida_frente_pro(ancho_hueco, alto_hueco, config, tipo="Superpuesto"):
    # En lugar de -4 hardcoded, usamos la variable del sistema
    descuento = config.get('luz_puerta_perimetral', 2.0) * 2
    
    ancho_real = ancho_hueco - descuento
    alto_real = alto_hueco - descuento
    
    return ancho_real, alto_real
