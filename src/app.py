import streamlit as st
import pandas as pd
import sqlite3
import os
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
    generar_dxf_bvm,
    exportar_para_aspire,
    generar_link_whatsapp,
)

CONFIG_TECNICA = {
    "ranura_profundidad": 10.0,
    "ranura_distancia_borde": 10.0,
    "retazo_min_ancho": 150,
    "retazo_min_largo": 400,
}

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


def generar_pdf_obra(cliente, modulos, dias_entrega, pct_seña):
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

    total_obra = sum(m["precio"] for m in modulos)

    for i, mod in enumerate(modulos):
        # Cabecera del módulo con fondo verde suave
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(230, 245, 238)
        pdf.cell(0, 11, f"  {i+1}. {mod['nombre']}", ln=True, fill=True)

        # Datos del módulo en dos columnas
        pdf.set_font("Arial", "", 10)
        pdf.set_fill_color(250, 250, 250)
        pdf.cell(95, 7, f"  Tipo: {mod['tipo']}", border="L", ln=False)
        pdf.cell(95, 7, f"  Material: {mod['material']}", border="R", ln=True)
        pdf.cell(95, 7, f"  Ancho: {mod['ancho']} mm", border="L", ln=False)
        pdf.cell(95, 7, f"  Alto: {mod['alto']} mm", border="R", ln=True)
        pdf.cell(95, 7, f"  Profundidad: {mod['prof']} mm", border="LB", ln=False)
        pdf.cell(95, 7, f"  Terminacion: {mod.get('tipo_tapa', 'Estandar')}", border="RB", ln=True)

        # Subtotal alineado a la derecha
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 9, f"  Subtotal: ${mod['precio']:,.0f}", ln=True, align="R")
        pdf.ln(4)

    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 12, f"TOTAL OBRA: ${total_obra:,.0f}", ln=True, align="C", fill=True)
    monto_seña = total_obra * (pct_seña / 100)
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, f"Seña requerida ({pct_seña}%): ${monto_seña:,.0f}", ln=True, align="C")
    pdf.cell(0, 8, f"Tiempo estimado de entrega: {dias_entrega} dias habiles", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", "I", 9)
    pdf.multi_cell(0, 5, "Nota: Los precios se mantienen por 48hs. Una vez abonada la seña, se congelan los materiales y comienza la produccion.")
    return bytes(pdf.output())


def generar_link_whatsapp_obra(cliente, modulos, dias_entrega, pct_seña):
    import urllib.parse
    total_obra = sum(m["precio"] for m in modulos)
    monto_seña = total_obra * (pct_seña / 100)
    lineas = [f"*PRESUPUESTO DE OBRA BVM*", f"Cliente: {cliente}", ""]
    for i, mod in enumerate(modulos):
        lineas.append(f"- Modulo {i+1}: {mod['nombre']} ({mod['ancho']}x{mod['alto']}x{mod['prof']} mm) - ${mod['precio']:,.0f}")
    lineas += ["", f"*TOTAL OBRA: ${total_obra:,.0f}*", f"Seña ({pct_seña}%): ${monto_seña:,.0f}", f"Entrega: {dias_entrega} dias habiles", "", "Precios validos por 48hs."]
    texto_url = urllib.parse.quote("\n".join(lineas))
    return f"https://wa.me/?text={texto_url}"


def consultar_retazos_disponibles(material):
    id_ = st.session_state["user"].id
    try:
        res = supabase.table("retazos").select("*").eq("user_id", id_).execute()
        return res.data
    except Exception as e:
        st.error(f"Error al consultar retazos: {e}")
        return []


def registrar_retazo(material, largo, ancho):
    id_usuario = st.session_state["user"].id
    try:
        if (largo >= 400 and ancho >= 150) or (largo >= 150 and ancho >= 400):
            data = {"material": material, "largo": largo, "ancho": ancho, "user_id": id_usuario}
            supabase.table("retazos").insert(data).execute()
            st.toast(f"Retazo guardado: {int(largo)}x{int(ancho)}")
        else:
            st.error(f"Error: {int(largo)}x{int(ancho)} es inferior al minimo de 150x400.")
    except Exception as e:
        st.error(f"Error tecnico al registrar: {e}")


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
                pw = st.text_input("Contrasena", type="password")
                boton_login = st.form_submit_button("Entrar", use_container_width=True)
                if boton_login:
                    if email and pw:
                        with st.spinner("Conectando..."):
                            try:
                                res = supabase.auth.sign_in_with_password({"email": email, "password": pw})
                                if res.session:
                                    st.session_state["session"] = res.session
                                    st.session_state["user"] = res.user
                                    st.session_state["autenticado"] = True
                                    st.success("Acceso correcto.")
                                    st.rerun()
                            except Exception as e:
                                error_str = str(e).lower()
                                if "invalid login credentials" in error_str:
                                    st.error("Email o contrasena incorrectos.")
                                elif "network" in error_str:
                                    st.error("Error de red.")
                                else:
                                    st.error(f"Error de conexion: {e}")
                    else:
                        st.warning("Completa todos los campos.")

        with tab_reg:
            with st.form("registro_form"):
                new_email = st.text_input("Email Nuevo")
                new_pw = st.text_input("Password (min. 6 car.)", type="password")
                boton_reg = st.form_submit_button("Crear Cuenta", use_container_width=True)
                if boton_reg:
                    try:
                        supabase.auth.sign_up({"email": new_email, "password": new_pw})
                        st.success("Revisa tu email para confirmar la cuenta.")
                    except Exception as e:
                        st.error(f"Error al crear cuenta: {e}")
        return False
    return True


def actualizar_precio_nube(clave, valor, categoria):
    if "session" not in st.session_state or st.session_state["session"] is None:
        st.error("Sesion no iniciada.")
        return
    token = st.session_state["session"].access_token
    try:
        supabase.postgrest.auth(token)
        data = {"user_id": st.session_state["user"].id, "clave": clave, "valor": float(valor), "categoria": categoria}
        supabase.table("configuracion").upsert(data, on_conflict="user_id, clave").execute()
    except Exception as e:
        st.error(f"Error guardando {clave}: {e}")


def traer_datos():
    if "session" not in st.session_state or st.session_state["session"] is None:
        return {}, {}, {}

    token = st.session_state["session"].access_token
    id_usuario = st.session_state["user"].id

    maderas_default = {
        "Melamina Blanca 18mm": 60000.0,
        "Melamina Color 18mm": 85000.0,
        "Enchapado Roble 18mm": 120000.0
    }
    config_default = {
        'bisagra_cazoleta': 1200.0,
        'telescopica_45': 5000.0,
        'telescopica_soft': 12000.0,
        'gastos_fijos_diarios': 25000.0,
        'flete_capital': 15000.0,
        'flete_norte': 20000.0,
        'colocacion_dia': 45000.0,
        'ganancia_taller_pct': 0.30
    }

    try:
        supabase.postgrest.auth(token)
        res = supabase.table("configuracion").select("*").eq("user_id", id_usuario).execute()
        datos_db = res.data
        maderas_db = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria', '')).lower().strip() == 'maderas'}
        config_db = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria', '')).lower().strip() in ['costos', 'margen', 'herrajes']}
        maderas = {**maderas_default, **maderas_db}
        config = {**config_default, **config_db}
        fondos = {'Fibroplus Blanco 3mm': 34500.0, 'Faplac Fondo 5.5mm': 45000.0}
        return maderas, fondos, config
    except Exception as e:
        st.error(f"Error cargando configuracion: {e}")
        return maderas_default, {'Fibroplus Blanco 3mm': 34500.0}, config_default


def guardar_presupuesto_nube(cliente, mueble, total, parametros=None, id_editar=None):
    import json
    try:
        data = {
            "cliente": cliente,
            "mueble": mueble,
            "precio_final": float(total),
            "user_id": st.session_state["user"].id,
            "fecha": datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M"),
            "parametros": json.dumps(parametros) if parametros else None
        }
        if id_editar:
            # Actualizamos el registro existente
            supabase.table("ventas").update(data).eq("id", id_editar).execute()
            st.success("✅ Presupuesto actualizado en el historial.")
        else:
            # Creamos uno nuevo
            data["estado"] = "Pendiente"
            supabase.table("ventas").insert(data).execute()
            st.success("✅ Presupuesto guardado.")
    except Exception as e:
        st.error(f"Error al guardar: {e}")


def traer_datos_historial():
    try:
        response = supabase.table("ventas").select("*").eq("user_id", st.session_state["user"].id).execute()
        return pd.DataFrame(response.data)
    except:
        return pd.DataFrame()


def ejecutar_query(query, params=(), fetch=False):
    db_path = BASE_DIR / 'data' / 'carpinteria.db'
    if not os.path.exists(BASE_DIR / 'data'):
        os.makedirs(BASE_DIR / 'data')
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch:
            return cursor.fetchall()
        conn.commit()


# INTERFAZ
st.set_page_config(
    page_title="BVM — Sistema de Gestión para Carpintería",
    page_icon="🪵",
    layout="wide"
)

# =====================================================================
# CSS CUSTOM — DISEÑO PROFESIONAL BVM
# =====================================================================
st.markdown("""
<style>
/* --- FUENTE Y BASE --- */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* --- SIDEBAR VERDE --- */
[data-testid="stSidebar"] {
    background-color: #0F6E56 !important;
    border-right: none !important;
}
[data-testid="stSidebar"] * {
    color: rgba(255,255,255,0.85) !important;
}
[data-testid="stSidebar"] .stRadio label {
    color: rgba(255,255,255,0.75) !important;
    font-size: 14px !important;
    padding: 6px 0 !important;
}
[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] {
    background: transparent !important;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.15) !important;
}
[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.1) !important;
    color: rgba(255,255,255,0.8) !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.2) !important;
}

/* --- LOGO BVM EN SIDEBAR --- */
[data-testid="stSidebarNav"] { display: none; }

/* --- HEADER DE PÁGINA --- */
[data-testid="stAppViewContainer"] > .main .block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 1400px !important;
}

/* --- TÍTULOS --- */
h1 { font-size: 22px !important; font-weight: 500 !important; letter-spacing: -0.3px !important; }
h2 { font-size: 17px !important; font-weight: 500 !important; }
h3 { font-size: 15px !important; font-weight: 500 !important; }

/* --- BOTÓN PRIMARIO VERDE --- */
.stButton > button[kind="primary"] {
    background-color: #1D9E75 !important;
    border-color: #1D9E75 !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    padding: 10px 20px !important;
    font-size: 14px !important;
    transition: background 0.15s !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #0F6E56 !important;
    border-color: #0F6E56 !important;
}

/* --- BOTONES SECUNDARIOS --- */
.stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    font-size: 13px !important;
    border-color: #D3D1C7 !important;
}

/* --- MÉTRICAS MÁS GRANDES --- */
[data-testid="stMetric"] {
    background: #F8F8F6 !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    border: 0.5px solid #E0DED6 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 12px !important;
    color: #888780 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
}
[data-testid="stMetricValue"] {
    font-size: 22px !important;
    font-weight: 500 !important;
    color: #2C2C2A !important;
}

/* --- EXPANDERS MÁS LIMPIOS --- */
[data-testid="stExpander"] {
    border: 0.5px solid #E0DED6 !important;
    border-radius: 10px !important;
    background: white !important;
    margin-bottom: 8px !important;
}
[data-testid="stExpander"] summary {
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
    background: #F8F8F6 !important;
    border-radius: 10px !important;
}

/* --- INPUTS MÁS COMPACTOS --- */
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] select {
    border-radius: 7px !important;
    font-size: 13px !important;
    border-color: #D3D1C7 !important;
}

/* --- DATA EDITOR (TABLA DE CORTE) --- */
[data-testid="stDataFrame"] {
    border: 0.5px solid #E0DED6 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* --- ALERTS Y SUCCESS --- */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    font-size: 13px !important;
}

/* --- TABS --- */
[data-testid="stTabs"] [role="tab"] {
    font-size: 13px !important;
    font-weight: 500 !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #1D9E75 !important;
    border-bottom-color: #1D9E75 !important;
}

/* --- DOWNLOAD BUTTONS --- */
[data-testid="stDownloadButton"] button {
    border-radius: 8px !important;
    font-size: 13px !important;
    border-color: #D3D1C7 !important;
}

/* --- INFO BOX --- */
[data-testid="stInfo"] {
    background: #E1F5EE !important;
    border: none !important;
    border-left: 3px solid #1D9E75 !important;
    color: #0F6E56 !important;
    border-radius: 0 8px 8px 0 !important;
}

/* --- CAPTION / HELPER TEXT --- */
[data-testid="stCaptionContainer"] {
    font-size: 12px !important;
    color: #888780 !important;
}

/* --- SLIDER --- */
[data-testid="stSlider"] [role="slider"] {
    background-color: #1D9E75 !important;
}
[data-testid="stSlider"] [data-testid="stSliderTrack"] div:first-child {
    background-color: #1D9E75 !important;
}
</style>
""", unsafe_allow_html=True)

if not gestionar_auth():
    st.stop()

# --- ONBOARDING: primera vez que entra ---
if "onboarding_visto" not in st.session_state:
    st.session_state["onboarding_visto"] = False

if not st.session_state["onboarding_visto"]:
    st.markdown("""
    <div style="background: linear-gradient(135deg, #1D9E75 0%, #0F6E56 100%);
                border-radius: 16px; padding: 40px 48px; margin-bottom: 32px; text-align:center;">
        <div style="font-size:48px; margin-bottom:12px;">🪵</div>
        <h1 style="color:white; margin:0 0 10px 0; font-size:32px; letter-spacing:-0.5px;">Bienvenido a BVM</h1>
        <p style="color:white; font-size:17px; margin:0; opacity:0.9; max-width:520px; margin:0 auto;">
            El sistema de presupuestación y gestión diseñado para carpinteros profesionales.
            Calculá precios exactos, generá presupuestos en segundos y ganale al que tarda más.
        </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div style="border:1.5px solid #E0E0E0; border-radius:12px; padding:24px; height:180px;">
            <div style="font-size:32px; margin-bottom:10px;">📐</div>
            <div style="font-weight:600; font-size:15px; margin-bottom:8px;">Paso 1 — Calculá el mueble</div>
            <div style="font-size:13px; color:#666; line-height:1.5;">
                Ingresá las medidas del mueble y el sistema genera automáticamente la lista de corte 
                con las piezas exactas. Sin errores, sin desperdicios.
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div style="border:1.5px solid #E0E0E0; border-radius:12px; padding:24px; height:180px;">
            <div style="font-size:32px; margin-bottom:10px;">🏗️</div>
            <div style="font-weight:600; font-size:15px; margin-bottom:8px;">Paso 2 — Armá la obra completa</div>
            <div style="font-size:13px; color:#666; line-height:1.5;">
                Agregá módulo por módulo — bajo mesada, alacena, cajonera — 
                y BVM los acumula en un solo presupuesto total para el cliente.
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div style="border:1.5px solid #E0E0E0; border-radius:12px; padding:24px; height:180px;">
            <div style="font-size:32px; margin-bottom:10px;">📲</div>
            <div style="font-weight:600; font-size:15px; margin-bottom:8px;">Paso 3 — Enviá y cerrá</div>
            <div style="font-size:13px; color:#666; line-height:1.5;">
                Generá el PDF o mandá el presupuesto directo por WhatsApp. 
                El historial registra cada trabajo para que puedas hacer seguimiento.
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")
    st.markdown("""
    <div style="background:#F8F8F6; border-radius:10px; padding:16px 24px; margin:16px 0; text-align:center;">
        <span style="font-size:13px; color:#666;">
            💡 <b>Consejo:</b> El que presupuesta primero y con precisión, gana la obra. 
            BVM te da esa ventaja.
        </span>
    </div>
    """, unsafe_allow_html=True)

    col_start, _, _ = st.columns(3)
    with col_start:
        if st.button("✅ Empezar a usar BVM", type="primary", use_container_width=True):
            st.session_state["onboarding_visto"] = True
            st.rerun()
    st.stop()

if "obra_modulos" not in st.session_state:
    st.session_state["obra_modulos"] = []
if "editar_presupuesto" not in st.session_state:
    st.session_state["editar_presupuesto"] = None
if "editar_id" not in st.session_state:
    st.session_state["editar_id"] = None
if "editar_cliente" not in st.session_state:
    st.session_state["editar_cliente"] = ""
if "editar_obra_modulos" not in st.session_state:
    st.session_state["editar_obra_modulos"] = None
if "editar_obra_id" not in st.session_state:
    st.session_state["editar_obra_id"] = None
if "editar_obra_cliente" not in st.session_state:
    st.session_state["editar_obra_cliente"] = ""
if "idx_modulo_editar" not in st.session_state:
    st.session_state["idx_modulo_editar"] = None

maderas, fondos, config = traer_datos()
# Si hay un presupuesto para editar, forzamos el cotizador
_opciones_menu = ["🪵 Cotizador", "♻️ Retazos", "📋 Historial", "⚙️ Precios"]

# Si hay edición en curso, forzamos el cotizador
_forzar_cotizador = (
    st.session_state.get("editar_presupuesto") is not None or
    st.session_state.get("editar_obra_modulos") is not None
)

# --- LOGO EN SIDEBAR ---
st.sidebar.markdown("""
<div style="padding: 8px 4px 16px 4px; border-bottom: 1px solid rgba(255,255,255,0.12); margin-bottom: 12px;">
    <div style="font-size: 22px; font-weight: 500; color: white; letter-spacing: -0.5px;">🪵 BVM</div>
    <div style="font-size: 11px; color: rgba(255,255,255,0.5); margin-top: 2px;">Sistema de carpintería</div>
</div>
""", unsafe_allow_html=True)

if _forzar_cotizador:
    menu = "🪵 Cotizador"
    st.sidebar.radio("Navegación", _opciones_menu, index=0)
else:
    menu = st.sidebar.radio("Navegación", _opciones_menu, index=st.session_state.get("menu_idx", 0))
    st.session_state["menu_idx"] = _opciones_menu.index(menu)

# Widget de obra en curso en el sidebar
if st.session_state["obra_modulos"]:
    total_obra_sb = sum(m["precio"] for m in st.session_state["obra_modulos"])
    st.sidebar.markdown(f"""
    <div style="background: rgba(255,255,255,0.1); border-radius: 8px; padding: 10px 12px; margin: 12px 0 4px 0;">
        <div style="font-size: 10px; color: rgba(255,255,255,0.5); letter-spacing: 0.06em; margin-bottom: 4px;">OBRA EN CURSO</div>
        <div style="font-size: 20px; font-weight: 500; color: white;">${total_obra_sb:,.0f}</div>
        <div style="font-size: 11px; color: rgba(255,255,255,0.6); margin-top: 2px;">{len(st.session_state['obra_modulos'])} módulo(s)</div>
    </div>
    """, unsafe_allow_html=True)

st.sidebar.write("---")
if st.sidebar.button("Cerrar sesión"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if menu == "🪵 Cotizador":
    try:
        st.title("🪵 BVM — Cotizador de muebles")

        # --- OBRA MULTI-MÓDULO: selector de módulo a editar ---
        obra_mods = st.session_state.get("editar_obra_modulos")
        if obra_mods and not st.session_state.get("editar_presupuesto"):
            cliente_obra_edit = st.session_state.get("editar_obra_cliente", "")
            st.warning(f"**Editando obra de {cliente_obra_edit}** — Elegí qué módulo querés rehacer:")
            for i, mod in enumerate(obra_mods):
                col_info, col_sel = st.columns([4, 1])
                col_info.write(f"**{i+1}. {mod['nombre']}** — {mod['ancho_m']}x{mod['alto_m']}x{mod['prof_m']} mm — {mod['mat_principal']} — ${mod['precio']:,.0f}")
                if col_sel.button("Editar este", key=f"sel_mod_obra_{i}"):
                    st.session_state["editar_presupuesto"] = mod
                    st.session_state["editar_cliente"] = cliente_obra_edit
                    st.session_state["idx_modulo_editar"] = i  # guardamos posición para reemplazar
                    st.session_state["editar_obra_modulos"] = None
                    st.session_state["menu_idx"] = 0
                    st.rerun()
            if st.button("Cancelar", key="cancel_obra_edit"):
                st.session_state["editar_obra_modulos"] = None
                st.rerun()

        # --- MÓDULO INDIVIDUAL: detectar si hay un presupuesto cargado para editar ---
        ep = st.session_state.get("editar_presupuesto")
        if ep:
            st.info(f"**Editando módulo guardado** — Cliente: {st.session_state.get('editar_cliente', '')}. Modificá lo que necesites y guardá de nuevo.")
            if st.button("Cancelar edición"):
                st.session_state["editar_presupuesto"] = None
                st.session_state["editar_id"] = None
                st.session_state["editar_cliente"] = ""
                st.rerun()

        def _v(key, default):
            """Devuelve el valor del presupuesto en edicion o el default."""
            if ep and key in ep:
                return ep[key]
            return default

        df_corte = pd.DataFrame()
        costo_madera = 0.0
        costo_fondo = 0.0
        costo_herrajes = 0.0
        costo_flete = 0.0
        precio_final = 0.0
        total_costo = 0.0
        m2_18mm = 0.0
        m2_fondo = 0.0
        costo_operativo = 0.0
        utilidad = 0.0
        tiene_parante = _v("tiene_parante", False)
        tipo_parante = _v("tipo_parante", "Corto (100mm)")
        tipo_estante_manual = _v("tipo_estante_manual", "Completo")
        distancia_parante = _v("distancia_parante", 0.0)
        luz_perimetral_tapa = _v("luz_perimetral_tapa", 4.0)
        aire_trasero = _v("aire_trasero", 30.0)
        esp_corredera = _v("esp_corredera", 13.0)
        distribucion_tapas = _v("distribucion_tapas", "Iguales")
        cant_puertas = _v("cant_puertas", 0)
        tiene_cenefa = _v("tiene_cenefa", False)
        alto_cenefa = _v("alto_cenefa", 0.0)
        estantes_fijos = _v("estantes_fijos", 0)
        estantes_moviles = _v("estantes_moviles", 0)
        cant_cajones = _v("cant_cajones", 0)
        luz_entre_tapas = _v("luz_entre_tapas", 3.0)
        alto_frentin_emb = _v("alto_frentin_emb", 0.0)
        tipo_tapa = _v("tipo_tapa", "Superpuesta")
        tipo_base = _v("tipo_base", "Nada")
        altura_base = _v("altura_base", 0.0)

        # Listas para selectbox con índice correcto al editar
        lista_modulos = ["Cajonera", "Bajo Mesada", "Alacena"]
        lista_maderas = list(maderas.keys())
        lista_fondos  = list(fondos.keys())

        idx_modulo = lista_modulos.index(_v("tipo_modulo", "Cajonera")) if _v("tipo_modulo", "Cajonera") in lista_modulos else 0
        idx_madera = lista_maderas.index(_v("mat_principal", lista_maderas[0])) if _v("mat_principal", lista_maderas[0]) in lista_maderas else 0
        idx_fondo  = lista_fondos.index(_v("mat_fondo_sel", lista_fondos[0])) if _v("mat_fondo_sel", lista_fondos[0]) in lista_fondos else 0

        # Si venimos de edición, preseleccionamos el tipo correcto
        if ep and "tipo_modulo" in ep:
            st.session_state["tipo_modulo_sel"] = ep["tipo_modulo"]

        col_in, col_out = st.columns([1, 1.2])

        with col_in:
            with st.expander("🛠️ Definición de estructura", expanded=True):
                cliente = st.text_input("Cliente", st.session_state.get("editar_cliente", ""))

                # --- SELECTOR VISUAL DE MUEBLE ---
                st.markdown("**Tipo de mueble**")

                # Inicializamos el tipo seleccionado
                if "tipo_modulo_sel" not in st.session_state:
                    st.session_state["tipo_modulo_sel"] = lista_modulos[idx_modulo]

                _svgs = {
                    "Bajo Mesada": """<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg">
                        <rect x="2" y="18" width="76" height="38" rx="2" fill="currentColor" opacity="0.12" stroke="currentColor" stroke-width="1.5"/>
                        <rect x="2" y="18" width="76" height="8" rx="1" fill="currentColor" opacity="0.25"/>
                        <line x1="41" y1="26" x2="41" y2="56" stroke="currentColor" stroke-width="1.2"/>
                        <rect x="5" y="30" width="33" height="22" rx="1.5" fill="currentColor" opacity="0.18"/>
                        <rect x="44" y="30" width="33" height="22" rx="1.5" fill="currentColor" opacity="0.18"/>
                        <circle cx="39" cy="41" r="2" fill="currentColor" opacity="0.6"/>
                        <circle cx="43" cy="41" r="2" fill="currentColor" opacity="0.6"/>
                        <rect x="8" y="56" width="64" height="4" rx="1" fill="currentColor" opacity="0.15"/>
                    </svg>""",
                    "Cajonera": """<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg">
                        <rect x="5" y="4" width="70" height="52" rx="2" fill="currentColor" opacity="0.12" stroke="currentColor" stroke-width="1.5"/>
                        <rect x="8" y="8" width="64" height="13" rx="1.5" fill="currentColor" opacity="0.2"/>
                        <rect x="8" y="24" width="64" height="13" rx="1.5" fill="currentColor" opacity="0.2"/>
                        <rect x="8" y="40" width="64" height="13" rx="1.5" fill="currentColor" opacity="0.2"/>
                        <circle cx="40" cy="14.5" r="2" fill="currentColor" opacity="0.7"/>
                        <circle cx="40" cy="30.5" r="2" fill="currentColor" opacity="0.7"/>
                        <circle cx="40" cy="46.5" r="2" fill="currentColor" opacity="0.7"/>
                    </svg>""",
                    "Alacena": """<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg">
                        <rect x="2" y="2" width="76" height="52" rx="2" fill="currentColor" opacity="0.12" stroke="currentColor" stroke-width="1.5"/>
                        <rect x="2" y="2" width="76" height="7" rx="1" fill="currentColor" opacity="0.2"/>
                        <line x1="41" y1="9" x2="41" y2="54" stroke="currentColor" stroke-width="1.2"/>
                        <rect x="5" y="13" width="33" height="37" rx="1.5" fill="currentColor" opacity="0.18"/>
                        <rect x="44" y="13" width="33" height="37" rx="1.5" fill="currentColor" opacity="0.18"/>
                        <circle cx="39" cy="31" r="2" fill="currentColor" opacity="0.6"/>
                        <circle cx="43" cy="31" r="2" fill="currentColor" opacity="0.6"/>
                        <line x1="5" y1="28" x2="38" y2="28" stroke="currentColor" stroke-width="0.8" opacity="0.4"/>
                        <line x1="44" y1="28" x2="77" y2="28" stroke="currentColor" stroke-width="0.8" opacity="0.4"/>
                        <rect x="8" y="54" width="64" height="4" rx="1" fill="currentColor" opacity="0.15"/>
                    </svg>""",
                }

                col_bm, col_caj, col_ala = st.columns(3)
                for col, nombre in [(col_bm, "Bajo Mesada"), (col_caj, "Cajonera"), (col_ala, "Alacena")]:
                    with col:
                        seleccionado = st.session_state["tipo_modulo_sel"] == nombre
                        color = "#1D9E75" if seleccionado else "#888780"
                        bg = "#E1F5EE" if seleccionado else "transparent"
                        borde = "#1D9E75" if seleccionado else "#D3D1C7"
                        st.markdown(f"""
                        <div style="border:2px solid {borde}; border-radius:10px; padding:12px 8px 8px 8px;
                                    background:{bg}; text-align:center; color:{color}; cursor:pointer;">
                            {_svgs[nombre].replace('currentColor', color)}
                            <div style="font-size:12px; font-weight:600; margin-top:6px;">{nombre}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        if st.button("Seleccionar", key=f"sel_{nombre}", use_container_width=True,
                                     type="primary" if seleccionado else "secondary"):
                            st.session_state["tipo_modulo_sel"] = nombre
                            st.rerun()

                tipo_modulo = st.session_state["tipo_modulo_sel"]
                c1, c2, c3 = st.columns(3)
                ancho_m = c1.number_input("Ancho total (mm)", min_value=0.0, max_value=5000.0, value=float(_v("ancho_m", 0.0)), step=0.5, help="Medida exterior total del módulo de izquierda a derecha")
                alto_m  = c2.number_input("Alto total (mm)",  min_value=0.0, max_value=5000.0, value=float(_v("alto_m",  0.0)), step=0.5, help="Medida exterior total del módulo de abajo hacia arriba")
                prof_m  = c3.number_input("Profundidad (mm)", min_value=0.0, max_value=2000.0, value=float(_v("prof_m",  0.0)), step=0.5, help="Medida de fondo del módulo. Estándar: 550mm para bajo mesada, 350mm para alacena")
                mat_principal = st.selectbox("Material del cuerpo (18mm)", lista_maderas, index=idx_madera, help="Material principal con el que se construye la estructura del mueble")
                esp_real = st.number_input("Espesor real de placa (mm)", min_value=1.0, max_value=50.0, value=float(_v("esp_real", 18.0)), step=0.1, help="El espesor nominal es 18mm pero puede variar según el proveedor. Medí la placa real para mayor precisión")
                mat_fondo_sel = st.selectbox("Material del fondo", lista_fondos, index=idx_fondo, help="Material para el panel trasero del mueble. Normalmente es un material más delgado que el cuerpo")

            with st.expander("🏗️ Configuración del módulo", expanded=False):
                if tipo_modulo == "Bajo Mesada":
                    st.markdown("#### Configuracion de Frente")
                    tipo_tapa = st.radio("Estilo de Bajo Mesada", ["Superpuesta", "Gola BVM", "Embutida"])
                    cant_puertas = st.selectbox("Cantidad de Puertas", [2, 3])
                    if cant_puertas == 3:
                        tiene_parante = True
                        st.info("3 puertas: Parante divisor incluido automaticamente.")
                        c_p1, c_p2 = st.columns(2)
                        tipo_parante = c_p1.selectbox("Tipo de Parante", ["Corto (100mm)", "Largo (Fondo Lateral)"])
                        distancia_parante = c_p2.number_input("Distancia desde lateral izq. (mm)", value=ancho_m / cant_puertas if ancho_m > 0 else 0.0, step=1.0)
                    st.markdown("---")
                    st.markdown("#### Configuracion de Estantes")
                    cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=1, step=1, key="cant_est_bm")
                    tipo_estante_manual = st.radio("Formato de Estante", ["Completo", "Medio"], key="fmt_est_bm")
                    indices_fijos = []
                    if cant_total_est > 0:
                        st.write("Selecciona los estantes que son FIJOS:")
                        cols_estantes = st.columns(int(cant_total_est))
                        for i in range(int(cant_total_est)):
                            with cols_estantes[i]:
                                if st.checkbox(f"E{i+1}", value=False, key=f"check_est_bm_{i}"):
                                    indices_fijos.append(i)
                    estantes_fijos = len(indices_fijos)
                    estantes_moviles = cant_total_est - estantes_fijos
                    st.caption(f"Resumen: {estantes_fijos} Fijos y {estantes_moviles} Moviles")
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "Especial"])
                    cant_cajones = 0
                    luz_entre_tapas = 3.0
                    luz_perimetral_tapa = 4.0
                    alto_frentin_emb = 0.0

                elif tipo_modulo == "Alacena":
                    st.markdown("#### Configuracion de Alacena BVM")
                    c_ala1, c_ala2 = st.columns(2)
                    tipo_tapa = c_ala1.radio("Sistema de Apertura", ["Superpuesta", "Unero", "Embutida"])
                    cant_puertas = c_ala2.selectbox("Cantidad de Puertas", [2, 3, 4])
                    st.markdown("---")
                    cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=1, step=1)
                    indices_fijos = []
                    if cant_total_est > 0:
                        st.write("Selecciona los estantes que son FIJOS:")
                        cols_estantes = st.columns(int(cant_total_est))
                        for i in range(int(cant_total_est)):
                            with cols_estantes[i]:
                                if st.checkbox(f"E{i+1}", value=False, key=f"check_est_{i}"):
                                    indices_fijos.append(i)
                    estantes_fijos = len(indices_fijos)
                    estantes_moviles = cant_total_est - estantes_fijos
                    st.caption(f"Resumen: {estantes_fijos} Fijos y {estantes_moviles} Moviles")
                    tiene_cenefa = False
                    alto_cenefa = 0.0
                    if "Unero" in tipo_tapa:
                        tiene_cenefa = st.checkbox("Lleva Cenefa inferior?", value=True)
                        if tiene_cenefa:
                            alto_cenefa = st.number_input("Altura de Cenefa (mm)", value=50.0, step=5.0)
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "C0 Estandar"])
                    cant_cajones = 0
                    luz_entre_tapas = 0.0
                    luz_perimetral_tapa = 0.0
                    alto_frentin_emb = 0.0

                else:
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "Especial"])
                    tipo_corredera = st.radio("Tipo de Corredera", ["Telescopica 45cm", "Cierre Suave Pesada"])
                    c_caj, c_hue = st.columns(2)
                    cant_cajones = c_caj.number_input("Cant. Cajones", value=0, min_value=0)
                    opciones_estilo = ["Superpuesta", "Embutida"]
                    if cant_cajones == 3:
                        opciones_estilo.append("Gola")
                    tipo_tapa = st.radio("Estilo de Tapa", opciones_estilo)
                    st.markdown(f"#### Parametros del Cajon ({tipo_tapa})")
                    col_l1, col_l2 = st.columns(2)
                    luz_entre_tapas = col_l1.number_input("Luz entre tapas (mm)", value=3.0, help="Espacio entre la tapa de un cajón y el siguiente. Estándar BVM: 3mm")
                    if cant_cajones > 0:
                        if tipo_tapa == "Superpuesta":
                            luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=4.0, help="Espacio total entre el mueble y la tapa en sentido horizontal. Estándar BVM: 4mm")
                        elif tipo_tapa == "Embutida":
                            alto_frentin_emb = col_l2.number_input("Altura Frentin Superior (mm)", value=30.0)
                            luz_perimetral_tapa = 6.0
                        else:
                            luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=4.0, help="Espacio total entre el mueble y la tapa en sentido horizontal. Estándar BVM: 4mm")
                            alto_frentin_emb = 0.0
                        distribucion_tapas = col_l1.radio("Distribucion", ["Iguales", "Proporcional (20/35/45)"])
                        col_c1, col_c2 = st.columns(2)
                        esp_corredera = col_c1.number_input("Espesor de corredera (mm)", value=13.0, help="Espacio que ocupa la corredera a cada lado del cajón. Corredera telescópica estándar: 13mm")
                        aire_trasero = col_c2.number_input("Espacio libre trasero (mm)", value=30.0, help="Espacio entre el fondo del cajón y el panel trasero del mueble. Mínimo recomendado: 30mm")

            with st.expander("📦 Soporte y logística", expanded=False):
                tipo_base = st.selectbox("Tipo de Soporte", ["Zocalo de Madera", "Banquina", "Patas Plasticas", "Nada"])
                if tipo_base == "Zocalo de Madera":
                    altura_base = st.number_input("Altura de Zocalo (mm)", min_value=0.0, value=100.0, step=5.0)
                elif tipo_base == "Banquina":
                    altura_base = st.number_input("Altura de Banquina (mm)", min_value=0.0, value=100.0, step=5.0)
                elif tipo_base == "Patas Plasticas":
                    altura_base = st.number_input("Altura de Patas (mm)", min_value=0.0, value=100.0, step=5.0)
                else:
                    altura_base = 0.0
                costo_base = 5000 if tipo_base == "Patas Plasticas" else 0
                dias_prod = st.number_input("Dias de taller", value=0.0, step=0.5)
                necesita_colocacion = st.checkbox("Requiere Colocacion?")
                flete_sel = st.selectbox("Zona Envio", ["Ninguno", "Capital", "Zona Norte"])
                dias_col = st.number_input("Dias de obra", value=0) if necesita_colocacion else 0

        with col_out:
            st.subheader("📐 Planilla de corte")

            # Cliente obligatorio
            if not cliente:
                st.info("👆 Ingresá el nombre del cliente para comenzar a calcular.")

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
                )
                df_corte = pd.DataFrame(piezas_calculadas)

                if not df_corte.empty and 'L' in df_corte.columns:
                    for col in ['Tipo', 'L', 'A', 'Cant']:
                        if col not in df_corte.columns:
                            df_corte[col] = 0 if col != 'Tipo' else 'Cuerpo'
                    df_corte['L'] = pd.to_numeric(df_corte['L'], errors='coerce').fillna(0)
                    df_corte['A'] = pd.to_numeric(df_corte['A'], errors='coerce').fillna(0)
                    df_corte['Cant'] = pd.to_numeric(df_corte['Cant'], errors='coerce').fillna(0)
                    df_corte['Tipo'] = df_corte['Tipo'].fillna('Cuerpo').astype(str)
                    st.data_editor(df_corte, use_container_width=True, hide_index=True)

                    df_placa = df_corte[~df_corte['Tipo'].isin(['Fondo', 'Piso'])]
                    m2_18mm = (df_placa['L'] * df_placa['A'] * df_placa['Cant']).sum() / 1_000_000
                    costo_madera = m2_18mm * (maderas.get(mat_principal, 0.0) / 5.03)
                    df_fondo_only = df_corte[df_corte['Tipo'].isin(['Fondo', 'Piso'])]
                    m2_fondo = (df_fondo_only['L'] * df_fondo_only['A'] * df_fondo_only['Cant']).sum() / 1_000_000 if not df_fondo_only.empty else 0.0
                    costo_fondo = m2_fondo * (fondos.get(mat_fondo_sel, 0.0) / 5.03)
                    if tipo_modulo in ["Bajo Mesada", "Alacena"]:
                        costo_herrajes = cant_puertas * 2 * config.get('bisagra_cazoleta', 0)
                    else:
                        costo_herrajes = cant_cajones * config.get('telescopica_45', 0)
                    costo_flete = config.get('flete_capital', 0) if flete_sel == "Capital" else config.get('flete_norte', 0) if flete_sel == "Zona Norte" else 0.0
                    costo_operativo = dias_prod * config.get('gastos_fijos_diarios', 0)
                    total_costo = costo_madera + costo_fondo + costo_herrajes + costo_operativo + costo_base + costo_flete
                    if necesita_colocacion:
                        total_costo += dias_col * config.get('colocacion_dia', 0)
                else:
                    st.warning("Esperando medidas para calcular...")

            st.write("---")
            retazos_en_stock = consultar_retazos_disponibles(mat_principal)
            ahorro_madera, matches = calcular_ahorro_retazos(df_corte, retazos_en_stock, maderas.get(mat_principal, 0.0))

            total_costo_real = total_costo - ahorro_madera
            utilidad = total_costo_real * config.get('ganancia_taller_pct', 0.30)
            precio_final = total_costo_real + utilidad
            pct_utilidad_real = (utilidad / precio_final * 100) if precio_final > 0 else 0.0

            # PRECIO FINAL — destacado arriba
            if precio_final > 0:
                color_margen = "#0F6E56" if pct_utilidad_real >= 12 else "#A32D2D"
                icono_margen = "✅" if pct_utilidad_real >= 12 else "⚠️"
                alerta = "Operación rentable" if pct_utilidad_real >= 12 else "Margen bajo — revisá los costos"
                precio_str = f"${precio_final:,.0f}"
                margen_str = f"{pct_utilidad_real:.1f}%"
                st.markdown(f"""
                <div style="background:{color_margen}; border-radius:10px; padding:20px 24px; margin:8px 0 16px 0; text-align:center;">
                    <div style="color:white; font-size:12px; letter-spacing:0.1em; opacity:0.8; margin-bottom:6px;">PRECIO FINAL AL CLIENTE</div>
                    <div style="color:white; font-size:40px; font-weight:700; letter-spacing:-1px;">{precio_str}</div>
                    <div style="color:white; font-size:12px; opacity:0.8; margin-top:8px;">{icono_margen} Margen: {margen_str} — {alerta}</div>
                </div>
                """, unsafe_allow_html=True)

            # Métricas secundarias
            c1, c2, c3 = st.columns(3)
            c1.metric("Costo real", f"${total_costo_real:,.0f}")
            c2.metric("M² de placa", f"{m2_18mm:.2f}")
            c3.metric("Ganancia neta", f"${utilidad:,.0f}")

            # Retazos disponibles
            if matches:
                st.success(f"♻️ **¡Ahorro por retazos!** Podés reutilizar material en {len(matches)} pieza(s) — Ahorro estimado: **${ahorro_madera:,.0f}**")
                with st.expander("Ver detalle de retazos", expanded=False):
                    for m in matches:
                        st.write(f"• **{m['pieza']}** entra en Retazo ID-{m['retazo_id']} — Ahorro: ${m['ahorro']:,.0f}")

            # Desglose visual
            if precio_final > 0:
                with st.expander("📊 Ver desglose de costos", expanded=False):
                    datos_grafico = {
                        "Categoría": ["Madera/Fondo", "Herrajes", "Operativo/Taller", "Logística/Flete", "Ganancia Neta"],
                        "Monto": [costo_madera + costo_fondo, costo_herrajes, costo_operativo + costo_base, costo_flete, utilidad]
                    }
                    st.bar_chart(data=pd.DataFrame(datos_grafico), x="Categoría", y="Monto", color="#2e7d32")

            # AGREGAR A OBRA
            st.write("---")
            st.subheader("🏠 Gestión de obra")
            nombre_modulo = st.text_input("Nombre del modulo (ej: Bajo mesada izquierdo)", value=f"{tipo_modulo} {ancho_m:.0f}mm")

            # Si venimos de editar una obra, mostramos qué módulo estamos reemplazando
            idx_modulo_editar = st.session_state.get("idx_modulo_editar")

            col_ag, col_sv = st.columns(2)
            with col_ag:
                label_boton = "✏️ Reemplazar módulo en la obra" if idx_modulo_editar is not None else "+ Agregar módulo a la obra"
                if st.button(label_boton, use_container_width=True, type="primary"):
                    if ancho_m > 0 and alto_m > 0 and precio_final > 0:
                        nuevo_mod = {
                            "nombre": nombre_modulo,
                            "tipo": tipo_modulo,
                            "ancho": int(ancho_m),
                            "alto": int(alto_m),
                            "prof": int(prof_m),
                            "material": mat_principal,
                            "precio": precio_final,
                            "df_corte": df_corte.copy() if not df_corte.empty else None,
                        }
                        if idx_modulo_editar is not None:
                            # Reemplazamos el módulo en la posición correcta
                            st.session_state["obra_modulos"][idx_modulo_editar] = nuevo_mod
                            st.session_state["idx_modulo_editar"] = None
                            st.session_state["editar_presupuesto"] = None
                        else:
                            st.session_state["obra_modulos"].append(nuevo_mod)
                        st.session_state["ultimo_modulo_agregado"] = nombre_modulo
                        st.session_state["ultimo_precio_agregado"] = precio_final
                        st.rerun()
                    else:
                        st.warning("Ingresa las medidas y calcula el modulo antes de agregar.")

            with col_sv:
                if st.button("Guardar solo este modulo", use_container_width=True):
                    if cliente:
                        params = {
                            "tipo_modulo": tipo_modulo, "ancho_m": ancho_m, "alto_m": alto_m,
                            "prof_m": prof_m, "esp_real": esp_real, "mat_principal": mat_principal,
                            "mat_fondo_sel": mat_fondo_sel, "tipo_tapa": tipo_tapa,
                            "cant_puertas": cant_puertas, "cant_cajones": cant_cajones,
                            "tiene_parante": tiene_parante, "tipo_parante": tipo_parante,
                            "tipo_base": tipo_base, "altura_base": altura_base,
                            "estantes_fijos": estantes_fijos, "estantes_moviles": estantes_moviles,
                            "tipo_estante_manual": tipo_estante_manual,
                            "luz_entre_tapas": luz_entre_tapas, "luz_perimetral_tapa": luz_perimetral_tapa,
                            "alto_frentin_emb": alto_frentin_emb, "aire_trasero": aire_trasero,
                            "esp_corredera": esp_corredera, "distribucion_tapas": distribucion_tapas,
                            "tiene_cenefa": tiene_cenefa, "alto_cenefa": alto_cenefa,
                        }
                        guardar_presupuesto_nube(
                            cliente, tipo_modulo, precio_final,
                            parametros=params,
                            id_editar=st.session_state.get("editar_id")
                        )
                        # Limpiamos el modo edición
                        st.session_state["editar_presupuesto"] = None
                        st.session_state["editar_id"] = None
                        st.session_state["editar_cliente"] = ""
                    else:
                        st.warning("Ingresa el nombre del Cliente.")

            # Cartel de confirmación cuando se acaba de agregar un módulo
            if st.session_state.get("ultimo_modulo_agregado"):
                total_actual = sum(m["precio"] for m in st.session_state["obra_modulos"])
                st.info(f"""
**✅ Módulo agregado: {st.session_state['ultimo_modulo_agregado']}** — ${st.session_state['ultimo_precio_agregado']:,.0f}

📋 Tenés **{len(st.session_state['obra_modulos'])} módulo(s)** en la obra — Total acumulado: **${total_actual:,.0f}**

👉 **¿Qué hacer ahora?**
- Configurá el siguiente módulo arriba y volvé a hacer click en "Agregar"
- Cuando terminés todos los módulos, bajá a **Resumen de Obra** para generar el PDF y el WhatsApp
                """)
                st.session_state["ultimo_modulo_agregado"] = None
                st.session_state["ultimo_precio_agregado"] = 0

            if not df_corte.empty:
                # --- PROPUESTA COMERCIAL MODULO INDIVIDUAL ---
                st.write("---")
                st.subheader("Propuesta para este modulo")
                col_ent, col_sena = st.columns(2)
                with col_ent:
                    dias_entrega = st.number_input("Dias de entrega", value=15, step=1, key="dias_mod")
                with col_sena:
                    pct_seña = st.slider("% de Sena", 0, 100, 50, 5, key="sena_mod")

                from fpdf import FPDF
                import urllib.parse as _up

                # PDF modulo individual
                def _pdf_modulo(cliente, nombre, tipo, ancho, alto, prof, mat, precio, dias, pct):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", "B", 20)
                    pdf.set_text_color(46, 125, 50)
                    pdf.cell(200, 20, "PRESUPUESTO - BVM", ln=True, align="C")
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font("Arial", "", 10)
                    from datetime import datetime, timedelta, timezone as tz
                    fecha = datetime.now(tz(timedelta(hours=-3))).strftime("%d/%m/%Y")
                    pdf.cell(200, 8, f"Fecha: {fecha}    Cliente: {cliente}", ln=True, align="R")
                    pdf.ln(6)
                    pdf.set_font("Arial", "B", 12)
                    pdf.set_fill_color(230, 245, 238)
                    pdf.cell(0, 11, f"  {nombre}", ln=True, fill=True)
                    pdf.set_font("Arial", "", 11)
                    pdf.cell(95, 8, f"  Tipo: {tipo}", ln=False)
                    pdf.cell(95, 8, f"  Material: {mat}", ln=True)
                    pdf.cell(95, 8, f"  Ancho: {ancho} mm", ln=False)
                    pdf.cell(95, 8, f"  Alto: {alto} mm", ln=True)
                    pdf.cell(95, 8, f"  Profundidad: {prof} mm", ln=True)
                    pdf.ln(4)
                    monto_sena = precio * (pct / 100)
                    pdf.set_font("Arial", "B", 14)
                    pdf.set_fill_color(240, 240, 240)
                    pdf.cell(0, 14, f"TOTAL: ${precio:,.0f}", ln=True, align="C", fill=True)
                    pdf.set_font("Arial", "", 11)
                    pdf.cell(0, 8, f"Seña requerida ({pct}%): ${monto_sena:,.0f}", ln=True, align="C")
                    pdf.cell(0, 8, f"Entrega: {dias} dias habiles", ln=True, align="C")
                    pdf.ln(4)
                    pdf.set_font("Arial", "I", 9)
                    pdf.multi_cell(0, 5, "Precios validos por 48hs. Una vez abonada la seña se congelan los materiales.")
                    return bytes(pdf.output())

                def _wa_modulo(cliente, nombre, tipo, ancho, alto, prof, mat, precio, dias, pct):
                    monto = precio * (pct / 100)
                    lineas = [
                        f"*PRESUPUESTO BVM — {nombre.upper()}*",
                        f"Cliente: {cliente}", "",
                        f"• Tipo: {tipo}",
                        f"• Medidas: {ancho}x{alto}x{prof} mm",
                        f"• Material: {mat}", "",
                        f"*TOTAL: ${precio:,.0f}*",
                        f"Seña ({pct}%): ${monto:,.0f}",
                        f"Entrega: {dias} dias habiles", "",
                        "Precios validos por 48hs.",
                    ]
                    return f"https://wa.me/?text={_up.quote(chr(10).join(lineas))}"

                pdf_mod = _pdf_modulo(cliente, nombre_modulo, tipo_modulo, int(ancho_m), int(alto_m), int(prof_m), mat_principal, precio_final, dias_entrega, pct_seña)
                wa_mod  = _wa_modulo(cliente, nombre_modulo, tipo_modulo, int(ancho_m), int(alto_m), int(prof_m), mat_principal, precio_final, dias_entrega, pct_seña)

                # Solo mostramos PDF/WA individual si NO hay obra en curso
                # (si hay obra, el PDF completo está en el Resumen de Obra)
                if not st.session_state["obra_modulos"]:
                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        st.download_button(label="PDF este módulo", data=pdf_mod, file_name=f"Presupuesto_{nombre_modulo}.pdf", mime="application/pdf", use_container_width=True)
                    with col_p2:
                        st.link_button("WhatsApp este módulo", wa_mod, use_container_width=True)
                else:
                    st.info("📄 Cuando termines de agregar todos los módulos, generá el PDF completo en el **Resumen de Obra** de abajo.")

                with st.expander("Terminal CNC - Este modulo", expanded=False):
                    archivo_aspire = exportar_para_aspire(df_corte, mat_principal, esp_real)
                    dxf_bytes = generar_dxf_bvm(df_corte)
                    col_cnc1, col_cnc2 = st.columns(2)
                    with col_cnc1:
                        st.download_button(label="DXF (Vectores)", data=dxf_bytes, file_name=f"Vectores_{nombre_modulo}.dxf", mime="application/dxf", use_container_width=True)
                    with col_cnc2:
                        st.download_button(label="CSV (Aspire)", data=archivo_aspire, file_name=f"CNC_{nombre_modulo}.csv", mime="text/csv", use_container_width=True)

        # RESUMEN DE OBRA
        if st.session_state["obra_modulos"]:
            st.write("---")
            st.header("Resumen de Obra Completa")
            total_obra = sum(m["precio"] for m in st.session_state["obra_modulos"])

            for i, mod in enumerate(st.session_state["obra_modulos"]):
                col_mod, col_del = st.columns([5, 1])
                with col_mod:
                    st.write(f"**{i+1}. {mod['nombre']}** - {mod['ancho']}x{mod['alto']}x{mod['prof']} mm - {mod['material']} - `${mod['precio']:,.0f}`")
                with col_del:
                    if st.button("X", key=f"del_mod_{i}", help="Eliminar este modulo"):
                        st.session_state["obra_modulos"].pop(i)
                        st.rerun()

            st.write("---")
            col_t1, col_t2 = st.columns(2)
            col_t1.metric("Total modulos", len(st.session_state["obra_modulos"]))
            col_t2.metric("TOTAL OBRA", f"${total_obra:,.0f}")

            st.write("---")
            col_pdf1, col_pdf2 = st.columns(2)
            with col_pdf1:
                dias_entrega_obra = st.number_input("Dias de entrega total", value=20, step=1, key="dias_obra")
            with col_pdf2:
                pct_seña_obra = st.slider("% de Sena", 0, 100, 50, 5, key="sena_obra")

            cliente_obra = cliente if cliente else "Cliente"
            col_gen1, col_gen2, col_gen3 = st.columns(3)

            with col_gen1:
                pdf_obra = generar_pdf_obra(cliente_obra, st.session_state["obra_modulos"], dias_entrega_obra, pct_seña_obra)
                st.download_button(label="PDF Presupuesto Completo", data=pdf_obra, file_name=f"Obra_{cliente_obra}.pdf", mime="application/pdf", use_container_width=True)

            with col_gen2:
                link_wa_obra = generar_link_whatsapp_obra(cliente_obra, st.session_state["obra_modulos"], dias_entrega_obra, pct_seña_obra)
                st.link_button("Enviar por WhatsApp", link_wa_obra, use_container_width=True)

            with col_gen3:
                if st.button("Limpiar obra completa", use_container_width=True):
                    st.session_state["obra_modulos"] = []
                    st.rerun()

            if st.button("Guardar obra en historial", use_container_width=True):
                if cliente:
                    import json
                    params_obra = {
                        "es_obra": True,
                        "modulos": [
                            {
                                "nombre": m["nombre"],
                                "tipo_modulo": m["tipo"],
                                "ancho_m": m["ancho"],
                                "alto_m": m["alto"],
                                "prof_m": m["prof"],
                                "mat_principal": m["material"],
                                "precio": m["precio"],
                            }
                            for m in st.session_state["obra_modulos"]
                        ]
                    }
                    # Si estamos editando una obra existente, actualizamos ese registro
                    id_obra_editar = st.session_state.get("editar_obra_id")
                    guardar_presupuesto_nube(
                        cliente,
                        f"Obra ({len(st.session_state['obra_modulos'])} módulos)",
                        total_obra,
                        parametros=params_obra,
                        id_editar=id_obra_editar
                    )
                    # Limpiamos todo el modo edición
                    st.session_state["obra_modulos"] = []
                    st.session_state["editar_obra_modulos"] = None
                    st.session_state["editar_obra_id"] = None
                    st.session_state["editar_obra_cliente"] = ""
                    st.session_state["editar_presupuesto"] = None
                    st.session_state["editar_id"] = None
                    st.session_state["editar_cliente"] = ""
                    st.rerun()
                else:
                    st.warning("Ingresa el nombre del Cliente arriba.")

    except Exception as e:
        st.error(f"Error en el Cotizador: {e}")

elif menu == "📋 Historial":
    st.title("📋 Historial de presupuestos")

    ESTADOS = ["Pendiente", "Señado", "Pagado"]
    COLORES = {
        "Pendiente": ("🔴", "#FCEBEB", "#A32D2D"),
        "Señado":    ("🟡", "#FAEEDA", "#854F0B"),
        "Pagado":    ("🟢", "#E1F5EE", "#0F6E56"),
    }

    def actualizar_estado(id_venta, nuevo_estado):
        try:
            token = st.session_state["session"].access_token
            supabase.postgrest.auth(token)
            supabase.table("ventas").update({"estado": nuevo_estado}).eq("id", id_venta).execute()
        except Exception as e:
            st.error(f"Error al actualizar estado: {e}")

    try:
        df_hist = traer_datos_historial()

        if df_hist.empty:
            st.info("Todavia no hay presupuestos guardados. Cuando guardes uno desde el Cotizador va a aparecer acá.")
        else:
            # --- RESUMEN SUPERIOR ---
            total_pendiente = df_hist[df_hist['estado'] == 'Pendiente']['precio_final'].sum()
            total_señado    = df_hist[df_hist['estado'] == 'Señado']['precio_final'].sum()
            total_pagado    = df_hist[df_hist['estado'] == 'Pagado']['precio_final'].sum()

            c1, c2, c3 = st.columns(3)
            c1.metric("🔴 Pendientes", f"${total_pendiente:,.0f}", f"{len(df_hist[df_hist['estado']=='Pendiente'])} presupuestos")
            c2.metric("🟡 Señados",    f"${total_señado:,.0f}",    f"{len(df_hist[df_hist['estado']=='Señado'])} presupuestos")
            c3.metric("🟢 Pagados",    f"${total_pagado:,.0f}",    f"{len(df_hist[df_hist['estado']=='Pagado'])} presupuestos")

            st.write("---")

            # --- FILTRO ---
            filtro = st.radio(
                "Mostrar",
                ["Todos", "Pendiente", "Señado", "Pagado"],
                horizontal=True
            )

            df_filtrado = df_hist if filtro == "Todos" else df_hist[df_hist['estado'] == filtro]
            df_filtrado = df_filtrado.sort_values("fecha", ascending=False) if "fecha" in df_filtrado.columns else df_filtrado

            st.write(f"**{len(df_filtrado)} presupuesto(s) encontrado(s)**")
            st.write("---")

            # --- TARJETAS POR PRESUPUESTO ---
            for _, row in df_filtrado.iterrows():
                estado_actual = row.get('estado', 'Pendiente')
                if estado_actual not in COLORES:
                    estado_actual = 'Pendiente'

                icono, bg_color, text_color = COLORES[estado_actual]
                id_venta = row.get('id', None)

                with st.container():
                    # Usamos markdown para el fondo de color
                    st.markdown(
                        f"""<div style="background:{bg_color}; border-radius:8px; padding:12px 16px; margin-bottom:4px;">
                        <span style="color:{text_color}; font-weight:600; font-size:15px;">{icono} {row.get('cliente','Sin nombre')} — {row.get('mueble','')}</span>
                        <span style="color:{text_color}; float:right; font-size:15px; font-weight:600;">${row['precio_final']:,.0f}</span>
                        </div>""",
                        unsafe_allow_html=True
                    )

                    col_fecha, col_estado, col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 1, 1, 1])

                    fecha_str = str(row.get('fecha', ''))[:16] if row.get('fecha') else 'Sin fecha'
                    col_fecha.caption(f"📅 {fecha_str}")

                    nuevo_estado = col_estado.selectbox(
                        "Estado",
                        ESTADOS,
                        index=ESTADOS.index(estado_actual),
                        key=f"estado_{id_venta}_{_}",
                        label_visibility="collapsed"
                    )

                    with col_btn1:
                        if st.button("Guardar", key=f"save_{id_venta}_{_}", use_container_width=True):
                            if id_venta and nuevo_estado != estado_actual:
                                actualizar_estado(id_venta, nuevo_estado)
                                st.success(f"Estado actualizado a {nuevo_estado}")
                                st.rerun()

                    with col_btn2:
                        import json as _json
                        tiene_params = row.get('parametros') not in [None, '', 'null']
                        if st.button(
                            "Editar" if tiene_params else "—",
                            key=f"edit_{id_venta}_{_}",
                            use_container_width=True,
                            disabled=not tiene_params,
                            help="Editar este presupuesto" if tiene_params else "Este presupuesto fue creado antes de que existiera esta función"
                        ):
                            try:
                                params = _json.loads(row['parametros'])
                                es_obra = params.get("es_obra", False)

                                if es_obra:
                                    # OBRA MULTI-MÓDULO: mostramos los módulos para elegir cuál editar
                                    st.session_state["editar_obra_modulos"] = params.get("modulos", [])
                                    st.session_state["editar_obra_id"] = id_venta
                                    st.session_state["editar_obra_cliente"] = row.get('cliente', '')
                                    st.session_state["editar_presupuesto"] = None
                                    st.session_state["menu_idx"] = 0
                                    st.rerun()
                                else:
                                    # MÓDULO INDIVIDUAL: carga directo en el cotizador
                                    st.session_state["editar_presupuesto"] = params
                                    st.session_state["editar_id"] = id_venta
                                    st.session_state["editar_cliente"] = row.get('cliente', '')
                                    st.session_state["editar_obra_modulos"] = None
                                    st.session_state["menu_idx"] = 0
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error al cargar parámetros: {e}")

                    with col_btn3:
                        if st.button("Borrar", key=f"del_{id_venta}_{_}", use_container_width=True):
                            try:
                                token = st.session_state["session"].access_token
                                supabase.postgrest.auth(token)
                                supabase.table("ventas").delete().eq("id", id_venta).execute()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al borrar: {e}")

                    st.write("---")

    except Exception as e:
        st.error(f"Error en el historial: {e}")

elif menu == "♻️ Retazos":
    st.title("♻️ Depósito de retazos")
    st.caption("Registra los sobrantes del taller. El sistema los usa automaticamente al calcular presupuestos para ahorrarte material.")

    # --- REGISTRAR NUEVO RETAZO ---
    with st.expander("+ Registrar nuevo retazo", expanded=True):
        st.markdown("**Medida minima para que sea util: 150 x 400 mm**")
        c_mat, c_largo, c_ancho = st.columns([2, 1, 1])
        mat_r  = c_mat.selectbox("Material", list(maderas.keys()), key="mat_ret")
        largo_r = c_largo.number_input("Largo (mm)", min_value=0, value=0, step=10, key="lar_r_indep")
        ancho_r = c_ancho.number_input("Ancho (mm)", min_value=0, value=0, step=10, key="anc_r_indep")

        # Preview en tiempo real
        if largo_r > 0 and ancho_r > 0:
            es_util = (largo_r >= 400 and ancho_r >= 150) or (largo_r >= 150 and ancho_r >= 400)
            area_m2 = (largo_r * ancho_r) / 1_000_000
            precio_mat = maderas.get(mat_r, 0)
            valor_est = area_m2 * (precio_mat / 5.03)
            if es_util:
                st.success(f"Retazo valido — {largo_r}x{ancho_r} mm — {area_m2:.3f} m² — Valor estimado: ${valor_est:,.0f}")
            else:
                st.error(f"Retazo demasiado chico ({largo_r}x{ancho_r} mm). Minimo requerido: 150x400 mm en cualquier orientacion.")

        if st.button("Guardar en deposito", use_container_width=True, type="primary"):
            if largo_r > 0 and ancho_r > 0:
                if (largo_r >= 400 and ancho_r >= 150) or (largo_r >= 150 and ancho_r >= 400):
                    registrar_retazo(mat_r, largo_r, ancho_r)
                    st.success(f"Retazo de {mat_r} ({largo_r}x{ancho_r} mm) guardado en el deposito.")
                    st.rerun()
                else:
                    st.warning("El retazo no cumple el minimo. No se guardo.")
            else:
                st.warning("Ingresa las medidas antes de guardar.")

    st.write("---")

    # --- STOCK ACTUAL ---
    retazos_db = consultar_retazos_disponibles("Todos")

    if not retazos_db:
        st.info("El deposito esta vacio. Cuando cargues retazos van a aparecer aca y el sistema los va a usar automaticamente.")
    else:
        df_inv = pd.DataFrame(retazos_db)

        # Métricas del depósito
        c1, c2, c3 = st.columns(3)
        c1.metric("Retazos en stock", len(df_inv))
        materiales_unicos = df_inv['material'].nunique() if 'material' in df_inv.columns else 0
        c2.metric("Materiales distintos", materiales_unicos)
        if 'largo' in df_inv.columns and 'ancho' in df_inv.columns:
            area_total = (df_inv['largo'] * df_inv['ancho']).sum() / 1_000_000
            c3.metric("Area total en stock", f"{area_total:.2f} m²")

        st.write("---")
        st.subheader("Stock por material")

        # Agrupamos por material para que sea más fácil de leer
        materiales = df_inv['material'].unique() if 'material' in df_inv.columns else []

        for mat in materiales:
            df_mat = df_inv[df_inv['material'] == mat]
            with st.expander(f"{mat} — {len(df_mat)} retazo(s)", expanded=True):
                for _, ret in df_mat.iterrows():
                    col_info, col_area, col_del = st.columns([3, 2, 1])
                    largo = ret.get('largo', 0)
                    ancho = ret.get('ancho', 0)
                    area = (largo * ancho) / 1_000_000
                    precio_mat = maderas.get(mat, 0)
                    valor = area * (precio_mat / 5.03)

                    col_info.markdown(f"**{int(largo)} x {int(ancho)} mm**")
                    col_area.caption(f"{area:.3f} m²  —  Valor est. ${valor:,.0f}")

                    ret_id = ret.get('id')
                    if col_del.button("X", key=f"del_ret_{ret_id}", help="Eliminar este retazo"):
                        try:
                            token = st.session_state["session"].access_token
                            supabase.postgrest.auth(token)
                            supabase.table("retazos").delete().eq("id", ret_id).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar: {e}")

elif menu == "⚙️ Precios":
    st.title("⚙️ Configuración de precios")

    with st.expander("Precios de Placas (18mm)"):
        for madera, precio in maderas.items():
            maderas[madera] = st.number_input(f"Precio {madera}", value=float(precio), step=1000.0)

    with st.expander("Herrajes y Accesorios"):
        c1, c2 = st.columns(2)
        config['bisagra_cazoleta'] = c1.number_input("Precio Bisagra Cazoleta", value=float(config['bisagra_cazoleta']), step=100.0)
        config['telescopica_45'] = c2.number_input("Precio Guia Telescopica 45cm", value=float(config['telescopica_45']), step=100.0)
        config['telescopica_soft'] = c1.number_input("Precio Guia Cierre Suave", value=float(config['telescopica_soft']), step=100.0)

    with st.expander("Gastos Fijos y Logistica"):
        f1, f2 = st.columns(2)
        config['gastos_fijos_diarios'] = f1.number_input("Gasto Diario Taller", value=float(config['gastos_fijos_diarios']), step=5000.0)
        config['flete_capital'] = f2.number_input("Flete Capital", value=float(config['flete_capital']), step=1000.0)
        config['flete_norte'] = f1.number_input("Flete Zona Norte", value=float(config['flete_norte']), step=1000.0)
        config['colocacion_dia'] = f2.number_input("Costo Dia de Colocacion", value=float(config['colocacion_dia']), step=5000.0)

    with st.expander("Margen de Ganancia"):
        config['ganancia_taller_pct'] = st.slider("Porcentaje de Utilidad Bruta", 0.0, 1.0, float(config['ganancia_taller_pct']), 0.05)
        st.write(f"Margen actual: {config['ganancia_taller_pct'] * 100:.0f}%")

    if st.button("Guardar Precios Permanentemente"):
        for madera, precio in maderas.items():
            actualizar_precio_nube(madera, precio, 'maderas')
        for k, v in config.items():
            actualizar_precio_nube(k, v, 'costos')
        st.success("Configuracion guardada.")
