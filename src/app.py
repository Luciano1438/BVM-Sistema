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
import ezdxf
import io

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
    id_ = st.session_state["user"].id
    try:
        # Traemos todos los retazos de ese material
        res = supabase.table("retazos").select("*").eq("user_id", id_).execute()
        return res.data
    except Exception as e:
        st.error(f"Error al consultar retazos: {e}")
        return []

def registrar_retazo(material, largo, ancho):
    id_usuario = st.session_state["user"].id
    try:
        # Validamos contra el mínimo de 150x400
        if (largo >= 400 and ancho >= 150) or (largo >= 150 and ancho >= 400): 
            data = {
                "material": material, 
                "largo": largo, 
                "ancho": ancho, 
                "user_id": id_usuario
            }
            supabase.table("retazos").insert(data).execute()
            st.toast(f"♻️ Retazo guardado: {int(largo)}x{int(ancho)}")
        else:
            # Este else debe estar exactamente bajo el 'if'
            st.error(f"❌ Error: {int(largo)}x{int(ancho)} es inferior al mínimo de 150x400.")
    except Exception as e:
        st.error(f"Error técnico al registrar: {e}")
def generar_dxf_bvm(df):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    x_offset = 0
    margen = 50 # Espacio entre piezas dibujadas
    
    for _, row in df.iterrows():
        largo = float(row['L'])
        ancho = float(row['A'])
        cant = int(row['Cant'])
        nombre = str(row['Pieza'])
        
        for i in range(cant):
            # Dibujamos el rectángulo de la pieza
            puntos = [
                (x_offset, 0),
                (x_offset + largo, 0),
                (x_offset + largo, ancho),
                (x_offset, ancho),
                (x_offset, 0)
            ]
            msp.add_lwpolyline(puntos, close=True)
            
            # Le ponemos el nombre adentro para que el operario no se pierda
            msp.add_text(f"{nombre}", height=15).set_placement((x_offset + 5, 5))
            
            x_offset += largo + margen
            
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode('utf-8')
def generar_despiece_bvm(tipo, ancho_m, alto_m, prof_m, esp_real, tiene_parante, tipo_parante, 
                         distancia_parante, cant_cajones, tipo_tapa, tipo_base, altura_base, 
                         luz_entre_tapas, luz_perimetral_tapa, alto_frentin_emb, 
                         aire_trasero, esp_corredera, distribucion_tapas,
                         cant_puertas=0, tiene_cenefa=False, alto_cenefa=0.0,
                         estantes_fijos=0, estantes_moviles=0): 
        despiece = []
        ancho_interno_total = ancho_m - (esp_real * 2)

        if tipo == "Bajo Mesada":
        # 1. BASE
            despiece.append({"Pieza": "Base Módulo", "Cant": 1, "L": ancho_m, "A": prof_m, "Tipo": "Cuerpo"})
            
            # 2. LATERALES (Apoyan sobre base)
            altura_lateral = alto_m - esp_real
            despiece.append({"Pieza": "Lateral Exterior", "Cant": 2, "L": altura_lateral, "A": prof_m, "Tipo": "Cuerpo"})
            
            # 3. FRENTINES Y ESTILOS
            if tipo_tapa == "Superpuesta":
                despiece.append({"Pieza": "Frentín Frontal", "Cant": 1, "L": ancho_interno_total, "A": 50, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_interno_total, "A": 100, "Tipo": "Cuerpo"})
                alto_puerta = alto_m - 4
            elif tipo_tapa == "Gola BVM":
                despiece.append({"Pieza": "Frentín Gola L (A)", "Cant": 1, "L": ancho_interno_total, "A": 40, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Frentín Gola L (B)", "Cant": 1, "L": ancho_interno_total, "A": 50, "Tipo": "Cuerpo"})
                alto_puerta = alto_m - 30
            else: 
                despiece.append({"Pieza": "Frentín Embutido", "Cant": 1, "L": ancho_interno_total, "A": 40, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_interno_total, "A": 100, "Tipo": "Cuerpo"})
                alto_puerta = alto_m - esp_real - 46
            
            # 4. TRAVESAÑOS TRASEROS (Doble refuerzo)
            despiece.append({"Pieza": "Travesaño Trasero (100)", "Cant": 1, "L": ancho_interno_total, "A": 100, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Travesaño Trasero (70)", "Cant": 1, "L": ancho_interno_total, "A": 70, "Tipo": "Cuerpo"})
            
            # 5. FONDO (Regla 80mm alto y 20mm ancho)
            alto_fondo = alto_m - 80 - esp_real
            despiece.append({"Pieza": "Fondo Mueble", "Cant": 1, "L": alto_fondo, "A": ancho_m - 20, "Tipo": "Fondo"})
    
            # 6. INTERIORES Y PUERTAS
            if tiene_parante:
                # --- Lógica de 3 Puertas ---
                ancho_par = prof_m if tipo_parante == "Largo (Fondo Lateral)" else 100
                despiece.append({"Pieza": "Parante Divisor", "Cant": 1, "L": altura_lateral, "A": ancho_par, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Medio Estante", "Cant": 2, "L": ancho_interno_total / 2, "A": prof_m - 20, "Tipo": "Cuerpo"})
                
                # Cálculo de Ancho para 3 Puertas
                if tipo_tapa == "Embutida":
                    ancho_p = (ancho_m - (esp_real * 3) - 16) / 3
                else:
                    ancho_p = (ancho_m - 12) / 3
                    
                despiece.append({"Pieza": "Puerta", "Cant": 3, "L": alto_puerta, "A": round(ancho_p, 1), "Tipo": "Frente"})
                
            else:
                # --- Lógica de 2 Puertas ---
                despiece.append({"Pieza": "Estante Completo", "Cant": 1, "L": ancho_interno_total, "A": prof_m - 20, "Tipo": "Cuerpo"})
                
                # Cálculo de Ancho para 2 Puertas
                if tipo_tapa == "Embutida":
                    ancho_p = (ancho_m - (esp_real * 2) - 10) / 2
                else:
                    ancho_p = (ancho_m - 8) / 2
                    
                despiece.append({"Pieza": "Puerta", "Cant": 2, "L": alto_puerta, "A": round(ancho_p, 1), "Tipo": "Frente"})
            
        elif tipo == "Cajonera":
            # --- TU LÓGICA DE CAJONERA ORIGINAL (INTACTA) ---
            altura_caja_real = alto_m
            if tipo_base in ["Banquina de Obra", "Patas Plásticas"]:
                altura_caja_real = alto_m - altura_base
    
            despiece.append({"Pieza": "Base Módulo", "Cant": 1, "L": ancho_m, "A": prof_m, "Tipo": "Cuerpo"})
            altura_lateral_bvm = alto_m - esp_real
            despiece.append({"Pieza": "Lateral Exterior", "Cant": 2, "L": altura_lateral_bvm, "A": prof_m, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_interno_total, "A": 100, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Travesaño Trasero", "Cant": 1, "L": ancho_interno_total, "A": 70, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Frentín Frontal", "Cant": 1, "L": ancho_interno_total, "A": 50, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Fondo Mueble", "Cant": 1, "L": alto_m - 20, "A": ancho_m - 20, "Tipo": "Fondo"})
    
            if tipo_base == "Zócalo de Madera":
                despiece.append({"Pieza": "Zócalo Frontal", "Cant": 2, "L": altura_base, "A": ancho_interno_total, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Zócalo Lateral", "Cant": 2, "L": altura_base, "A": prof_m - 50, "Tipo": "Cuerpo"})
    
            if tiene_parante:
                altura_interna = altura_caja_real - (esp_real * 2)
                despiece.append({"Pieza": "Parante Divisor", "Cant": 1, "L": altura_interna, "A": prof_m - 20, "Tipo": "Cuerpo"})
    
            if cant_cajones > 0:
                if "Superpuesta" in tipo_tapa:
                    espacio_util_total = alto_m - 30 - ((cant_cajones - 1) * luz_entre_tapas)
                    ancho_tapa_bvm = ancho_m - luz_perimetral_tapa
                    largo_lateral_caja = prof_m - aire_trasero
                elif tipo_tapa == "Embutida":
                    espacio_util_total = alto_m - alto_frentin_emb - esp_real - ((cant_cajones + 1) * luz_entre_tapas)
                    ancho_tapa_bvm = ancho_interno_total - 6
                    largo_lateral_caja = prof_m - 30 - esp_real
                else: # GOLA
                    espacio_util_total = alto_m - 60 - ((cant_cajones - 1) * luz_entre_tapas)
                    ancho_tapa_bvm = ancho_m - luz_perimetral_tapa
                    largo_lateral_caja = prof_m - aire_trasero   
                    despiece.append({"Pieza": "Frentín Gola L (A)", "Cant": 2, "L": 40, "A": ancho_interno_total, "Tipo": "Cuerpo"})
                    despiece.append({"Pieza": "Frentín Gola L (B)", "Cant": 2, "L": 50, "A": ancho_interno_total, "Tipo": "Cuerpo"})
    
                if distribucion_tapas == "Proporcional (20/35/45)" and cant_cajones == 3:
                    alturas_tapas = [espacio_util_total * 0.20, espacio_util_total * 0.35, espacio_util_total * 0.45]
                else:
                    divisor_seguro = cant_cajones if cant_cajones > 0 else 1
                    alturas_tapas = [espacio_util_total / divisor_seguro] * int(cant_cajones)
    
                for i, alto_tapa in enumerate(alturas_tapas):
                    despiece.append({"Pieza": f"Tapa de Cajon {i+1}", "Cant": 1, "L": round(alto_tapa,1), "A": ancho_tapa_bvm, "Tipo": "Frente"})
    
                ancho_caja_total = ancho_interno_total - (esp_corredera * 2)
                despiece.append({"Pieza": "Lateral Cajón", "Cant": int(cant_cajones * 2), "L": 150, "A": largo_lateral_caja, "Tipo": "Cuerpo"})
                ancho_frente_interno = ancho_caja_total - (esp_real * 2)
                despiece.append({"Pieza": "Frente/Fondo Interno", "Cant": int(cant_cajones * 2), "L": 150, "A": ancho_frente_interno, "Tipo": "Cuerpo"})
                despiece.append({"Pieza": "Piso Cajón", "Cant": int(cant_cajones), "L": round(largo_lateral_caja - 20, 1), "A": round(ancho_caja_total - 20, 1), "Tipo": "Piso"})
        # --- NUEVO MÓDULO: ALACENA BVM (Lógica de Estantes Variables) ---
        elif tipo == "Alacena":
            ancho_base = ancho_m - (esp_real * 2)
            
            # 1. ESTRUCTURA (Reglas de tu viejo)
            despiece.append({"Pieza": "Piso (Base)", "Cant": 1, "L": ancho_base, "A": prof_m, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Techo", "Cant": 1, "L": ancho_m, "A": prof_m, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Lateral", "Cant": 2, "L": alto_m - esp_real, "A": prof_m, "Tipo": "Cuerpo"})
            despiece.append({"Pieza": "Fondo", "Cant": 1, "L": alto_m - 10, "A": ancho_m - 10, "Tipo": "Fondo"})
            despiece.append({"Pieza": "Travesaño Superior", "Cant": 1, "L": ancho_base, "A": 100, "Tipo": "Cuerpo"})

            # 2. PARANTE INTERMEDIO (Solo 3 y 4 puertas)
            if cant_puertas in [3, 4]:
                despiece.append({"Pieza": "Parante Intermedio", "Cant": 1, "L": alto_m - (esp_real * 2), "A": prof_m - 20, "Tipo": "Cuerpo"})

            # 3. ESTANTES DINÁMICOS (Lógica BVM - Fix 4 Puertas)
            prof_est = prof_m - 30
            
            # Calculamos anchos base según configuración de vanos
            if cant_puertas == 2:
                ancho_est_ref = ancho_base
            elif cant_puertas == 3:
                ancho_est_ref_grande = round(((ancho_m/3)*2) - (esp_real*2), 1)
                ancho_est_ref_chico = round((ancho_m/3) - (esp_real*1.5), 1)
            else: # 4 puertas (Vanos simétricos divididos por parante)
                ancho_est_ref = round((ancho_m/2) - (esp_real*1.5), 1)

            # Inyección de FIJOS
            if estantes_fijos > 0:
                if cant_puertas == 3:
                    despiece.append({"Pieza": "Estante Fijo (Vano 2/3)", "Cant": int(estantes_fijos), "L": ancho_est_ref_grande, "A": prof_est, "Tipo": "Cuerpo"})
                    despiece.append({"Pieza": "Estante Fijo (Vano 1/3)", "Cant": int(estantes_fijos), "L": ancho_est_ref_chico, "A": prof_est, "Tipo": "Cuerpo"})
                elif cant_puertas == 4:
                    # Si marcaste 2 niveles, necesitás 4 maderas (2 para cada lado del parante)
                    despiece.append({"Pieza": "Estante Fijo", "Cant": int(estantes_fijos * 2), "L": ancho_est_ref, "A": prof_est, "Tipo": "Cuerpo"})
                else: # 2 puertas
                    despiece.append({"Pieza": "Estante Fijo", "Cant": int(estantes_fijos), "L": ancho_est_ref, "A": prof_est, "Tipo": "Cuerpo"})

            # Inyección de MÓVILES (-2mm luz para armado fácil)
            if estantes_moviles > 0:
                if cant_puertas == 3:
                    despiece.append({"Pieza": "Estante Móvil (Vano 2/3)", "Cant": int(estantes_moviles), "L": ancho_est_ref_grande - 2, "A": prof_est, "Tipo": "Cuerpo"})
                    despiece.append({"Pieza": "Estante Móvil (Vano 1/3)", "Cant": int(estantes_moviles), "L": ancho_est_ref_chico - 2, "A": prof_est, "Tipo": "Cuerpo"})
                elif cant_puertas == 4:
                    despiece.append({"Pieza": "Estante Móvil", "Cant": int(estantes_moviles * 2), "L": ancho_est_ref - 2, "A": prof_est, "Tipo": "Cuerpo"})
                else: # 2 puertas
                    despiece.append({"Pieza": "Estante Móvil", "Cant": int(estantes_moviles), "L": ancho_est_ref - 2, "A": prof_est, "Tipo": "Cuerpo"})
            # 4. PUERTAS Y FRENTES
            if "Uñero" in tipo_tapa:
                alto_p = alto_m + 20
                if tiene_cenefa:
                    despiece.append({"Pieza": "Cenefa", "Cant": 1, "L": ancho_m, "A": alto_cenefa if alto_cenefa > 0 else 50, "Tipo": "Frente"})
            elif "Embutida" in tipo_tapa:
                alto_p = alto_m - (esp_real * 2) - 6
            else:
                alto_p = alto_m - 4

            if "Embutida" in tipo_tapa:
                if cant_puertas == 2: ancho_p = (ancho_base - 10) / 2
                elif cant_puertas == 3: ancho_p = (ancho_m - (esp_real*3) - 16) / 3
                else: ancho_p = (ancho_m - (esp_real*3) - 20) / 4
            else:
                if cant_puertas == 2: ancho_p = (ancho_m - 8) / 2
                elif cant_puertas == 3: ancho_p = (ancho_m - 12) / 3
                else: ancho_p = (ancho_m - 16) / 4
            
            despiece.append({"Pieza": "Puerta", "Cant": cant_puertas, "L": alto_p, "A": round(ancho_p, 1), "Tipo": "Frente"})
            return despiece 
    
 
def exportar_para_aspire(df, material, espesor):
    # Forzamos una copia limpia
    df_aspire = df.copy()
    
    # Mapeo explícito: nos aseguramos de que los nombres existan antes de renombrar
    mapeo = {
        "Pieza": "Name",
        "L": "Length",
        "A": "Width",
        "Cant": "Quantity"
    }
    
    # Renombramos solo las columnas que existan en el DataFrame actual
    df_aspire = df_aspire.rename(columns=mapeo)
    
    # Agregamos los datos fijos
    df_aspire["Thickness"] = espesor
    df_aspire["Material"] = material
    
    # Definimos las columnas finales que Aspire espera
    columnas_finales = ["Name", "Length", "Width", "Thickness", "Quantity", "Material"]
    
    # Filtramos solo las que necesitamos (esto evita el error de 'not in index')
    existentes = [c for c in columnas_finales if c in df_aspire.columns]
    
    return df_aspire[existentes].to_csv(index=False, sep=',', decimal='.').encode('utf-8')
# --- 0. SEGURIDAD DE ACCESO MULTIUSUARIO (VALOR PRO) ---
def gestionar_auth():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False
        st.session_state["user"] = None

    if not st.session_state["autenticado"]:
        st.title("🚀 BVM - Terminal de Operaciones")
        tab_login, tab_reg = st.tabs(["🔑 Ingresar", "📝 Registro"])
        
        with tab_login:
            # Encapsulamos en un form para que no refresque al escribir
            with st.form("login_form"):
                email = st.text_input("Email")
                pw = st.text_input("Contraseña", type="password")
                boton_login = st.form_submit_button("Entrar", use_container_width=True)
                
                if boton_login:
                    if email and pw:
                        # Ponemos un spinner para ver que el sistema está trabajando
                        with st.spinner("Conectando con la base de datos de BVM..."):
                            try:
                                res = supabase.auth.sign_in_with_password({"email": email, "password": pw})
                                if res.session:
                                    st.session_state["session"] = res.session
                                    st.session_state["user"] = res.user
                                    st.session_state["autenticado"] = True
                                    st.success("✅ Acceso correcto.")
                                    st.rerun()
                            except Exception as e:
                                error_str = str(e).lower()
                                st.toast(f"Error técnico: {e}") 
                                err = str(e).lower()
                                if "invalid login credentials" in error_str:
                                    st.error("❌ Email o contraseña incorrectos.")
                                elif "network" in error_str:
                                    st.error("🌐 Error de red. Revisá tu internet.")
                                else:
                                    st.error(f"⚠️ Error de conexión: {e}")
                    else:
                        st.warning("⚠️ Completá todos los campos.")
        
        with tab_reg:
            with st.form("registro_form"):
                new_email = st.text_input("Email Nuevo")
                new_pw = st.text_input("Password (min. 6 car.)", type="password")
                boton_reg = st.form_submit_button("Crear Cuenta", use_container_width=True)
                
                if boton_reg:
                    try:
                        supabase.auth.sign_up({"email": new_email, "password": new_pw})
                        st.success("✅ ¡Revisá tu email para confirmar la cuenta!")
                    except Exception as e:
                        st.error(f"❌ Error al crear cuenta: {e}")
        return False
    return True
def actualizar_precio_nube(clave, valor, categoria):
    if "session" not in st.session_state or st.session_state["session"] is None:
        st.error("❌ Sesión no iniciada.")
        return

    # SINTAXIS CORREGIDA: Usamos post_grest_client options o simplemente pasamos el token
    token = st.session_state["session"].access_token
    
    try:
        # Usamos el cliente global pero le inyectamos el header de autenticación
        supabase.postgrest.auth(token) 
        
        data = {
            "user_id": st.session_state["user"].id,
            "clave": clave,
            "valor": float(valor),
            "categoria": categoria
        }
        
        # Ejecutamos con la identidad ya inyectada
        supabase.table("configuracion").upsert(data, on_conflict="user_id, clave").execute()
        
    except Exception as e:
        st.error(f"Error guardando {clave}: {e}")
# --- 1. MOTOR DE INTELIGENCIA DE NEGOCIO (BVM PRO) ---
def traer_datos():
    if "session" not in st.session_state or st.session_state["session"] is None:
        return {}, {}, {}

    token = st.session_state["session"].access_token
    id_usuario = st.session_state["user"].id
    
    # --- 1. DEFAULTS SIEMPRE DISPONIBLES ---
    # Poné acá todas las placas que querés que aparezcan SIEMPRE
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
        
        # --- 2. MAPEAMOS LO QUE VIENE DE LA NUBE ---
        maderas_db = {
            d['clave']: d['valor']
            for d in datos_db
            if str(d.get('categoria', '')).lower().strip() == 'maderas'
        }

        config_db = {
            d['clave']: d['valor']
            for d in datos_db
            if str(d.get('categoria', '')).lower().strip() in ['costos', 'margen', 'herrajes']
        }
        
        # --- 3. FUSIÓN MAESTRA ---
        # Las maderas de la DB pisan a las de default, pero las que no están en la DB se mantienen.
        maderas = {**maderas_default, **maderas_db}
        config = {**config_default, **config_db}
        
        fondos = {
            'Fibroplus Blanco 3mm': 34500.0,
            'Faplac Fondo 5.5mm': 45000.0
        }
        
        return maderas, fondos, config

    except Exception as e:
        st.error(f"Error cargando configuración: {e}")
        return maderas_default, {'Fibroplus Blanco 3mm': 34500.0}, config_default

    except Exception as e:
        st.error(f"Error cargando configuración: {e}")
        # Retorno de emergencia seguro
        return maderas_default, {'Fibroplus Blanco 3mm': 34500.0}, config_default

    except Exception as e:
        st.error(f"Error cargando configuración: {e}")
        return {}, {}, {}
def guardar_presupuesto_nube(cliente, mueble, total):
    id_ = st.session_state["user"].id
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
        st.success(f"🚀 Venta guardada en la nube")
    except Exception as e:
        st.error(f"Error al impactar nube: {e}")
def traer_datos_historial():
    id_ = st.session_state["user"].id
    try:
       response = supabase.table("ventas").select("*").eq("user_id", st.session_state["user"].id).execute()
       return pd.DataFrame(response.data)
    except:
        return pd.DataFrame()
# --- 2. CONECTIVIDAD LOCAL (Mantenida para guardar localmente) ---
def ejecutar_query(query, params=(), fetch=False):
    db_path = BASE_DIR / 'data' / 'carpinteria.db'
    
    # ÚNICO AGREGADO PERMITIDO: Que cree la carpeta si falta
    if not os.path.exists(BASE_DIR / 'data'):
        os.makedirs(BASE_DIR / 'data')
        
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch: return cursor.fetchall()
        conn.commit()
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
if not gestionar_auth():
    st.stop()

maderas, fondos, config = traer_datos()
# --- ACTUALIZACIÓN DE MENÚ (VALOR PRO) ---
menu = st.sidebar.radio("Navegación", ["Cotizador CNC","Depósito de Retazos", "Historial de Ventas", "⚙️ Configuración de Precios"])
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
        tiene_parante = False
        mueble_nom = "Mueble BVM"
        tiene_parante = False
        distancia_parante = 0.0     
        cant_estantes = 0
        luz_perimetral_tapa = 4.0
        aire_trasero = 30.0  
        esp_corredera = 13.0
        distribucion_tapas = "Iguales"
        cant_puertas = 0
        tiene_cenefa = False
        alto_cenefa = 0.0
        
        col_in, col_out = st.columns([1, 1.2])
        with col_in:
            # Agrupamos los datos básicos en un contenedor expandible
            with st.expander("🛠️ Definición de Estructura", expanded=True):
                cliente = st.text_input("Cliente", "")
                tipo_modulo = st.selectbox("Tipo de Mueble", ["Cajonera", "Bajo Mesada", "Alacena"], key="tipo_mueble_sel")
                
                c1, c2, c3 = st.columns(3)
                ancho_m = c1.number_input("Ancho Total (mm)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
                alto_m = c2.number_input("Alto Total (mm)", min_value=0.0, max_value=5000.0, value=0.0, step=0.5)
                prof_m = c3.number_input("Profundo (mm)", min_value=0.0, max_value=2000.0, value=0.0, step=0.5)
                
                mat_principal = st.selectbox("Material Cuerpo (18mm)", list(maderas.keys()))
                esp_real = st.number_input("Espesor Real Placa (mm)", min_value=1.0, max_value=50.0, value=18.0, step=0.1)
                mat_fondo_sel = st.selectbox("Material Fondo", list(fondos.keys()))

            # Agrupamos los módulos en otro contenedor
            with st.expander("🏗️ Configuración de Módulos", expanded=False):
                if tipo_modulo == "Bajo Mesada":
                # --- 1. LÓGICA EXCLUSIVA BAJO MESADA ---
                    st.markdown("#### 🚪 Configuración de Frente")
                    
                    # Selector de estilo (Gola es el que ya programamos)
                    opciones_bm = ["Superpuesta", "Gola BVM", "Embutida"]
                    tipo_tapa = st.radio("Estilo de Bajo Mesada", opciones_bm)
                    
                    # Selector de puertas y sincronización con parante
                    cant_puertas = st.selectbox("Cantidad de Puertas", [2, 3])
                    
                    if cant_puertas == 3:
                        tiene_parante = True
                        st.info("💡 3 puertas: Parante divisor incluido automáticamente.")
    
                        c_p1, c_p2 = st.columns(2)
                        tipo_parante = st.selectbox("Tipo de Parante", ["Corto (100mm)", "Largo (Fondo Lateral)"])
                        distancia_parante = c_p2.number_input("Distancia desde lateral izq. (mm)", 
                                                            value=ancho_m/cant_puertas if ancho_m > 0 else 0.0, 
                                                            step=1.0)
                    
                    # Configuración de herrajes (Bisagras)
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "Especial"])
                    precio_bisagra = config['bisagra_cazoleta']
                    
                    # Reseteamos valores de cajones para que el motor no explote
                    cant_cajones = 0
                    luz_entre_tapas = 3.0
                    luz_perimetral_tapa = 4.0
                    alto_frentin_emb = 0.0
                elif tipo_modulo == "Alacena":
                    st.markdown("#### 🪵 Configuración de Alacena BVM")
                    
                    c_ala1, c_ala2 = st.columns(2)
                    opciones_ala = ["Superpuesta", "Uñero", "Embutida"]
                    tipo_tapa = c_ala1.radio("Sistema de Apertura", opciones_ala)
                    cant_puertas = c_ala2.selectbox("Cantidad de Puertas", [2, 3, 4])

                    # CONFIGURACIÓN DE ESTANTES (Nivel Pro)
                    st.markdown("---")
                    cant_total_est = st.number_input("Cantidad Total Estantes", min_value=0, value=1, step=1)
                    
                    # Creamos una lista para guardar qué estantes elige el usuario como fijos
                    indices_fijos = []
                    
                    if cant_total_est > 0:
                        st.write("Seleccioná los estantes que son **FIJOS**:")
                        # Creamos columnas automáticas según la cantidad de estantes
                        cols_estantes = st.columns(int(cant_total_est))
                        
                        for i in range(int(cant_total_est)):
                            with cols_estantes[i]:
                                # Si el checkbox está marcado, guardamos el índice
                                es_fijo = st.checkbox(f"E{i+1}", value=False, key=f"check_est_{i}")
                                if es_fijo:
                                    indices_fijos.append(i)
                    
                    # Calculamos los totales para mandarle al motor de despiece
                    estantes_fijos = len(indices_fijos)
                    estantes_moviles = cant_total_est - estantes_fijos
            
                    st.caption(f"Resumen: {estantes_fijos} Fijos y {estantes_moviles} Móviles")
                    
                    # CENEFA PARA UÑERO
                    tiene_cenefa = False
                    alto_cenefa = 0.0
                    if "Uñero" in tipo_tapa:
                        tiene_cenefa = st.checkbox("¿Lleva Cenefa inferior?", value=True)
                        if tiene_cenefa:
                            alto_cenefa = st.number_input("Altura de Cenefa (mm)", value=50.0, step=5.0)
                    
                    # VARIABLES DE CONTROL
                    tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave", "C0 Estándar"])
                    precio_bisagra = config['bisagra_cazoleta']
                    cant_cajones = 0
                    luz_entre_tapas = 0.0
                    luz_perimetral_tapa = 0.0
                    alto_frentin_emb = 0.0
                else:
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
                if cant_cajones > 0: 
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
    
                        
                #PARÁMETROS FINANCIEROS Y ENVÍO ---
            with st.expander("💰 Soporte y Logística", expanded=False):
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
                return {
                    "Pieza": nombre, 
                    "Cant": cant, 
                    "L": round(largo, 1), 
                    "A": round(ancho, 1), 
                    "Notas": ""
                }
            if alto_m > 0 and ancho_m > 0:
                # LLAMADA EXPLÍCITA AL MOTOR BVM
                piezas_calculadas = generar_despiece_bvm(
                    tipo=tipo_modulo, 
                    ancho_m=ancho_m, 
                    alto_m=alto_m, 
                    prof_m=prof_m, 
                    esp_real=esp_real,
                    tiene_parante=tiene_parante,
                    tipo_parante=tipo_parante if tiene_parante else "Corto",
                    distancia_parante=distancia_parante,
                    cant_cajones=cant_cajones,
                    tipo_tapa=tipo_tapa,
                    tipo_base=tipo_base,
                    altura_base=altura_base,
                    luz_entre_tapas=luz_entre_tapas,
                    luz_perimetral_tapa=luz_perimetral_tapa,
                    alto_frentin_emb=alto_frentin_emb,
                    aire_trasero=aire_trasero,
                    esp_corredera=esp_corredera,
                    distribucion_tapas=distribucion_tapas,
                    cant_puertas=cant_puertas, 
                    tiene_cenefa=tiene_cenefa, 
                    alto_cenefa=alto_cenefa,
                    estantes_fijos=estantes_fijos, 
                    estantes_moviles=estantes_moviles
                )
                # Convertimos los resultados en la tabla
                df_corte = pd.DataFrame(piezas_calculadas)
                st.data_editor(df_corte, use_container_width=True, hide_index=True)
    
               # --- RE-CÁLCULO DE MÉTRICAS (FIX MAESTRO BVM) ---
                df_placa = df_corte[~df_corte['Tipo'].isin(['Fondo', 'Piso'])]
                m2_18mm = (df_placa['L'] * df_placa['A'] * df_placa['Cant']).sum() / 1_000_000
                
                # FALLA 1: Estabas usando 'maderas' antes de verificar si tenía datos.
                # Usamos .get() con un valor default de 1.0 para que no multiplique por 0 en el peor caso.
                precio_placa_unitario = maderas.get(mat_principal, 0.0)
                costo_madera = m2_18mm * (precio_placa_unitario / 5.03)

                # Superficie de Fondos
                df_fondo_only = df_corte[df_corte['Tipo'].isin(['Fondo', 'Piso'])]
                m2_fondo = (df_fondo_only['L'] * df_fondo_only['A'] * df_fondo_only['Cant']).sum() / 1_000_000
                precio_fondo_unitario = fondos.get(mat_fondo_sel, 0.0)
                costo_fondo = m2_fondo * (precio_fondo_unitario / 5.03)
                
                # FALLA 2: costo_herrajes se quedaba en 0.0 porque no lo calculabas según el tipo.
                if tipo_modulo == "Bajo Mesada":
                    # Mínimo 2 bisagras por puerta
                    costo_herrajes = (cant_puertas * 2 * config.get('bisagra_cazoleta', 0))
                else:
                    # Guías por cajón
                    costo_herrajes = (cant_cajones * config.get('telescopica_45', 0))

                # FALLA 3: Los fletes y operativos se reseteaban si no los capturabas bien del dict 'config'
                if flete_sel == "Capital": costo_flete = config.get('flete_capital', 0)
                elif flete_sel == "Zona Norte": costo_flete = config.get('flete_norte', 0)
                else: costo_flete = 0.0
                    
                costo_operativo = (dias_prod * config.get('gastos_fijos_diarios', 0))
                
                # SUMA FINAL: Si alguno de estos sigue siendo 0, el total será bajo pero no 0.00
                total_costo = costo_madera + costo_fondo + costo_herrajes + costo_operativo + costo_base + costo_flete
                if necesita_colocacion: total_costo += (dias_col * config.get('colocacion_dia', 0))

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

                # Alerta de Rentabilidad Estilo Burry con protección
        # Alerta de Rentabilidad con protección contra división por cero
        if precio_final > 0:
            pct_utilidad_real = (utilidad / precio_final) * 100
        else:
            pct_utilidad_real = 0.0
        if pct_utilidad_real < 12:
            st.error(f"⚠️ ALERTA DE MARGEN: La rentabilidad es del {pct_utilidad_real:.1f}%. Revisar costos fijos.")
        else:
            st.success(f"✅ OPERACIÓN RENTABLE: Margen del {pct_utilidad_real:.1f}%")
        st.subheader(f"PRECIO FINAL: ${precio_final:,.2f}")

         # --- 1. GESTIÓN DE GUARDADO UNIFICADA (REDUNDANCIA PRO) ---
        st.write("---")
        if st.button("Guardar", use_container_width=True):
            if cliente:
                try:
                    # A. Guardado en Nube (Supabase) - Tu respaldo de seguridad
                    guardar_presupuesto_nube(cliente, tipo_modulo, precio_final)
                    
                    # B. Guardado Local (SQLite) - Con fix para que no falle la carpeta
                    if not os.path.exists(BASE_DIR / 'data'):
                        os.makedirs(BASE_DIR / 'data')
                        
                    # Agregamos 'cliente' a la query local para que no quede huérfana la info
                    ejecutar_query(
                        "INSERT INTO ventas (mueble, precio_final, estado, cliente) VALUES (?, ?, ?, ?)", 
                        (tipo_modulo, precio_final, "Pendiente", cliente)
                    )
                    
                    st.success(f"✅ ÉXITO: Presupuesto de {tipo_modulo} para {cliente} blindado en ambos sistemas.")
                    st.balloons()
                except Exception as e:
                   if "no such table" in str(e).lower():
                        st.warning("⚠️ Nota: Respaldo local no disponible (Tabla 'ventas' no existe en disco). En la Nube ya se guardó.")
                   else:
                       st.error(f"⚠️ Error en Respaldo Local: {e}")
            else:
                st.warning("📢 Ingrese el nombre del Cliente antes de guardar para evitar datos basura.")
        st.write("---")
        st.subheader("📄 Generar Propuesta para Cliente")
                
        c_com1, c_com2 = st.columns(2)
        with c_com1:
            dias_entrega = st.number_input("Días de entrega", value=15, step=1)
        with c_com2:
            pct_seña = st.slider("% de Seña", 0, 100, 50, 5) # Default 50%, saltos de 5%
                # Preparamos el paquete de datos para el PDF (incluimos el % de seña)
        datos_pdf = {
            'cliente': cliente,
            'mueble': tipo_modulo,
            'precio': precio_final, 'material': mat_principal,
            'ancho': ancho_m, 'alto': alto_m, 'prof': prof_m,
            'entrega': dias_entrega,
            'pct_seña': pct_seña
            }
                
        # --- 1. PREPARACIÓN DE ARCHIVOS (Primero generamos la data) ---
        pdf_bytes = generar_pdf_presupuesto(datos_pdf)
        link_wa = generar_link_whatsapp(datos_pdf)
        archivo_aspire = exportar_para_aspire(df_corte, mat_principal, esp_real)
        dxf_bytes = generar_dxf_bvm(df_corte)

        # --- 2. INTERFAZ DE USUARIO (Ahora dibujamos los botones) ---
        st.write("---")
        st.subheader("📄 Gestión Comercial")
        
        col_com1, col_com2 = st.columns(2)
        with col_com1:
            st.download_button(
                label="📥 Descargar Presupuesto PDF",
                data=pdf_bytes,
                file_name=f"Presupuesto_{cliente}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        with col_com2:
            st.link_button("🟢 Enviar por WhatsApp", link_wa, use_container_width=True)

        st.write("---")
        st.subheader("⚙️ Terminal de Producción CNC")

        col_cnc1, col_cnc2 = st.columns(2)
        with col_cnc1:
            st.download_button(
                label="📐 Descargar Dibujo DXF (Vectores)",
                data=dxf_bytes,
                file_name=f"Vectores_{cliente}.dxf",
                mime="application/dxf",
                use_container_width=True
            )
        with col_cnc2:
            st.download_button(
                label="🤖 Descargar Lista CSV (Aspire)",
                data=archivo_aspire,
                file_name=f"CNC_{cliente}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
            
                # 6. --- GENERACIÓN DE ETIQUETAS (VALOR PRO) ---
        st.write("---") # Una línea divisoria para separar administración de taller
        if st.button("🖨️ Generar Etiquetas de Taller"):
            st.info(f"Generando etiquetas para las {len(df_corte)} piezas...")
            cols_etiquetas = st.columns(2) 
            for index, row in df_corte.iterrows():
                 with cols_etiquetas[index % 2]: # Esto las ordena en 2 columnas visuales
                     with st.expander(f"📍 {row['Pieza']} ({int(row['L'])}x{int(row['A'])})"):
                        st.write(f"**Cliente:** {cliente}")
                        st.write(f"**Mueble:** {mueble_nom}")
                        st.code(f"PIEZA N°: {index+1}\nDIM: {int(row['L'])} x {int(row['A'])} mm")
       
    except Exception as e:
        st.error(f"Error en el Cotizador: {e}")


        # --- 3. GESTIÓN COMERCIAL (PDF PRO) ---
            
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
elif menu == "Depósito de Retazos":
    st.title("♻️ Gestión de Sobrantes (Estándar BVM)")
    st.info("Cargá aquí los recortes del taller para que el sistema los use automáticamente en los presupuestos.")

    # 1. Registro de piezas nuevas
    with st.expander("➕ Registrar Nuevo Retazo en Depósito", expanded=True):
        st.write("Cargá sobrantes útiles (>150x400mm) para que el sistema los detecte.") 
        c_ret_mat, c_ret1, c_ret2 = st.columns([2, 1, 1])
        
        # Necesitamos saber el material para guardarlo bien
        mat_r = c_ret_mat.selectbox("Material del sobrante", list(maderas.keys()))
        ancho_r = c_ret1.number_input("Ancho (mm)", value=0, key="anc_r_indep") 
        largo_r = c_ret2.number_input("Largo (mm)", value=0, key="lar_r_indep") 
    
        if st.button("💾 Guardar en Inventario"): 
            if (ancho_r >= 150 and largo_r >= 400) or (ancho_r >= 400 and largo_r >= 150): 
                registrar_retazo(mat_r, largo_r, ancho_r)
                st.success(f"Retazo de {mat_r} guardado correctamente.")
            else:
                st.warning("El retazo es muy chico para ser útil (mínimo 150x400mm según estándar BVM).") 

    st.write("---")
    
    # 2. Visualización de lo que hay hoy
    st.subheader("📋 Stock Actual")
    id_ = st.session_state["user"].id
    retazos_db = consultar_retazos_disponibles("Todos") # Podés ajustar tu función para que traiga todos
    
    if retazos_db:
        df_inv = pd.DataFrame(retazos_db)
        st.dataframe(df_inv[["material", "largo", "ancho"]], use_container_width=True)
    else:
        st.info("El depósito está vacío.")

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
        # 1. Guardamos los precios de las maderas
        for madera, precio in maderas.items():
            actualizar_precio_nube(madera, precio, 'maderas')
        
        # 2. Guardamos herrajes, costos fijos y márgenes
        # Pasamos la categoría 'costos' para que sepa dónde buscarlos después
        for k, v in config.items():
            actualizar_precio_nube(k, v, 'costos')
            
        st.success("✅ Configuración blindada.")
































































































































































































































