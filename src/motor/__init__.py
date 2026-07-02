from .despiece import generar_despiece_bvm, obtener_veta_automatica, calcular_medida_frente
from .retazos import es_retazo_util, pieza_entra_en_retazo, calcular_ahorro_retazos
try:
    from .exportadores import generar_pdf_presupuesto, generar_dxf_bvm, exportar_para_aspire, generar_link_whatsapp
except ImportError:
    def _exportador_no_disponible(*args, **kwargs):
        raise RuntimeError("Exportadores no disponibles: falta una dependencia opcional.")

    generar_pdf_presupuesto = _exportador_no_disponible
    generar_dxf_bvm = _exportador_no_disponible
    exportar_para_aspire = _exportador_no_disponible
    generar_link_whatsapp = _exportador_no_disponible

try:
    from .brs_bks import validar_medidas_brs, validar_herrajes_bks
except ImportError:
    def validar_medidas_brs(params: dict) -> list[str]:
        return []

    def validar_herrajes_bks(params: dict, config: dict) -> list[str]:
        return []

try:
    from .optimizador import optimizar_obra, generar_svg_placa, PLACA_ANCHO_DEFAULT, PLACA_ALTO_DEFAULT
except ImportError:
    optimizar_obra = None
    generar_svg_placa = None
    PLACA_ANCHO_DEFAULT = 2440.0
    PLACA_ALTO_DEFAULT = 1830.0
