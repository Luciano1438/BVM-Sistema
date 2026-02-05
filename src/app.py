import streamlit as st
import pandas as pd
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

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

# --- 1. DATOS DE PRODUCCIÓN (FUNCIÓN ÚNICA Y FUNCIONAL) ---
# --- 1. MOTOR DE INTELIGENCIA DE NEGOCIO (BVM PRO) ---
def traer_datos():
    # Precios Base (se mantienen como respaldo)
    maderas_base = {
        'Melamina Blanca 18mm': 95000.0,
        'Melamina Colores 18mm': 120000.0,
        'Enchapado Paraiso 18mm': 180000.0,
        'Enchapado Roble Claro 18mm': 285000.0
    }
    
    # Inyectamos el Multiplicador de Inflación dinámico
    # Esto permite al dueño actualizar TODO el taller con un solo clic en el futuro
    factor_ajuste = st.sidebar.number_input("Factor de Ajuste Inflacionario", value=1.0, step=0.05)
    maderas = {k: v * factor_ajuste for k, v in maderas_base.items()}

    fondos = {
        'Fibroplus Blanco 3mm': 34500.0 * factor_ajuste,
        'Faplac Fondo 5.5mm': 45000.0 * factor_ajuste
    }
    
    config = {
        'gastos_fijos_diarios': 179768.0,
        'amortizacion_maquinas_pct': 0.10,
        'ganancia_taller_pct': 0.15,
        'desperdicio_placa_pct': 0.10,
        'flete_capital': 70000.0,
        'flete_norte': 35000.0,
        'colocacion_dia': 100000.0,
        'bisagra_cazoleta': 1300.0,
        'telescopica_45': 6000.0,
        'telescopica_soft': 18000.0
    }
    return maderas, fondos, config

def guardar_presupuesto_nube(cliente, mueble, total):
    try:
        data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "cliente": cliente,
            "mueble": mueble,
            "precio_final": float(total),
            "estado": "Pendiente"
        }
        supabase.table("ventas").insert(data).execute()
        st.success(f"✅ ¡Impactado en SQL! Cliente: {cliente}")
        st.balloons()
    except Exception as e:
        st.error(f"❌ Error de comunicación: {e}")

def traer_datos_historial():
    try:
        response = supabase.table("ventas").select("*").execute()
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

# --- 3. INTERFAZ Y LÓGICA (INTACTA) ---
maderas, fondos, config = traer_datos()
st.set_page_config(page_title="BVM - Gestión materiales", layout="wide")
menu = st.sidebar.radio("Navegación", ["Cotizador CNC", "Historial de Ventas"])

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

                # MARGEN Y PRECIO FINAL
                utilidad = total_costo * config['ganancia_taller_pct']
                precio_final = total_costo + utilidad

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

              # --- BOTONES DE GUARDADO ---
                c_save1, c_save2 = st.columns(2)
                with c_save1:
                    if st.button("💾 Guardar Local"):
                        ejecutar_query("INSERT INTO presupuestos_guardados (cliente, mueble, precio_final, estado) VALUES (?, ?, ?, ?)", (cliente, mueble_nom, precio_final, "Pendiente"))
                        st.success("Guardado Local.")
                with c_save2:
                    if st.button("💾 Guardar en Nube"):
                        guardar_presupuesto_nube(cliente, mueble_nom, precio_final)

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
            else:
                st.warning("Ingrese dimensiones.")
    except Exception as e: 
        st.error(f"Error en el Cotizador: {e}")

else:
    st.title("📊 Gestión y Seguimiento de Ventas")
    try:
        df_hist = traer_datos_historial()
        if not df_hist.empty:
            st.subheader("📈 Balance General")
            st.write(f"Ventas Totales: ${df_hist['precio_final'].sum():,.0f}")
            df_editado = st.data_editor(df_hist, use_container_width=True, key="ed_v10")
            if st.button("💾 Sincronizar Cambios"):
                st.info("Los cambios en la tabla son visuales. Para guardar una venta nueva, usá el Cotizador.")
    except Exception as e:
        st.error(f"Error de conexión: {e}")










