import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import io
import ezdxf
import urllib.parse
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from fpdf import FPDF
from motor import (
    generar_despiece_bvm,
    obtener_veta_automatica,
    calcular_medida_frente,
    calcular_ahorro_retazos,
)

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / '.env')

try:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
except:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

if url and key:
    supabase: Client = create_client(url, key)
else:
    st.error("Error: No se cargaron las credenciales.")


# ===========================================================================
# EXPORTADORES — DXF, CSV, PDF, WHATSAPP
# ===========================================================================

def generar_dxf_obra(modulos_con_df):
    """Genera DXF con todos los módulos, separados por módulo, con material y espesor."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    y_offset = 0
    margen_modulo = 100

    for mod in modulos_con_df:
        df = mod.get("df_corte")
        nombre_mod = mod.get("nombre", "Modulo")
        material = mod.get("material", "")
        if df is None or df.empty:
            continue

        # Título del módulo
        msp.add_text(f"=== {nombre_mod} | {material} ===", height=20).set_placement((0, y_offset + 10))
        y_offset += 40

        x_offset = 0
        for _, row in df.iterrows():
            largo  = float(row['L'])
            ancho  = float(row['A'])
            cant   = int(row['Cant'])
            nombre = str(row['Pieza'])
            tipo   = str(row.get('Tipo', ''))

            for _ in range(cant):
                puntos = [
                    (x_offset, y_offset),
                    (x_offset + largo, y_offset),
                    (x_offset + largo, y_offset + ancho),
                    (x_offset, y_offset + ancho),
                    (x_offset, y_offset),
                ]
                msp.add_lwpolyline(puntos, close=True)
                etiqueta = f"{nombre}\n{int(largo)}x{int(ancho)} | {material}"
                msp.add_text(etiqueta, height=10).set_placement((x_offset + 5, y_offset + 5))
                x_offset += largo + 50

        y_offset += 600 + margen_modulo

    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode('utf-8')


def exportar_csv_obra(modulos_con_df, esp_real):
    """Genera CSV con todos los módulos para Aspire, separados por módulo."""
    filas = []
    for mod in modulos_con_df:
        df = mod.get("df_corte")
        nombre_mod = mod.get("nombre", "Modulo")
        material = mod.get("material", "")
        if df is None or df.empty:
            continue
        filas.append({"Name": f"=== {nombre_mod} ===", "Length": "", "Width": "", "Thickness": "", "Quantity": "", "Material": ""})
        for _, row in df.iterrows():
            filas.append({
                "Name": f"{row['Pieza']} [{nombre_mod}]",
                "Length": row['L'],
                "Width": row['A'],
                "Thickness": esp_real,
                "Quantity": row['Cant'],
                "Material": material,
            })
    return pd.DataFrame(filas).to_csv(index=False).encode('utf-8')


def generar_pdf_obra(cliente, modulos, dias_entrega, pct_seña, costo_logistica=0, dias_colocacion=0, costo_colocacion_dia=0):
    pdf = FPDF()
    pdf.add_page()
    
    # Colores Corporativos BVM
    r_main, g_main, b_main = 15, 110, 86  # Verde BVM (#0F6E56)
    
    # --- HEADER ---
    pdf.set_font("Arial", "B", 22)
    pdf.set_text_color(r_main, g_main, b_main)
    pdf.cell(100, 10, "PROPUESTA DE DISEÑO", ln=False, align="L")
    
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(120, 120, 120)
    tz_arg = timezone(timedelta(hours=-3))
    fecha_hoy = datetime.now(tz_arg).strftime("%d/%m/%Y")
    pdf.cell(90, 10, f"FECHA: {fecha_hoy}", ln=True, align="R")
    
    pdf.set_draw_color(220, 220, 220)
    pdf.line(10, 22, 200, 22)
    pdf.ln(8)
    
    # --- DATOS DEL CLIENTE ---
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(100, 5, "PREPARADO PARA:", ln=True)
    pdf.set_font("Arial", "B", 13)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(100, 6, cliente.upper(), ln=True)
    pdf.ln(8)
    
    # --- ENCABEZADO DE TABLA ---
    pdf.set_fill_color(r_main, g_main, b_main)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(10, 8, "#", border=0, fill=True, align="C")
    pdf.cell(90, 8, "DESCRIPCIÓN DEL MÓDULO", border=0, fill=True)
    pdf.cell(45, 8, "MEDIDAS (mm)", border=0, fill=True, align="C")
    pdf.cell(45, 8, "SUBTOTAL", border=0, fill=True, align="R")
    pdf.ln(8)
    
    # --- ÍTEMS ---
    pdf.set_text_color(40, 40, 40)
    pdf.set_font("Arial", "", 10)
    fill = False
    pdf.set_fill_color(245, 248, 247)
    
    subtotal_modulos = sum(m["precio"] for m in modulos)
    costo_col = dias_colocacion * costo_colocacion_dia
    total_obra = subtotal_modulos + costo_logistica + costo_col
    
    for i, mod in enumerate(modulos):
        pdf.cell(10, 10, str(i+1), fill=fill, align="C")
        desc = f"{mod['nombre']} | {mod['material']}"
        desc_corta = desc[:48] + "..." if len(desc) > 48 else desc
        pdf.cell(90, 10, desc_corta, fill=fill)
        medidas = f"{int(mod['ancho'])} x {int(mod['alto'])} x {int(mod['prof'])}"
        pdf.cell(45, 10, medidas, fill=fill, align="C")
        pdf.set_font("Arial", "B", 10)
        pdf.cell(45, 10, f"${mod['precio']:,.0f} ", fill=fill, align="R")
        pdf.set_font("Arial", "", 10)
        pdf.ln(10)
        fill = not fill
        
    # --- ADICIONALES DE LOGÍSTICA ---
    if costo_logistica > 0 or costo_col > 0:
        pdf.ln(2)
        pdf.set_font("Arial", "", 10)
        pdf.set_text_color(100, 100, 100)
        adicional = costo_logistica + costo_col
        pdf.cell(145, 8, "Costos de Flete e Instalación:", align="R")
        pdf.set_text_color(40, 40, 40)
        pdf.cell(45, 8, f"${adicional:,.0f} ", align="R")
        pdf.ln(8)
        
    # --- BLOQUE DE TOTAL ---
    pdf.ln(4)
    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(r_main, g_main, b_main)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(145, 14, "INVERSIÓN TOTAL DE OBRA", align="R", fill=True)
    pdf.cell(45, 14, f"${total_obra:,.0f} ", align="R", fill=True)
    pdf.ln(20)
    
    # --- TÉRMINOS Y CONDICIONES ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 6, "TÉRMINOS Y CONDICIONES DEL PROYECTO", ln=True)
    pdf.set_font("Arial", "", 9)
    pdf.set_text_color(80, 80, 80)
    
    monto_seña = total_obra * (pct_seña / 100)
    pdf.cell(0, 5, f"1. Anticipo requerido para acopio de materiales y congelamiento de precios ({pct_seña}%): ${monto_seña:,.0f}", ln=True)
    pdf.cell(0, 5, f"2. Tiempo estimado de entrega: {dias_entrega} días hábiles desde la acreditación del anticipo.", ln=True)
    pdf.cell(0, 5, "3. Validez de esta cotización: 48 horas.", ln=True)
    pdf.cell(0, 5, "4. Saldo restante a cancelar contra entrega e instalación de la obra.", ln=True)
    
    # --- FIRMAS ---
    pdf.ln(25)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(20, pdf.get_y(), 80, pdf.get_y())
    pdf.line(130, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(90, 5, "Firma y Aclaración del Cliente", align="C")
    pdf.cell(20, 5, "")
    pdf.cell(80, 5, "Aprobación del Taller", align="C")
    
    return bytes(pdf.output())


def generar_link_whatsapp_obra(cliente, modulos, dias_entrega, pct_seña, costo_logistica=0, dias_colocacion=0, costo_colocacion_dia=0):
    subtotal = sum(m["precio"] for m in modulos)
    costo_col = dias_colocacion * costo_colocacion_dia
    total_obra = subtotal + costo_logistica + costo_col
    monto_seña = total_obra * (pct_seña / 100)
    lineas = [f"*PRESUPUESTO DE OBRA BVM*", f"Cliente: {cliente}", ""]
    for i, mod in enumerate(modulos):
        lineas.append(f"- Modulo {i+1}: {mod['nombre']} ({mod['ancho']}x{mod['alto']}x{mod['prof']} mm) - ${mod['precio']:,.0f}")
    if costo_logistica > 0:
        lineas.append(f"- Flete/Logistica: ${costo_logistica:,.0f}")
    if costo_col > 0:
        lineas.append(f"- Colocacion: ${costo_col:,.0f}")
    lineas += ["", f"*TOTAL OBRA: ${total_obra:,.0f}*", f"Seña ({pct_seña}%): ${monto_seña:,.0f}", f"Entrega: {dias_entrega} dias habiles", "", "Precios validos 48hs."]
    return f"https://wa.me/?text={urllib.parse.quote(chr(10).join(lineas))}"


# ===========================================================================
# BASE DE DATOS
# ===========================================================================

def refrescar_sesion():
    """Refresca el token JWT si expiró."""
    try:
        res = supabase.auth.refresh_session()
        if res and res.session:
            st.session_state["session"] = res.session
            st.session_state["user"] = res.user
            return True
    except:
        pass
    return False

def get_token():
    """Devuelve el token vigente, refrescando si es necesario."""
    if "session" not in st.session_state or not st.session_state["session"]:
        return None
    try:
        token = st.session_state["session"].access_token
        supabase.postgrest.auth(token)
        return token
    except Exception as e:
        if "JWT" in str(e) or "expired" in str(e).lower():
            if refrescar_sesion():
                return st.session_state["session"].access_token
        return None

def consultar_retazos_disponibles(material):
    try:
        token = get_token()
        if token: supabase.postgrest.auth(token)
        res = supabase.table("retazos").select("*").eq("user_id", st.session_state["user"].id).execute()
        return res.data
    except Exception as e:
        if "JWT" in str(e) or "expired" in str(e).lower() or "PGRST303" in str(e):
            if refrescar_sesion():
                try:
                    res = supabase.table("retazos").select("*").eq("user_id", st.session_state["user"].id).execute()
                    return res.data
                except:
                    pass
        st.warning("Sesión expirada. Recargá la página si el problema persiste.")
        return []

def registrar_retazo(material, largo, ancho):
    try:
        if (largo >= 400 and ancho >= 150) or (largo >= 150 and ancho >= 400):
            supabase.table("retazos").insert({"material": material, "largo": largo, "ancho": ancho, "user_id": st.session_state["user"].id}).execute()
            st.toast(f"Retazo guardado: {int(largo)}x{int(ancho)}")
        else:
            st.error(f"Error: {int(largo)}x{int(ancho)} inferior al mínimo 150x400.")
    except Exception as e:
        st.error(f"Error al registrar: {e}")

def gestionar_auth():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False
        st.session_state["user"] = None
    if not st.session_state["autenticado"]:
        st.title("BVM - Terminal de Operaciones")
        tab_login, tab_reg = st.tabs(["Ingresar", "Registro"])
        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email")
                pw    = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Entrar", use_container_width=True):
                    if email and pw:
                        with st.spinner("Conectando..."):
                            try:
                                res = supabase.auth.sign_in_with_password({"email": email, "password": pw})
                                if res.session:
                                    st.session_state.update({"session": res.session, "user": res.user, "autenticado": True})
                                    st.rerun()
                            except Exception as e:
                                err = str(e).lower()
                                if "invalid login credentials" in err: st.error("Email o contraseña incorrectos.")
                                elif "network" in err:                 st.error("Error de red.")
                                else:                                  st.error(f"Error: {e}")
                    else:
                        st.warning("Completá todos los campos.")
        with tab_reg:
            with st.form("registro_form"):
                new_email = st.text_input("Email")
                new_pw    = st.text_input("Password (min. 6 car.)", type="password")
                if st.form_submit_button("Crear Cuenta", use_container_width=True):
                    try:
                        supabase.auth.sign_up({"email": new_email, "password": new_pw})
                        st.success("Revisá tu email para confirmar la cuenta.")
                    except Exception as e:
                        st.error(f"Error: {e}")
        return False
    return True

def actualizar_precio_nube(clave, valor, categoria):
    if "session" not in st.session_state: return
    try:
        token = get_token()
        if not token: return
        supabase.postgrest.auth(token)
        supabase.table("configuracion").upsert(
            {"user_id": st.session_state["user"].id, "clave": clave, "valor": float(valor), "categoria": categoria},
            on_conflict="user_id, clave"
        ).execute()
    except Exception as e:
        st.error(f"Error guardando {clave}: {e}")

def eliminar_precio_nube(clave, categoria):
    if "session" not in st.session_state: return
    try:
        token = get_token()
        if not token: return
        supabase.postgrest.auth(token)
        supabase.table("configuracion").delete().eq("user_id", st.session_state["user"].id).eq("clave", clave).eq("categoria", categoria).execute()
    except Exception as e:
        st.error(f"Error al eliminar {clave}: {e}")

def traer_datos():
    if "session" not in st.session_state or not st.session_state["session"]:
        maderas_default = {"Melamina Blanca 18mm": 60000.0, "Melamina Color 18mm": 85000.0, "Enchapado Roble 18mm": 120000.0}
        config_default  = {'bisagra_cazoleta': 1200.0, 'telescopica_45': 5000.0, 'telescopica_soft': 12000.0,
                           'gastos_fijos_diarios': 25000.0, 'flete_capital': 15000.0, 'flete_norte': 20000.0,
                           'colocacion_dia': 45000.0, 'ganancia_taller_pct': 0.30}
        return maderas_default, {'Fibroplus Blanco 3mm': 34500.0, 'Sin fondo': 0.0}, config_default

    try:
        token = get_token()
        if not token: raise Exception("No token")
        
        supabase.postgrest.auth(token)
        datos_db = supabase.table("configuracion").select("*").eq("user_id", st.session_state["user"].id).execute().data
        
        maderas_db = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria','')).lower().strip() == 'maderas'}
        config_db  = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria','')).lower().strip() in ['costos','margen','herrajes']}
        
        maderas_default = {"Melamina Blanca 18mm": 60000.0, "Melamina Color 18mm": 85000.0, "Enchapado Roble 18mm": 120000.0}
        config_default  = {'bisagra_cazoleta': 1200.0, 'telescopica_45': 5000.0, 'telescopica_soft': 12000.0,
                           'gastos_fijos_diarios': 25000.0, 'flete_capital': 15000.0, 'flete_norte': 20000.0,
                           'colocacion_dia': 45000.0, 'ganancia_taller_pct': 0.30}
                           
        maderas = {**maderas_default, **maderas_db}
        config  = {**config_default,  **config_db}
        fondos  = {'Fibroplus Blanco 3mm': 34500.0, 'Faplac Fondo 5.5mm': 45000.0, 'Sin fondo': 0.0}
        
        return maderas, fondos, config

    except Exception as e:
        st.warning("La sesión se actualizó. Por favor, recargá la página.")
        st.stop()

def guardar_presupuesto_nube(cliente, mueble, total, parametros=None, id_editar=None):
    try:
        data = {"cliente": cliente, "mueble": mueble, "precio_final": float(total),
                "user_id": st.session_state["user"].id,
                "fecha": datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M"),
                "parametros": json.dumps(parametros) if parametros else None}
        if id_editar:
            supabase.table("ventas").update(data).eq("id", id_editar).execute()
            st.success("✅ Presupuesto actualizado.")
        else:
            data["estado"] = "Pendiente"
            supabase.table("ventas").insert(data).execute()
            st.success("✅ Presupuesto guardado.")
    except Exception as e:
        st.error(f"Error al guardar: {e}")

def traer_datos_historial():
    try:
        return pd.DataFrame(supabase.table("ventas").select("*").eq("user_id", st.session_state["user"].id).execute().data)
    except:
        return pd.DataFrame()

def generar_svg_mueble(tipo_modulo, ancho_m, alto_m, prof_m, tipo_tapa, cant_puertas, cant_cajones, estantes_fijos, estantes_moviles, tiene_parante, sin_fondo, distribucion_tapas="Iguales", tipo_base="Nada", altura_base=0):
    """Genera un SVG esquemático del mueble con proporciones reales."""
    try:
        ancho_m = float(ancho_m)
        alto_m = float(alto_m)
    except:
        return ""
        
    if ancho_m <= 0 or alto_m <= 0:
        return ""

    W   = 300
    pad = 16
    esp = 10

    # Altura proporcional al mueble, con espacio extra abajo para el soporte
    tiene_soporte = tipo_base not in ("Nada", "", None)
    soporte_px    = 22 if tiene_soporte else 0   # píxeles que ocupa el soporte
    H_mueble = int(W * (alto_m / ancho_m))
    H_mueble = max(130, min(H_mueble, 370))
    H = H_mueble + soporte_px + pad  # canvas total

    es_embutida = "Embutida" in tipo_tapa
    es_gola     = "Gola"     in tipo_tapa
    es_unero    = "Uñero"    in tipo_tapa

    c_estructura = "#5D4E37"
    c_fondo_int  = "#F5F0E8" if not sin_fondo else "#EAEAEA"
    c_puerta     = "#8B6F47"
    c_cajon      = "#7A6040"
    c_estante    = "#9B7D55"
    c_manija     = "#D4AF7A"
    c_texto      = "#4A3728"
    c_gola       = "#2A2A2A"
    c_soporte    = "#8B7355"
    c_pata       = "#A0522D"
    c_metal      = "#B0B0B0"

    # La caja del mueble ocupa desde pad hasta pad+H_mueble
    caja_y = pad
    caja_h = H_mueble

    ix = pad + esp
    iy = caja_y + esp
    iw = W - pad*2 - esp*2
    ih = caja_h - esp*2

    lines = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;border-radius:8px;">']

    # ── SOPORTE (se dibuja ANTES de la caja para que quede atrás) ──
    if tiene_soporte:
        sx     = pad
        sy     = caja_y + caja_h          # justo debajo de la caja
        sw     = W - pad * 2
        sh     = soporte_px

        if tipo_base == "Zócalo de Madera":
            # Rectángulo macizo de madera, mismo ancho que la caja
            lines.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="1" fill="{c_soporte}" stroke="{c_estructura}" stroke-width="1"/>')
            lines.append(f'<rect x="{sx+4}" y="{sy+3}" width="{sw-8}" height="{sh-6}" rx="1" fill="{c_soporte}" opacity="0.5" stroke="{c_estructura}" stroke-width="0.5"/>')
            lines.append(f'<text x="{W//2}" y="{sy+sh//2+4}" text-anchor="middle" font-size="7" fill="white" opacity="0.8">ZÓCALO</text>')

        elif tipo_base == "Banquina":
            # Dos bloques laterales (tipo U invertida)
            bw = sw // 5
            lines.append(f'<rect x="{sx}"        y="{sy}" width="{bw}" height="{sh}" rx="1" fill="{c_soporte}" stroke="{c_estructura}" stroke-width="1"/>')
            lines.append(f'<rect x="{sx+sw-bw}"  y="{sy}" width="{bw}" height="{sh}" rx="1" fill="{c_soporte}" stroke="{c_estructura}" stroke-width="1"/>')
            # Barra horizontal arriba
            lines.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="4" fill="{c_soporte}" opacity="0.6"/>')
            lines.append(f'<text x="{W//2}" y="{sy+sh//2+4}" text-anchor="middle" font-size="7" fill="{c_texto}" opacity="0.7">BANQUINA</text>')

        elif tipo_base == "Patas Plásticas":
            # 4 patas cilíndricas
            pw2 = 10
            ph2 = sh - 2
            posiciones = [sx+6, sx+sw//3, sx+2*sw//3, sx+sw-pw2-6]
            for px2 in posiciones:
                lines.append(f'<rect x="{px2}" y="{sy+2}" width="{pw2}" height="{ph2}" rx="3" fill="{c_metal}" stroke="#888" stroke-width="0.8"/>')
                lines.append(f'<ellipse cx="{px2+pw2//2}" cy="{sy+2}" rx="{pw2//2}" ry="2.5" fill="{c_metal}" stroke="#888" stroke-width="0.8"/>')
            lines.append(f'<text x="{W//2}" y="{sy+sh+10}" text-anchor="middle" font-size="7" fill="{c_texto}" opacity="0.6">PATAS</text>')

    # ── CAJA DEL MUEBLE ──
    lines.append(f'<rect x="{pad}" y="{caja_y}" width="{W-pad*2}" height="{caja_h}" rx="3" fill="{c_fondo_int}" stroke="{c_estructura}" stroke-width="2"/>')
    lines.append(f'<rect x="{pad}" y="{caja_y}" width="{esp}" height="{caja_h}" fill="{c_estructura}"/>')
    lines.append(f'<rect x="{W-pad-esp}" y="{caja_y}" width="{esp}" height="{caja_h}" fill="{c_estructura}"/>')
    lines.append(f'<rect x="{pad}" y="{caja_y}" width="{W-pad*2}" height="{esp}" fill="{c_estructura}"/>')
    lines.append(f'<rect x="{pad}" y="{caja_y+caja_h-esp}" width="{W-pad*2}" height="{esp}" fill="{c_estructura}"/>')

    if es_embutida:
        px_start = pad + esp + 2
        pw_total = W - pad*2 - esp*2 - 4
    else: 
        px_start = pad + 1
        pw_total = W - pad*2 - 2

    if tipo_modulo == "Bajo Mesada":
        frenin_h = int(ih * 0.12)
        lines.append(f'<rect x="{ix}" y="{iy}" width="{iw}" height="{frenin_h}" fill="{c_estructura}" opacity="0.6"/>')

        if es_embutida:
            py = iy + frenin_h + 2
            ph = ih - frenin_h - 4
        else:
            py = iy + frenin_h + 1
            ph = H - pad - py - 1

        if es_gola:
            gola_h = 10
            lines.append(f'<rect x="{px_start}" y="{py}" width="{pw_total}" height="{gola_h}" fill="{c_gola}"/>')
            py += gola_h + 2
            ph -= gola_h + 2

        cant_p = max(1, int(cant_puertas))
        pw = (pw_total - (cant_p-1)*2) // cant_p

        for p in range(cant_p):
            px = px_start + p * (pw + 2)
            lines.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="2" fill="{c_puerta}" opacity="0.85" stroke="{c_estructura}" stroke-width="1"/>')
            if not (es_gola or es_unero): 
                mx = px + pw - 12 if p == 0 else px + 6
                lines.append(f'<rect x="{mx}" y="{py + 10}" width="6" height="24" rx="2" fill="{c_manija}"/>')

    elif tipo_modulo == "Cajonera":
        if es_embutida:
            cy_start = iy + 2
            ch_total = ih - 4
        else:
            cy_start = pad + 1
            ch_total = H - pad*2 - 2

        cajones = int(cant_cajones)
        if cajones > 0:
            ch_útil = ch_total - (cajones - 1) * 3
            if es_gola:
                ch_útil -= (cajones * 8 + 2) 

            props = [1.0 / cajones] * cajones
            if "Proporcional" in distribucion_tapas:
                if cajones == 2: props = [0.40, 0.60]
                elif cajones == 3: props = [0.20, 0.35, 0.45]
                elif cajones == 4: props = [0.15, 0.20, 0.30, 0.35]

            cy_actual = cy_start
            for c in range(cajones):
                caj_h_mod = ch_útil * props[c]
                
                if es_gola:
                    gola_h = 10 if c == 0 else 8
                    lines.append(f'<rect x="{px_start}" y="{cy_actual}" width="{pw_total}" height="{gola_h}" fill="{c_gola}"/>')
                    cy_actual += gola_h + 2

                lines.append(f'<rect x="{px_start}" y="{cy_actual}" width="{pw_total}" height="{caj_h_mod}" rx="2" fill="{c_cajon}" opacity="0.85" stroke="{c_estructura}" stroke-width="1"/>')
                
                if not (es_gola or es_unero):
                    lines.append(f'<rect x="{px_start + pw_total//2 - 20}" y="{cy_actual + caj_h_mod//2 - 3}" width="40" height="6" rx="3" fill="{c_manija}"/>')
                
                cy_actual += caj_h_mod + 3

    elif tipo_modulo == "Alacena":
        if es_embutida:
            frenin_h = int(ih * 0.08)
            lines.append(f'<rect x="{ix}" y="{iy}" width="{iw}" height="{frenin_h}" fill="{c_estructura}" opacity="0.5"/>')
            py = iy + 2
            ph = ih - 4
        else:
            py = pad + 1
            ph = H - pad*2 - 2

        if es_unero:
            unero_h = 8
            ph -= unero_h

        cant_p = max(1, int(cant_puertas))
        pw = (pw_total - (cant_p - 1)*2) // cant_p
        
        for p in range(cant_p):
            px = px_start + p * (pw + 2)
            lines.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="2" fill="{c_puerta}" opacity="0.85" stroke="{c_estructura}" stroke-width="1"/>')
            if not (es_gola or es_unero):
                mx = px + pw - 12 if p % 2 == 0 else px + 6
                lines.append(f'<rect x="{mx}" y="{py + ph - 30}" width="6" height="24" rx="2" fill="{c_manija}"/>')

    _label_soporte = f" + {tipo_base}" if tiene_soporte else ""
    lines.append(f'<text x="{W//2}" y="{H-2}" text-anchor="middle" font-size="8" fill="{c_texto}" opacity="0.5">{int(ancho_m)}×{int(alto_m)} mm{_label_soporte}</text>')
    lines.append('</svg>')
    return '\n'.join(lines)


# ===========================================================================
# INTERFAZ
# ===========================================================================
st.set_page_config(page_title="BVM — Sistema de Gestión para Carpintería", page_icon="🪵", layout="wide")

st.markdown("""<style>
html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
[data-testid="stSidebar"] { background-color: #0F6E56 !important; border-right: none !important; }
[data-testid="stSidebar"] * { color: rgba(255,255,255,0.85) !important; }
[data-testid="stSidebar"] .stRadio label { color: rgba(255,255,255,0.75) !important; font-size: 14px !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15) !important; }
[data-testid="stSidebar"] .stButton button { background: rgba(255,255,255,0.1) !important; color: rgba(255,255,255,0.8) !important; border: 1px solid rgba(255,255,255,0.2) !important; border-radius: 8px !important; }
[data-testid="stSidebarNav"] { display: none; }
[data-testid="stAppViewContainer"] > .main .block-container { padding-top: 1.5rem !important; max-width: 1400px !important; }
h1 { font-size: 22px !important; font-weight: 500 !important; }
h2 { font-size: 17px !important; font-weight: 500 !important; }
.stButton > button[kind="primary"] { background-color: #1D9E75 !important; border-color: #1D9E75 !important; color: white !important; border-radius: 8px !important; font-weight: 500 !important; }
.stButton > button[kind="primary"]:hover { background-color: #0F6E56 !important; }
.stButton > button[kind="secondary"] { border-radius: 8px !important; font-size: 13px !important; border-color: #D3D1C7 !important; }
[data-testid="stMetric"] { background: #F8F8F6 !important; border-radius: 10px !important; padding: 14px 16px !important; border: 0.5px solid #E0DED6 !important; }
[data-testid="stMetricLabel"] { font-size: 12px !important; color: #888780 !important; text-transform: uppercase !important; letter-spacing: 0.04em !important; }
[data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 500 !important; }
[data-testid="stExpander"] { border: 0.5px solid #E0DED6 !important; border-radius: 10px !important; margin-bottom: 8px !important; }
[data-testid="stExpander"] summary { font-weight: 500 !important; font-size: 13px !important; padding: 10px 14px !important; background: #F8F8F6 !important; border-radius: 10px !important; }
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input { border-radius: 7px !important; font-size: 13px !important; border-color: #D3D1C7 !important; }
[data-testid="stAlert"] { border-radius: 8px !important; font-size: 13px !important; }
[data-testid="stDownloadButton"] button { border-radius: 8px !important; font-size: 13px !important; }
[data-testid="stInfo"] { background: #E1F5EE !important; border-left: 3px solid #1D9E75 !important; border-radius: 0 8px 8px 0 !important; }
</style>""", unsafe_allow_html=True)

if not gestionar_auth():
    st.stop()

# ONBOARDING
if "onboarding_visto" not in st.session_state:
    st.session_state["onboarding_visto"] = False

if not st.session_state["onboarding_visto"]:
    st.markdown("""<div style="background:linear-gradient(135deg,#1D9E75 0%,#0F6E56 100%);border-radius:16px;padding:40px 48px;margin-bottom:32px;text-align:center;">
    <div style="font-size:48px;margin-bottom:12px;">🪵</div>
    <h1 style="color:white;margin:0 0 10px 0;font-size:32px;">Bienvenido a BVM</h1>
    <p style="color:white;font-size:17px;opacity:0.9;max-width:520px;margin:0 auto;">
    El sistema de presupuestación y gestión diseñado para carpinteros profesionales.
    Calculá precios exactos, generá presupuestos en segundos y ganale al que tarda más.</p></div>""", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    for col, icono, titulo, desc in [
        (c1, "📐", "Paso 1 — Calculá el mueble", "Ingresá las medidas y el sistema genera la lista de corte con las piezas exactas. Sin errores, sin desperdicios."),
        (c2, "🏗️", "Paso 2 — Armá la obra completa", "Agregá módulo por módulo y BVM los acumula en un solo presupuesto total para el cliente."),
        (c3, "📲", "Paso 3 — Enviá y cerrá", "Generá el PDF o mandá por WhatsApp. El historial registra cada trabajo para hacer seguimiento."),
    ]:
        with col:
            st.markdown(f"""<div style="border:1.5px solid #E0E0E0;border-radius:12px;padding:24px;min-height:160px;">
            <div style="font-size:32px;margin-bottom:10px;">{icono}</div>
            <div style="font-weight:600;font-size:15px;margin-bottom:8px;">{titulo}</div>
            <div style="font-size:13px;color:#666;line-height:1.5;">{desc}</div></div>""", unsafe_allow_html=True)

    st.write("")
    _, col_start, _ = st.columns([1, 2, 1])
    with col_start:
        if st.button("✅ Empezar a usar BVM", type="primary", use_container_width=True):
            st.session_state["onboarding_visto"] = True
            st.rerun()
    st.stop()


# ===========================================================================
# SESSION STATE — un único dict edit_ctx maneja todo el estado de edición
# ===========================================================================
# edit_ctx puede tener estos modos:
#   None                  → cotizador limpio (nuevo módulo)
#   {"modo": "nuevo_modulo_obra"}           → agregando módulo a obra en curso
#   {"modo": "editar_modulo_obra",
#    "idx": int, "obra_id": str|None,
#    "obra_cliente": str, "params": dict}   → editando un módulo de la obra
#   {"modo": "editar_legacy",
#    "id": str, "cliente": str,
#    "params": dict}                        → editando presupuesto individual
# ===========================================================================
for k, v in {
    "obra_modulos":  [],
    "edit_ctx":      None,
    "ultimo_agregado": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

maderas, fondos, config = traer_datos()
_opciones_menu  = ["🪵 Cotizador", "♻️ Retazos", "📋 Historial", "⚙️ Precios"]
_editando_algo  = st.session_state.get("edit_ctx") is not None

# SIDEBAR
st.sidebar.markdown("""<div style="padding:8px 4px 16px 4px;border-bottom:1px solid rgba(255,255,255,0.12);margin-bottom:12px;">
<div style="font-size:22px;font-weight:500;color:white;">🪵 BVM</div>
<div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:2px;">Sistema de carpintería</div></div>""", unsafe_allow_html=True)

if _editando_algo:
    menu = "🪵 Cotizador"
    st.sidebar.radio("Navegación", _opciones_menu, index=0)
else:
    menu = st.sidebar.radio("Navegación", _opciones_menu, index=st.session_state.get("menu_idx", 0))
    st.session_state["menu_idx"] = _opciones_menu.index(menu)

_mods_validos = [m for m in st.session_state["obra_modulos"] if m is not None]
if _mods_validos:
    total_obra_sb = sum(m["precio"] for m in _mods_validos)
    st.sidebar.markdown(f"""<div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:10px 12px;margin:12px 0 4px 0;">
    <div style="font-size:10px;color:rgba(255,255,255,0.5);letter-spacing:0.06em;margin-bottom:4px;">OBRA EN CURSO</div>
    <div style="font-size:20px;font-weight:500;color:white;">${total_obra_sb:,.0f}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:2px;">{len(_mods_validos)} módulo(s)</div></div>""", unsafe_allow_html=True)

st.sidebar.write("---")
if st.sidebar.button("Cerrar sesión"):
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()


# ===========================================================================
# HELPERS DE SERIALIZACIÓN
# ===========================================================================
def _params_desde_mod(m):
    """Extrae el dict de params de un módulo (compatible con formato viejo y nuevo)."""
    p = m.get("params") or {}
    return {
        "tipo_modulo":          m.get("tipo_modulo", m.get("tipo", p.get("tipo_modulo", ""))),
        "ancho_m":              m.get("ancho_m", m.get("ancho", p.get("ancho_m", 0))),
        "alto_m":               m.get("alto_m",  m.get("alto",  p.get("alto_m",  0))),
        "prof_m":               m.get("prof_m",  m.get("prof",  p.get("prof_m",  0))),
        "mat_principal":        m.get("mat_principal", m.get("material", p.get("mat_principal", ""))),
        "precio_guardado":      m.get("precio", p.get("precio_guardado", 0)),
        "nombre":               m.get("nombre") or p.get("nombre") or "",
        "mat_fondo_sel":        p.get("mat_fondo_sel", "Fibroplus Blanco 3mm"),
        "esp_real":             p.get("esp_real", 18.0),
        "tipo_tapa":            p.get("tipo_tapa", m.get("tipo_tapa", "Superpuesta")),
        "cant_puertas":         p.get("cant_puertas", 2),
        "cant_cajones":         p.get("cant_cajones", 0),
        "tiene_parante":        p.get("tiene_parante", False),
        "tipo_parante":         p.get("tipo_parante", "Corto (100mm)"),
        "tiene_parante_medio":  p.get("tiene_parante_medio", False),
        "tipo_base":            p.get("tipo_base", "Nada"),
        "altura_base":          p.get("altura_base", 0.0),
        "estantes_fijos":       p.get("estantes_fijos", 0),
        "estantes_moviles":     p.get("estantes_moviles", 0),
        "tipo_estante_manual":  p.get("tipo_estante_manual", "Completo"),
        "sin_fondo":            p.get("sin_fondo", False),
        "luz_entre_tapas":      p.get("luz_entre_tapas", 3.0),
        "luz_perimetral_tapa":  p.get("luz_perimetral_tapa", 4.0),
        "alto_frentin_emb":     p.get("alto_frentin_emb", 0.0),
        "aire_trasero":         p.get("aire_trasero", 30.0),
        "esp_corredera":        p.get("esp_corredera", 13.0),
        "distribucion_tapas":   p.get("distribucion_tapas", "Iguales"),
        "tiene_cenefa":         p.get("tiene_cenefa", False),
        "alto_cenefa":          p.get("alto_cenefa", 0.0),
        "dias_prod":            p.get("dias_prod", 0.0),
        "indices_estantes_fijos": p.get("indices_estantes_fijos", []),
        "herrajes_extra":       p.get("herrajes_extra", {}),
        "distancia_parante":    p.get("distancia_parante", 0.0),
    }

def _serializar_obra_para_nube(mods):
    """Convierte lista de módulos al formato que se guarda en Supabase."""
    return [dict(_params_desde_mod(m), precio=m.get("precio", 0), nombre=m.get("nombre","")) for m in mods if m is not None]

def _limpiar_edicion():
    st.session_state["edit_ctx"] = None
    st.session_state.pop("_tipo_modulo_sel", None)
    st.session_state.pop("_ctx_sig_prev",    None)

def _guardar_obra_nube(mods, cliente, obra_id=None):
    mods  = [m for m in mods if m is not None]
    total = sum(m["precio"] for m in mods)
    params = {"es_obra": True, "modulos": _serializar_obra_para_nube(mods)}
    guardar_presupuesto_nube(cliente, f"Obra ({len(mods)} módulos)", total,
                              parametros=params, id_editar=obra_id)


# ===========================================================================
# COTIZADOR
# ===========================================================================
if menu == "🪵 Cotizador":
  try:
    st.title("🪵 BVM — Cotizador de muebles")

    ctx = st.session_state.get("edit_ctx")   # contexto de edición activo
    modo = ctx.get("modo") if ctx else None

    # ───────────────────────────────────────────────────────────────────────
    # BANNER de edición activa
    # ───────────────────────────────────────────────────────────────────────
    # ── MODO ESPECIAL: selector de módulo para obras con varios módulos ──
    if modo == "elegir_modulo_obra":
        _mods_elegir = [m for m in st.session_state.get("obra_modulos", []) if m is not None]
        _cli_elegir  = ctx.get("obra_cliente", "")
        _oid_elegir  = ctx.get("obra_id")
        st.markdown(f"### ✏️ Editando obra de **{_cli_elegir}** — ¿Qué módulo querés editar?")
        for i_e, mod_e in enumerate(_mods_elegir):
            c_info, c_btn = st.columns([5, 1])
            c_info.markdown(f"**{i_e+1}. {mod_e['nombre']}** — {mod_e['ancho']}×{mod_e['alto']}×{mod_e['prof']} mm — {mod_e['material']} — `${mod_e['precio']:,.0f}`")
            if c_btn.button("✏️ Editar", key=f"elegir_{i_e}", use_container_width=True):
                st.session_state["edit_ctx"] = {
                    "modo":        "editar_modulo_obra",
                    "idx":         i_e,
                    "obra_id":     _oid_elegir,
                    "obra_cliente": _cli_elegir,
                    "params":      _params_desde_mod(mod_e),
                }
                st.session_state.pop("_tipo_modulo_sel", None)
                st.session_state.pop("_ctx_sig_prev",    None)
                st.rerun()
        if st.button("✕ Cancelar", key="btn_cancel_elegir"):
            st.session_state["obra_modulos"] = []
            st.session_state.pop("_obra_id_historial",      None)
            st.session_state.pop("_obra_cliente_historial", None)
            _limpiar_edicion()
            st.rerun()
        # No renderizamos el cotizador en este modo
        st.stop()

    elif modo == "editar_modulo_obra":
        st.info(f"✏️ **Editando módulo** de la obra de **{ctx.get('obra_cliente','')}** — Cambiá lo que necesitás y confirmá.")
        if st.button("✕ Cancelar edición", key="btn_cancel_edit"):
            _limpiar_edicion()
            st.rerun()

    elif modo == "editar_legacy":
        st.info(f"✏️ **Editando presupuesto** de **{ctx.get('cliente','')}** — Modificá y guardá.")
        if st.button("✕ Cancelar edición", key="btn_cancel_edit"):
            _limpiar_edicion()
            st.rerun()

    # ───────────────────────────────────────────────────────────────────────
    # Carga de params desde contexto de edición
    # ───────────────────────────────────────────────────────────────────────
    ep = ctx.get("params") if ctx else None

    def _v(key, default):
        return ep[key] if ep and key in ep else default

    # ───────────────────────────────────────────────────────────────────────
    # Tipo de módulo: se persiste en session_state para que los botones
    # de selección funcionen sin conflicto
    # ───────────────────────────────────────────────────────────────────────
    _tipo_default = _v("tipo_modulo", "Bajo Mesada")
    # Hash estable: usamos el tipo_modulo + ancho + alto del contexto
    # así el hash no cambia entre reruns del mismo contexto
    _ctx_sig = f"{_tipo_default}_{_v('ancho_m',0)}_{_v('alto_m',0)}_{_v('precio_guardado',0)}" if ep else "none"
    if "_tipo_modulo_sel" not in st.session_state or st.session_state.get("_ctx_sig_prev") != _ctx_sig:
        st.session_state["_tipo_modulo_sel"] = _tipo_default
        st.session_state["_ctx_sig_prev"]    = _ctx_sig

    # Defaults de variables (se usan antes de renderizar los expanders)
    df_corte = pd.DataFrame()
    costo_madera = costo_fondo = costo_herrajes = precio_final = total_costo = 0.0
    m2_18mm = m2_fondo = costo_operativo = utilidad = 0.0
    tiene_parante       = _v("tiene_parante", False)
    tiene_parante_medio = _v("tiene_parante_medio", False)
    tipo_parante        = _v("tipo_parante", "Corto (100mm)")
    tipo_estante_manual = _v("tipo_estante_manual", "Completo")
    distancia_parante   = _v("distancia_parante", 0.0)
    luz_perimetral_tapa = _v("luz_perimetral_tapa", 4.0)
    aire_trasero        = _v("aire_trasero", 30.0)
    esp_corredera       = _v("esp_corredera", 13.0)
    distribucion_tapas  = _v("distribucion_tapas", "Iguales")
    cant_puertas        = _v("cant_puertas", 0)
    tiene_cenefa        = _v("tiene_cenefa", False)
    alto_cenefa         = _v("alto_cenefa", 0.0)
    estantes_fijos      = _v("estantes_fijos", 0)
    estantes_moviles    = _v("estantes_moviles", 0)
    cant_cajones        = _v("cant_cajones", 0)
    luz_entre_tapas     = _v("luz_entre_tapas", 3.0)
    alto_frentin_emb    = _v("alto_frentin_emb", 0.0)
    tipo_tapa           = _v("tipo_tapa", "Superpuesta")
    tipo_base           = _v("tipo_base", "Nada")
    altura_base         = _v("altura_base", 0.0)
    sin_fondo           = _v("sin_fondo", False)
    indices_fijos       = []

    lista_maderas = list(maderas.keys())
    lista_fondos  = list(fondos.keys())
    idx_madera = lista_maderas.index(_v("mat_principal", lista_maderas[0])) if _v("mat_principal", lista_maderas[0]) in lista_maderas else 0
    idx_fondo  = lista_fondos.index(_v("mat_fondo_sel",  lista_fondos[0]))  if _v("mat_fondo_sel",  lista_fondos[0])  in lista_fondos  else 0

    col_in, col_out = st.columns([1, 1.2])

    # ═══════════════════════════════════════════════════════════════════════
    # COLUMNA IZQUIERDA — inputs
    # ═══════════════════════════════════════════════════════════════════════
    with col_in:
      with st.expander("🛠️ Definición de estructura", expanded=True):
        _cliente_default = ""
        if modo == "editar_modulo_obra": _cliente_default = ctx.get("obra_cliente", "")
        elif modo == "editar_legacy":    _cliente_default = ctx.get("cliente", "")
        cliente = st.text_input("Cliente", _cliente_default)

        st.markdown("**Tipo de mueble**")
        _svgs = {
            "Bajo Mesada": '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="18" width="76" height="38" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="18" width="76" height="8" rx="1" fill="COLOR" opacity="0.25"/><line x1="41" y1="26" x2="41" y2="56" stroke="COLOR" stroke-width="1.2"/><rect x="5" y="30" width="33" height="22" rx="1.5" fill="COLOR" opacity="0.18"/><rect x="44" y="30" width="33" height="22" rx="1.5" fill="COLOR" opacity="0.18"/><circle cx="39" cy="41" r="2" fill="COLOR" opacity="0.6"/><circle cx="43" cy="41" r="2" fill="COLOR" opacity="0.6"/></svg>',
            "Cajonera":    '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="5" y="4" width="70" height="52" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="8" y="8" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><rect x="8" y="24" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><rect x="8" y="40" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><circle cx="40" cy="14.5" r="2" fill="COLOR" opacity="0.7"/><circle cx="40" cy="30.5" r="2" fill="COLOR" opacity="0.7"/><circle cx="40" cy="46.5" r="2" fill="COLOR" opacity="0.7"/></svg>',
            "Alacena":     '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="2" width="76" height="52" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="2" width="76" height="7" rx="1" fill="COLOR" opacity="0.2"/><line x1="41" y1="9" x2="41" y2="54" stroke="COLOR" stroke-width="1.2"/><rect x="5" y="13" width="33" height="37" rx="1.5" fill="COLOR" opacity="0.18"/><rect x="44" y="13" width="33" height="37" rx="1.5" fill="COLOR" opacity="0.18"/><circle cx="39" cy="31" r="2" fill="COLOR" opacity="0.6"/><circle cx="43" cy="31" r="2" fill="COLOR" opacity="0.6"/></svg>',
        }
        col_bm, col_caj, col_ala = st.columns(3)
        for col_btn, nombre_btn in [(col_bm, "Bajo Mesada"), (col_caj, "Cajonera"), (col_ala, "Alacena")]:
            with col_btn:
                sel   = st.session_state["_tipo_modulo_sel"] == nombre_btn
                color = "#1D9E75" if sel else "#888780"
                bg    = "#E1F5EE" if sel else "transparent"
                borde = "#1D9E75" if sel else "#D3D1C7"
                svg   = _svgs[nombre_btn].replace("COLOR", color)
                st.markdown(f'<div style="border:2px solid {borde};border-radius:10px;padding:12px 8px 8px 8px;background:{bg};text-align:center;color:{color};">{svg}<div style="font-size:12px;font-weight:600;margin-top:6px;">{nombre_btn}</div></div>', unsafe_allow_html=True)
                if st.button("Seleccionar", key=f"sel_{nombre_btn}", use_container_width=True, type="primary" if sel else "secondary"):
                    st.session_state["_tipo_modulo_sel"] = nombre_btn
                    st.rerun()

        tipo_modulo = st.session_state["_tipo_modulo_sel"]
        c1, c2, c3 = st.columns(3)
        ancho_m = c1.number_input("Ancho total (mm)", min_value=0.0, max_value=5000.0, value=float(_v("ancho_m", 0.0)), step=0.5)
        alto_m  = c2.number_input("Alto total (mm)",  min_value=0.0, max_value=5000.0, value=float(_v("alto_m",  0.0)), step=0.5)
        prof_m  = c3.number_input("Profundidad (mm)", min_value=0.0, max_value=2000.0, value=float(_v("prof_m",  0.0)), step=0.5)
        mat_principal = st.selectbox("Material del cuerpo (18mm)", lista_maderas, index=idx_madera)
        esp_real      = st.number_input("Espesor real de placa (mm)", min_value=1.0, max_value=50.0, value=float(_v("esp_real", 18.0)), step=0.1)
        mat_fondo_sel = st.selectbox("Material del fondo", lista_fondos, index=idx_fondo)
        sin_fondo = mat_fondo_sel == "Sin fondo"

      with st.expander("🏗️ Configuración del módulo", expanded=False):
        if tipo_modulo == "Bajo Mesada":
            _bm_opts = ["Superpuesta", "Gola BVM", "Embutida"]
            tipo_tapa    = st.radio("Estilo", _bm_opts, index=_bm_opts.index(_v("tipo_tapa","Superpuesta")) if _v("tipo_tapa","Superpuesta") in _bm_opts else 0)
            cant_puertas = st.selectbox("Cantidad de Puertas", [2, 3], index=0 if int(_v("cant_puertas",2)) == 2 else 1)
            if cant_puertas == 3:
                tiene_parante = True
                st.info("3 puertas: Parante divisor incluido.")
                c_p1, c_p2 = st.columns(2)
                tipo_parante      = c_p1.selectbox("Tipo de Parante", ["Corto (100mm)", "Largo (Fondo Lateral)"])
                distancia_parante = c_p2.number_input("Distancia desde lateral izq. (mm)", value=ancho_m/cant_puertas if ancho_m > 0 else 0.0, step=1.0)
            tiene_parante_medio = st.checkbox("¿Lleva parante medio?", value=bool(_v("tiene_parante_medio", False)))
            st.markdown("---")
            st.markdown("#### Estantes")
            _cant_est_def = max(1, int(_v("estantes_fijos",0)) + int(_v("estantes_moviles",0)))
            cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=_cant_est_def, step=1, key="cant_est_bm")
            _fmt_opts = ["Completo", "Medio"]
            tipo_estante_manual = st.radio("Formato de Estante", _fmt_opts, index=_fmt_opts.index(_v("tipo_estante_manual","Completo")) if _v("tipo_estante_manual","Completo") in _fmt_opts else 0, key="fmt_est_bm")
            _indices_guard = _v("indices_estantes_fijos", [])
            indices_fijos = []
            if cant_total_est > 0:
                st.write("¿Cuáles son fijos?")
                cols_e = st.columns(int(cant_total_est))
                for i_e in range(int(cant_total_est)):
                    with cols_e[i_e]:
                        if st.checkbox(f"E{i_e+1}", value=(i_e in _indices_guard), key=f"check_est_bm_{i_e}"):
                            indices_fijos.append(i_e)
            estantes_fijos   = len(indices_fijos)
            estantes_moviles = cant_total_est - estantes_fijos
            st.caption(f"{estantes_fijos} fijo(s) / {estantes_moviles} móvil(es)")
            cant_cajones = 0

        elif tipo_modulo == "Alacena":
            c_ala1, c_ala2 = st.columns(2)
            _ala_opts = ["Superpuesta", "Uñero", "Embutida"]
            tipo_tapa    = c_ala1.radio("Sistema de Apertura", _ala_opts, index=_ala_opts.index(_v("tipo_tapa","Superpuesta")) if _v("tipo_tapa","Superpuesta") in _ala_opts else 0)
            _p_ala = int(_v("cant_puertas",2))
            cant_puertas = c_ala2.selectbox("Cantidad de Puertas", [2,3,4], index=[2,3,4].index(_p_ala) if _p_ala in [2,3,4] else 0)
            st.markdown("---")
            cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=1, step=1)
            _indices_guard_ala = _v("indices_estantes_fijos", [])
            indices_fijos = []
            if cant_total_est > 0:
                st.write("¿Cuáles son fijos?")
                cols_e = st.columns(int(cant_total_est))
                for i_e in range(int(cant_total_est)):
                    with cols_e[i_e]:
                        if st.checkbox(f"E{i_e+1}", value=(i_e in _indices_guard_ala), key=f"check_est_{i_e}"):
                            indices_fijos.append(i_e)
            estantes_fijos   = len(indices_fijos)
            estantes_moviles = cant_total_est - estantes_fijos
            st.caption(f"{estantes_fijos} fijo(s) / {estantes_moviles} móvil(es)")
            tiene_cenefa = False
            alto_cenefa  = 0.0
            if "Uñero" in tipo_tapa:
                tiene_cenefa = st.checkbox("¿Lleva Cenefa inferior?", value=True)
                if tiene_cenefa:
                    alto_cenefa = st.number_input("Altura de Cenefa (mm)", value=50.0, step=5.0)
            cant_cajones = 0

        else:  # CAJONERA
            c_caj, _ = st.columns(2)
            cant_cajones = c_caj.number_input("Cant. Cajones", value=int(_v("cant_cajones", 0)), min_value=0)
            _caj_opts = ["Superpuesta", "Embutida"] + (["Gola"] if cant_cajones == 3 else [])
            _tapa_def = _v("tipo_tapa","Superpuesta")
            tipo_tapa = st.radio("Estilo de Tapa", _caj_opts, index=_caj_opts.index(_tapa_def) if _tapa_def in _caj_opts else 0)
            st.markdown(f"#### Parámetros del cajón ({tipo_tapa})")
            col_l1, col_l2 = st.columns(2)
            luz_entre_tapas = col_l1.number_input("Luz entre tapas (mm)", value=float(_v("luz_entre_tapas", 3.0)))
            if cant_cajones > 0:
                if tipo_tapa == "Embutida":
                    alto_frentin_emb    = col_l2.number_input("Altura Frentín Superior (mm)", value=float(_v("alto_frentin_emb", 30.0)))
                    luz_perimetral_tapa = 6.0
                else:
                    luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=float(_v("luz_perimetral_tapa", 4.0)))
                    alto_frentin_emb    = 0.0
                _dist_opts = ["Iguales", "Proporcional (20/35/45)"]
                distribucion_tapas = col_l1.radio("Distribución", _dist_opts, index=_dist_opts.index(_v("distribucion_tapas","Iguales")) if _v("distribucion_tapas","Iguales") in _dist_opts else 0)
                col_c1, col_c2 = st.columns(2)
                esp_corredera = col_c1.number_input("Espesor de corredera (mm)", value=float(_v("esp_corredera", 13.0)))
                aire_trasero  = col_c2.number_input("Espacio libre trasero (mm)", value=float(_v("aire_trasero", 30.0)))

      if tipo_modulo != "Alacena":
        with st.expander("📦 Soporte", expanded=False):
            _opts_base = ["Zócalo de Madera", "Banquina", "Patas Plásticas", "Nada"]
            _base_def  = _v("tipo_base","Nada") if _v("tipo_base","Nada") in _opts_base else "Nada"
            tipo_base = st.selectbox("Tipo de Soporte", _opts_base, index=_opts_base.index(_base_def))
            if tipo_base != "Nada":
                altura_base = st.number_input("Altura (mm)", min_value=0.0, value=float(_v("altura_base",100.0)), step=5.0)
            else:
                altura_base = 0.0
            costo_base = 5000 if tipo_base == "Patas Plásticas" else 0
      else:
        tipo_base = "Nada"; altura_base = 0.0; costo_base = 0

      st.markdown("---")
      st.markdown("#### 🔩 Herrajes y Accesorios")
      if tipo_modulo in ["Bajo Mesada","Alacena"] and cant_puertas > 0:
          st.info(f"💡 Sugerencia: {cant_puertas * 2} bisagras.")
      elif tipo_modulo == "Cajonera" and cant_cajones > 0:
          st.info(f"💡 Sugerencia: {cant_cajones} pares de correderas.")

      herrajes_disp = {k: v for k, v in config.items() if k not in ['gastos_fijos_diarios','flete_capital','flete_norte','colocacion_dia','ganancia_taller_pct']}
      herrajes_extra_sel = {}
      if herrajes_disp:
          _herr_guard = _v("herrajes_extra", {})
          _mapa = {
              "bisagra_cazoleta":  "Bisagra Cazoleta Estándar",
              "telescopica_45":    "Guía Telescópica 45cm",
              "telescopica_soft":  "Guía Telescópica Cierre Suave",
          }
          opciones_limpias = [_mapa.get(k, k) for k in herrajes_disp]
          mapa_inv         = {v: k for k, v in _mapa.items()}
          def_sel = [_mapa.get(k, k) for k in _herr_guard if _mapa.get(k, k) in opciones_limpias]
          seleccionados = st.multiselect("Herrajes para este módulo", opciones_limpias, default=def_sel)
          if seleccionados:
              c_h1, c_h2 = st.columns(2)
              for i_h, nm in enumerate(seleccionados):
                  clave = mapa_inv.get(nm, nm)
                  col_h = c_h1 if i_h % 2 == 0 else c_h2
                  cant_h = col_h.number_input(f"Cant. {nm}", min_value=1, value=int(_herr_guard.get(clave, 1)), step=1, key=f"cant_{clave}")
                  herrajes_extra_sel[clave] = cant_h

      with st.expander("🔨 Días de taller", expanded=False):
          dias_prod = st.number_input("Días de trabajo en taller", value=float(_v("dias_prod", 0.0)), step=0.5)

    # ═══════════════════════════════════════════════════════════════════════
    # COLUMNA DERECHA — preview + planilla + precio + botones
    # ═══════════════════════════════════════════════════════════════════════
    with col_out:
      if ancho_m > 0 and alto_m > 0:
          svg_prev = generar_svg_mueble(tipo_modulo, ancho_m, alto_m, prof_m, tipo_tapa,
                                         cant_puertas, cant_cajones, estantes_fijos, estantes_moviles,
                                         tiene_parante, sin_fondo, distribucion_tapas,
                                         tipo_base=tipo_base, altura_base=altura_base)
          if svg_prev:
              st.markdown(f'<div style="text-align:center;padding:16px;background:white;border:1px solid #E0DED6;border-radius:10px;margin-bottom:24px;">{svg_prev}</div>', unsafe_allow_html=True)

      st.subheader("📐 Planilla de corte")
      if not cliente:
          st.markdown('''<div style="background:#FFF8E6;border-left:3px solid #EF9F27;border-radius:0 8px 8px 0;padding:12px 16px;">
          <b style="color:#854F0B;">👆 Ingresá el nombre del cliente primero</b></div>''', unsafe_allow_html=True)

      nombre_modulo = _v("nombre", f"{tipo_modulo} {ancho_m:.0f}mm")
      if alto_m > 0 and ancho_m > 0 and cliente:
          piezas = generar_despiece_bvm(
              tipo=tipo_modulo, ancho_m=ancho_m, alto_m=alto_m, prof_m=prof_m,
              esp_real=esp_real, tiene_parante=tiene_parante, tipo_parante=tipo_parante,
              distancia_parante=distancia_parante, cant_cajones=cant_cajones,
              tipo_tapa=tipo_tapa, tipo_base=tipo_base, altura_base=altura_base,
              luz_entre_tapas=luz_entre_tapas, luz_perimetral_tapa=luz_perimetral_tapa,
              alto_frentin_emb=alto_frentin_emb, aire_trasero=aire_trasero,
              esp_corredera=esp_corredera, distribucion_tapas=distribucion_tapas,
              cant_puertas=cant_puertas, tiene_cenefa=tiene_cenefa, alto_cenefa=alto_cenefa,
              estantes_fijos=estantes_fijos, estantes_moviles=estantes_moviles,
              tipo_estante_manual=tipo_estante_manual, sin_fondo=sin_fondo,
              tiene_parante_medio=tiene_parante_medio,
          )
          df_corte = pd.DataFrame(piezas)
          if not df_corte.empty and "L" in df_corte.columns:
              for col_n in ["Tipo","L","A","Cant"]:
                  if col_n not in df_corte.columns: df_corte[col_n] = 0 if col_n != "Tipo" else "Cuerpo"
              df_corte["L"]    = pd.to_numeric(df_corte["L"],    errors="coerce").fillna(0)
              df_corte["A"]    = pd.to_numeric(df_corte["A"],    errors="coerce").fillna(0)
              df_corte["Cant"] = pd.to_numeric(df_corte["Cant"], errors="coerce").fillna(0)
              df_corte["Tipo"] = df_corte["Tipo"].fillna("Cuerpo").astype(str)
              st.data_editor(df_corte, use_container_width=True, hide_index=True)

              df_placa  = df_corte[~df_corte["Tipo"].isin(["Fondo","Piso"])]
              m2_18mm   = (df_placa["L"] * df_placa["A"] * df_placa["Cant"]).sum() / 1_000_000
              costo_madera = m2_18mm * (maderas.get(mat_principal, 0.0) / 5.03)
              df_fondo_ = df_corte[df_corte["Tipo"].isin(["Fondo","Piso"])]
              m2_fondo  = (df_fondo_["L"] * df_fondo_["A"] * df_fondo_["Cant"]).sum() / 1_000_000 if not df_fondo_.empty else 0.0
              costo_fondo = 0.0 if sin_fondo else m2_fondo * (fondos.get(mat_fondo_sel, 0.0) / 5.03)
              costo_herrajes  = sum(config.get(k, 0.0) * v for k, v in herrajes_extra_sel.items())
              costo_operativo = dias_prod * config.get("gastos_fijos_diarios", 0)
              total_costo     = costo_madera + costo_fondo + costo_herrajes + costo_operativo + costo_base

              # Terminal CNC — solo se muestra cuando hay datos calculados en esta sesión
              st.write("---")
              with st.expander("⚙️ Terminal CNC — Este módulo"):
                  import io as _io, ezdxf as _ezdxf
                  _doc = _ezdxf.new("R2010"); _msp = _doc.modelspace(); _x = 0
                  for _, _row in df_corte.iterrows():
                      for _ in range(int(_row["Cant"])):
                          _pts = [(_x,0),(_x+float(_row["L"]),0),(_x+float(_row["L"]),float(_row["A"])),(_x,float(_row["A"])),(_x,0)]
                          _msp.add_lwpolyline(_pts, close=True)
                          _msp.add_text(f"{_row['Pieza']}\n{int(_row['L'])}x{int(_row['A'])}", height=10).set_placement((_x+5,5))
                          _x += float(_row["L"]) + 50
                  _out = _io.StringIO(); _doc.write(_out)
                  _dxf_b = _out.getvalue().encode("utf-8")
                  _df_a  = df_corte.copy().rename(columns={"Pieza":"Name","L":"Length","A":"Width","Cant":"Quantity"})
                  _df_a["Thickness"] = esp_real; _df_a["Material"] = mat_principal
                  _csv_b = _df_a[["Name","Length","Width","Thickness","Quantity","Material"]].to_csv(index=False).encode("utf-8")
                  cc1, cc2 = st.columns(2)
                  cc1.download_button("📐 DXF", data=_dxf_b, file_name=f"BVM_{nombre_modulo}.dxf", mime="application/dxf", use_container_width=True)
                  cc2.download_button("🤖 CSV Aspire", data=_csv_b, file_name=f"BVM_{nombre_modulo}.csv", mime="text/csv", use_container_width=True)
      else:
          st.warning("Esperando medidas para calcular...")

      st.write("---")
      esp_real = esp_real if "esp_real" in dir() else 18.0  # guard por si no se calculó
      retazos_stock = consultar_retazos_disponibles(mat_principal)
      if not df_corte.empty:
          ahorro_madera, matches = calcular_ahorro_retazos(df_corte, retazos_stock, maderas.get(mat_principal, 0.0))
      else:
          ahorro_madera, matches = 0.0, []
      total_costo_real = total_costo - ahorro_madera
      utilidad     = total_costo_real * config.get("ganancia_taller_pct", 0.30)
      precio_final = total_costo_real + utilidad
      pct_margen   = (utilidad / precio_final * 100) if precio_final > 0 else 0.0

      # Precio a usar: recálculo si hubo, o precio guardado en edición
      _precio_guardado = float(_v("precio_guardado", 0))
      precio_a_usar = precio_final if precio_final > 0 else _precio_guardado

      if precio_a_usar > 0:
          _color  = "#0F6E56" if pct_margen >= 12 else "#A32D2D"
          _alerta = "Operación rentable" if pct_margen >= 12 else "Margen bajo — revisá los costos"
          _icono  = "✅" if pct_margen >= 12 else "⚠️"
          _nota   = " (precio guardado — recalculá si cambiaste medidas)" if precio_final == 0 and _precio_guardado > 0 else ""
          st.markdown(f'''<div style="background:{_color};border-radius:10px;padding:20px 24px;margin:8px 0 16px 0;text-align:center;">
          <div style="color:white;font-size:12px;opacity:0.8;margin-bottom:6px;">VALOR DEL MUEBLE{_nota}</div>
          <div style="color:white;font-size:44px;font-weight:700;letter-spacing:-1px;">${precio_a_usar:,.0f}</div>
          <div style="color:white;font-size:12px;opacity:0.8;margin-top:8px;">{_icono} Margen: {pct_margen:.1f}% — {_alerta}</div>
          </div>''', unsafe_allow_html=True)

      c1, c2, c3 = st.columns(3)
      c1.metric("Costo real",    f"${total_costo_real:,.0f}")
      c2.metric("M² de placa",   f"{m2_18mm:.2f}")
      c3.metric("Ganancia neta", f"${utilidad:,.0f}")

      if matches:
          st.success(f"♻️ **¡Ahorro por retazos!** {len(matches)} pieza(s) — **${ahorro_madera:,.0f}**")
          with st.expander("Ver detalle"):
              for m_r in matches:
                  st.write(f"• **{m_r['pieza']}** → Retazo ID-{m_r['retazo_id']} — ${m_r['ahorro']:,.0f}")

      if precio_final > 0:
          with st.expander("📊 Desglose de costos"):
              st.bar_chart(pd.DataFrame({
                  "Categoría": ["Madera/Fondo","Herrajes","Operativo","Ganancia"],
                  "Monto":     [costo_madera+costo_fondo, costo_herrajes, costo_operativo+costo_base, utilidad],
              }), x="Categoría", y="Monto", color="#2e7d32")

      # ─────────────────────────────────────────────────────────────────────
      # SECCIÓN: botones de acción
      # ─────────────────────────────────────────────────────────────────────
      st.write("---")

      # nombre_modulo tiene default aquí para que el Terminal CNC siempre lo tenga

      def _build_params_dict():
          return {
              "tipo_modulo": tipo_modulo, "ancho_m": ancho_m, "alto_m": alto_m,
              "prof_m": prof_m, "esp_real": esp_real, "mat_principal": mat_principal,
              "mat_fondo_sel": mat_fondo_sel, "tipo_tapa": tipo_tapa,
              "cant_puertas": cant_puertas, "cant_cajones": cant_cajones,
              "tiene_parante": tiene_parante, "tipo_parante": tipo_parante,
              "tiene_parante_medio": tiene_parante_medio,
              "tipo_base": tipo_base, "altura_base": altura_base,
              "estantes_fijos": estantes_fijos, "estantes_moviles": estantes_moviles,
              "tipo_estante_manual": tipo_estante_manual, "sin_fondo": sin_fondo,
              "luz_entre_tapas": luz_entre_tapas, "luz_perimetral_tapa": luz_perimetral_tapa,
              "alto_frentin_emb": alto_frentin_emb, "aire_trasero": aire_trasero,
              "esp_corredera": esp_corredera, "distribucion_tapas": distribucion_tapas,
              "tiene_cenefa": tiene_cenefa, "alto_cenefa": alto_cenefa,
              "dias_prod": dias_prod,
              "indices_estantes_fijos": indices_fijos,
              "herrajes_extra": herrajes_extra_sel,
              "distancia_parante": distancia_parante,
              "precio_guardado": precio_a_usar,
          }

      # ── MODO: edición de presupuesto individual legacy ──
      if modo == "editar_legacy":
          st.subheader("💾 Guardar cambios")
          if st.button("Guardar cambios en el Historial", use_container_width=True, type="primary"):
              if not cliente:
                  st.warning("Ingresá el nombre del cliente.")
              elif precio_a_usar <= 0:
                  st.warning("El precio es 0. Completá las medidas para calcular.")
              else:
                  guardar_presupuesto_nube(cliente, tipo_modulo, precio_a_usar,
                                            parametros=_build_params_dict(),
                                            id_editar=ctx["id"])
                  _limpiar_edicion()
                  st.rerun()

      # ── MODO: edición de módulo dentro de obra ──
      elif modo == "editar_modulo_obra":
          st.subheader("✅ Confirmar cambios en el módulo")
          nombre_modulo = st.text_input("Nombre del módulo", value=_v("nombre", f"{tipo_modulo} {ancho_m:.0f}mm"))
          if st.button("Confirmar edición y volver a la Obra", use_container_width=True, type="primary"):
              if precio_a_usar <= 0:
                  st.warning("El precio es 0. Completá las medidas.")
              else:
                  nuevo_mod = {
                      "nombre": nombre_modulo, "tipo": tipo_modulo,
                      "ancho": int(ancho_m), "alto": int(alto_m), "prof": int(prof_m),
                      "material": mat_principal, "precio": precio_a_usar,
                      "df_corte": df_corte.copy() if not df_corte.empty else None,
                      "tipo_tapa": tipo_tapa, "params": _build_params_dict(),
                  }
                  mods = list(st.session_state["obra_modulos"])
                  idx  = ctx.get("idx", 0)
                  if idx < len(mods): mods[idx] = nuevo_mod
                  else: mods.append(nuevo_mod)
                  mods = [m for m in mods if m is not None]
                  st.session_state["obra_modulos"] = mods
                  # Auto-guardado en nube si tiene obra_id
                  _oid = ctx.get("obra_id")
                  _cli = ctx.get("obra_cliente") or cliente
                  if _oid and _cli:
                      _guardar_obra_nube(mods, _cli, _oid)
                  _limpiar_edicion()
                  st.rerun()

      # ── MODO: módulo nuevo → va al carrito de obra ──
      else:
          st.subheader("🛒 Agregar al Resumen de Obra")
          st.markdown("<span style='color:#666;font-size:14px;'>Cada módulo se suma al presupuesto total de la obra.</span>", unsafe_allow_html=True)
          nombre_modulo = st.text_input("Nombre del módulo", value=f"{tipo_modulo} {ancho_m:.0f}mm")
          if st.button("👇 Agregar mueble al Resumen de Obra", use_container_width=True, type="primary"):
              if ancho_m <= 0 or alto_m <= 0:
                  st.warning("Ingresá las medidas del módulo.")
              elif precio_a_usar <= 0:
                  st.warning("El precio es 0. Completá las medidas para calcular.")
              else:
                  nuevo_mod = {
                      "nombre": nombre_modulo, "tipo": tipo_modulo,
                      "ancho": int(ancho_m), "alto": int(alto_m), "prof": int(prof_m),
                      "material": mat_principal, "precio": precio_a_usar,
                      "df_corte": df_corte.copy() if not df_corte.empty else None,
                      "tipo_tapa": tipo_tapa, "params": _build_params_dict(),
                  }
                  st.session_state["obra_modulos"].append(nuevo_mod)
                  st.session_state["ultimo_agregado"] = {"nombre": nombre_modulo, "precio": precio_a_usar}
                  _limpiar_edicion()
                  st.rerun()

      if st.session_state.get("ultimo_agregado"):
          ua = st.session_state["ultimo_agregado"]
          n  = len(st.session_state["obra_modulos"])
          tot = sum(m["precio"] for m in st.session_state["obra_modulos"] if m is not None)
          st.info(f"**✅ {ua['nombre']}** agregado — ${ua['precio']:,.0f}\n\n📋 Tenés **{n} módulo(s)** — Total: **${tot:,.0f}**\n\n👉 Configurá el siguiente módulo arriba o bajá al Resumen de Obra.")
          st.session_state["ultimo_agregado"] = None


    # ═══════════════════════════════════════════════════════════════════════
    # RESUMEN DE OBRA
    # ═══════════════════════════════════════════════════════════════════════
    _mods_obra = [m for m in st.session_state["obra_modulos"] if m is not None]
    if _mods_obra and modo not in ["editar_legacy", "editar_modulo_obra", "elegir_modulo_obra"]:
        st.write("---")
        st.header("🏠 Resumen de Obra Completa")

        subtotal_mods = sum(m["precio"] for m in _mods_obra)

        for i_m, mod in enumerate(_mods_obra):
            col_mod, col_edit, col_del = st.columns([5, 1, 1])
            col_mod.write(f"**{i_m+1}. {mod['nombre']}** — {mod['ancho']}×{mod['alto']}×{mod['prof']} mm — {mod['material']} — `${mod['precio']:,.0f}`")
            if col_edit.button("✏️", key=f"edit_mod_{i_m}", help="Editar este módulo"):
                # Si la obra vino del historial, preservamos su ID para auto-guardado
                _obra_id_ctx     = st.session_state.get("_obra_id_historial")
                _obra_cli_ctx    = st.session_state.get("_obra_cliente_historial") or (cliente if cliente else "")
                st.session_state["edit_ctx"] = {
                    "modo":        "editar_modulo_obra",
                    "idx":         i_m,
                    "obra_id":     _obra_id_ctx,
                    "obra_cliente": _obra_cli_ctx,
                    "params":      _params_desde_mod(mod),
                }
                st.session_state.pop("_tipo_modulo_sel", None)
                st.session_state.pop("_ctx_sig_prev",    None)
                st.rerun()
            if col_del.button("✕", key=f"del_mod_{i_m}"):
                st.session_state["obra_modulos"].pop(i_m)
                st.rerun()

        st.write("---")

        with st.expander("🚛 Logística y colocación", expanded=True):
            st.caption("Costos que se suman al total de la obra.")
            col_fl, col_col, col_dias = st.columns(3)
            flete_sel     = col_fl.selectbox("Flete", ["Ninguno","Capital","Zona Norte"], key="flete_obra")
            necesita_col  = col_col.checkbox("¿Requiere colocación?", key="col_obra")
            dias_col_obra = col_dias.number_input("Días de colocación", value=0, min_value=0, key="dias_col_obra") if necesita_col else 0
            costo_flete   = config.get("flete_capital",0) if flete_sel=="Capital" else config.get("flete_norte",0) if flete_sel=="Zona Norte" else 0.0
            costo_col     = dias_col_obra * config.get("colocacion_dia", 0)
            costo_log     = costo_flete + costo_col
            if costo_log > 0:
                st.info(f"Logística y colocación: **${costo_log:,.0f}**")

        total_obra = subtotal_mods + costo_log
        st.markdown(f'''<div style="background:#0F6E56;border-radius:12px;padding:20px 24px;margin:12px 0;text-align:center;">
        <div style="color:rgba(255,255,255,0.7);font-size:12px;letter-spacing:0.1em;margin-bottom:6px;">TOTAL DE LA OBRA</div>
        <div style="color:white;font-size:44px;font-weight:700;letter-spacing:-2px;">${total_obra:,.0f}</div>
        <div style="color:rgba(255,255,255,0.65);font-size:13px;margin-top:6px;">{len(_mods_obra)} módulo(s) · Módulos: ${subtotal_mods:,.0f}{f" · Logística: ${costo_log:,.0f}" if costo_log > 0 else ""}</div>
        </div>''', unsafe_allow_html=True)

        col_d1, col_d2 = st.columns(2)
        dias_entrega = col_d1.number_input("Días de entrega total", value=20, step=1, key="dias_obra")
        pct_seña     = col_d2.slider("% de Seña", 0, 100, 50, 5, key="sena_obra")
        cliente_obra = cliente or ""

        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            _mods_pdf = _mods_obra
            pdf_data = generar_pdf_obra(cliente_obra, _mods_pdf, dias_entrega, pct_seña,
                                         costo_logistica=costo_flete, dias_colocacion=dias_col_obra,
                                         costo_colocacion_dia=config.get("colocacion_dia",0))
            st.download_button("📥 PDF Presupuesto", data=pdf_data,
                                file_name=f"Obra_{cliente_obra}.pdf", mime="application/pdf", use_container_width=True)
        with col_g2:
            link_wa = generar_link_whatsapp_obra(cliente_obra, _mods_pdf, dias_entrega, pct_seña,
                                                   costo_logistica=costo_flete, dias_colocacion=dias_col_obra,
                                                   costo_colocacion_dia=config.get("colocacion_dia",0))
            st.link_button("🟢 WhatsApp", link_wa, use_container_width=True)
        with col_g3:
            if st.button("🗑️ Limpiar obra", use_container_width=True):
                st.session_state["obra_modulos"] = []; st.rerun()

        with st.expander("⚙️ Terminal CNC — Obra completa"):
            _mods_cnc = [m for m in _mods_obra if m.get("df_corte") is not None]
            if _mods_cnc:
                dxf_obra = generar_dxf_obra(_mods_cnc)
                csv_obra = exportar_csv_obra(_mods_cnc, esp_real)
                cc1, cc2 = st.columns(2)
                cc1.download_button("📐 DXF Obra", data=dxf_obra, file_name=f"DXF_{cliente_obra}.dxf", mime="application/dxf", use_container_width=True)
                cc2.download_button("🤖 CSV Obra", data=csv_obra, file_name=f"CNC_{cliente_obra}.csv", mime="text/csv", use_container_width=True)
            else:
                st.warning("Calculá los módulos en esta sesión para exportar CNC.")

        if st.button("💾 Guardar obra en historial", use_container_width=True):
            if not cliente_obra:
                st.warning("Ingresá el nombre del cliente arriba.")
            else:
                # Usamos el obra_id del historial si estamos editando una obra existente
                _id_a_guardar = st.session_state.pop("_obra_id_historial", None)
                _guardar_obra_nube(_mods_obra, cliente_obra, _id_a_guardar)
                # Limpieza total del cotizador
                st.session_state["obra_modulos"] = []
                st.session_state.pop("_obra_cliente_historial", None)
                st.session_state.pop("_tipo_modulo_sel",        None)
                st.session_state.pop("_ctx_sig_prev",           None)
                _limpiar_edicion()
                st.rerun()

  except Exception as e:
      import traceback
      st.error(f"Error en el Cotizador: {e}")
      with st.expander("Ver detalle del error"):
          st.code(traceback.format_exc())

elif menu == "📋 Historial":
    st.title("📋 Historial de presupuestos")
    ESTADOS = ["Pendiente","Señado","Pagado"]
    COLORES = {"Pendiente": ("🔴","#FCEBEB","#A32D2D"), "Señado": ("🟡","#FAEEDA","#854F0B"), "Pagado": ("🟢","#E1F5EE","#0F6E56")}

    def actualizar_estado(id_venta, nuevo_estado):
        try:
            supabase.postgrest.auth(st.session_state["session"].access_token)
            supabase.table("ventas").update({"estado": nuevo_estado}).eq("id", id_venta).execute()
        except Exception as e:
            st.error(f"Error: {e}")

    try:
        df_hist = traer_datos_historial()
        if df_hist.empty:
            st.info("No hay presupuestos guardados todavía.")
        else:
            total_pend  = df_hist[df_hist['estado']=='Pendiente']['precio_final'].sum()
            total_señad = df_hist[df_hist['estado']=='Señado']['precio_final'].sum()
            total_pag   = df_hist[df_hist['estado']=='Pagado']['precio_final'].sum()
            c1,c2,c3 = st.columns(3)
            c1.metric("🔴 Pendientes", f"${total_pend:,.0f}",  f"{len(df_hist[df_hist['estado']=='Pendiente'])} presupuestos")
            c2.metric("🟡 Señados",    f"${total_señad:,.0f}", f"{len(df_hist[df_hist['estado']=='Señado'])} presupuestos")
            c3.metric("🟢 Pagados",    f"${total_pag:,.0f}",   f"{len(df_hist[df_hist['estado']=='Pagado'])} presupuestos")
            st.write("---")
            filtro = st.radio("Mostrar", ["Todos","Pendiente","Señado","Pagado"], horizontal=True)
            df_f = df_hist if filtro=="Todos" else df_hist[df_hist['estado']==filtro]
            df_f = df_f.sort_values("fecha", ascending=False) if "fecha" in df_f.columns else df_f
            st.write(f"**{len(df_f)} presupuesto(s)**")
            st.write("---")

            for idx, row in df_f.iterrows():
                estado_actual = row.get('estado','Pendiente')
                if estado_actual not in COLORES: estado_actual = 'Pendiente'
                icono, bg, tc = COLORES[estado_actual]
                id_venta = row.get('id')

                st.markdown(f"""<div style="background:{bg};border-radius:8px;padding:12px 16px;margin-bottom:4px;">
                <span style="color:{tc};font-weight:600;font-size:15px;">{icono} {row.get('cliente','Sin nombre')} — {row.get('mueble','')}</span>
                <span style="color:{tc};float:right;font-size:15px;font-weight:600;">${row['precio_final']:,.0f}</span></div>""", unsafe_allow_html=True)

                col_fecha, col_estado, col_b1, col_b2, col_b3 = st.columns([2,2,1,1,1])
                fecha_str = str(row.get('fecha',''))[:16] if row.get('fecha') else 'Sin fecha'
                col_fecha.caption(f"📅 {fecha_str}")
                nuevo_estado = col_estado.selectbox("Estado", ESTADOS, index=ESTADOS.index(estado_actual),
                                                     key=f"estado_{id_venta}_{idx}", label_visibility="collapsed")

                with col_b1:
                    if st.button("Guardar", key=f"save_{id_venta}_{idx}", use_container_width=True):
                        if id_venta and nuevo_estado != estado_actual:
                            actualizar_estado(id_venta, nuevo_estado)
                            st.rerun()

                with col_b2:
                    tiene_params = row.get('parametros') not in [None,'','null']
                    if st.button("Editar" if tiene_params else "—", key=f"edit_{id_venta}_{idx}",
                                 use_container_width=True, disabled=not tiene_params,
                                 help="Editar este presupuesto" if tiene_params else "Sin parámetros guardados"):
                        try:
                            params = json.loads(row['parametros'])
                            if params.get("es_obra"):
                                mods      = params.get("modulos", [])
                                cliente_h = row.get('cliente','')

                                # Convertimos al formato interno de obra_modulos
                                mods_internos = []
                                for m in mods:
                                    p = _params_desde_mod(m)
                                    mods_internos.append({
                                        "nombre":    m.get("nombre", p.get("nombre","")),
                                        "tipo":      m.get("tipo_modulo", p.get("tipo_modulo","")),
                                        "ancho":     int(m.get("ancho_m", p.get("ancho_m", 0))),
                                        "alto":      int(m.get("alto_m",  p.get("alto_m",  0))),
                                        "prof":      int(m.get("prof_m",  p.get("prof_m",  0))),
                                        "material":  m.get("mat_principal", p.get("mat_principal","")),
                                        "precio":    m.get("precio", p.get("precio_guardado", 0)),
                                        "tipo_tapa": p.get("tipo_tapa","Superpuesta"),
                                        "df_corte":  None,
                                        "params":    p,
                                    })

                                st.session_state["obra_modulos"]            = mods_internos
                                st.session_state["_obra_id_historial"]      = id_venta
                                st.session_state["_obra_cliente_historial"] = cliente_h
                                st.session_state.pop("_tipo_modulo_sel", None)
                                st.session_state.pop("_ctx_sig_prev",    None)
                                st.session_state["menu_idx"] = 0

                                if len(mods_internos) == 1:
                                    # Un solo módulo: cargarlo directo en el cotizador
                                    st.session_state["edit_ctx"] = {
                                        "modo":        "editar_modulo_obra",
                                        "idx":         0,
                                        "obra_id":     id_venta,
                                        "obra_cliente": cliente_h,
                                        "params":      mods_internos[0]["params"],
                                    }
                                else:
                                    # Varios módulos: ir al cotizador y mostrar selector arriba
                                    st.session_state["edit_ctx"] = {
                                        "modo":        "elegir_modulo_obra",
                                        "obra_id":     id_venta,
                                        "obra_cliente": cliente_h,
                                    }
                            else:
                                # Presupuesto individual
                                params["precio_guardado"] = float(row.get("precio_final", 0))
                                st.session_state["edit_ctx"] = {
                                    "modo":    "editar_legacy",
                                    "id":      id_venta,
                                    "cliente": row.get('cliente',''),
                                    "params":  params,
                                }
                                st.session_state.pop("_tipo_modulo_sel", None)
                                st.session_state.pop("_ctx_sig_prev",    None)
                                st.session_state["menu_idx"] = 0
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                with col_b3:
                    if st.button("Borrar", key=f"del_{id_venta}_{idx}", use_container_width=True):
                        try:
                            token = get_token()
                            if token: supabase.postgrest.auth(token)
                            supabase.table("ventas").delete().eq("id", id_venta).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                st.write("---")
    except Exception as e:
        st.error(f"Error en el historial: {e}")


# ===========================================================================
# RETAZOS
# ===========================================================================
elif menu == "♻️ Retazos":
    st.title("♻️ Depósito de retazos")
    with st.expander("+ Registrar nuevo retazo", expanded=True):
        st.markdown("**Mínimo útil: 150 × 400 mm**")
        c_mat, c_l, c_a = st.columns([2,1,1])
        mat_r   = c_mat.selectbox("Material", list(maderas.keys()), key="mat_ret")
        largo_r = c_l.number_input("Largo (mm)", min_value=0, value=0, step=10, key="lar_r_indep")
        ancho_r = c_a.number_input("Ancho (mm)", min_value=0, value=0, step=10, key="anc_r_indep")
        if largo_r > 0 and ancho_r > 0:
            es_util = (largo_r>=400 and ancho_r>=150) or (largo_r>=150 and ancho_r>=400)
            area    = (largo_r * ancho_r) / 1_000_000
            valor   = area * (maderas.get(mat_r,0) / 5.03)
            if es_util:
                st.success(f"Válido — {largo_r}×{ancho_r} mm — {area:.3f} m² — Valor est. ${valor:,.0f}")
            else:
                st.error(f"Demasiado chico ({largo_r}×{ancho_r}). Mínimo: 150×400 mm.")
        if st.button("Guardar en depósito", use_container_width=True, type="primary"):
            if largo_r > 0 and ancho_r > 0:
                if (largo_r>=400 and ancho_r>=150) or (largo_r>=150 and ancho_r>=400):
                    registrar_retazo(mat_r, largo_r, ancho_r); st.rerun()
                else:
                    st.warning("No cumple el mínimo.")
            else:
                st.warning("Ingresá las medidas.")

    st.write("---")
    retazos_db = consultar_retazos_disponibles("Todos")
    if not retazos_db:
        st.info("El depósito está vacío.")
    else:
        df_inv = pd.DataFrame(retazos_db)
        c1,c2,c3 = st.columns(3)
        c1.metric("Retazos en stock", len(df_inv))
        c2.metric("Materiales", df_inv['material'].nunique() if 'material' in df_inv.columns else 0)
        if 'largo' in df_inv.columns:
            c3.metric("Área total", f"{(df_inv['largo']*df_inv['ancho']).sum()/1_000_000:.2f} m²")
        st.write("---")
        for mat in df_inv['material'].unique():
            df_mat = df_inv[df_inv['material']==mat]
            with st.expander(f"{mat} — {len(df_mat)} retazo(s)", expanded=True):
                for _, ret in df_mat.iterrows():
                    c_i, c_a2, c_d = st.columns([3,2,1])
                    largo = ret.get('largo',0); ancho = ret.get('ancho',0)
                    area  = (largo*ancho)/1_000_000
                    valor = area * (maderas.get(mat,0)/5.03)
                    c_i.markdown(f"**{int(largo)} × {int(ancho)} mm**")
                    c_a2.caption(f"{area:.3f} m² — ${valor:,.0f}")
                    ret_id = ret.get('id')
                    if c_d.button("✕", key=f"del_ret_{ret_id}"):
                        try:
                            token = get_token()
                            if token: supabase.postgrest.auth(token)
                            supabase.table("retazos").delete().eq("id", ret_id).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")


elif menu == "⚙️ Precios":
    st.title("⚙️ Configuración de precios")

    with st.expander("🪵 Precios de Placas (18mm)", expanded=True):
        for madera, precio in list(maderas.items()):
            col_name, col_price, col_del = st.columns([5, 3, 1])
            col_name.markdown(f"<div style='padding-top: 8px; font-weight: 500;'>{madera}</div>", unsafe_allow_html=True)
            maderas[madera] = col_price.number_input("Precio", value=float(precio), step=1000.0, key=f"p_{madera}", label_visibility="collapsed")
            if col_del.button("🗑️", key=f"del_{madera}", help=f"Eliminar {madera}"):
                eliminar_precio_nube(madera, 'maderas')
                st.rerun()

        st.write("---")
        st.markdown("**➕ Agregar nueva placa**")
        c_nm, c_np, c_nb = st.columns([5, 3, 1])
        nueva_mad_n = c_nm.text_input("Nombre", key="new_mad_n", label_visibility="collapsed", placeholder="Ej: Enchapado Nogal 18mm")
        nueva_mad_p = c_np.number_input("Precio", min_value=0.0, step=1000.0, key="new_mad_p", label_visibility="collapsed")
        if c_nb.button("Agregar", key="add_mad", use_container_width=True):
            if nueva_mad_n and nueva_mad_p > 0:
                actualizar_precio_nube(nueva_mad_n, nueva_mad_p, 'maderas')
                st.rerun()

    claves_base = ['bisagra_cazoleta', 'telescopica_45', 'telescopica_soft']
    herrajes_custom = {k: v for k, v in config.items() if k not in ['gastos_fijos_diarios', 'flete_capital', 'flete_norte', 'colocacion_dia', 'ganancia_taller_pct'] + claves_base}

    with st.expander("🔩 Herrajes, Cerraduras y Extras", expanded=False):
        st.caption("Herrajes base del cotizador automático:")
        c1, c2, c3 = st.columns(3)
        config['bisagra_cazoleta'] = c1.number_input("Bisagra Cazoleta", value=float(config.get('bisagra_cazoleta', 1200)), step=100.0)
        config['telescopica_45']   = c2.number_input("Guía 45cm", value=float(config.get('telescopica_45', 5000)), step=100.0)
        config['telescopica_soft'] = c3.number_input("Guía Cierre Suave", value=float(config.get('telescopica_soft', 12000)), step=100.0)

        st.write("---")
        st.caption("Tus accesorios y cerraduras personalizadas:")
        if not herrajes_custom:
            st.info("No hay accesorios extra guardados. Agregá uno abajo.")
        else:
            for h_nom, h_pre in herrajes_custom.items():
                ch_n, ch_p, ch_d = st.columns([5, 3, 1])
                ch_n.markdown(f"<div style='padding-top: 8px; font-weight: 500;'>{h_nom}</div>", unsafe_allow_html=True)
                config[h_nom] = ch_p.number_input("Precio", value=float(h_pre), step=100.0, key=f"p_{h_nom}", label_visibility="collapsed")
                if ch_d.button("🗑️", key=f"del_{h_nom}", help=f"Eliminar {h_nom}"):
                    eliminar_precio_nube(h_nom, 'herrajes')
                    st.rerun()

        st.write("---")
        st.markdown("**➕ Agregar nuevo accesorio**")
        ch_nm, ch_np, ch_nb = st.columns([5, 3, 1])
        nuevo_herr_n = ch_nm.text_input("Nombre", key="new_herr_n", label_visibility="collapsed", placeholder="Ej: Cerradura cajón Hafele")
        nuevo_herr_p = ch_np.number_input("Precio", min_value=0.0, step=100.0, key="new_herr_p", label_visibility="collapsed")
        if ch_nb.button("Agregar", key="add_herr", use_container_width=True):
            if nuevo_herr_n and nuevo_herr_p > 0:
                actualizar_precio_nube(nuevo_herr_n, nuevo_herr_p, 'herrajes')
                st.rerun()

    with st.expander("🚛 Gastos Fijos y Logística", expanded=False):
        f1, f2 = st.columns(2)
        config['gastos_fijos_diarios'] = f1.number_input("Gasto Diario Taller", value=float(config.get('gastos_fijos_diarios', 25000)), step=5000.0)
        config['flete_capital']        = f2.number_input("Flete Capital", value=float(config.get('flete_capital', 15000)), step=1000.0)
        config['flete_norte']          = f1.number_input("Flete Zona Norte", value=float(config.get('flete_norte', 20000)), step=1000.0)
        config['colocacion_dia']       = f2.number_input("Costo Día de Colocación", value=float(config.get('colocacion_dia', 45000)), step=5000.0)

    with st.expander("💰 Margen de Ganancia", expanded=False):
        config['ganancia_taller_pct'] = st.slider("Porcentaje de Utilidad", 0.0, 1.0, float(config.get('ganancia_taller_pct', 0.3)), 0.05)
        st.write(f"Margen actual: {config.get('ganancia_taller_pct', 0.3)*100:.0f}%")

    if st.button("💾 Guardar Configuración", type="primary", use_container_width=True):
        for madera, precio in maderas.items():
            actualizar_precio_nube(madera, precio, 'maderas')
        for k, v in config.items():
            cat = 'costos' if k in ['gastos_fijos_diarios', 'flete_capital', 'flete_norte', 'colocacion_dia', 'ganancia_taller_pct'] else 'herrajes'
            actualizar_precio_nube(k, v, cat)
        st.success("✅ Configuración guardada")
