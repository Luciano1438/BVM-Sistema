import streamlit as st
import pandas as pd
import sqlite3
import os
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv
from fpdf import FPDF
from datetime import datetime, timedelta, timezone
import urllib.parse

# --- PARÁMETROS TÉCNICOS DE TALLER ---
CONFIG_TECNICA = {
    "ranura_profundidad": 10.0,  # mm
    "ranura_distancia_borde": 10.0, # mm
    "retazo_min_ancho": 150,     # mm
    "retazo_min_largo": 400,     # mm
}

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

def calcular_medida_frente(ancho_hueco, alto_hueco, tipo_montaje="Superpuesto", es_doble=False):
    """
    Calcula la medida real de la placa para un frente.
    """
    if tipo_montaje == "Superpuesto":
        # Se deja 2mm menos en los 4 lados sobre la medida externa
        ancho_real = ancho_hueco - 4 
        alto_real = alto_hueco - 4
    else:  # Embutido
        # 3mm arriba, abajo y bisagra. 2mm en el encuentro si es doble.
        alto_real = alto_hueco - 6 # 3mm arriba + 3mm abajo
        if es_doble:
            ancho_real = ancho_hueco - 5 # 3mm bisagra + 2mm encuentro
        else:
            ancho_real = ancho_hueco - 6 # 3mm de cada lado
    return ancho_real, alto_real

def generar_pdf_presupuesto(datos):
    pdf = FPDF()
    pdf.add_page()
    
    # Diseño de Cabecera Profesional
    pdf.set_font("Arial", 'B', 20)
    pdf.set_text_color(46, 125, 50) # Verde BVM
    pdf.cell(200, 20, "PRESUPUESTO COMERCIAL - BVM", ln=True, align='C')
    
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", '', 10)
    tz_arg = timezone(timedelta(hours=-3))
    fecha_hoy = datetime.now(tz_arg).strftime('%d/%m/%Y')
    pdf.cell(200, 10, f"Fecha de emisión: {fecha_hoy}", ln=True, align='R')    

    # Cuerpo del Presupuesto
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "DETALLES DEL PROYECTO", ln=True)
    pdf.set_font("Arial", '', 11)
    
    # Información Clave Solicitada
    pdf.cell(0, 8, f"Cliente: {datos['cliente']}", ln=True)
    pdf.cell(0, 8, f"Proyecto: {datos['mueble']}", ln=True)
    pdf.cell(0, 8, f"Dimensiones Generales: {datos['ancho']} x {datos['alto']} x {datos['prof']} mm", ln=True)
    pdf.cell(0, 8, f"Material Principal: {datos['material']}", ln=True)
    pdf.ln(5)
    
   # generar_pdf_presupuesto y reemplazala:
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "CONDICIONES Y ENTREGA", ln=True)
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 8, f"Tiempo estimado de entrega: {datos['entrega']} días hábiles.", ln=True)
    
    # Calculamos la seña dinámicamente
    monto_seña = datos['precio'] * (datos['pct_seña'] / 100)
    pdf.cell(0, 8, f"Monto de Seña ({datos['pct_seña']}%): ${monto_seña:,.2f}", ln=True)

    # Precio Final Destacado
    pdf.set_font("Arial", 'B', 16)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 15, f"VALOR TOTAL: ${datos['precio']:,.2f}", ln=True, align='C', fill=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 9)
    pdf.multi_cell(0, 5, "Nota: Los precios están sujetos a cambios por volatilidad de insumos si no se abona la seña dentro de las 48hs.")

    return pdf.output(dest='S').encode('latin-1')    

# --- CONFIGURACIÓN DE RUTAS ---
BASE_DIR = Path(__file__).resolve().parent.parent 
load_dotenv(dotenv_path=BASE_DIR / '.env')

# --- CONEXIÓN SUPABASE ---
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
def consultar_retazos_disponibles(material):
    usuario_actual = st.session_state["user_data"]["usuario"]
    try:
        # Traemos todos los retazos de ese material
        res = supabase.table("retazos").select("*").eq("material", material).eq("usuario", usuario_actual).execute()
        return res.data
    except Exception as e:
        st.error(f"Error al consultar retazos: {e}")
        return []

def registrar_retazo(material, largo, ancho):
    usuario_actual = st.session_state["user_data"]["usuario"]
    try:
        # REGLA BVM: Validamos contra 150x400 (en cualquier sentido)

        if (largo >= 400 and ancho >= 150) or (largo >= 150 and ancho >= 400): 
            data = {"material": material, "largo": largo, "ancho": ancho, "usuario" : usuario_actual}
            supabase.table("retazos").insert(data).execute()
            st.toast(f"♻️ Retazo guardado: {int(largo)}x{int(ancho)}")
        else:
            # AHORA SÍ TE AVISA POR QUÉ NO GUARDA
            st.error(f"❌ Error: {int(largo)}x{int(ancho)} es inferior al mínimo de 150x400.")
    except Exception as e:
        st.error(f"Error técnico al registrar: {e}")

# --- 0. SEGURIDAD DE ACCESO MULTIUSUARIO (VALOR PRO) ---
def verificar_password():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False

    if not st.session_state["autenticado"]:
        with st.sidebar:
            st.title("🔐 Acceso BVM Pro")
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            
            if st.button("Ingresar"):
                try:
                    # Consultamos si el usuario existe y la password coincide
                    res = supabase.table("usuarios").select("*").eq("usuario", user_input).eq("password", pass_input).execute()
                    
                    if len(res.data) > 0:
                        st.session_state["autenticado"] = True
                        st.session_state["user_data"] = res.data[0] # Guardamos info del usuario
                        st.success(f"Bienvenido, {res.data[0]['usuario']}")
                        st.rerun()
                    else:
                        st.error("Credenciales incorrectas o usuario inexistente.")
                except Exception as e:
                    st.error(f"Error de conexión: {e}")
        return False
    return True
# --- 1. MOTOR DE INTELIGENCIA DE NEGOCIO (BVM PRO) ---
def traer_datos():
    usuario_actual = st.session_state["user_data"]["usuario"]
    try:
        res = supabase.table("configuracion").select("*").eq("usuario", usuario_actual).execute()
        datos_db = res.data        
        
        # 2. Mapeamos los datos de la DB a los diccionarios del sistema
        maderas = {d['clave']: d['valor'] for d in datos_db if d['categoria'] == 'maderas'}
        config = {d['clave']: d['valor'] for d in datos_db if d['categoria'] in ['costos', 'margen', 'herrajes']}
        
        # 3. Mantenemos los fondos como respaldo o podés agregarlos a la DB también
        fondos = {
            'Fibroplus Blanco 3mm': 34500.0,
            'Faplac Fondo 5.5mm': 45000.0
        }
        
        # Inyectamos el factor de ajuste (opcional, para cambios rápidos)
        factor_ajuste = st.sidebar.number_input("Ajuste Rápido Inflación (%)", value=0.0, step=1.0) / 100
        if factor_ajuste != 0:
            maderas = {k: v * (1 + factor_ajuste) for k, v in maderas.items()}
            
        return maderas, fondos, config
    except Exception as e:
        st.error(f"Error cargando configuración desde la nube: {e}")
        # Retorno de emergencia si falla la red
        return {}, {}, {}
def guardar_presupuesto_nube(cliente, mueble, total):
    usuario_actual = st.session_state["user_data"]["usuario"]
    try:
        data = {
            "cliente": cliente,
            "mueble": mueble,
            "precio_final": float(total),
            "estado": "Pendiente",
            "usuario": usuario_actual, # <-- ESTA ES LA FIRMA DE PROPIEDAD
            "fecha": datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M")
        }
        supabase.table("ventas").insert(data).execute()
        st.success(f"🚀 Venta blindada para {usuario_actual}")
    except Exception as e:
        st.error(f"Error al impactar nube: {e}")
def traer_datos_historial():
    usuario_actual = st.session_state["user_data"]["usuario"]
    try:
        response = supabase.table("ventas").select("*").eq("usuario", usuario_actual).execute()
        return pd.DataFrame(response.data)
    except:
        return pd.DataFrame()
# --- 2. CONECTIVIDAD LOCAL (Mantenida para guardar localmente) ---
def ejecutar_query(query, params=(), fetch=False):
    db_path = BASE_DIR / 'data' / 'carpinteria.db'
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch: return cursor.fetchall()
        conn.commit()
import urllib.parse

def generar_link_whatsapp(datos):
    # Formato limpio y profesional sin caracteres especiales
    lineas = [
        f"*PRESUPUESTO BVM - {datos['mueble'].upper()}*",
        "",
        "Hola! Te envio los detalles de la cotización:",
        "",
        f"Medidas: {datos['ancho']}x{datos['alto']}x{datos['prof']} mm",
        f"Material: {datos['material']}",
        f"Entrega: {datos['entrega']} dias habiles",
        "",
        f"VALOR TOTAL: ${datos['precio']:,.2f}",
        f"SEÑA REQUERIDA ({datos['pct_seña']}%): ${datos['precio'] * (datos['pct_seña']/100):,.2f}",
        "",
        "Nota: Los precios se mantienen por 48hs. Una vez abonada la seña, se congelan los materiales y comienza la producción."
    ]

    # Unimos con saltos de línea
    mensaje_final = "\n".join(lineas)
    
    # Codificamos solo el texto plano
    texto_url = urllib.parse.quote(mensaje_final)
    return f"https://wa.me/?text={texto_url}"

# --- 3. INTERFAZ Y LÓGICA (INTACTA) ---
st.set_page_config(page_title="BVM - Gestión materiales", layout="wide")
if not verificar_password():
    st.info("Por favor, ingrese sus credenciales para operar el sistema.")
    st.stop()

maderas, fondos, config = traer_datos()
# --- ACTUALIZACIÓN DE MENÚ (VALOR PRO) ---
menu = st.sidebar.radio("Navegación", ["Cotizador CNC", "Historial de Ventas", "⚙️ Configuración de Precios"])
# --- AGREGAR ESTO EN LA SIDEBAR (O EN LA PESTAÑA DE AJUSTES) ---


# --- BOTÓN DE CIERRE DE SESIÓN ---
st.sidebar.write("---")
if st.sidebar.button("🚪 Cerrar Sesión"):
    # Limpiamos todo el estado de la sesión para forzar el re-login
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
if menu == "Cotizador CNC":
    try:
        st.title("🏭 BVM | Control de Producción Industrial")
        # --- DASHBOARD DE CONTROL ---
        st.write("---")
        # Calculamos la rentabilidad proyectada (usamos valores base si no hay datos)
        # Esto le da el look de "Terminal de Inversión"
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("📦 Piezas Totales", f"{len(df_corte) if 'df_corte' in locals() else 0}")
        with m2:
            st.metric("🪵 Consumo Placa", f"{m2_18mm:.2f} m²" if 'm2_18mm' in locals() else "0.0 m²")
        with m3:
            st.metric("📈 Margen Bruto", f"{config['ganancia_taller_pct']*100:.0f}%")
        with m4:
            color_precio = "normal" if 'precio_final' in locals() else "off"
            st.metric("💵 Cotización", f"${precio_final:,.0f}" if 'precio_final' in locals() else "$0", delta_color=color_precio)
        st.write("---")
        col_in, col_out = st.columns([1, 1.2])

        with col_in:
            # Agrupamos los datos básicos en un contenedor expandible
            with st.expander("🛠️ 1. Definición de Estructura", expanded=True):
                cliente = st.text_input("Cliente", "")
                mueble_nom = st.text_input("Mueble", "")
                
                c1, c2, c3 = st.columns(3)
                ancho_m = c1.number_input("Ancho Total (mm)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
                alto_m = c2.number_input("Alto Total (mm)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
                prof_m = c3.number_input("Profundo (mm)", min_value=0.0, max_value=2000.0, value=0.0, step=0.5)
                altura_travesano = st.number_input("Altura Travesaño Trasero (mm)", value=100.0, key="travesano_base")
                
                mat_principal = st.selectbox("Material Cuerpo (18mm)", list(maderas.keys()))
                tiene_veta = st.toggle("💎 El material tiene veta (Respetar orientación)", value=True)
                esp_real = st.number_input("Espesor Real Placa (mm)", min_value=1.0, max_value=50.0, value=18.0, step=0.1)
                mat_fondo_sel = st.selectbox("Material Fondo", list(fondos.keys()))

            # Agrupamos los módulos en otro contenedor
            with st.expander("🏗️ 2. Configuración de Módulos", expanded=False):
                # Configuración de Herrajes
                tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "Especial"])
                precio_bisagra = config['bisagra_cazoleta']
                tipo_corredera = st.radio("Tipo de Corredera", ["Telescópica 45cm", "Cierre Suave Pesada"])
                precio_guia = config['telescopica_45'] if "45cm" in tipo_corredera else config['telescopica_soft']
                
                c_caj, c_hue = st.columns(2)
                cant_cajones = c_caj.number_input("Cant. Cajones", value=0, min_value=0)
                tipo_tapa = "Superpuesta" 
                alto_frentin_emb = 0.0
                if tipo_tapa == "Tapa Embutida":
                    alto_frentin_emb = st.number_input("Altura del Frentín Superior (mm)", value=30.0)
                
                opciones_estilo = ["Superpuesta", "Embutida"]

                if cant_cajones > 0:
                # 2. Si hay 3 cajones, le sumamos el Gola
                   if cant_cajones == 3:
                       opciones_estilo.append("Gola")
                
                # 3. Usamos la lista en el radio
                tipo_tapa = st.radio("Estilo de Tapa", opciones_estilo)
                st.markdown(f"#### 📏 Parámetros del Cajón ({tipo_tapa})")
                col_l1, col_l2 = st.columns(2)
                luz_entre_tapas = col_l1.number_input("Luz entre tapas (mm)", value=3.0)
    
                # Si es Tipo 1 pide luz de ancho, si es Tipo 2 pide el frentín de tu viejo
                if tipo_tapa == "Superpuesta":
                    luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=4.0)
                elif tipo_tapa == "Embutida": 
                    alto_frentin_emb = col_l2.number_input("Altura Frentín Superior (mm)", value=30.0)
                    luz_perimetral_tapa = 6.0 # Valor fijo por fórmula para Tipo 2
                else: # GOLA
                    luz_perimetral_tapa = col_l2.number_input("Luz total ancho (mm)", value=4.0)
                    alto_frentin_emb = 0.0
                
                distribucion_tapas = col_l1.radio("Distribución", ["Iguales", "Proporcional (20/35/45)"])

                col_c1, col_c2 = st.columns(2)
                esp_corredera = col_c1.number_input("Espesor de Corredera (mm)", value=13.0)
                aire_trasero = col_c2.number_input("Espacio libre trasero (mm)", value=30.0)
            # --- SECCIÓN 3: INTERIORES Y SIMETRÍA ---
            with st.expander("⚖️ 3. Parante, Estantes y Simetría", expanded=False):
                tiene_parante = st.checkbox("¿Lleva parante divisor?", value=False)
                distancia_parante = 0.0
                
                if tiene_parante:
                    max_pos = float(ancho_m - (esp_real * 2)) if ancho_m > (esp_real * 2) else 0.0
                    distancia_parante = st.number_input(
                        "Distancia Parante desde borde IZQ interno (mm)", 
                        min_value=0.0, 
                        max_value=max_pos, 
                        value=ancho_hueco_cajon if ancho_hueco_cajon > 0 else (max_pos / 2),
                        step=0.5
                    )
                
                c_pue, c_est = st.columns(2)
                cant_puertas = c_pue.number_input("Cant. Puertas", value=0, min_value=0, key="cant_pue_p")
                cant_estantes = c_est.number_input("Cant. Estantes", value=0, min_value=0, key="cant_est_p")
                
                # Inteligencia de Simetría BVM (Cálculo Automático)
                if cant_puertas > 0 and ancho_m > 0:
                    esp_parante_din = esp_real if tiene_parante else 0
                    ancho_disp_p = ancho_m - (esp_real * 2) - ancho_hueco_cajon - esp_parante_din
                    total_luces = (luz_e * 2) + (luz_i * (cant_puertas - 1))
                    ancho_sugerido = (ancho_disp_p - total_luces) / cant_puertas
                    st.info(f"💡 Simetría BVM (Espesor {esp_real}mm): {ancho_sugerido:.1f} mm c/u")

                medidas_puertas = [st.number_input(f"Ancho Puerta {i+1} (mm)", value=0.0, key=f"pue_{i}", step=0.5) for i in range(int(cant_puertas))]
                medidas_estantes = [st.number_input(f"Ancho Estante {i+1} (mm)", value=0.0, key=f"est_{i}", step=0.5) for i in range(int(cant_estantes))]
                
                st.write("---")
                cant_travesaños = st.number_input("Cantidad de Travesaños", value=0, min_value=0)
                medidas_travesaños = []
                for i in range(int(cant_travesaños)):
                    ct1, ct2 = st.columns(2)
                    l_sug = float(ancho_m - (esp_real * 2) if ancho_m > (esp_real * 2) else 0)
                    l_t = ct1.number_input(f"Largo Travesaño {i+1}", value=l_sug, key=f"lt_{i}", step=0.5)
                    a_t = ct2.number_input(f"Ancho Travesaño {i+1}", value=100.0, key=f"at_{i}", step=0.5)
                    medidas_travesaños.append({"L": l_t, "A": a_t})

            # --- SECCIÓN 4: PARÁMETROS FINANCIEROS Y ENVÍO ---
            with st.expander("💰 4. Soporte y Logística", expanded=False):
                tipo_base = st.selectbox("Tipo de Soporte", ["Zócalo de Madera", "Banquina", "Patas Plásticas", "Nada"])
                costo_base = 5000 if tipo_base == "Patas Plásticas" else 0
                altura_base = st.number_input("Altura de Base/Zócalo (mm)", min_value=0.0, value=100.0, step=5.0)
                
                if tipo_base == "Zócalo de Madera":
                    st.caption("💡 El sistema sumará las piezas de zócalo al despiece.")
                elif tipo_base == "Banquina":
                    st.info(f"⚠️ El mueble apoyará sobre base de {altura_base}mm. Ajustando laterales.")
                
                dias_prod = st.number_input("Días de taller", value=0.0, step=0.5)
                necesita_colocacion = st.checkbox("¿Requiere Colocación?")
                flete_sel = st.selectbox("Zona Envío", ["Ninguno", "Capital", "Zona Norte"])
                dias_col = st.number_input("Días de obra", value=0) if necesita_colocacion else 0
        with col_out:
            st.subheader("📐 Planilla de Corte e Inteligencia de Materiales")
            
                # --- A. CONFIGURACIÓN DE PRECISIÓN ---
            c_prec1, c_prec2 = st.columns(2)                
            def crear_pieza(nombre, cant, largo, ancho):
               
                return {"Pieza": nombre, "Cant": cant, "L": round(l_f, 1), "A": round(a_f, 1)}
        if alto_m > 0 and ancho_m > 0:
            despiece = []   
             # --- LÓGICA DE ESTRUCTURA REAL BVM CON CANTEADO ---
            altura_caja_real = alto_m
            if tipo_base in ["Banquina de Obra", "Patas Plásticas"]:
                altura_caja_real = alto_m - altura_base
                # --- LÓGICA DE ESTRUCTURA REAL BVM (TIPO 1) ---

            # 1. BASE (Piso): Ancho total y profundidad total
            despiece.append(crear_pieza("Base Módulo", 1, ancho_m, prof_m))

            # 2. LATERALES: (Altura - 1 espesor) y profundidad total
            # Apoyan sobre la base, por eso descontamos solo 1 espesor real
            altura_lateral_bvm = alto_m - esp_real
            despiece.append(crear_pieza("Lateral Exterior", 2, altura_lateral_bvm, prof_m))

            # 3. TRAVESAÑO TRASERO Y FRENTÍN (Horizontales)
            # Ambos van entre laterales, por eso descuentan (esp_real * 2)
            ancho_hueco_interno = ancho_m - (esp_real * 2)
            # Hacemos que ambos nombres valgan lo mismo para que no de error
            ancho_interno_total = ancho_hueco_interno
            despiece.append(crear_pieza("Travesaño Trasero", 1, ancho_hueco_interno, altura_travesano))
            despiece.append(crear_pieza("Frentín Frontal", 1, ancho_hueco_interno, 50))

            # 4. FONDO DEL MUEBLE: -20mm en ambos lados
            despiece.append({
                "Pieza": "Fondo Mueble", 
                "Cant": 1, 
                "L": alto_m - 20, 
                "A": ancho_m - 20, 
                "Veta": "Vertical", 
                "Tipo": "Fondo"
            })
                        
                # 3. ZÓCALOS DE MADERA: Si existen, llevan canto al frente
            if tipo_base == "Zócalo de Madera":
                despiece.append(crear_pieza("Zócalo Frontal", 2, altura_base, ancho_interno_total))
                despiece.append(crear_pieza("Zócalo Lateral", 2, altura_base, prof_m - 50))
                
                # 4. PARANTE DIVISOR: Altura interna y canto al frente
            if tiene_parante:
                altura_interna = altura_caja_real - (esp_real * 2)
                despiece.append(crear_pieza("Parante Divisor", 1, altura_interna, prof_m - 20))
                    
                hueco_izq = distancia_parante
                hueco_der = ancho_interno_total - distancia_parante - esp_real
                st.info(f"📏 Luz Interna Izquierda: {hueco_izq:.1f}mm")
                st.info(f"📏 Luz Interna Derecha: {hueco_der:.1f}mm")

                # 5. ESTANTES: Respetan el canteado frontal
            for i, e_ancho in enumerate(medidas_estantes):
                if e_ancho > 0: 
                    despiece.append(crear_pieza(f"Estante {i+1}", 1, e_ancho, prof_m - 20))
                
                # 6. TRAVESAÑOS: Respetan el canteado frontal
            for i, trav in enumerate(medidas_travesaños):
                if trav['L'] > 0: 
                    despiece.append(crear_pieza(f"Travesaño {i+1}", 1, trav['L'], trav['A']))
                # 2. Frentes (Puertas y Cajones con Altura de Caja Real)
            if cant_puertas > 0:
                w_pue, h_pue = calcular_medida_frente(ancho_sugerido, altura_caja_real, "Superpuesto")
                if usa_gola: h_pue -= 20 
                for i in range(int(cant_puertas)):
                    despiece.append(crear_pieza(f"Puerta {i+1}", 1, h_pue, w_pue))

            if cant_cajones > 0:
                # Si es TIPO 1 (Superpuesta), mantenés tus fórmulas originales:
                if "Superpuesta" in tipo_tapa:
                    espacio_util_total = alto_m - 30 - ((cant_cajones - 1) * luz_entre_tapas)
                    ancho_tapa_bvm = ancho_m - luz_perimetral_tapa
                    largo_lateral_caja = prof_m - aire_trasero # Tu fórmula de siempre
                
                # Si es TIPO 2 (Embutida),
                elif tipo_tapa == "Embutida":
                    # Altura: Fórmula de tu viejo
                    espacio_util_total = alto_m - alto_frentin_emb - esp_real - ((cant_cajones + 1) * luz_entre_tapas)
                    ancho_tapa_bvm = ancho_interno_total - 6
                    largo_lateral_caja = prof_m - 30 - esp_real
                else:
                    # Tu fórmula: (Alto - 60 - luces) / 3
                    espacio_util_total = alto_m - 60 - ((cant_cajones - 1) * luz_entre_tapas)
                    ancho_tapa_bvm = ancho_m - luz_perimetral_tapa
                    largo_lateral_caja = prof_m - aire_trasero
                    
                    # AGREGAMOS LAS 4 PIEZAS DE LA "L" ESTRUCTURAL
                    # Van entre laterales, por eso usamos 'ancho_interno_total'
                    despiece.append(crear_pieza("Frentín Gola L (A)", 2, 40, ancho_interno_total))
                    despiece.append(crear_pieza("Frentín Gola L (B)", 2, 50, ancho_interno_total))

                # 2. Lógica de Alturas (Simétrica o Proporcional)
                alturas_tapas = []
                if distribucion_tapas == "Proporcional (20/35/45)" and cant_cajones == 3:
                    alturas_tapas = [
                        espacio_util_total * 0.20, # Tapa Superior
                        espacio_util_total * 0.35, # Tapa Media
                        espacio_util_total * 0.45  # Tapa Inferior
                    ]
                else:
                    alto_igual = espacio_util_total / cant_cajones
                    alturas_tapas = [alto_igual] * int(cant_cajones)

                # 3. Generamos las Tapas en el despiece
                for i, alto_tapa in enumerate(alturas_tapas):
                    despiece.append(crear_pieza(f"Tapa de Cajon {i+1}", 1, alto_tapa, ancho_tapa_bvm))
                ancho_caja_total = ancho_interno_total - (esp_corredera * 2)
                    
                # Laterales de 150mm (2 por cajón)
                despiece.append(crear_pieza("Lateral Cajón", cant_cajones * 2, 150, largo_lateral_caja))
                    
                 # Frente/Fondo de la caja (Van entre laterales de la caja)
                ancho_frente_interno = ancho_caja_total - (esp_real * 2)
                despiece.append(crear_pieza("Frente/Fondo Interno", cant_cajones * 2, 150, ancho_frente_interno))
                    
               # --- PISO DEL CAJÓN (ANCHO CAJA - 20 Y PROF CAJA - 20) ---
                despiece.append({
                    "Pieza": "Piso Cajón", 
                    "Cant": int(cant_cajones), 
                    "L": round(largo_lateral_caja - 20, 1), 
                    "A": round(ancho_caja_total - 20, 1), 
                    "Veta": "Horizontal", 
                    "Tipo": "Piso"
                            })
            
            # --- MOSTRAR RESULTADOS FINAL TIPO 1 ---
            df_corte = pd.DataFrame(despiece)
            st.data_editor(df_corte, use_container_width=True, hide_index=True)

                # 
                # --- B. CÁLCULO DE COSTOS CON REFILADO Y MAQUINARIA ---                
            m2_18mm = ((df_corte[df_corte.get('Tipo') != 'Fondo']['L']) * (df_corte['A']) * df_corte['Cant']).sum() / 1_000_000
            m2_fondo = (df_corte[df_corte.get('Tipo') == 'Fondo']['L'] * df_corte['A'] * df_corte['Cant']).sum() / 1_000_000

           
            if flete_sel == "Capital": costo_flete = config['flete_capital']
            elif flete_sel == "Zona Norte": costo_flete = config['flete_norte']
                
            costo_operativo = (dias_prod * config['gastos_fijos_diarios'])
            total_costo = costo_madera + costo_fondo + costo_herrajes + costo_operativo + costo_base + costo_flete
            if necesita_colocacion: total_costo += (dias_col * config['colocacion_dia'])

                # --- C. RETAZOS Y PRECIO FINAL (Igual que antes) ---
            st.write("---")
               # --- C. TU LÓGICA DE RETAZOS (REGLA EXPERTA: 150x400) ---
            st.write("---")
            retazos_en_stock = consultar_retazos_disponibles(mat_principal)
            ahorro_madera = 0
                
            if retazos_en_stock:
                st.subheader("♻️ Oportunidades de Ahorro")
                piezas_que_encajan = 0
                for ret in retazos_en_stock:
                        # AJUSTE SEGÚN TU VIEJO: Mínimo 150x400
                        # Verificamos si el retazo sirve (en cualquier orientación)
                    if (ret['largo'] >= 400 and ret['ancho'] >= 150) or \
                        (ret['largo'] >= 150 and ret['ancho'] >= 400):
                            
                        for index, row in df_corte.iterrows():
                            if (ret['largo'] >= row['L'] and ret['ancho'] >= row['A']) or \
                                (ret['largo'] >= row['A'] and ret['ancho'] >= row['L']):
                                    
                                piezas_que_encajan += 1
                                m2_p = (row['L'] * row['A']) / 1_000_000
                                ahorro_madera += (m2_p * maderas[mat_principal] / 5.03)
                                st.success(f"¡Match! '{row['Pieza']}' entra en Retazo ID-{ret['id']}")
                                break

                total_costo_real = total_costo - ahorro_madera
                utilidad = total_costo_real * config['ganancia_taller_pct']
                precio_final = total_costo_real + utilidad

                c1, c2, c3 = st.columns(3)
                c1.metric("Costo Real", f"${total_costo_real:,.0f}")
                c2.metric("M2 Placa", f"{m2_18mm:.2f}")
                c3.metric("Precio Final", f"${precio_final:,.2f}")
            
                # 5. --- ANÁLISIS FINANCIERO VISUAL (VALOR PRO) ---
                st.write("---")
                st.subheader("📊 Desglose de Inversión y Rentabilidad")
                
                # Preparamos los datos para el gráfico
                datos_grafico = {
                    "Categoría": ["Madera/Fondo", "Herrajes", "Operativo/Taller", "Logística/Flete", "Ganancia Neta"],
                    "Monto": [costo_madera + costo_fondo, costo_herrajes, costo_operativo + costo_base, costo_flete, utilidad]
                }
                df_grafico = pd.DataFrame(datos_grafico)
                
                # Mostramos un gráfico de barras horizontal para comparar pesos
                st.bar_chart(data=df_grafico, x="Categoría", y="Monto", color="#2e7d32")

                # Alerta de Rentabilidad Estilo Burry
                pct_utilidad_real = (utilidad / precio_final) * 100
                if pct_utilidad_real < 12:
                    st.error(f"⚠️ ALERTA DE MARGEN: La rentabilidad es del {pct_utilidad_real:.1f}%. Revisar costos fijos.")
                else:
                    st.success(f"✅ OPERACIÓN RENTABLE: Margen del {pct_utilidad_real:.1f}%")
                st.subheader(f"PRECIO FINAL: ${precio_final:,.2f}")

            # --- 1. GESTIÓN DE GUARDADO (ADMINISTRACIÓN) ---
                st.write("---")
                c_save1, c_save2 = st.columns(2)
                with c_save1:
                    if st.button("💾 Guardar Local"):
                        ejecutar_query("INSERT INTO ventas (mueble, precio_final, estado) VALUES (?, ?, ?)", (mueble_nom, precio_final, "Pendiente"))
                        st.success("Guardado Local.")
                with c_save2:
                    if st.button("💾 Guardar en Nube"):
                        guardar_presupuesto_nube(cliente, mueble_nom, precio_final)

               # --- 2. GESTIÓN DE INVENTARIO (RETAZOS CORREGIDO A 150x400) ---
                with st.expander("➕ Registrar Nuevo Retazo en Depósito"):
                    st.write("Cargá sobrantes útiles (>150x400mm) para que el sistema los detecte.")
                    c_ret1, c_ret2 = st.columns(2)
                    ancho_r = c_ret1.number_input("Ancho (mm)", value=0, key="anc_r")
                    largo_r = c_ret2.number_input("Largo (mm)", value=0, key="lar_r")
    
                    if st.button("💾 Guardar en Inventario de Retazos"):
                        # Aplicamos la Regla de Oro de tu viejo: 150x400
                        if (ancho_r >= 150 and largo_r >= 400) or (ancho_r >= 400 and largo_r >= 150):
                            registrar_retazo(mat_principal, largo_r, ancho_r)
                        else:
                            st.warning("El retazo es muy chico para ser útil (mínimo 150x400mm según estándar BVM).")
               # --- 3. GESTIÓN COMERCIAL (PDF PRO) ---
                st.write("---")
                st.subheader("📄 Generar Propuesta para Cliente")
                
                c_com1, c_com2 = st.columns(2)
                with c_com1:
                    dias_entrega = st.number_input("Días de entrega", value=15, step=1)
                with c_com2:
                    pct_seña = st.slider("% de Seña", 0, 100, 50, 5) # Default 50%, saltos de 5%
                
                # Preparamos el paquete de datos para el PDF (incluimos el % de seña)
                datos_pdf = {
                    'cliente': cliente, 'mueble': mueble_nom, 
                    'precio': precio_final, 'material': mat_principal,
                    'ancho': ancho_m, 'alto': alto_m, 'prof': prof_m,
                    'entrega': dias_entrega,
                    'pct_seña': pct_seña
                }
                
                pdf_bytes = generar_pdf_presupuesto(datos_pdf)
                link_wa = generar_link_whatsapp(datos_pdf)

                # 2. Después dibujamos los botones (Interfaz)
                st.download_button(
                    label="📥 Descargar Presupuesto Profesional",
                    data=pdf_bytes,
                    file_name=f"Presupuesto_{cliente}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                
                st.link_button("🟢 Enviar Presupuesto por WhatsApp", link_wa, use_container_width=True)
            
                # 6. --- GENERACIÓN DE ETIQUETAS (VALOR PRO) ---
                st.write("---") # Una línea divisoria para separar administración de taller
                if st.button("🖨️ Generar Etiquetas de Taller"):
                    st.info(f"Generando etiquetas para las {len(df_corte)} piezas...")
                    # Creamos una cuadrícula para que las etiquetas no ocupen toda la pantalla hacia abajo
                    cols_etiquetas = st.columns(2) 
                    for index, row in df_corte.iterrows():
                        with cols_etiquetas[index % 2]: # Esto las ordena en 2 columnas visuales
                            with st.expander(f"📍 {row['Pieza']} ({int(row['L'])}x{int(row['A'])})"):
                                st.write(f"**Cliente:** {cliente}")
                                st.write(f"**Mueble:** {mueble_nom}")
                                st.code(f"PIEZA N°: {index+1}\nDIM: {int(row['L'])} x {int(row['A'])} mm")
                                st.caption("📋 Lados a tapacantear: Largos.")
            # --- CIERRE DEL COTIZADOR CNC ---
            else:
                st.warning("Ingrese dimensiones.")

    except Exception as e:
        st.error(f"Error en el Cotizador: {e}")

elif menu == "Historial de Ventas":
    st.title("📊 Gestión y Seguimiento de Ventas")
    try:
        df_hist = traer_datos_historial()
        if not df_hist.empty:
            # --- LÓGICA DE AUDITORÍA DE PRECIOS (EL ESCUDO) ---
            st.subheader("⚠️ Monitor de Reposición e Inflación")
            
            # Simulamos un aumento del 15% en materiales desde que se guardó (ajustable)
            inflacion_estimada = 0.15 
            
            for index, row in df_hist.iterrows():
                precio_original = row['precio_final']
                precio_reposicion = precio_original * (1 + inflacion_estimada)
                
                if row['estado'] == 'Pendiente':
                    col1, col2, col3 = st.columns([2, 1, 1])
                    col1.write(f"**{row['mueble']}** (Cliente: {row.get('cliente', 'N/A')})")
                    col2.write(f"Venta: ${precio_original:,.0f}")
                    
                    # Alerta si el presupuesto quedó viejo
                    st.warning(f"🚨 Valor de reposición hoy: ${precio_reposicion:,.0f}. Sugerencia: Actualizar +15% antes de cobrar señas.")
            
            st.write("---")
            st.subheader("📈 Balance General")
            st.data_editor(df_hist, use_container_width=True)
            
    except Exception as e:
        st.error(f"Error en el monitor: {e}")

# --- PESTAÑA: CONFIGURACIÓN DE PRECIOS (VALOR PRO) ---
elif menu == "⚙️ Configuración de Precios":
    st.title("⚙️ Administración de Insumos y Costos")
    st.info("Desde aquí podés actualizar los valores base. Los cambios impactarán en todos los nuevos presupuestos.")

    with st.expander("🪵 Precios de Placas (18mm)"):
        for madera, precio in maderas.items():
            maderas[madera] = st.number_input(f"Precio {madera}", value=float(precio), step=1000.0)

    with st.expander("🛠️ Herrajes y Accesorios"):
        c1, c2 = st.columns(2)
        config['bisagra_cazoleta'] = c1.number_input("Precio Bisagra Cazoleta", value=float(config['bisagra_cazoleta']), step=100.0)
        config['telescopica_45'] = c2.number_input("Precio Guía Telescópica 45cm", value=float(config['telescopica_45']), step=100.0)
        config['telescopica_soft'] = c1.number_input("Precio Guía Cierre Suave", value=float(config['telescopica_soft']), step=100.0)

    with st.expander("🚛 Gastos Fijos y Logística"):
        f1, f2 = st.columns(2)
        config['gastos_fijos_diarios'] = f1.number_input("Gasto Diario Taller", value=float(config['gastos_fijos_diarios']), step=5000.0)
        config['flete_capital'] = f2.number_input("Flete Capital", value=float(config['flete_capital']), step=1000.0)
        config['flete_norte'] = f1.number_input("Flete Zona Norte", value=float(config['flete_norte']), step=1000.0)
        config['colocacion_dia'] = f2.number_input("Costo Día de Colocación", value=float(config['colocacion_dia']), step=5000.0)

    with st.expander("💰 Margen de Ganancia"):
        config['ganancia_taller_pct'] = st.slider("Porcentaje de Utilidad Bruta", 0.0, 1.0, float(config['ganancia_taller_pct']), 0.05)
        st.write(f"Margen actual: {config['ganancia_taller_pct']*100}%")
    with st.expander("📐 Estándares de Taller (Luces y Holguras)"):
        st.info("Configurá las reglas que BVM aplicará a todos tus despieces automáticamente.")
        c_tec1, c_tec2 = st.columns(2)
        
        # Leemos de 'config' (que ya traes de Supabase) o ponemos el default técnico
        luz_f = c_tec1.number_input("Luz Perimetral Frentes (mm)", 
                                   value=float(config.get('luz_frente', 2.0)), step=0.5)
        luz_e = c_tec2.number_input("Luz entre Puertas/Cajones (mm)", 
                                   value=float(config.get('luz_entre', 3.0)), step=0.5)
        desc_f = c_tec1.number_input("Descuento Fondo vs Vano (mm)", 
                                    value=float(config.get('desc_fondo', 5.0)), step=1.0)
        
        # Actualizamos el diccionario para que el despiece lo tome en tiempo real
        config['luz_frente'] = luz_f
        config['luz_entre'] = luz_e
        config['desc_fondo'] = desc_f
    if st.button("💾 Guardar Precios Permanentemente"):
        # 1. Guardamos las maderas (lo que ya tenés)
        for madera, precio in maderas.items():
            actualizar_precio_nube(madera, precio)
        
        # 2. AGREGADO: Guardamos los costos operativos y márgenes
        # Asegurate de que estas 'claves' existan tal cual en tu tabla de Supabase
        actualizar_precio_nube('gastos_fijos_diarios', config['gastos_fijos_diarios'])
        actualizar_precio_nube('ganancia_taller_pct', config['ganancia_taller_pct'])
        actualizar_precio_nube('flete_capital', config['flete_capital'])
        actualizar_precio_nube('flete_norte', config['flete_norte'])
        actualizar_precio_nube('colocacion_dia', config['colocacion_dia'])
        
        st.success("Configuración blindada en Supabase para todos los parámetros.")
        # --- PESTAÑA: ADMINISTRACIÓN DE LICENCIAS (SOLO ADMIN) ---
# --- PESTAÑA: ADMINISTRACIÓN DE LICENCIAS (SOLO ADMIN) ---
if menu == "⚙️ Configuración de Precios" and st.session_state["user_data"]["usuario"] == "bvm_admin":
    st.write("---")
    st.header("👤 Panel de Control de Licencias")
    st.info("Desde aquí podés crear nuevas cuentas para otros carpinteros.")
    
    with st.expander("🆕 Registrar Nuevo Cliente SaaS"):
        c1, c2 = st.columns(2)
        nuevo_user = c1.text_input("Usuario (ej: pepe_muebles)")
        nueva_pass = c2.text_input("Contraseña Inicial", type="password")
        nom_carpinteria = st.text_input("Nombre del Negocio")
        
        if st.button("🚀 Activar Licencia"):
            if nuevo_user and nueva_pass:
                try:
                    # 1. Creamos el usuario alineado a tu tabla de Supabase
                    data_user = {
                        "usuario": nuevo_user, 
                        "password": nueva_pass, 
                        "nombre_carpinteria": nom_carpinteria, # <-- Corregido según image_add0a8
                        "role": "cliente"                      # <-- Corregido según image_add0a8
                    }
                    supabase.table("usuarios").insert(data_user).execute()
                    
                    # 2. SEED: Cargamos los precios base para el nuevo cliente
                    precios_base = []
                    # Costos, herrajes y márgenes
                    for k, v in config.items():
                        precios_base.append({
                            "usuario": nuevo_user, 
                            "clave": k, 
                            "valor": v, 
                            "categoria": "costos"
                        })
                    
                    # Precios de maderas (18mm)
                    for m, p in maderas.items():
                        precios_base.append({
                            "usuario": nuevo_user, 
                            "clave": m, 
                            "valor": p, 
                            "categoria": "maderas"
                        })
                    
                    # Impactamos la tabla configuracion en la nube
                    supabase.table("configuracion").insert(precios_base).execute()
                    
                    st.success(f"✅ Licencia activada para {nuevo_user}. Ya puede loguearse.")
                    st.balloons() # Festejá tu primera venta del SaaS
                except Exception as e:
                    st.error(f"Error al crear cuenta: {e}")
            else:
                st.warning("Completá usuario y contraseña para continuar.")



















































































































