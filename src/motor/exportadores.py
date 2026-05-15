# motor/exportadores.py
# Generadores de archivos de salida BVM
# Sin Streamlit. Reciben datos, devuelven bytes o strings.

import io
import urllib.parse
from datetime import datetime, timedelta, timezone

import ezdxf
from fpdf import FPDF


# ---------------------------------------------------------------------------
# PDF DE PRESUPUESTO
# ---------------------------------------------------------------------------

def generar_pdf_presupuesto(datos: dict) -> bytes:
    """
    Genera el PDF comercial del presupuesto.

    datos debe tener:
        cliente, mueble, precio, material,
        ancho, alto, prof, entrega, pct_seña
    """
    pdf = FPDF()
    pdf.add_page()

    # Cabecera
    pdf.set_font("Arial", "B", 20)
    pdf.set_text_color(46, 125, 50)
    pdf.cell(200, 20, "PRESUPUESTO COMERCIAL - BVM", ln=True, align="C")

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 10)
    tz_arg   = timezone(timedelta(hours=-3))
    fecha_hoy = datetime.now(tz_arg).strftime("%d/%m/%Y")
    pdf.cell(200, 10, f"Fecha de emisión: {fecha_hoy}", ln=True, align="R")

    # Detalles del proyecto
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "DETALLES DEL PROYECTO", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Cliente: {datos['cliente']}", ln=True)
    pdf.cell(0, 8, f"Proyecto: {datos['mueble']}", ln=True)
    pdf.cell(0, 8, f"Dimensiones Generales: {datos['ancho']} x {datos['alto']} x {datos['prof']} mm", ln=True)
    pdf.cell(0, 8, f"Material Principal: {datos['material']}", ln=True)
    pdf.ln(5)

    # Condiciones y entrega
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "CONDICIONES Y ENTREGA", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Tiempo estimado de entrega: {datos['entrega']} días hábiles.", ln=True)

    monto_seña = datos["precio"] * (datos["pct_seña"] / 100)
    pdf.cell(0, 8, f"Monto de Seña ({datos['pct_seña']}%): ${monto_seña:,.2f}", ln=True)

    # Precio final
    pdf.set_font("Arial", "B", 16)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 15, f"VALOR TOTAL: ${datos['precio']:,.2f}", ln=True, align="C", fill=True)

    pdf.ln(10)
    pdf.set_font("Arial", "I", 9)
    pdf.multi_cell(
        0, 5,
        "Nota: Los precios están sujetos a cambios por volatilidad de insumos "
        "si no se abona la seña dentro de las 48hs.",
    )

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# DXF PARA CNC
# ---------------------------------------------------------------------------

def generar_dxf_bvm(df) -> bytes:
    """
    Genera un archivo DXF con cada pieza dibujada como rectángulo.
    df : pandas DataFrame con columnas Pieza, L, A, Cant
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    x_offset = 0
    margen   = 50

    for _, row in df.iterrows():
        largo  = float(row["L"])
        ancho  = float(row["A"])
        cant   = int(row["Cant"])
        nombre = str(row["Pieza"])

        for _ in range(cant):
            puntos = [
                (x_offset, 0),
                (x_offset + largo, 0),
                (x_offset + largo, ancho),
                (x_offset, ancho),
                (x_offset, 0),
            ]
            msp.add_lwpolyline(puntos, close=True)
            msp.add_text(nombre, height=15).set_placement((x_offset + 5, 5))
            x_offset += largo + margen

    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# CSV PARA ASPIRE / CNC
# ---------------------------------------------------------------------------

def exportar_para_aspire(df, material: str, espesor: float) -> bytes:
    """
    Genera el CSV en formato que espera Vectric Aspire.
    df : pandas DataFrame con columnas Pieza, L, A, Cant
    """
    df_aspire = df.copy().rename(columns={
        "Pieza": "Name",
        "L":     "Length",
        "A":     "Width",
        "Cant":  "Quantity",
    })
    df_aspire["Thickness"] = espesor
    df_aspire["Material"]  = material

    columnas = ["Name", "Length", "Width", "Thickness", "Quantity", "Material"]
    existentes = [c for c in columnas if c in df_aspire.columns]
    return df_aspire[existentes].to_csv(index=False, sep=",", decimal=".").encode("utf-8")


# ---------------------------------------------------------------------------
# LINK DE WHATSAPP
# ---------------------------------------------------------------------------

def generar_link_whatsapp(datos: dict) -> str:
    """
    Genera el link de WhatsApp con el resumen del presupuesto.
    datos : mismo dict que generar_pdf_presupuesto
    """
    monto_seña = datos["precio"] * (datos["pct_seña"] / 100)
    lineas = [
        f"*PRESUPUESTO BVM - {datos['mueble'].upper()}*",
        "",
        "Hola! Te envío los detalles de la cotización:",
        "",
        f"Medidas: {datos['ancho']}x{datos['alto']}x{datos['prof']} mm",
        f"Material: {datos['material']}",
        f"Entrega: {datos['entrega']} días hábiles",
        "",
        f"VALOR TOTAL: ${datos['precio']:,.2f}",
        f"SEÑA REQUERIDA ({datos['pct_seña']}%): ${monto_seña:,.2f}",
        "",
        "Nota: Los precios se mantienen por 48hs. "
        "Una vez abonada la seña, se congelan los materiales y comienza la producción.",
    ]
    texto_url = urllib.parse.quote("\n".join(lineas))
    return f"https://wa.me/?text={texto_url}"
