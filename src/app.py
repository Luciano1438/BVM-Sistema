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
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(230, 245, 238)
        pdf.cell(0, 10, f"  Modulo {i+1}: {mod['nombre']}  -  {mod['ancho']}x{mod['alto']}x{mod['prof']} mm", ln=True, fill=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 7, f"  Material: {mod['material']}", ln=True)

        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(70, 6, "Pieza", border=1, fill=True)
        pdf.cell(25, 6, "Largo", border=1, fill=True, align="C")
        pdf.cell(25, 6, "Ancho", border=1, fill=True, align="C")
        pdf.cell(20, 6, "Cant", border=1, fill=True, align="C")
        pdf.cell(30, 6, "Tipo", border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font("Arial", "", 9)
        if mod["df_corte"] is not None and not mod["df_corte"].empty:
            for _, row in mod["df_corte"].iterrows():
                pdf.cell(70, 6, str(row["Pieza"])[:35], border=1)
                pdf.cell(25, 6, str(int(row["L"])), border=1, align="C")
                pdf.cell(25, 6, str(int(row["A"])), border=1, align="C")
                pdf.cell(20, 6, str(int(row["Cant"])), border=1, align="C")
                pdf.cell(30, 6, str(row.get("Tipo", ""))[:12], border=1, align="C")
                pdf.ln()

        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 8, f"  Subtotal modulo: ${mod['precio']:,.0f}", ln=True, align="R")
        pdf.ln(3)

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


def guardar_presupuesto_nube(cliente, mueble, total):
    try:
        data = {
            "cliente": cliente,
            "mueble": mueble,
            "precio_final": float(total),
            "estado": "Pendiente",
            "user_id": st.session_state["user"].id,
            "fecha": datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M")
        }
        supabase.table("ventas").insert(data).execute()
        st.success("Venta guardada en la nube")
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
st.set_page_config(page_title="BVM - Sistema", layout="wide")
if not gestionar_auth():
    st.stop()

if "obra_modulos" not in st.session_state:
    st.session_state["obra_modulos"] = []

maderas, fondos, config = traer_datos()
menu = st.sidebar.radio("Navegacion", ["Cotizador CNC", "Deposito de Retazos", "Historial de Ventas", "Configuracion de Precios"])

if st.session_state["obra_modulos"]:
    st.sidebar.info(f"Obra en curso: {len(st.session_state['obra_modulos'])} modulo(s)")

st.sidebar.write("---")
if st.sidebar.button("Cerrar Sesion"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if menu == "Cotizador CNC":
    try:
        st.title("BVM | Control de Produccion Industrial")

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
        tiene_parante = False
        tipo_parante = "Corto (100mm)"
        tipo_estante_manual = "Completo"
        distancia_parante = 0.0
        luz_perimetral_tapa = 4.0
        aire_trasero = 30.0
        esp_corredera = 13.0
        distribucion_tapas = "Iguales"
        cant_puertas = 0
        tiene_cenefa = False
        alto_cenefa = 0.0
        estantes_fijos = 0
        estantes_moviles = 0
        cant_cajones = 0
        luz_entre_tapas = 3.0
        alto_frentin_emb = 0.0
        tipo_tapa = "Superpuesta"
        tipo_base = "Nada"
        altura_base = 0.0

        col_in, col_out = st.columns([1, 1.2])

        with col_in:
            with st.expander("Definicion de Estructura", expanded=True):
                cliente = st.text_input("Cliente", "")
                tipo_modulo = st.selectbox("Tipo de Mueble", ["Cajonera", "Bajo Mesada", "Alacena"], key="tipo_mueble_sel")
                c1, c2, c3 = st.columns(3)
                ancho_m = c1.number_input("Ancho Total (mm)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
                alto_m = c2.number_input("Alto Total (mm)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
                prof_m = c3.number_input("Profundo (mm)", min_value=0.0, max_value=2000.0, value=0.0, step=0.5)
                mat_principal = st.selectbox("Material Cuerpo (18mm)", list(maderas.keys()))
                esp_real = st.number_input("Espesor Real Placa (mm)", min_value=1.0, max_value=50.0, value=18.0, step=0.1)
                mat_fondo_sel = st.selectbox("Material Fondo", list(fondos.keys()))

            with st.expander("Configuracion de Modulos", expanded=False):
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
                    luz_entre_tapas = col_l1.number_input("Luz entre tapas (mm)", value=3.0)
                    if cant_cajones > 0:
                        if tipo_tapa == "Superpuesta":
                            luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=4.0)
                        elif tipo_tapa == "Embutida":
                            alto_frentin_emb = col_l2.number_input("Altura Frentin Superior (mm)", value=30.0)
                            luz_perimetral_tapa = 6.0
                        else:
                            luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=4.0)
                            alto_frentin_emb = 0.0
                        distribucion_tapas = col_l1.radio("Distribucion", ["Iguales", "Proporcional (20/35/45)"])
                        col_c1, col_c2 = st.columns(2)
                        esp_corredera = col_c1.number_input("Espesor de Corredera (mm)", value=13.0)
                        aire_trasero = col_c2.number_input("Espacio libre trasero (mm)", value=30.0)

            with st.expander("Soporte y Logistica", expanded=False):
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
            st.subheader("Planilla de Corte e Inteligencia de Materiales")

            if alto_m > 0 and ancho_m > 0:
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

            if matches:
                st.subheader("Oportunidades de Ahorro")
                for m in matches:
                    st.success(f"Match! '{m['pieza']}' entra en Retazo ID-{m['retazo_id']} - Ahorro: ${m['ahorro']:,.0f}")

            total_costo_real = total_costo - ahorro_madera
            utilidad = total_costo_real * config.get('ganancia_taller_pct', 0.30)
            precio_final = total_costo_real + utilidad

            c1, c2, c3 = st.columns(3)
            c1.metric("Costo Real", f"${total_costo_real:,.0f}")
            c2.metric("M2 Placa", f"{m2_18mm:.2f}")
            c3.metric("Precio Final", f"${precio_final:,.2f}")

            if precio_final > 0:
                st.write("---")
                st.subheader("Desglose de Inversion y Rentabilidad")
                datos_grafico = {
                    "Categoria": ["Madera/Fondo", "Herrajes", "Operativo/Taller", "Logistica/Flete", "Ganancia Neta"],
                    "Monto": [costo_madera + costo_fondo, costo_herrajes, costo_operativo + costo_base, costo_flete, utilidad]
                }
                st.bar_chart(data=pd.DataFrame(datos_grafico), x="Categoria", y="Monto", color="#2e7d32")

            pct_utilidad_real = (utilidad / precio_final * 100) if precio_final > 0 else 0.0
            if pct_utilidad_real < 12:
                st.error(f"ALERTA DE MARGEN: La rentabilidad es del {pct_utilidad_real:.1f}%. Revisar costos fijos.")
            else:
                st.success(f"OPERACION RENTABLE: Margen del {pct_utilidad_real:.1f}%")

            st.subheader(f"PRECIO FINAL: ${precio_final:,.2f}")

            # AGREGAR A OBRA
            st.write("---")
            st.subheader("Gestion de Obra")
            nombre_modulo = st.text_input("Nombre del modulo (ej: Bajo mesada izquierdo)", value=f"{tipo_modulo} {ancho_m:.0f}mm")

            col_ag, col_sv = st.columns(2)
            with col_ag:
                if st.button("+ Agregar modulo a la obra", use_container_width=True, type="primary"):
                    if ancho_m > 0 and alto_m > 0 and precio_final > 0:
                        st.session_state["obra_modulos"].append({
                            "nombre": nombre_modulo,
                            "tipo": tipo_modulo,
                            "ancho": int(ancho_m),
                            "alto": int(alto_m),
                            "prof": int(prof_m),
                            "material": mat_principal,
                            "precio": precio_final,
                            "df_corte": df_corte.copy() if not df_corte.empty else None,
                        })
                        st.success(f"'{nombre_modulo}' agregado. Total modulos: {len(st.session_state['obra_modulos'])}")
                        st.rerun()
                    else:
                        st.warning("Ingresa las medidas y calcula el modulo antes de agregar.")

            with col_sv:
                if st.button("Guardar solo este modulo", use_container_width=True):
                    if cliente:
                        guardar_presupuesto_nube(cliente, tipo_modulo, precio_final)
                    else:
                        st.warning("Ingresa el nombre del Cliente.")

            if not df_corte.empty:
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
                    guardar_presupuesto_nube(cliente, f"Obra ({len(st.session_state['obra_modulos'])} modulos)", total_obra)
                else:
                    st.warning("Ingresa el nombre del Cliente arriba.")

    except Exception as e:
        st.error(f"Error en el Cotizador: {e}")

elif menu == "Historial de Ventas":
    st.title("Gestion y Seguimiento de Ventas")
    try:
        df_hist = traer_datos_historial()
        if not df_hist.empty:
            st.subheader("Monitor de Reposicion e Inflacion")
            inflacion_estimada = 0.15
            for index, row in df_hist.iterrows():
                precio_original = row['precio_final']
                precio_reposicion = precio_original * (1 + inflacion_estimada)
                if row['estado'] == 'Pendiente':
                    col1, col2, col3 = st.columns([2, 1, 1])
                    col1.write(f"**{row['mueble']}** (Cliente: {row.get('cliente', 'N/A')})")
                    col2.write(f"Venta: ${precio_original:,.0f}")
                    st.warning(f"Valor de reposicion hoy: ${precio_reposicion:,.0f}. Actualizar +15% antes de cobrar senas.")
            st.write("---")
            st.subheader("Balance General")
            st.data_editor(df_hist, use_container_width=True)
    except Exception as e:
        st.error(f"Error en el monitor: {e}")

elif menu == "Deposito de Retazos":
    st.title("Gestion de Sobrantes (Estandar BVM)")
    st.info("Carga aqui los recortes del taller para que el sistema los use automaticamente.")

    with st.expander("Registrar Nuevo Retazo en Deposito", expanded=True):
        c_ret_mat, c_ret1, c_ret2 = st.columns([2, 1, 1])
        mat_r = c_ret_mat.selectbox("Material del sobrante", list(maderas.keys()))
        ancho_r = c_ret1.number_input("Ancho (mm)", value=0, key="anc_r_indep")
        largo_r = c_ret2.number_input("Largo (mm)", value=0, key="lar_r_indep")
        if st.button("Guardar en Inventario"):
            if (ancho_r >= 150 and largo_r >= 400) or (ancho_r >= 400 and largo_r >= 150):
                registrar_retazo(mat_r, largo_r, ancho_r)
                st.success(f"Retazo de {mat_r} guardado.")
            else:
                st.warning("El retazo es muy chico (minimo 150x400mm).")

    st.write("---")
    st.subheader("Stock Actual")
    retazos_db = consultar_retazos_disponibles("Todos")
    if retazos_db:
        df_inv = pd.DataFrame(retazos_db)
        st.dataframe(df_inv[["material", "largo", "ancho"]], use_container_width=True)
    else:
        st.info("El deposito esta vacio.")

elif menu == "Configuracion de Precios":
    st.title("Administracion de Insumos y Costos")

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
