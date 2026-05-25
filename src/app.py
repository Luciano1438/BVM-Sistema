
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
    pdf.set_font("Arial", "B", 20)
    pdf.set_text_color(46, 125, 50)
    pdf.cell(200, 20, "PRESUPUESTO DE OBRA - BVM", ln=True, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 10)
    tz_arg = timezone(timedelta(hours=-3))
    fecha_hoy = datetime.now(tz_arg).strftime("%d/%m/%Y")
    pdf.cell(200, 8, f"Fecha: {fecha_hoy}    Cliente: {cliente}", ln=True, align="R")
    pdf.ln(4)

    subtotal_modulos = sum(m["precio"] for m in modulos)
    costo_col = dias_colocacion * costo_colocacion_dia
    total_obra = subtotal_modulos + costo_logistica + costo_col

    for i, mod in enumerate(modulos):
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(230, 245, 238)
        pdf.cell(0, 11, f"  {i+1}. {mod['nombre']}", ln=True, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(95, 7, f"  Tipo: {mod['tipo']}", border="L", ln=False)
        pdf.cell(95, 7, f"  Material: {mod['material']}", border="R", ln=True)
        pdf.cell(95, 7, f"  Ancho: {mod['ancho']} mm", border="L", ln=False)
        pdf.cell(95, 7, f"  Alto: {mod['alto']} mm", border="R", ln=True)
        pdf.cell(95, 7, f"  Profundidad: {mod['prof']} mm", border="LB", ln=False)
        pdf.cell(95, 7, f"  Terminacion: {mod.get('tipo_tapa', 'Estandar')}", border="RB", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"  Subtotal: ${mod['precio']:,.0f}", ln=True, align="R")
        pdf.ln(3)

    # Logística y colocación al final
    if costo_logistica > 0 or costo_col > 0:
        pdf.set_font("Arial", "B", 11)
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(0, 9, "  Costos adicionales de obra", ln=True, fill=True)
        pdf.set_font("Arial", "", 10)
        if costo_logistica > 0:
            pdf.cell(0, 7, f"  Flete / Logistica: ${costo_logistica:,.0f}", ln=True)
        if costo_col > 0:
            pdf.cell(0, 7, f"  Colocacion ({dias_colocacion} dias): ${costo_col:,.0f}", ln=True)
        pdf.ln(2)

    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 12, f"TOTAL OBRA: ${total_obra:,.0f}", ln=True, align="C", fill=True)
    monto_seña = total_obra * (pct_seña / 100)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Seña requerida ({pct_seña}%): ${monto_seña:,.0f}", ln=True, align="C")
    pdf.cell(0, 8, f"Tiempo estimado de entrega: {dias_entrega} dias habiles", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", "I", 9)
    pdf.multi_cell(0, 5, "Los precios se mantienen 48hs. Una vez abonada la seña se congelan los materiales.")
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

def consultar_retazos_disponibles(material):
    try:
        res = supabase.table("retazos").select("*").eq("user_id", st.session_state["user"].id).execute()
        return res.data
    except Exception as e:
        st.error(f"Error al consultar retazos: {e}")
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
        supabase.postgrest.auth(st.session_state["session"].access_token)
        supabase.table("configuracion").upsert(
            {"user_id": st.session_state["user"].id, "clave": clave, "valor": float(valor), "categoria": categoria},
            on_conflict="user_id, clave"
        ).execute()
    except Exception as e:
        st.error(f"Error guardando {clave}: {e}")

def traer_datos():
    if "session" not in st.session_state or not st.session_state["session"]:
        return {}, {}, {}
    maderas_default = {"Melamina Blanca 18mm": 60000.0, "Melamina Color 18mm": 85000.0, "Enchapado Roble 18mm": 120000.0}
    config_default  = {'bisagra_cazoleta': 1200.0, 'telescopica_45': 5000.0, 'telescopica_soft': 12000.0,
                       'gastos_fijos_diarios': 25000.0, 'flete_capital': 15000.0, 'flete_norte': 20000.0,
                       'colocacion_dia': 45000.0, 'ganancia_taller_pct': 0.30}
    try:
        supabase.postgrest.auth(st.session_state["session"].access_token)
        datos_db = supabase.table("configuracion").select("*").eq("user_id", st.session_state["user"].id).execute().data
        maderas_db = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria','')).lower().strip() == 'maderas'}
        config_db  = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria','')).lower().strip() in ['costos','margen','herrajes']}
        maderas = {**maderas_default, **maderas_db}
        config  = {**config_default,  **config_db}
        fondos  = {'Fibroplus Blanco 3mm': 34500.0, 'Faplac Fondo 5.5mm': 45000.0, 'Sin fondo': 0.0}
        return maderas, fondos, config
    except Exception as e:
        st.error(f"Error cargando configuración: {e}")
        return maderas_default, {'Fibroplus Blanco 3mm': 34500.0, 'Sin fondo': 0.0}, config_default

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

# SESSION STATE
for k, v in {
    "obra_modulos": [], "editar_presupuesto": None, "editar_id": None,
    "editar_cliente": "", "editar_obra_modulos": None, "editar_obra_id": None,
    "editar_obra_cliente": "", "idx_modulo_editar": None,
    "edicion_tipo_cargado": False, "logistica_obra": {},
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

maderas, fondos, config = traer_datos()
_opciones_menu = ["🪵 Cotizador", "♻️ Retazos", "📋 Historial", "⚙️ Precios"]
_forzar_cotizador = bool(st.session_state.get("editar_presupuesto") or st.session_state.get("editar_obra_modulos"))

# SIDEBAR
st.sidebar.markdown("""<div style="padding:8px 4px 16px 4px;border-bottom:1px solid rgba(255,255,255,0.12);margin-bottom:12px;">
<div style="font-size:22px;font-weight:500;color:white;">🪵 BVM</div>
<div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:2px;">Sistema de carpintería</div></div>""", unsafe_allow_html=True)

if _forzar_cotizador:
    menu = "🪵 Cotizador"
    st.sidebar.radio("Navegación", _opciones_menu, index=0)
else:
    menu = st.sidebar.radio("Navegación", _opciones_menu, index=st.session_state.get("menu_idx", 0))
    st.session_state["menu_idx"] = _opciones_menu.index(menu)

if st.session_state["obra_modulos"]:
    total_obra_sb = sum(m["precio"] for m in st.session_state["obra_modulos"])
    st.sidebar.markdown(f"""<div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:10px 12px;margin:12px 0 4px 0;">
    <div style="font-size:10px;color:rgba(255,255,255,0.5);letter-spacing:0.06em;margin-bottom:4px;">OBRA EN CURSO</div>
    <div style="font-size:20px;font-weight:500;color:white;">${total_obra_sb:,.0f}</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:2px;">{len(st.session_state['obra_modulos'])} módulo(s)</div></div>""", unsafe_allow_html=True)

st.sidebar.write("---")
if st.sidebar.button("Cerrar sesión"):
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()


# ===========================================================================
# COTIZADOR
# ===========================================================================
if menu == "🪵 Cotizador":
    try:
        st.title("🪵 BVM — Cotizador de muebles")

        # Selector de módulo de obra multi-módulo
        obra_mods = st.session_state.get("editar_obra_modulos")
        if obra_mods and not st.session_state.get("editar_presupuesto"):
            cliente_obra_edit = st.session_state.get("editar_obra_cliente", "")
            st.warning(f"**Editando obra de {cliente_obra_edit}** — Elegí qué módulo querés rehacer:")
            for i, mod in enumerate(obra_mods):
                col_info, col_sel = st.columns([4, 1])
                col_info.write(f"**{i+1}. {mod['nombre']}** — {mod['ancho_m']}x{mod['alto_m']}x{mod['prof_m']} mm — {mod['mat_principal']} — ${mod['precio']:,.0f}")
                if col_sel.button("Editar este", key=f"sel_mod_obra_{i}"):
                    otros = []
                    for j, m in enumerate(obra_mods):
                        if j != i:
                            otros.append({"nombre": m["nombre"], "tipo": m.get("tipo_modulo", ""), "ancho": m.get("ancho_m", 0),
                                          "alto": m.get("alto_m", 0), "prof": m.get("prof_m", 0),
                                          "material": m.get("mat_principal", ""), "precio": m.get("precio", 0), "df_corte": None})
                    lista = otros[:i] + [None] + otros[i:]
                    st.session_state.update({"obra_modulos": lista, "editar_presupuesto": mod,
                                             "editar_cliente": cliente_obra_edit, "idx_modulo_editar": i,
                                             "editar_obra_modulos": None, "menu_idx": 0,
                                             "edicion_tipo_cargado": False})
                    st.rerun()
            if st.button("Cancelar", key="cancel_obra_edit"):
                st.session_state["editar_obra_modulos"] = None
                st.rerun()

        ep = st.session_state.get("editar_presupuesto")
        if ep:
            st.info(f"**Editando módulo** — Cliente: {st.session_state.get('editar_cliente', '')}. Modificá lo que necesitás y guardá.")
            if st.button("Cancelar edición"):
                st.session_state.update({"editar_presupuesto": None, "editar_id": None, "editar_cliente": ""})
                st.rerun()

        def _v(key, default):
            return ep[key] if ep and key in ep else default

        # Defaults
        df_corte = pd.DataFrame()
        costo_madera = costo_fondo = costo_herrajes = precio_final = total_costo = 0.0
        m2_18mm = m2_fondo = costo_operativo = utilidad = 0.0
        tiene_parante = _v("tiene_parante", False)
        tiene_parante_medio = _v("tiene_parante_medio", False)
        tipo_parante  = _v("tipo_parante", "Corto (100mm)")
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

        lista_modulos = ["Cajonera", "Bajo Mesada", "Alacena"]
        lista_maderas = list(maderas.keys())
        lista_fondos  = list(fondos.keys())
        idx_madera = lista_maderas.index(_v("mat_principal", lista_maderas[0])) if _v("mat_principal", lista_maderas[0]) in lista_maderas else 0
        idx_fondo  = lista_fondos.index(_v("mat_fondo_sel",  lista_fondos[0]))  if _v("mat_fondo_sel",  lista_fondos[0])  in lista_fondos  else 0

        if ep and "tipo_modulo" in ep and not st.session_state.get("edicion_tipo_cargado"):
            st.session_state["tipo_modulo_sel"] = ep["tipo_modulo"]
            st.session_state["edicion_tipo_cargado"] = True
        elif not ep:
            st.session_state["edicion_tipo_cargado"] = False

        col_in, col_out = st.columns([1, 1.2])

        with col_in:
            with st.expander("🛠️ Definición de estructura", expanded=True):
                cliente = st.text_input("Cliente", st.session_state.get("editar_cliente", ""))

                st.markdown("**Tipo de mueble**")
                if "tipo_modulo_sel" not in st.session_state:
                    st.session_state["tipo_modulo_sel"] = "Cajonera"

                _svgs = {
                    "Bajo Mesada": '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="18" width="76" height="38" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="18" width="76" height="8" rx="1" fill="COLOR" opacity="0.25"/><line x1="41" y1="26" x2="41" y2="56" stroke="COLOR" stroke-width="1.2"/><rect x="5" y="30" width="33" height="22" rx="1.5" fill="COLOR" opacity="0.18"/><rect x="44" y="30" width="33" height="22" rx="1.5" fill="COLOR" opacity="0.18"/><circle cx="39" cy="41" r="2" fill="COLOR" opacity="0.6"/><circle cx="43" cy="41" r="2" fill="COLOR" opacity="0.6"/></svg>',
                    "Cajonera":    '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="5" y="4" width="70" height="52" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="8" y="8" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><rect x="8" y="24" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><rect x="8" y="40" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><circle cx="40" cy="14.5" r="2" fill="COLOR" opacity="0.7"/><circle cx="40" cy="30.5" r="2" fill="COLOR" opacity="0.7"/><circle cx="40" cy="46.5" r="2" fill="COLOR" opacity="0.7"/></svg>',
                    "Alacena":     '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="2" width="76" height="52" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="2" width="76" height="7" rx="1" fill="COLOR" opacity="0.2"/><line x1="41" y1="9" x2="41" y2="54" stroke="COLOR" stroke-width="1.2"/><rect x="5" y="13" width="33" height="37" rx="1.5" fill="COLOR" opacity="0.18"/><rect x="44" y="13" width="33" height="37" rx="1.5" fill="COLOR" opacity="0.18"/><circle cx="39" cy="31" r="2" fill="COLOR" opacity="0.6"/><circle cx="43" cy="31" r="2" fill="COLOR" opacity="0.6"/></svg>',
                }

                col_bm, col_caj, col_ala = st.columns(3)
                for col, nombre in [(col_bm, "Bajo Mesada"), (col_caj, "Cajonera"), (col_ala, "Alacena")]:
                    with col:
                        sel   = st.session_state["tipo_modulo_sel"] == nombre
                        color = "#1D9E75" if sel else "#888780"
                        bg    = "#E1F5EE" if sel else "transparent"
                        borde = "#1D9E75" if sel else "#D3D1C7"
                        svg   = _svgs[nombre].replace("COLOR", color)
                        st.markdown(f'<div style="border:2px solid {borde};border-radius:10px;padding:12px 8px 8px 8px;background:{bg};text-align:center;color:{color};">{svg}<div style="font-size:12px;font-weight:600;margin-top:6px;">{nombre}</div></div>', unsafe_allow_html=True)
                        if st.button("Seleccionar", key=f"sel_{nombre}", use_container_width=True, type="primary" if sel else "secondary"):
                            st.session_state["tipo_modulo_sel"] = nombre
                            st.rerun()

                tipo_modulo = st.session_state["tipo_modulo_sel"]
                c1, c2, c3 = st.columns(3)
                ancho_m = c1.number_input("Ancho total (mm)", min_value=0.0, max_value=5000.0, value=float(_v("ancho_m", 0.0)), step=0.5, help="Medida exterior de izquierda a derecha")
                alto_m  = c2.number_input("Alto total (mm)",  min_value=0.0, max_value=5000.0, value=float(_v("alto_m",  0.0)), step=0.5, help="Medida exterior de abajo hacia arriba")
                prof_m  = c3.number_input("Profundidad (mm)", min_value=0.0, max_value=2000.0, value=float(_v("prof_m",  0.0)), step=0.5, help="Estándar: 550mm bajo mesada, 350mm alacena")
                mat_principal = st.selectbox("Material del cuerpo (18mm)", lista_maderas, index=idx_madera)
                esp_real      = st.number_input("Espesor real de placa (mm)", min_value=1.0, max_value=50.0, value=float(_v("esp_real", 18.0)), step=0.1)
                mat_fondo_sel = st.selectbox("Material del fondo", lista_fondos, index=idx_fondo)
                sin_fondo = mat_fondo_sel == "Sin fondo"

            with st.expander("🏗️ Configuración del módulo", expanded=False):
                if tipo_modulo == "Bajo Mesada":
                    _bm_opts = ["Superpuesta", "Gola BVM", "Embutida"]
                    _bm_idx  = _bm_opts.index(_v("tipo_tapa", "Superpuesta")) if _v("tipo_tapa", "Superpuesta") in _bm_opts else 0
                    tipo_tapa    = st.radio("Estilo", _bm_opts, index=_bm_idx)
                    _puertas_bm  = int(_v("cant_puertas", 2))
                    cant_puertas = st.selectbox("Cantidad de Puertas", [2, 3], index=0 if _puertas_bm == 2 else 1)

                    if cant_puertas == 3:
                        tiene_parante = True
                        st.info("3 puertas: Parante divisor incluido.")
                        c_p1, c_p2 = st.columns(2)
                        tipo_parante      = c_p1.selectbox("Tipo de Parante", ["Corto (100mm)", "Largo (Fondo Lateral)"])
                        distancia_parante = c_p2.number_input("Distancia desde lateral izq. (mm)", value=ancho_m/cant_puertas if ancho_m > 0 else 0.0, step=1.0)

                    # Parante medio
                    tiene_parante_medio = st.checkbox("¿Lleva parante medio?", value=bool(_v("tiene_parante_medio", False)),
                                                       help="Parante central para dividir el bajo mesada en dos sectores")

                    st.markdown("---")
                    st.markdown("#### Estantes")
                    _cant_est_def = int(_v("estantes_fijos", 0)) + int(_v("estantes_moviles", 0))
                    cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=max(1, _cant_est_def), step=1, key="cant_est_bm")
                    _fmt_opts  = ["Completo", "Medio"]
                    _fmt_idx   = _fmt_opts.index(_v("tipo_estante_manual", "Completo")) if _v("tipo_estante_manual", "Completo") in _fmt_opts else 0
                    tipo_estante_manual = st.radio("Formato de Estante", _fmt_opts, index=_fmt_idx, key="fmt_est_bm")
                    indices_fijos = []
                    if cant_total_est > 0:
                        st.write("¿Cuáles son fijos?")
                        cols_e = st.columns(int(cant_total_est))
                        for i in range(int(cant_total_est)):
                            with cols_e[i]:
                                if st.checkbox(f"E{i+1}", key=f"check_est_bm_{i}"):
                                    indices_fijos.append(i)
                    estantes_fijos   = len(indices_fijos)
                    estantes_moviles = cant_total_est - estantes_fijos
                    st.caption(f"{estantes_fijos} fijo(s) / {estantes_moviles} móvil(es)")
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "Especial"])
                    cant_cajones = 0

                elif tipo_modulo == "Alacena":
                    c_ala1, c_ala2 = st.columns(2)
                    _ala_opts    = ["Superpuesta", "Uñero", "Embutida"]
                    _ala_idx     = _ala_opts.index(_v("tipo_tapa", "Superpuesta")) if _v("tipo_tapa", "Superpuesta") in _ala_opts else 0
                    tipo_tapa    = c_ala1.radio("Sistema de Apertura", _ala_opts, index=_ala_idx)
                    _puertas_ala = int(_v("cant_puertas", 2))
                    cant_puertas = c_ala2.selectbox("Cantidad de Puertas", [2, 3, 4], index=[2,3,4].index(_puertas_ala) if _puertas_ala in [2,3,4] else 0)
                    st.markdown("---")
                    cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=1, step=1)
                    indices_fijos = []
                    if cant_total_est > 0:
                        st.write("¿Cuáles son fijos?")
                        cols_e = st.columns(int(cant_total_est))
                        for i in range(int(cant_total_est)):
                            with cols_e[i]:
                                if st.checkbox(f"E{i+1}", key=f"check_est_{i}"):
                                    indices_fijos.append(i)
                    estantes_fijos   = len(indices_fijos)
                    estantes_moviles = cant_total_est - estantes_fijos
                    st.caption(f"{estantes_fijos} fijo(s) / {estantes_moviles} móvil(es)")
                    tiene_cenefa = False
                    alto_cenefa  = 0.0
                    if "Uñero" in tipo_tapa:
                        tiene_cenefa = st.checkbox("¿Lleva Cenefa inferior?", value=True)
                        if tiene_cenefa:
                            alto_cenefa = st.number_input("Altura de Cenefa (mm)", value=50.0, step=5.0)
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "C0 Estándar"])
                    cant_cajones = 0

                else:  # CAJONERA — sin bisagras
                    tipo_corredera = st.radio("Tipo de Corredera", ["Telescópica 45cm", "Cierre Suave Pesada"])
                    c_caj, _ = st.columns(2)
                    cant_cajones = c_caj.number_input("Cant. Cajones", value=int(_v("cant_cajones", 0)), min_value=0)
                    opciones_estilo = ["Superpuesta", "Embutida"]
                    if cant_cajones == 3:
                        opciones_estilo.append("Gola")
                    _tapa_default = _v("tipo_tapa", "Superpuesta")
                    _tapa_idx = opciones_estilo.index(_tapa_default) if _tapa_default in opciones_estilo else 0
                    tipo_tapa = st.radio("Estilo de Tapa", opciones_estilo, index=_tapa_idx)
                    st.markdown(f"#### Parámetros del cajón ({tipo_tapa})")
                    col_l1, col_l2 = st.columns(2)
                    luz_entre_tapas = col_l1.number_input("Luz entre tapas (mm)", value=float(_v("luz_entre_tapas", 3.0)), help="Estándar BVM: 3mm")
                    if cant_cajones > 0:
                        if tipo_tapa == "Superpuesta":
                            luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=float(_v("luz_perimetral_tapa", 4.0)))
                        elif tipo_tapa == "Embutida":
                            alto_frentin_emb    = col_l2.number_input("Altura Frentín Superior (mm)", value=float(_v("alto_frentin_emb", 30.0)))
                            luz_perimetral_tapa = 6.0
                        else:
                            luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=float(_v("luz_perimetral_tapa", 4.0)))
                            alto_frentin_emb    = 0.0
                        _dist_opts = ["Iguales", "Proporcional (20/35/45)"]
                        _dist_idx  = _dist_opts.index(_v("distribucion_tapas", "Iguales")) if _v("distribucion_tapas", "Iguales") in _dist_opts else 0
                        distribucion_tapas = col_l1.radio("Distribución", _dist_opts, index=_dist_idx)
                        col_c1, col_c2 = st.columns(2)
                        esp_corredera = col_c1.number_input("Espesor de corredera (mm)", value=float(_v("esp_corredera", 13.0)), help="Estándar: 13mm")
                        aire_trasero  = col_c2.number_input("Espacio libre trasero (mm)", value=float(_v("aire_trasero", 30.0)),  help="Mínimo: 30mm")

            with st.expander("📦 Soporte (por módulo)", expanded=False):
                # Alacena no tiene banquina
                _opts_base = ["Zócalo de Madera", "Patas Plásticas", "Nada"] if tipo_modulo == "Alacena" else ["Zócalo de Madera", "Banquina", "Patas Plásticas", "Nada"]
                _base_default = _v("tipo_base", "Nada")
                if _base_default not in _opts_base:
                    _base_default = "Nada"
                tipo_base = st.selectbox("Tipo de Soporte", _opts_base, index=_opts_base.index(_base_default))
                if tipo_base == "Zócalo de Madera":
                    altura_base = st.number_input("Altura de Zócalo (mm)", min_value=0.0, value=100.0, step=5.0)
                elif tipo_base == "Banquina":
                    altura_base = st.number_input("Altura de Banquina (mm)", min_value=0.0, value=100.0, step=5.0)
                elif tipo_base == "Patas Plásticas":
                    altura_base = st.number_input("Altura de Patas (mm)", min_value=0.0, value=100.0, step=5.0)
                else:
                    altura_base = 0.0
                costo_base = 5000 if tipo_base == "Patas Plásticas" else 0
                dias_prod = st.number_input("Días de taller (este módulo)", value=0.0, step=0.5)

        # COLUMNA DERECHA
        with col_out:
            st.subheader("📐 Planilla de corte")

            if not cliente:
                st.markdown("""<div style="background:#FFF8E6;border-left:3px solid #EF9F27;border-radius:0 8px 8px 0;padding:12px 16px;margin:8px 0;">
                <b style="color:#854F0B;">👆 Ingresá el nombre del cliente</b>
                <div style="color:#854F0B;font-size:13px;margin-top:2px;">Para calcular el presupuesto necesitás ingresar el nombre del cliente primero.</div></div>""", unsafe_allow_html=True)

            if alto_m > 0 and ancho_m > 0 and cliente:
                piezas_calculadas = generar_despiece_bvm(
                    tipo=tipo_modulo, ancho_m=ancho_m, alto_m=alto_m, prof_m=prof_m,
                    esp_real=esp_real, tiene_parante=tiene_parante, tipo_parante=tipo_parante,
                    distancia_parante=distancia_parante, cant_cajones=cant_cajones,
                    tipo_tapa=tipo_tapa, tipo_base=tipo_base, altura_base=altura_base,
                    luz_entre_tapas=luz_entre_tapas, luz_perimetral_tapa=luz_perimetral_tapa,
                    alto_frentin_emb=alto_frentin_emb, aire_trasero=aire_trasero,
                    esp_corredera=esp_corredera, distribucion_tapas=distribucion_tapas,
                    cant_puertas=cant_puertas, tiene_cenefa=tiene_cenefa, alto_cenefa=alto_cenefa,
                    estantes_fijos=estantes_fijos, estantes_moviles=estantes_moviles,
                    tipo_estante_manual=tipo_estante_manual,
                    sin_fondo=sin_fondo,
                    tiene_parante_medio=tiene_parante_medio,
                )
                df_corte = pd.DataFrame(piezas_calculadas)

                if not df_corte.empty and 'L' in df_corte.columns:
                    for col in ['Tipo','L','A','Cant']:
                        if col not in df_corte.columns:
                            df_corte[col] = 0 if col != 'Tipo' else 'Cuerpo'
                    df_corte['L']    = pd.to_numeric(df_corte['L'],    errors='coerce').fillna(0)
                    df_corte['A']    = pd.to_numeric(df_corte['A'],    errors='coerce').fillna(0)
                    df_corte['Cant'] = pd.to_numeric(df_corte['Cant'], errors='coerce').fillna(0)
                    df_corte['Tipo'] = df_corte['Tipo'].fillna('Cuerpo').astype(str)
                    st.data_editor(df_corte, use_container_width=True, hide_index=True)

                    df_placa     = df_corte[~df_corte['Tipo'].isin(['Fondo','Piso'])]
                    m2_18mm      = (df_placa['L'] * df_placa['A'] * df_placa['Cant']).sum() / 1_000_000
                    costo_madera = m2_18mm * (maderas.get(mat_principal, 0.0) / 5.03)
                    df_fondo_only = df_corte[df_corte['Tipo'].isin(['Fondo','Piso'])]
                    m2_fondo     = (df_fondo_only['L'] * df_fondo_only['A'] * df_fondo_only['Cant']).sum() / 1_000_000 if not df_fondo_only.empty else 0.0
                    costo_fondo  = 0.0 if sin_fondo else m2_fondo * (fondos.get(mat_fondo_sel, 0.0) / 5.03)
                    if tipo_modulo in ["Bajo Mesada","Alacena"]:
                        costo_herrajes = cant_puertas * 2 * config.get('bisagra_cazoleta', 0)
                    else:
                        costo_herrajes = cant_cajones * config.get('telescopica_45', 0)
                    costo_operativo = dias_prod * config.get('gastos_fijos_diarios', 0)
                    total_costo = costo_madera + costo_fondo + costo_herrajes + costo_operativo + costo_base
                else:
                    st.warning("Esperando medidas para calcular...")

            st.write("---")
            retazos_en_stock = consultar_retazos_disponibles(mat_principal)
            ahorro_madera, matches = calcular_ahorro_retazos(df_corte, retazos_en_stock, maderas.get(mat_principal, 0.0))
            total_costo_real = total_costo - ahorro_madera
            utilidad  = total_costo_real * config.get('ganancia_taller_pct', 0.30)
            precio_final = total_costo_real + utilidad
            pct_utilidad_real = (utilidad / precio_final * 100) if precio_final > 0 else 0.0

            if precio_final > 0:
                color_margen = "#0F6E56" if pct_utilidad_real >= 12 else "#A32D2D"
                precio_str   = f"${precio_final:,.0f}"
                margen_str   = f"{pct_utilidad_real:.1f}%"
                alerta       = "Operación rentable" if pct_utilidad_real >= 12 else "Margen bajo — revisá los costos"
                icono_m      = "✅" if pct_utilidad_real >= 12 else "⚠️"
                st.markdown(f"""<div style="background:{color_margen};border-radius:10px;padding:20px 24px;margin:8px 0 16px 0;text-align:center;">
                <div style="color:white;font-size:12px;letter-spacing:0.1em;opacity:0.8;margin-bottom:6px;">PRECIO FINAL AL CLIENTE</div>
                <div style="color:white;font-size:40px;font-weight:700;letter-spacing:-1px;">{precio_str}</div>
                <div style="color:white;font-size:12px;opacity:0.8;margin-top:8px;">{icono_m} Margen: {margen_str} — {alerta}</div></div>""", unsafe_allow_html=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("Costo real",    f"${total_costo_real:,.0f}")
            c2.metric("M² de placa",   f"{m2_18mm:.2f}")
            c3.metric("Ganancia neta", f"${utilidad:,.0f}")

            if matches:
                st.success(f"♻️ **¡Ahorro por retazos!** {len(matches)} pieza(s) — Ahorro: **${ahorro_madera:,.0f}**")
                with st.expander("Ver detalle de retazos"):
                    for m in matches:
                        st.write(f"• **{m['pieza']}** → Retazo ID-{m['retazo_id']} — ${m['ahorro']:,.0f}")

            if precio_final > 0:
                with st.expander("📊 Ver desglose de costos"):
                    datos_g = {"Categoría": ["Madera/Fondo","Herrajes","Operativo/Taller","Ganancia Neta"],
                               "Monto": [costo_madera+costo_fondo, costo_herrajes, costo_operativo+costo_base, utilidad]}
                    st.bar_chart(pd.DataFrame(datos_g), x="Categoría", y="Monto", color="#2e7d32")

            # GESTIÓN DE OBRA
            st.write("---")
            st.subheader("🏠 Gestión de obra")
            nombre_modulo   = st.text_input("Nombre del módulo", value=f"{tipo_modulo} {ancho_m:.0f}mm")
            idx_mod_editar  = st.session_state.get("idx_modulo_editar")
            label_boton     = "✏️ Reemplazar módulo en la obra" if idx_mod_editar is not None else "+ Agregar módulo a la obra"

            col_ag, col_sv = st.columns(2)
            with col_ag:
                if st.button(label_boton, use_container_width=True, type="primary"):
                    if ancho_m > 0 and alto_m > 0 and precio_final > 0:
                        nuevo_mod = {"nombre": nombre_modulo, "tipo": tipo_modulo, "ancho": int(ancho_m),
                                     "alto": int(alto_m), "prof": int(prof_m), "material": mat_principal,
                                     "precio": precio_final, "df_corte": df_corte.copy() if not df_corte.empty else None,
                                     "tipo_tapa": tipo_tapa}
                        if idx_mod_editar is not None:
                            obra_actual = st.session_state["obra_modulos"]
                            if idx_mod_editar < len(obra_actual):
                                obra_actual[idx_mod_editar] = nuevo_mod
                            else:
                                obra_actual.append(nuevo_mod)
                            st.session_state["obra_modulos"] = [m for m in obra_actual if m is not None]
                            st.session_state.update({"idx_modulo_editar": None, "editar_presupuesto": None,
                                                     "editar_id": None, "editar_cliente": "",
                                                     "tipo_modulo_sel": "Bajo Mesada", "edicion_tipo_cargado": False})
                        else:
                            st.session_state["obra_modulos"].append(nuevo_mod)
                        st.session_state.update({"ultimo_modulo_agregado": nombre_modulo, "ultimo_precio_agregado": precio_final})
                        st.rerun()
                    else:
                        st.warning("Ingresá las medidas y calculá el módulo antes de agregar.")

            with col_sv:
                if st.button("Guardar solo este módulo", use_container_width=True):
                    if cliente:
                        params = {"tipo_modulo": tipo_modulo, "ancho_m": ancho_m, "alto_m": alto_m,
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
                                  "tiene_cenefa": tiene_cenefa, "alto_cenefa": alto_cenefa}
                        guardar_presupuesto_nube(cliente, tipo_modulo, precio_final, parametros=params,
                                                  id_editar=st.session_state.get("editar_id"))
                        st.session_state.update({"editar_presupuesto": None, "editar_id": None,
                                                  "editar_cliente": "", "tipo_modulo_sel": "Bajo Mesada",
                                                  "edicion_tipo_cargado": False})
                    else:
                        st.warning("Ingresá el nombre del Cliente.")

            if st.session_state.get("ultimo_modulo_agregado"):
                total_actual = sum(m["precio"] for m in st.session_state["obra_modulos"])
                n = len(st.session_state["obra_modulos"])
                st.info(f"**✅ Módulo agregado: {st.session_state['ultimo_modulo_agregado']}** — ${st.session_state['ultimo_precio_agregado']:,.0f}\n\n📋 Tenés **{n} módulo(s)** — Total: **${total_actual:,.0f}**\n\n👉 Configurá el siguiente módulo arriba o bajá al **Resumen de Obra**.")
                st.session_state.update({"ultimo_modulo_agregado": None, "ultimo_precio_agregado": 0})

            # PDF y WA por módulo individual
            if not df_corte.empty:
                st.write("---")
                if not st.session_state["obra_modulos"]:
                    st.subheader("Propuesta para este módulo")
                    col_ent, col_sena = st.columns(2)
                    dias_entrega = col_ent.number_input("Días de entrega", value=15, step=1, key="dias_mod")
                    pct_seña     = col_sena.slider("% de Seña", 0, 100, 50, 5, key="sena_mod")

                    def _pdf_mod(cli, nom, tip, aw, ah, ap, mat, precio, dias, pct):
                        pdf = FPDF(); pdf.add_page()
                        pdf.set_font("Arial","B",20); pdf.set_text_color(46,125,50)
                        pdf.cell(200,20,"PRESUPUESTO - BVM",ln=True,align="C")
                        pdf.set_text_color(0,0,0); pdf.set_font("Arial","",10)
                        fecha = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y")
                        pdf.cell(200,8,f"Fecha: {fecha}    Cliente: {cli}",ln=True,align="R"); pdf.ln(6)
                        pdf.set_font("Arial","B",12); pdf.set_fill_color(230,245,238)
                        pdf.cell(0,11,f"  {nom}",ln=True,fill=True)
                        pdf.set_font("Arial","",11)
                        pdf.cell(95,8,f"  Tipo: {tip}",ln=False); pdf.cell(95,8,f"  Material: {mat}",ln=True)
                        pdf.cell(95,8,f"  Ancho: {aw} mm",ln=False); pdf.cell(95,8,f"  Alto: {ah} mm",ln=True)
                        pdf.cell(95,8,f"  Profundidad: {ap} mm",ln=True); pdf.ln(4)
                        monto = precio*(pct/100)
                        pdf.set_font("Arial","B",14); pdf.set_fill_color(240,240,240)
                        pdf.cell(0,14,f"TOTAL: ${precio:,.0f}",ln=True,align="C",fill=True)
                        pdf.set_font("Arial","",11)
                        pdf.cell(0,8,f"Seña ({pct}%): ${monto:,.0f}",ln=True,align="C")
                        pdf.cell(0,8,f"Entrega: {dias} días hábiles",ln=True,align="C")
                        return bytes(pdf.output())

                    pdf_mod = _pdf_mod(cliente, nombre_modulo, tipo_modulo, int(ancho_m), int(alto_m), int(prof_m), mat_principal, precio_final, dias_entrega, pct_seña)
                    lineas_wa = [f"*PRESUPUESTO BVM — {nombre_modulo.upper()}*", f"Cliente: {cliente}", "",
                                 f"• {tipo_modulo}: {int(ancho_m)}x{int(alto_m)}x{int(prof_m)} mm", f"• Material: {mat_principal}", "",
                                 f"*TOTAL: ${precio_final:,.0f}*", f"Seña ({pct_seña}%): ${precio_final*(pct_seña/100):,.0f}",
                                 f"Entrega: {dias_entrega} días hábiles", "", "Precios válidos 48hs."]
                    wa_mod = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(lineas_wa))}"

                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        st.download_button("📥 PDF este módulo", data=pdf_mod, file_name=f"Presupuesto_{nombre_modulo}.pdf", mime="application/pdf", use_container_width=True)
                    with col_p2:
                        st.link_button("🟢 WhatsApp este módulo", wa_mod, use_container_width=True)
                else:
                    st.info("📄 Cuando termines todos los módulos, generá el PDF en el **Resumen de Obra** de abajo.")

                with st.expander("⚙️ Terminal CNC — Este módulo"):
                    import io as _io
                    import ezdxf as _ezdxf
                    doc = _ezdxf.new('R2010'); msp = doc.modelspace()
                    x_off = 0
                    for _, row in df_corte.iterrows():
                        for _ in range(int(row['Cant'])):
                            pts = [(x_off,0),(x_off+float(row['L']),0),(x_off+float(row['L']),float(row['A'])),(x_off,float(row['A'])),(x_off,0)]
                            msp.add_lwpolyline(pts, close=True)
                            msp.add_text(f"{row['Pieza']}\n{int(row['L'])}x{int(row['A'])} | {mat_principal}", height=10).set_placement((x_off+5,5))
                            x_off += float(row['L']) + 50
                    out_dxf = _io.StringIO(); doc.write(out_dxf)
                    dxf_bytes = out_dxf.getvalue().encode('utf-8')

                    df_aspire = df_corte.copy().rename(columns={"Pieza":"Name","L":"Length","A":"Width","Cant":"Quantity"})
                    df_aspire["Thickness"] = esp_real; df_aspire["Material"] = mat_principal
                    csv_bytes = df_aspire[["Name","Length","Width","Thickness","Quantity","Material"]].to_csv(index=False).encode('utf-8')

                    col_cnc1, col_cnc2 = st.columns(2)
                    with col_cnc1:
                        st.download_button("📐 DXF (Vectores)", data=dxf_bytes, file_name=f"Vectores_{nombre_modulo}.dxf", mime="application/dxf", use_container_width=True)
                    with col_cnc2:
                        st.download_button("🤖 CSV (Aspire)", data=csv_bytes, file_name=f"CNC_{nombre_modulo}.csv", mime="text/csv", use_container_width=True)

        # ===========================================================
        # RESUMEN DE OBRA
        # ===========================================================
        if st.session_state["obra_modulos"]:
            st.write("---")
            st.header("🏠 Resumen de Obra Completa")

            subtotal_modulos = sum(m["precio"] for m in st.session_state["obra_modulos"])

            # Lista de módulos
            for i, mod in enumerate(st.session_state["obra_modulos"]):
                col_mod, col_del = st.columns([5,1])
                with col_mod:
                    st.write(f"**{i+1}. {mod['nombre']}** — {mod['ancho']}x{mod['alto']}x{mod['prof']} mm — {mod['material']} — `${mod['precio']:,.0f}`")
                with col_del:
                    if st.button("✕", key=f"del_mod_{i}"):
                        st.session_state["obra_modulos"].pop(i); st.rerun()

            st.write("---")

            # LOGÍSTICA AL FINAL DE LA OBRA
            with st.expander("🚛 Logística y colocación de la obra", expanded=True):
                st.caption("Estos costos se suman al total de la obra, no por módulo.")
                col_fl, col_col, col_dias = st.columns(3)
                flete_sel_obra   = col_fl.selectbox("Flete", ["Ninguno","Capital","Zona Norte"], key="flete_obra")
                necesita_col     = col_col.checkbox("¿Requiere colocación?", key="col_obra")
                dias_col_obra    = col_dias.number_input("Días de colocación", value=0, min_value=0, key="dias_col_obra") if necesita_col else 0

                costo_flete_obra = config.get('flete_capital',0) if flete_sel_obra=="Capital" else config.get('flete_norte',0) if flete_sel_obra=="Zona Norte" else 0.0
                costo_col_obra   = dias_col_obra * config.get('colocacion_dia', 0)
                costo_log_total  = costo_flete_obra + costo_col_obra

                if costo_log_total > 0:
                    st.info(f"Logística y colocación: **${costo_log_total:,.0f}**")

            total_obra = subtotal_modulos + costo_log_total

            # TOTAL DESTACADO
            st.markdown(f"""<div style="background:#0F6E56;border-radius:12px;padding:20px 24px;margin:12px 0;text-align:center;">
            <div style="color:rgba(255,255,255,0.7);font-size:12px;letter-spacing:0.1em;margin-bottom:6px;">TOTAL DE LA OBRA</div>
            <div style="color:white;font-size:44px;font-weight:700;letter-spacing:-2px;">${total_obra:,.0f}</div>
            <div style="color:rgba(255,255,255,0.65);font-size:13px;margin-top:6px;">{len(st.session_state['obra_modulos'])} módulo(s) · Subtotal módulos: ${subtotal_modulos:,.0f}{f' · Logística: ${costo_log_total:,.0f}' if costo_log_total > 0 else ''}</div>
            </div>""", unsafe_allow_html=True)

            col_pdf1, col_pdf2 = st.columns(2)
            with col_pdf1:
                dias_entrega_obra = st.number_input("Días de entrega total", value=20, step=1, key="dias_obra")
            with col_pdf2:
                pct_seña_obra = st.slider("% de Seña", 0, 100, 50, 5, key="sena_obra")

            cliente_obra = cliente or st.session_state.get("editar_cliente","") or "Cliente"
            col_gen1, col_gen2, col_gen3 = st.columns(3)

            with col_gen1:
                pdf_obra = generar_pdf_obra(cliente_obra, st.session_state["obra_modulos"],
                                             dias_entrega_obra, pct_seña_obra,
                                             costo_logistica=costo_flete_obra,
                                             dias_colocacion=dias_col_obra,
                                             costo_colocacion_dia=config.get('colocacion_dia',0))
                st.download_button("📥 PDF Presupuesto Completo", data=pdf_obra,
                                   file_name=f"Obra_{cliente_obra}.pdf", mime="application/pdf", use_container_width=True)

            with col_gen2:
                link_wa = generar_link_whatsapp_obra(cliente_obra, st.session_state["obra_modulos"],
                                                      dias_entrega_obra, pct_seña_obra,
                                                      costo_logistica=costo_flete_obra,
                                                      dias_colocacion=dias_col_obra,
                                                      costo_colocacion_dia=config.get('colocacion_dia',0))
                st.link_button("🟢 Enviar por WhatsApp", link_wa, use_container_width=True)

            with col_gen3:
                if st.button("🗑️ Limpiar obra", use_container_width=True):
                    st.session_state["obra_modulos"] = []; st.rerun()

            # CNC DE TODA LA OBRA
            with st.expander("⚙️ Terminal CNC — Obra completa"):
                st.caption("Todos los módulos en un solo archivo, separados por sección.")
                modulos_con_df = [m for m in st.session_state["obra_modulos"] if m.get("df_corte") is not None]
                if modulos_con_df:
                    dxf_obra = generar_dxf_obra(modulos_con_df)
                    csv_obra = exportar_csv_obra(modulos_con_df, esp_real)
                    col_cnc1, col_cnc2 = st.columns(2)
                    with col_cnc1:
                        st.download_button("📐 DXF Obra completa", data=dxf_obra,
                                           file_name=f"DXF_Obra_{cliente_obra}.dxf", mime="application/dxf", use_container_width=True)
                    with col_cnc2:
                        st.download_button("🤖 CSV Obra completa (Aspire)", data=csv_obra,
                                           file_name=f"CNC_Obra_{cliente_obra}.csv", mime="text/csv", use_container_width=True)
                else:
                    st.warning("No hay datos CNC disponibles. Los módulos deben calcularse en la sesión actual.")

            # GUARDAR
            if st.button("💾 Guardar obra en historial", use_container_width=True):
                _cli = cliente or st.session_state.get("editar_cliente","")
                if _cli:
                    params_obra = {
                        "es_obra": True,
                        "modulos": [{"nombre": m["nombre"], "tipo_modulo": m["tipo"], "ancho_m": m["ancho"],
                                     "alto_m": m["alto"], "prof_m": m["prof"], "mat_principal": m["material"],
                                     "precio": m["precio"]} for m in st.session_state["obra_modulos"]]
                    }
                    guardar_presupuesto_nube(_cli, f"Obra ({len(st.session_state['obra_modulos'])} módulos)",
                                             total_obra, parametros=params_obra,
                                             id_editar=st.session_state.get("editar_obra_id"))
                    st.session_state.update({"obra_modulos":[], "editar_obra_modulos": None,
                                              "editar_obra_id": None, "editar_obra_cliente": "",
                                              "editar_presupuesto": None, "editar_id": None, "editar_cliente": ""})
                    st.rerun()
                else:
                    st.warning("Ingresá el nombre del cliente arriba.")

    except Exception as e:
        import traceback
        st.error(f"Error en el Cotizador: {e}")
        with st.expander("Ver detalle del error"):
            st.code(traceback.format_exc())


# ===========================================================================
# HISTORIAL
# ===========================================================================
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
                                st.session_state.update({"editar_obra_modulos": params.get("modulos",[]),
                                                          "editar_obra_id": id_venta,
                                                          "editar_obra_cliente": row.get('cliente',''),
                                                          "editar_presupuesto": None, "menu_idx": 0})
                            else:
                                st.session_state.update({"editar_presupuesto": params, "editar_id": id_venta,
                                                          "editar_cliente": row.get('cliente',''),
                                                          "editar_obra_modulos": None, "menu_idx": 0,
                                                          "edicion_tipo_cargado": False})
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                with col_b3:
                    if st.button("Borrar", key=f"del_{id_venta}_{idx}", use_container_width=True):
                        try:
                            supabase.postgrest.auth(st.session_state["session"].access_token)
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
                            supabase.postgrest.auth(st.session_state["session"].access_token)
                            supabase.table("retazos").delete().eq("id", ret_id).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")


# ===========================================================================
# PRECIOS
# ===========================================================================
elif menu == "⚙️ Precios":
    st.title("⚙️ Configuración de precios")

    with st.expander("🪵 Precios de Placas (18mm)"):
        for madera, precio in list(maderas.items()):
            maderas[madera] = st.number_input(f"{madera}", value=float(precio), step=1000.0, key=f"precio_{madera}")

    st.write("---")
    st.subheader("➕ Agregar nuevo material")
    col_nm, col_np = st.columns([2,1])
    nuevo_mat_nombre = col_nm.text_input("Nombre del material (ej: Enchapado Nogal 18mm)")
    nuevo_mat_precio = col_np.number_input("Precio por placa", min_value=0.0, step=1000.0)
    if st.button("Agregar material", type="primary"):
        if nuevo_mat_nombre and nuevo_mat_precio > 0:
            actualizar_precio_nube(nuevo_mat_nombre, nuevo_mat_precio, 'maderas')
            st.success(f"✅ {nuevo_mat_nombre} agregado. Recargá la página para verlo.")
        else:
            st.warning("Completá el nombre y el precio.")

    with st.expander("🛠️ Herrajes y Accesorios"):
        c1,c2 = st.columns(2)
        config['bisagra_cazoleta']  = c1.number_input("Bisagra Cazoleta",        value=float(config['bisagra_cazoleta']),  step=100.0)
        config['telescopica_45']    = c2.number_input("Guía Telescópica 45cm",   value=float(config['telescopica_45']),    step=100.0)
        config['telescopica_soft']  = c1.number_input("Guía Cierre Suave",       value=float(config['telescopica_soft']),  step=100.0)

    with st.expander("🚛 Gastos Fijos y Logística"):
        f1,f2 = st.columns(2)
        config['gastos_fijos_diarios'] = f1.number_input("Gasto Diario Taller",    value=float(config['gastos_fijos_diarios']), step=5000.0)
        config['flete_capital']        = f2.number_input("Flete Capital",           value=float(config['flete_capital']),        step=1000.0)
        config['flete_norte']          = f1.number_input("Flete Zona Norte",        value=float(config['flete_norte']),          step=1000.0)
        config['colocacion_dia']       = f2.number_input("Costo Día de Colocación", value=float(config['colocacion_dia']),       step=5000.0)

    with st.expander("💰 Margen de Ganancia"):
        config['ganancia_taller_pct'] = st.slider("Porcentaje de Utilidad", 0.0, 1.0, float(config['ganancia_taller_pct']), 0.05)
        st.write(f"Margen actual: {config['ganancia_taller_pct']*100:.0f}%")

    if st.button("💾 Guardar Configuración", type="primary"):
        for madera, precio in maderas.items():
            actualizar_precio_nube(madera, precio, 'maderas')
        for k, v in config.items():
            actualizar_precio_nube(k, v, 'costos')
        st.success("✅ Configuración guardada.")
