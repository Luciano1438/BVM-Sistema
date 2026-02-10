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

# --- FUNCIONES DE BASE DE DATOS (FUERA DEL IF/ELSE) ---
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
        if largo >= 300 and ancho >= 300: 
            data = {"material": material, "largo": largo, "ancho": ancho, "usuario" : usuario_actual}
            supabase.table("retazos").insert(data).execute()
            st.toast(f"♻️ Retazo de {material} ({int(largo)}x{int(ancho)}) guardado")
    except Exception as e:
        st.error(f"Error al registrar retazo: {e}")
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
        # 1. Consultamos la nueva tabla de configuración
        res = supabase.table("configuracion").select("*").execute()
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

import urllib.parse

def generar_link_whatsapp(datos):
    # Usamos Unicodes para asegurar que CUALQUIER celular los vea bien
    # \u2b50 = estrella, \U0001f4cf = regla, \U0001f6a7 = madera/obra, \U0001f4b0 = bolsa dinero
    
    linea1 = f"*PRESUPUESTO BVM - {datos['mueble'].upper()}*"
    linea2 = "Hola! Te envío los detalles de la cotización:"
    linea3 = f"\U0001f4cf *Medidas:* {datos['ancho']}x{datos['alto']}x{datos['prof']} mm"
    linea4 = f"\U0001fab5 *Material:* {datos['material']}"
    linea5 = f"\u23f3 *Entrega:* {datos['entrega']} días hábiles"
    linea6 = f"\U0001f4b5 *VALOR TOTAL:* ${datos['precio']:,.2f}"
    linea7 = f"\U0001f4b4 *SEÑA REQUERIDA ({datos['pct_seña']}%):* ${datos['precio'] * (datos['pct_seña']/100):,.2f}"
    linea8 = "⚠️ _Nota: Los precios se mantienen por 48hs._"

    # Unimos todo con saltos de línea reales
    mensaje_final = f"{linea1}\n\n{linea2}\n\n{linea3}\n{linea4}\n{linea5}\n\n{linea6}\n{linea7}\n\n{linea8}"
    
    # Codificamos
    texto_url = urllib.parse.quote(mensaje_final)
    return f"https://wa.me/?text={texto_url}"
    
    return f"https://wa.me/?text={texto_url}"

# --- 3. INTERFAZ Y LÓGICA (INTACTA) ---
st.set_page_config(page_title="BVM - Gestión materiales", layout="wide")
if not verificar_password():
    st.info("Por favor, ingrese sus credenciales para operar el sistema.")
    st.stop()

maderas, fondos, config = traer_datos()
# --- ACTUALIZACIÓN DE MENÚ (VALOR PRO) ---
menu = st.sidebar.radio("Navegación", ["Cotizador CNC", "Historial de Ventas", "⚙️ Configuración de Precios"])
if menu == "Cotizador CNC":
    try:
        st.title("🏭 BVM | Control de Producción Industrial")
        col_in, col_out = st.columns([1, 1.2])

        with col_in:
            st.subheader("📋 Datos del Proyecto")
            cliente = st.text_input("Cliente", "")
            mueble_nom = st.text_input("Mueble", "")
            c1, c2, c3 = st.columns(3)
            ancho_m = c1.number_input("Ancho Total (mm)", min_value=0, value=0)
            alto_m = c2.number_input("Alto Total (mm)", min_value=0, value=0)
            prof_m = c3.number_input("Profundo (mm)", min_value=0, value=0)
            mat_principal = st.selectbox("Material Cuerpo (18mm)", list(maderas.keys()))
            mat_fondo_sel = st.selectbox("Material Fondo", list(fondos.keys()))
            
            st.write("---")
            st.subheader("🏗️ Configuración de Módulos")
            esp, luz_e, luz_i = 18, 2, 3
            tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "Especial"])
            precio_bisagra = config['bisagra_cazoleta']
            tipo_corredera = st.radio("Tipo de Corredera", ["Telescópica 45cm", "Cierre Suave Pesada"])
            precio_guia = config['telescopica_45'] if "45cm" in tipo_corredera else config['telescopica_soft']
            
            c_caj, c_hue = st.columns(2)
            cant_cajones = c_caj.number_input("Cant. Cajones", value=0, min_value=0)
            ancho_hueco_cajon = c_hue.number_input("Ancho Hueco Cajonera (mm)", value=0)
            tiene_parante = st.checkbox("¿Lleva parante divisor?", value=False) # Ahora arranca en False
            esp_parante = 18 if tiene_parante else 0
            
            if cant_cajones > 0:
                for i in range(int(cant_cajones)):
                    st.number_input(f"Altura Frente Cajón {i+1} (mm)", value=150, key=f"h_caj_{i}")

            c_pue, c_est = st.columns(2)
            cant_puertas = c_pue.number_input("Cant. Puertas", value=0, min_value=0, key="cant_pue_p")
            cant_estantes = c_est.number_input("Cant. Estantes", value=0, min_value=0, key="cant_est_p")

            # --- Lógica de Simetría Original Restaurada ---
            if cant_puertas > 0 and ancho_m > 0:
                ancho_disp_p = ancho_m - (esp * 2) - ancho_hueco_cajon - esp_parante
                total_luces = (luz_e * 2) + (luz_i * (cant_puertas - 1))
                ancho_sugerido = (ancho_disp_p - total_luces) / cant_puertas
                st.info(f"💡 Simetría BVM: {ancho_sugerido:.1f} mm c/u")

            medidas_puertas = [st.number_input(f"Ancho Puerta {i+1} (mm)", value=0, key=f"pue_{i}") for i in range(int(cant_puertas))]
            medidas_estantes = [st.number_input(f"Ancho Estante {i+1} (mm)", value=0, key=f"est_{i}") for i in range(int(cant_estantes))]
            
            cant_travesaños = st.number_input("Cantidad de Travesaños", value=0, min_value=0)
            medidas_travesaños = []
            for i in range(int(cant_travesaños)):
                ct1, ct2 = st.columns(2)
                l_t = ct1.number_input(f"Largo Travesaño {i+1}", value=int(ancho_m-36 if ancho_m>36 else 0), key=f"lt_{i}")
                a_t = ct2.number_input(f"Ancho Travesaño {i+1}", value=100, key=f"at_{i}")
                medidas_travesaños.append({"L": l_t, "A": a_t})

            st.write("---")
            st.subheader("💰 Parámetros Financieros")
            tipo_base = st.selectbox("Soporte", ["Zócalo Madera", "Patas Plásticas", "Nada"])
            costo_base = 5000 if tipo_base == "Patas Plásticas" else 0
            dias_prod = st.number_input("Días de taller", value=0.0, step=0.5) # Arranca en 0
            necesita_colocacion = st.checkbox("¿Requiere Colocación?")
            flete_sel = st.selectbox("Zona Envío", ["Ninguno", "Capital", "Zona Norte"])
            dias_col = st.number_input("Días de obra", value=0) if necesita_colocacion else 0
        with col_out:
            st.subheader("📐 Planilla de Corte e Inteligencia de Materiales")
            despiece = []
            
            if alto_m > 0 and ancho_m > 0:
                # 1. --- MOTOR DE DESPIECE (Suma de todas las piezas) ---
                despiece.append({"Pieza": "Lateral Exterior", "Cant": 2, "L": alto_m, "A": prof_m})
                despiece.append({"Pieza": "Piso/Techo", "Cant": 2, "L": ancho_m - 36, "A": prof_m})
                
                if tiene_parante:
                    despiece.append({"Pieza": "Parante Divisor", "Cant": 1, "L": alto_m - 36, "A": prof_m - 20})
                
                for i, t in enumerate(medidas_travesaños):
                    despiece.append({"Pieza": f"Travesaño {i+1}", "Cant": 1, "L": t["L"], "A": t["A"]})

                # AGREGAMOS PUERTAS AL DESPIECE Y PRECIO
                for i, p_ancho in enumerate(medidas_puertas):
                    if p_ancho > 0:
                        despiece.append({"Pieza": f"Puerta {i+1}", "Cant": 1, "L": alto_m - 10, "A": p_ancho})

                # AGREGAMOS ESTANTES AL DESPIECE Y PRECIO
                for i, e_ancho in enumerate(medidas_estantes):
                    if e_ancho > 0:
                        despiece.append({"Pieza": f"Estante {i+1}", "Cant": 1, "L": e_ancho, "A": prof_m - 20})

                # AGREGAMOS CAJONES (Frentes)
                if cant_cajones > 0:
                    despiece.append({"Pieza": "Frentes de Cajón", "Cant": cant_cajones, "L": 200, "A": ancho_hueco_cajon - 10})

                # AGREGAMOS EL FONDO (Pieza separada)
                despiece.append({"Pieza": "Fondo Mueble", "Cant": 1, "L": alto_m - 5, "A": ancho_m - 5, "Tipo": "Fondo"})

                df_corte = pd.DataFrame(despiece)
                st.data_editor(df_corte, use_container_width=True)

                # 2. --- CÁLCULO DE COSTOS REALES ---
                # Separamos materiales por tipo (18mm vs Fondo)
                m2_18mm = (df_corte[df_corte.get('Tipo') != 'Fondo']['L'] * df_corte['A'] * df_corte['Cant']).sum() / 1_000_000
                m2_fondo = (df_corte[df_corte.get('Tipo') == 'Fondo']['L'] * df_corte['A'] * df_corte['Cant']).sum() / 1_000_000

                costo_madera = (m2_18mm * maderas[mat_principal] / 5.03)
                costo_fondo = (m2_fondo * fondos[mat_fondo_sel] / 5.03)
                
                # 3. --- HERRAJES Y LOGÍSTICA (Afectan el precio final) ---
                costo_herrajes = (cant_puertas * 2 * precio_bisagra) + (cant_cajones * precio_guia)
                
                costo_flete = 0
                if flete_sel == "Capital": costo_flete = config['flete_capital']
                elif flete_sel == "Zona Norte": costo_flete = config['flete_norte']

                costo_operativo = (dias_prod * config['gastos_fijos_diarios'])
                
                # SUMATORIA TOTAL DE COSTOS
                total_costo = costo_madera + costo_fondo + costo_herrajes + costo_operativo + costo_base + costo_flete
                if necesita_colocacion: total_costo += (dias_col * config['colocacion_dia'])
                # 8. --- INTELIGENCIA DE AHORRO (RETAZOS) ---
                st.write("---")
                retazos_en_stock = consultar_retazos_disponibles(mat_principal)
                ahorro_madera = 0 # Inicializamos el ahorro en 0
                
                if retazos_en_stock:
                    st.subheader("♻️ Oportunidades de Ahorro")
                    piezas_que_encajan = 0
                    for ret in retazos_en_stock:
                        for index, row in df_corte.iterrows():
                            # Lógica de encaje: largo y ancho (considerando que se pueden rotar)
                            if (ret['largo'] >= row['L'] and ret['ancho'] >= row['A']) or \
                               (ret['largo'] >= row['A'] and ret['ancho'] >= row['L']):
                                
                                piezas_que_encajan += 1
                                # Calculamos cuánto dinero representa ese retazo
                                m2_pieza = (row['L'] * row['A']) / 1_000_000
                                ahorro_pieza = (m2_pieza * maderas[mat_principal] / 5.03)
                                ahorro_madera += ahorro_pieza
                                
                                st.success(f"¡Match! '{row['Pieza']}' entra en Retazo ID-{ret['id']}. Ahorro: ${ahorro_pieza:,.0f}")
                                break 
                    
                    if piezas_que_encajan > 0:
                        st.info(f"💡 Ahorro total estimado en materiales: ${ahorro_madera:,.0f}")
                
                # APLICAMOS EL AHORRO AL COSTO TOTAL
                total_costo_real = total_costo - ahorro_madera

                # MARGEN Y PRECIO FINAL SOBRE EL COSTO REAL
                utilidad = total_costo_real * config['ganancia_taller_pct']
                precio_final = total_costo_real + utilidad

                # 4. --- MÉTRICAS ---
                c1, c2, c3 = st.columns(3)
                c1.metric("Costo Herrajes", f"${costo_herrajes:,.0f}")
                c2.metric("M2 Melamina", f"{m2_18mm:.2f} m²")
                c3.metric("Utilidad Bruta", f"${utilidad:,.0f}")
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

                # --- 2. GESTIÓN DE INVENTARIO (RETAZOS) ---
                with st.expander("➕ Registrar Nuevo Retazo en Depósito"):
                    st.write("Cargá sobrantes útiles (>300mm) para que el sistema los detecte en futuras cotizaciones.")
                    c_ret1, c_ret2 = st.columns(2)
                    ancho_r = c_ret1.number_input("Ancho (mm)", value=0, key="anc_r")
                    largo_r = c_ret2.number_input("Largo (mm)", value=0, key="lar_r")
    
                    if st.button("💾 Guardar en Inventario de Retazos"):
                        if ancho_r >= 300 and largo_r >= 300:
                            registrar_retazo(mat_principal, largo_r, ancho_r)
                        else:
                            st.warning("El retazo es muy chico para ser útil (mínimo 300x300).")

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

















