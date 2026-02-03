import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import sqlite3

# --- 1. CONECTIVIDAD NUBE ---
conn_nube = st.connection("gsheets", type=GSheetsConnection)

def traer_datos_historial():
    # Usamos la URL larga CON el gid=0 para que Google no tenga dudas
    url_larga = "https://docs.google.com/spreadsheets/d/1Nvxs3KhSuTBwJ24SIXh__KenLU_PXbRDec3bZjmMYLU/edit#gid=0"
    return conn_nube.read(spreadsheet=url_larga, worksheet="ventas", ttl="0s")
def guardar_presupuesto_nube(cliente, mueble, total):
    try:
        url_larga = "https://docs.google.com/spreadsheets/d/1Nvxs3KhSuTBwJ24SIXh__KenLU_PXbRDec3bZjmMYLU/edit#gid=0"
        df_actual = conn_nube.read(spreadsheet=url_larga, worksheet="ventas", ttl="0s")
        
        nueva_fila = pd.DataFrame([{
            "id": len(df_actual) + 1,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "cliente": cliente,
            "mueble": mueble,
            "precio_final": float(total),
            "estado": "Pendiente"
        }])
        
        df_final = pd.concat([df_actual, nueva_fila], ignore_index=True)
        # Forzamos el update con la url directa
        conn_nube.update(spreadsheet=url_larga, worksheet="ventas", data=df_final)
        
        st.success(f"✅ ¡Impactado en la Nube! Cliente: {cliente}")
        st.balloons() 
    except Exception as e:
        st.error(f"❌ Error de comunicación con Google: {e}")

# --- 2. CONECTIVIDAD LOCAL ---
def ejecutar_query(query, params=(), fetch=False):
    with sqlite3.connect('carpinteria.db') as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch: return cursor.fetchall()
        conn.commit()

def traer_datos():
    todos = ejecutar_query("SELECT nombre, precio, unidad FROM insumos", fetch=True)
    maderas = {n: p for n, p, u in todos if u == 'placa' and not any(x in n.lower() for x in ['fibro', 'fondo', '3mm', '5.5mm'])}
    fondos = {n: p for n, p, u in todos if any(x in n.lower() for x in ['fibro', 'fondo', '3mm', '5.5mm'])}
    config = {item: valor for item, valor in ejecutar_query("SELECT item, valor FROM taller_config", fetch=True)}
    return maderas, fondos, config

# --- 3. INTERFAZ Y LÓGICA ---
maderas, fondos, config = traer_datos()
st.set_page_config(page_title="BVM - Gestión materiales", layout="wide")
menu = st.sidebar.radio("Navegación", ["Cotizador CNC", "Historial de Ventas"])

if menu == "Cotizador CNC":
    try:
        st.title("🏭 BVM | Control de Producción Industrial")
        col_in, col_out = st.columns([1, 1.2])

        with col_in:
            st.subheader("📋 Datos del Proyecto")
            cliente = st.text_input("Cliente", "Cliente Nuevo")
            mueble_nom = st.text_input("Mueble", "Ingrese el tipo de mueble")
            c1, c2, c3 = st.columns(3)
            ancho_m = c1.number_input("Ancho Total (mm)", min_value=0, value=0)
            alto_m = c2.number_input("Alto Total (mm)", min_value=0, value=0)
            prof_m = c3.number_input("Profundo (mm)", min_value=0, value=0)
            mat_principal = st.selectbox("Material Cuerpo (18mm)", list(maderas.keys()))
            mat_fondo_sel = st.selectbox("Material Fondo", list(fondos.keys()))
            
            st.write("---")
            st.subheader("🏗️ Configuración de Módulos")
            esp, luz_e, luz_i = 18, 2, 3
            tipo_bisagra = st.selectbox("Tipo de Bisagra", ["Cazoleta C0 Cierre Suave ($1.300)", "Especial"])
            precio_bisagra = 1300 
            tipo_corredera = st.radio("Tipo de Corredera", ["Telescópica 45cm ($6.000)", "Cierre Suave Pesada ($18.000)"])
            precio_guia = 6000 if "45cm" in tipo_corredera else 18000
            
            c_caj, c_hue = st.columns(2)
            cant_cajones = c_caj.number_input("Cant. Cajones", value=0, min_value=0)
            ancho_hueco_cajon = c_hue.number_input("Ancho Hueco Cajonera (mm)", value=0)
            tiene_parante = st.checkbox("¿Lleva parante divisor?", value=True)
            esp_parante = 18 if tiene_parante else 0
            
            alturas_cajones = []
            if cant_cajones > 0:
                for i in range(int(cant_cajones)):
                    alturas_cajones.append(st.number_input(f"Altura Frente {i+1} (mm)", value=150))

            c_pue, c_est = st.columns(2)
            cant_puertas = c_pue.number_input("Cant. Puertas", value=0, min_value=0, key="cant_pue_p")
            cant_estantes = c_est.number_input("Cant. Estantes", value=0, min_value=0, key="cant_est_p")

            if cant_puertas > 0:
                ancho_disp_p = ancho_m - (esp * 2) - ancho_hueco_cajon - esp_parante
                total_luces = (luz_e * 2) + (luz_i * (cant_puertas - 1))
                ancho_sugerido = (ancho_disp_p - total_luces) / cant_puertas
                st.info(f"💡 Simetría BVM: {ancho_sugerido:.1f} mm c/u")

            medidas_puertas = [st.number_input(f"Ancho Puerta {i+1} (mm)", value=0, key=f"pue_{i}") for i in range(int(cant_puertas))]
            medidas_estantes = [st.number_input(f"Ancho Estante {i+1} (mm)", value=0, key=f"est_{i}") for i in range(int(cant_estantes))]
            
            cant_travesaños = st.number_input("Cantidad de Travesaños", value=2, min_value=0)
            medidas_travesaños = []
            for i in range(int(cant_travesaños)):
                ct1, ct2 = st.columns(2)
                l_t = ct1.number_input(f"Largo T_{i+1}", value=int(ancho_m-36 if ancho_m>36 else 0), key=f"lt_{i}")
                a_t = ct2.number_input(f"Ancho T_{i+1}", value=100, key=f"at_{i}")
                medidas_travesaños.append({"L": l_t, "A": a_t})

            st.write("---")
            st.subheader("💰 Parámetros Financieros")
            tipo_base = st.selectbox("Soporte", ["Zócalo Madera", "Patas Plásticas", "Nada"])
            costo_base = 5000 if tipo_base == "Patas Plásticas" else 0
            dias_prod = st.number_input("Días de taller", value=1.0, step=0.5)
            necesita_colocacion = st.checkbox("¿Requiere Colocación?")
            flete_sel = st.selectbox("Zona Envío", ["Ninguno", "Capital", "Zona Norte"])
            dias_col = st.number_input("Días de obra", value=0) if necesita_colocacion else 0

        with col_out:
            st.subheader("📐 Planilla de Corte Automática")
            despiece = []
            if alto_m > 0 and ancho_m > 0:
                # --- MOTOR DE DESPIECE ---
                despiece.append({"Pieza": "Lateral_Ext", "Cant": 2, "L": alto_m, "A": prof_m})
                despiece.append({"Pieza": "Piso", "Cant": 1, "L": ancho_m - 36, "A": prof_m})
                if tiene_parante: despiece.append({"Pieza": "Parante", "Cant": 1, "L": alto_m - 18, "A": prof_m - 20})
                for i, t in enumerate(medidas_travesaños): despiece.append({"Pieza": f"T_{i+1}", "Cant": 1, "L": t["L"], "A": t["A"]})
                
                df_final = st.data_editor(pd.DataFrame(despiece), use_container_width=True)
                
                # --- COSTOS ---
                m2_18 = (alto_m * ancho_m) / 1_000_000
                costo_mat = (m2_18 * maderas[mat_principal] / 5.03) * 1.10
                total_final = costo_mat + (dias_prod * 179768) + costo_base
                if necesita_colocacion: total_final += (dias_col * 100000)
                total_final *= 1.15 # Ganancia
                
                st.metric("PRECIO FINAL", f"${total_final:,.2f}")
                
                c_save1, c_save2 = st.columns(2)
                with c_save1:
                    if st.button("💾 Guardar Local"):
                        ejecutar_query("INSERT INTO presupuestos_guardados (cliente, mueble, precio_final, estado) VALUES (?, ?, ?, ?)", (cliente, mueble_nom, total_final, "Pendiente"))
                        st.success("Guardado Local.")
                with c_save2:
                    if st.button("💾 Guardar en Nube"):
                        guardar_presupuesto_nube(cliente, mueble_nom, total_final)
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
            if st.button("💾 Sincronizar Nube"):
                conn_nube.update(worksheet="ventas", data=df_editado)
                st.success("Sincronizado.")
    except Exception as e:
        st.error(f"Error de conexión: {e}")