"""Hooks vacios para conectar reglas BRS/BKS sin acoplarlas a la UI.

La interfaz de Streamlit solo recolecta datos y muestra resultados. Las reglas
estructurales y heuristicas deben vivir en este paquete cuando esten listas.
"""


def validar_medidas_brs(params: dict) -> list[str]:
    """TODO: Inyectar logica BRS estructural aqui."""
    return []


def validar_herrajes_bks(params: dict, config: dict) -> list[str]:
    """TODO: Inyectar logica BKS de herrajes y oficio aqui."""
    return []
