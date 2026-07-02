from .despiece import generar_despiece_bvm, obtener_veta_automatica, calcular_medida_frente
from .retazos import es_retazo_util, pieza_entra_en_retazo, calcular_ahorro_retazos
from .exportadores import generar_pdf_presupuesto, generar_dxf_bvm, exportar_para_aspire, generar_link_whatsapp
from .brs_bks import validar_medidas_brs, validar_herrajes_bks

try:
    from .optimizador import optimizar_obra, generar_svg_placa, PLACA_ANCHO_DEFAULT, PLACA_ALTO_DEFAULT
except ImportError:
    optimizar_obra = None
    generar_svg_placa = None
    PLACA_ANCHO_DEFAULT = 2440.0
    PLACA_ALTO_DEFAULT = 1830.0
