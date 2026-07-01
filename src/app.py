python
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
try:
    from motor.optimizador import optimizar_obra, generar_svg_placa, PLACA_ANCHO_DEFAULT, PLACA_ALTO_DEFAULT
    _OPTIMIZADOR_DISPONIBLE = True
except ImportError:
    _OPTIMIZADOR_DISPONIBLE = False

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Helpers de conversión segura ─────────────────────────────────────────
def _safe_int(val, default=0) -> int:
    """Convierte a int sin crashear — maneja None, '', strings, floats."""
    try:
        if val is None or val == "": return default
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default

def _safe_float(val, default=0.0) -> float:
    """Convierte a float sin crashear — maneja None, '', strings."""
    try:
        if val is None or val == "": return default
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


# ===========================================================================
# MODELOS DE DATOS (Pydantic) — single source of truth para un Módulo
# ===========================================================================
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any

class ModuloBVM(BaseModel):
    """Representa un módulo de mueble dentro de una obra. Valida y normaliza
    los datos venga de donde venga: form nuevo, Supabase plano, o legacy."""
    model_config = {"extra": "ignore"}  # tolera claves desconocidas sin crashear

    tipo_modulo: str = "Bajo Mesada"
    nombre: str = ""
    ancho_m: float = 0.0
    alto_m: float = 0.0
    prof_m: float = 0.0
    mat_principal: str = ""
    mat_fondo_sel: str = "Fibroplus Blanco 3mm"
    esp_real: float = 18.0
    precio_guardado: float = 0.0

    tipo_tapa: str = "Superpuesta"
    cant_puertas: int = 2
    cant_cajones: int = 0
    tiene_parante: bool = False
    tipo_parante: str = "Corto (100mm)"
    tiene_parante_medio: bool = False
    distancia_parante: float = 0.0

    tipo_base: str = "Nada"
    altura_base: float = 0.0

    estantes_fijos: int = 0
    estantes_moviles: int = 0
    tipo_estante_manual: str = "Completo"
    indices_estantes_fijos: List[int] = Field(default_factory=list)

    sin_fondo: bool = False
    luz_entre_tapas: float = 3.0
    luz_perimetral_tapa: float = 4.0
    alto_frentin_emb: float = 0.0
    aire_trasero: float = 30.0
    esp_corredera: float = 13.0
    distribucion_tapas: str = "Iguales"
    tiene_cenefa: bool = False
    alto_cenefa: float = 0.0
    dias_prod: float = 0.0
    herrajes_extra: Dict[str, int] = Field(default_factory=dict)

    # Placard
    division_placard: str = "Sin división"
    zona_izq: str = "Solo estantes"
    zona_der: str = "Solo estantes"
    zona_unica: str = "Solo estantes"
    altura_tubo: float = 1200.0
    cant_estantes_izq_fijos: int = 0
    cant_estantes_izq_moviles: int = 0
    cant_estantes_der_fijos: int = 0
    cant_estantes_der_moviles: int = 0
    cant_estantes_unica_fijos: int = 1
    cant_estantes_unica_moviles: int = 0
    cant_cajones_placard: int = 0
    tiene_frentin_placard: bool = False

    # Pieza Suelta
    cant_paneles: int = 1
    nota_pieza: str = ""

    @field_validator("ancho_m", "alto_m", "prof_m", "esp_real", "precio_guardado",
                      "distancia_parante", "altura_base", "luz_entre_tapas",
                      "luz_perimetral_tapa", "alto_frentin_emb", "aire_trasero",
                      "esp_corredera", "alto_cenefa", "dias_prod", "altura_tubo",
                      mode="before")
    @classmethod
    def _coerce_float(cls, v):
        return _safe_float(v, 0.0)

    @field_validator("cant_puertas", "cant_cajones", "estantes_fijos", "estantes_moviles",
                      "cant_estantes_izq_fijos", "cant_estantes_izq_moviles",
                      "cant_estantes_der_fijos", "cant_estantes_der_moviles",
                      "cant_estantes_unica_fijos", "cant_estantes_unica_moviles",
                      "cant_cajones_placard", "cant_paneles",
                      mode="before")
    @classmethod
    def _coerce_int(cls, v):
        return _safe_int(v, 0)

    @classmethod
    def from_raw(cls, m: dict) -> "ModuloBVM":
        """Construye el modelo tolerando el formato aplanado o anidado que
        puede llegar desde Supabase, desde un módulo nuevo del form, o legacy."""
        if not isinstance(m, dict):
            return cls()
        p = m.get("params") if isinstance(m.get("params"), dict) else {}
        # Mezcla: params tiene prioridad sobre raíz aplanada, salvo los alias
        merged = {**m, **p}
        merged.setdefault("tipo_modulo", m.get("tipo_modulo") or m.get("tipo") or p.get("tipo_modulo", "Bajo Mesada"))
        merged.setdefault("ancho_m", m.get("ancho_m", m.get("ancho", p.get("ancho_m", 0))))
        merged.setdefault("alto_m",  m.get("alto_m",  m.get("alto",  p.get("alto_m",  0))))
        merged.setdefault("prof_m",  m.get("prof_m",  m.get("prof",  p.get("prof_m",  0))))
        merged.setdefault("mat_principal", m.get("mat_principal") or m.get("material") or p.get("mat_principal", ""))
        merged.setdefault("precio_guardado", m.get("precio", p.get("precio_guardado", 0)))
        merged.setdefault("nombre", m.get("nombre") or p.get("nombre") or "")
        merged.setdefault("tipo_tapa", p.get("tipo_tapa", m.get("tipo_tapa", "Superpuesta")))
        return cls(**merged)

    def to_legacy_dict(self) -> dict:
        """Serializa al formato plano que ya consume el resto del sistema."""
        return self.model_dump()


load_dotenv(dotenv_path=BASE_DIR / '.env')

try:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
except (KeyError, FileNotFoundError):
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
    """Genera CSV con todos los módulos para Aspire, separados por módulo.
    Los fondos y pisos usan el material de fondo del módulo, no el principal."""
    filas = []
    for mod in modulos_con_df:
        df = mod.get("df_corte")
        nombre_mod  = mod.get("nombre", "Modulo")
        mat_cuerpo  = mod.get("material", "")
        mat_fondo   = mod.get("params", {}).get("mat_fondo_sel", "Fibroplus Blanco 3mm")
        esp_fondo   = 3.0  # espesor estándar del fondo (3mm o 5.5mm)
        if "5.5" in mat_fondo or "Faplac" in mat_fondo:
            esp_fondo = 5.5
        if df is None or df.empty:
            continue
        filas.append({"Name": f"=== {nombre_mod} ===", "Length": "", "Width": "", "Thickness": "", "Quantity": "", "Material": ""})
        for _, row in df.iterrows():
            es_fondo = str(row.get("Tipo","")).lower() in ["fondo", "piso"]
            filas.append({
                "Name":      f"{row['Pieza']} [{nombre_mod}]",
                "Length":    row['L'],
                "Width":     row['A'],
                "Thickness": esp_fondo if es_fondo else esp_real,
                "Quantity":  row['Cant'],
                "Material":  mat_fondo if es_fondo else mat_cuerpo,
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
    except Exception as e:
        pass
    return False

def get_token():
    """Devuelve el token vigente, refrescando si es necesario."""
    if "session" not in st.session_state or not st.session_state["session"]:
        return None
    try:
        token = st.session_state["session"].access_token
        if not token:
            return None
        supabase.postgrest.auth(token)
        return token
    except Exception as e:
        err = str(e).lower()
        if "jwt" in err or "expired" in err or "unauthorized" in err:
            if refrescar_sesion():
                new_token = st.session_state.get("session", {})
                if hasattr(new_token, "access_token"):
                    return new_token.access_token
        return None

@st.cache_data(ttl=120, show_spinner=False)
def _traer_retazos_db(scope_id: str, usa_taller: bool):
    """Carga retazos desde Supabase. Cacheado 2 minutos."""
    query = supabase.table("retazos").select("*")
    query = query.eq("taller_id", scope_id) if usa_taller else query.eq("user_id", scope_id)
    return query.execute().data

def _scope_lectura():
    """Devuelve (scope_id, usa_taller) listo para pasar a las funciones cacheadas."""
    tid = _taller_id_actual()
    if tid:
        return tid, True
    return _user_id(), False

def consultar_retazos_disponibles(material):
    try:
        token = get_token()
        if not token: return []
        supabase.postgrest.auth(token)
        _sid, _ut = _scope_lectura()
        return _traer_retazos_db(_sid, _ut)
    except Exception as e:
        err = str(e)
        if "JWT" in err or "expired" in err.lower() or "PGRST303" in err:
            if refrescar_sesion():
                try:
                    _traer_retazos_db.clear()
                    _sid, _ut = _scope_lectura()
                    return _traer_retazos_db(_sid, _ut)
                except Exception:
                    pass
        st.warning("Sesión expirada. Recargá la página si el problema persiste.")
        return []

def registrar_retazo(material, largo, ancho):
    try:
        if (largo >= 400 and ancho >= 150) or (largo >= 150 and ancho >= 400):
            supabase.table("retazos").insert({
                "material": material, "largo": largo, "ancho": ancho,
                "user_id": _user_id(), "taller_id": _taller_id_actual(),
            }).execute()
            _traer_retazos_db.clear()
            st.toast(f"Retazo guardado: {int(largo)}x{int(ancho)}")
        else:
            st.error(f"Error: {int(largo)}x{int(ancho)} inferior al mínimo 150x400.")
    except Exception as e:
        st.error(f"Error al registrar: {e}")


# ===========================================================================
# MULTI-USUARIO POR TALLER
# ===========================================================================

@st.cache_data(ttl=600, show_spinner=False)
def _resolver_datos_miembro(user_id: str):
    """Busca el taller_id, rol y nombre del taller para el usuario actual."""
    try:
        res = supabase.table("miembros_taller").select("taller_id, rol").eq("user_id", user_id).limit(1).execute()
        if res.data:
            t_id = res.data[0]["taller_id"]
            rol = res.data[0]["rol"]
            try:
                res_taller = supabase.table("talleres").select("nombre").eq("id", t_id).limit(1).execute()
                nombre_taller = res_taller.data[0]["nombre"] if res_taller.data else "Taller Compartido"
            except Exception:
                nombre_taller = "Taller Compartido"
            return {"taller_id": t_id, "rol": rol, "nombre_taller": nombre_taller}
    except Exception:
        pass
    return None

def _resolver_taller_id(user_id: str):
    """Busca si el usuario pertenece a un taller compartido."""
    info = _resolver_datos_miembro(user_id)
    return info["taller_id"] if info else None

def _obtener_rol_actual() -> Optional[str]:
    """Obtiene el rol del usuario actual en el taller ('dueño', 'empleado' o None)."""
    uid = _user_id()
    if not uid:
        return None
    info = _resolver_datos_miembro(uid)
    return info["rol"] if info else None

def _scope_id() -> str:
    """ID a usar para FILTRAR lecturas (select) de configuracion/ventas/retazos."""
    if "user" not in st.session_state or not st.session_state["user"]:
        return ""
    uid = st.session_state["user"].id
    taller_id = _resolver_taller_id(uid)
    return taller_id or uid

def _user_id() -> str:
    """El user_id real del usuario logueado."""
    if "user" not in st.session_state or not st.session_state["user"]:
        return ""
    return st.session_state["user"].id

def _taller_id_actual():
    """El taller_id del usuario logueado, o None si trabaja individual."""
    uid = _user_id()
    if not uid:
        return None
    return _resolver_taller_id(uid)

@st.cache_data(ttl=600, show_spinner=False)
def _resolver_owner_de_taller(taller_id: str):
    """Dado un taller_id, devuelve el owner_id de ese taller."""
    try:
        res = supabase.table("talleres").select("owner_id").eq("id", taller_id).limit(1).execute()
        if res.data:
            return res.data[0]["owner_id"]
    except Exception:
        pass
    return None

def _owner_id_para_escritura() -> str:
    """user_id a usar al ESCRIBIR en configuracion: si el usuario pertenece
    a un taller, siempre es el owner del taller."""
    uid = _user_id()
    tid = _taller_id_actual()
    if tid:
        owner = _resolver_owner_de_taller(tid)
        if owner:
            return owner
    return uid

def abandonar_taller() -> bool:
    """Permite a un empleado desvincularse y abandonar el taller compartido actual."""
    try:
        uid = _user_id()
        if not uid:
            return False
        info = _resolver_datos_miembro(uid)
        if not info:
            return False
        
        if info["rol"] == "dueño":
            st.error("Como dueño del taller, no podés abandonarlo directamente. Debés transferir la propiedad o eliminarlo.")
            return False
        
        # Eliminar el registro del miembro
        supabase.table("miembros_taller").delete().eq("taller_id", info["taller_id"]).eq("user_id", uid).execute()
        
        # Invalidar la caché
        _resolver_datos_miembro.clear()
        _resolver_taller_id.clear()
        _traer_datos_db.clear()
        _traer_retazos_db.clear()
        _traer_historial_db.clear()
        return True
    except Exception as e:
        st.error(f"Error al abandonar el taller: {e}")
        return False

def invitar_a_taller(email_invitado: str) -> bool:
    """Agrega a otro usuario (por email) al mismo taller del usuario actual.
    Previene auto-invitaciones, invitaciones redundantes y garantiza jerarquía."""
    try:
        uid = _user_id()
        if not uid:
            return False
            
        # 1. Evitar que se auto-invite
        email_actual = st.session_state.get("user", None)
        email_actual = email_actual.email if email_actual and hasattr(email_actual, "email") else ""
        if email_invitado.lower().strip() == email_actual.lower().strip():
            st.error("No podés invitarte a vos mismo.")
            return False

        # 2. Verificar que quien invita sea un Propietario o no sea empleado de otro
        info_propia = _resolver_datos_miembro(uid)
        if info_propia and info_propia["rol"] != "dueño":
            st.error("Solo el dueño del taller puede realizar invitaciones.")
            return False

        # 3. Buscar el user_id del invitado por email
        res_user = supabase.table("perfiles").select("id").eq("email", email_invitado).limit(1).execute()
        if not res_user.data:
            st.error("Ese email no tiene cuenta en BVM todavía. Pedile que se registre primero.")
            return False
        invitado_id = res_user.data[0]["id"]

        # 4. Verificar que el invitado no tenga ya un taller activo
        info_invitado = _resolver_datos_miembro(invitado_id)
        if info_invitado:
            st.error("El usuario invitado ya pertenece a un taller activo. Debe abandonarlo para que puedas agregarlo.")
            return False

        taller_id = info_propia["taller_id"] if info_propia else None
        if not taller_id:
            # Crear taller nuevo con el usuario actual como dueño
            nuevo = supabase.table("talleres").insert({"owner_id": uid, "nombre": "Mi Taller"}).execute()
            taller_id = nuevo.data[0]["id"]
            supabase.table("miembros_taller").insert({"taller_id": taller_id, "user_id": uid, "rol": "dueño"}).execute()

        # Insertar al nuevo miembro de tipo empleado
        supabase.table("miembros_taller").insert({"taller_id": taller_id, "user_id": invitado_id, "rol": "empleado"}).execute()
        
        # Invalidar la caché de los datos vinculados
        _resolver_datos_miembro.clear()
        _resolver_taller_id.clear()
        return True
    except Exception as e:
        st.error(f"No se pudo invitar: {e}")
        return False


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
        _owner_id = _owner_id_para_escritura()
        _tid = _taller_id_actual()
        supabase.table("configuracion").upsert(
            {"user_id": _owner_id, "taller_id": _tid, "clave": clave, "valor": float(valor), "categoria": categoria},
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
        _owner_id = _owner_id_para_escritura()
        supabase.table("configuracion").delete().eq("user_id", _owner_id).eq("clave", clave).eq("categoria", categoria).execute()
    except Exception as e:
        st.error(f"Error al eliminar {clave}: {e}")

@st.cache_data(ttl=300, show_spinner=False)
def _traer_datos_db(scope_id: str, token: str, usa_taller: bool):
    """Carga configuración desde Supabase. Cacheada 5 minutos por scope."""
    supabase.postgrest.auth(token)
    query = supabase.table("configuracion").select("*")
    query = query.eq("taller_id", scope_id) if usa_taller else query.eq("user_id", scope_id)
    datos_db = query.execute().data
    maderas_db = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria','')).lower().strip() == 'maderas'}
    config_db  = {d['clave']: d['valor'] for d in datos_db if str(d.get('categoria','')).lower().strip() in ['costos','margen','herrajes']}
    return maderas_db, config_db

def traer_datos():
    MADERAS_DEFAULT = {"Melamina Blanca 18mm": 60000.0, "Melamina Color 18mm": 85000.0, "Enchapado Roble 18mm": 120000.0}
    CONFIG_DEFAULT  = {'bisagra_cazoleta': 1200.0, 'telescopica_45': 5000.0, 'telescopica_soft': 12000.0,
                       'gastos_fijos_diarios': 25000.0, 'flete_capital': 15000.0, 'flete_norte': 20000.0,
                       'colocacion_dia': 45000.0, 'ganancia_taller_pct': 0.30}
    FONDOS          = {'Fibroplus Blanco 3mm': 34500.0, 'Faplac Fondo 5.5mm': 45000.0, 'Sin fondo': 0.0}

    if "session" not in st.session_state or not st.session_state["session"]:
        return MADERAS_DEFAULT, {'Fibroplus Blanco 3mm': 34500.0, 'Sin fondo': 0.0}, CONFIG_DEFAULT

    try:
        token = get_token()
        if not token: raise Exception("No token")
        _tid = _taller_id_actual()
        if _tid:
            maderas_db, config_db = _traer_datos_db(_tid, token, usa_taller=True)
        else:
            maderas_db, config_db = _traer_datos_db(_user_id(), token, usa_taller=False)
        return {**MADERAS_DEFAULT, **maderas_db}, FONDOS, {**CONFIG_DEFAULT, **config_db}
    except Exception:
        st.warning("La sesión se actualizó. Por favor, recargá la página.")
        st.stop()

def guardar_presupuesto_nube(cliente, mueble, total, parametros=None, id_editar=None):
    try:
        data = {"cliente": cliente, "mueble": mueble, "precio_final": float(total),
                "user_id": _user_id(),
                "taller_id": _taller_id_actual(),
                "fecha": datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M"),
                "parametros": json.dumps(parametros) if parametros else None}
        if id_editar:
            supabase.table("ventas").update(data).eq("id", id_editar).execute()
            _traer_historial_db.clear()
            st.success("✅ Presupuesto actualizado.")
        else:
            data["estado"] = "Pendiente"
            supabase.table("ventas").insert(data).execute()
            _traer_historial_db.clear()
            st.success("✅ Presupuesto guardado.")
    except Exception as e:
        err_msg = str(e)
        if "JWT" in err_msg or "expired" in err_msg.lower():
            st.error("Sesión expirada. Recargá la página e intentá de nuevo.")
        elif "duplicate" in err_msg.lower():
            st.error("Ya existe un registro con esos datos.")
        else:
            st.error(f"Error al guardar: {err_msg}")

@st.cache_data(ttl=60, show_spinner=False)
def _traer_historial_db(scope_id: str, usa_taller: bool):
    """Carga historial desde Supabase. Cacheado 60 segundos."""
    query = supabase.table("ventas").select("*")
    query = query.eq("taller_id", scope_id) if usa_taller else query.eq("user_id", scope_id)
    return pd.DataFrame(query.execute().data)

def traer_datos_historial():
    try:
        _sid, _ut = _scope_lectura()
        return _traer_historial_db(_sid, _ut)
    except Exception:
        return pd.DataFrame()

def generar_svg_mueble(tipo_modulo, ancho_m, alto_m, prof_m, tipo_tapa, cant_puertas, cant_cajones, estantes_fijos, estantes_moviles, tiene_parante, sin_fondo, distribucion_tapas="Iguales", tipo_base="Nada", altura_base=0, **kwargs):
    """Genera un SVG esquemático del mueble con proporciones reales."""
    ancho_m = _safe_float(ancho_m)
    alto_m  = _safe_float(alto_m)
    if ancho_m <= 0 or alto_m <= 0:
        return ""
    ancho_m = min(ancho_m, 9999)
    alto_m  = min(alto_m,  9999)

    W   = 300
    pad = 16
    esp = 10

    tiene_soporte = tipo_base not in ("Nada", "", None)
    soporte_px    = 22 if tiene_soporte else 0
    H_mueble = int(W * (alto_m / ancho_m))
    H_mueble = max(130, min(H_mueble, 370))
    H = H_mueble + soporte_px + pad

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
    c_metal      = "#B0B0B0"

    caja_y = pad
    caja_h = H_mueble

    ix = pad + esp
    iy = caja_y + esp
    iw = W - pad*2 - esp*2
    ih = caja_h - esp*2

    lines = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;border-radius:8px;">']

    if tiene_soporte:
        sx     = pad
        sy     = caja_y + caja_h
        sw     = W - pad * 2
        sh     = soporte_px

        if tipo_base == "Zócalo de Madera":
            lines.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="1" fill="{c_soporte}" stroke="{c_estructura}" stroke-width="1"/>')
            lines.append(f'<rect x="{sx+4}" y="{sy+3}" width="{sw-8}" height="{sh-6}" rx="1" fill="{c_soporte}" opacity="0.5" stroke="{c_estructura}" stroke-width="0.5"/>')
            lines.append(f'<text x="{W//2}" y="{sy+sh//2+4}" text-anchor="middle" font-size="7" fill="white" opacity="0.8">ZÓCALO</text>')

        elif tipo_base == "Banquina":
            bw = sw // 5
            lines.append(f'<rect x="{sx}"        y="{sy}" width="{bw}" height="{sh}" rx="1" fill="{c_soporte}" stroke="{c_estructura}" stroke-width="1"/>')
            lines.append(f'<rect x="{sx+sw-bw}"  y="{sy}" width="{bw}" height="{sh}" rx="1" fill="{c_soporte}" stroke="{c_estructura}" stroke-width="1"/>')
            lines.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="4" fill="{c_soporte}" opacity="0.6"/>')
            lines.append(f'<text x="{W//2}" y="{sy+sh//2+4}" text-anchor="middle" font-size="7" fill="{c_texto}" opacity="0.7">BANQUINA</text>')

        elif tipo_base == "Patas Plásticas":
            pw2 = 10
            ph2 = sh - 2
            posiciones = [sx+6, sx+sw//3, sx+2*sw//3, sx+sw-pw2-6]
            for px2 in posiciones:
                lines.append(f'<rect x="{px2}" y="{sy+2}" width="{pw2}" height="{ph2}" rx="3" fill="{c_metal}" stroke="#888" stroke-width="0.8"/>')
                lines.append(f'<ellipse cx="{px2+pw2//2}" cy="{sy+2}" rx="{pw2//2}" ry="2.5" fill="{c_metal}" stroke="#888" stroke-width="0.8"/>')
            lines.append(f'<text x="{W//2}" y="{sy+sh+10}" text-anchor="middle" font-size="7" fill="{c_texto}" opacity="0.6">PATAS</text>')

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

    elif tipo_modulo == "Placard":
        _div = kwargs.get("division_placard", "Sin división")
        _z_izq   = kwargs.get("zona_izq",   "Solo estantes")
        _z_der   = kwargs.get("zona_der",   "Solo estantes")
        _z_unica = kwargs.get("zona_unica", "Solo estantes")

        frenin_h = int(ih * 0.07)
        lines.append(f'<rect x="{ix}" y="{iy}" width="{iw}" height="{frenin_h}" fill="{c_estructura}" opacity="0.5"/>')

        if _div == "Una división central":
            mid_x = ix + iw // 2
            lines.append(f'<rect x="{mid_x - 2}" y="{iy}" width="4" height="{ih}" fill="{c_estructura}"/>')
            zonas_svg = [
                (ix, iw // 2 - 2, _z_izq),
                (mid_x + 2, iw // 2 - 2, _z_der),
            ]
        elif _div == "Dos divisiones":
            tercio = iw // 3
            x1 = ix + tercio
            x2 = ix + tercio * 2
            lines.append(f'<rect x="{x1 - 2}" y="{iy}" width="4" height="{ih}" fill="{c_estructura}"/>')
            lines.append(f'<rect x="{x2 - 2}" y="{iy}" width="4" height="{ih}" fill="{c_estructura}"/>')
            zonas_svg = [
                (ix,      tercio - 2, _z_izq),
                (x1 + 2,  tercio - 4, _z_unica),
                (x2 + 2,  iw - tercio * 2 - 2, _z_der),
            ]
        else:  # Sin división
            zonas_svg = [(ix, iw, _z_unica)]

        for zx, zw, ztipo in zonas_svg:
            zy_content = iy + frenin_h + 4
            zh_content = ih - frenin_h - 8
            if ztipo == "Solo estantes":
                paso = zh_content // 4
                for k in range(1, 4):
                    sy = zy_content + paso * k
                    lines.append(f'<rect x="{zx+2}" y="{sy}" width="{zw-4}" height="3" rx="1" fill="{c_estante}" opacity="0.6"/>')
            elif ztipo == "Ropa colgada":
                tubo_y = zy_content + int(zh_content * 0.60)
                lines.append(f'<rect x="{zx+4}" y="{tubo_y}" width="{zw-8}" height="4" rx="2" fill="{c_metal}" opacity="0.8"/>')
                paso_p = (zw - 8) // 4
                for k in range(1, 4):
                    px_p = zx + 4 + paso_p * k
                    lines.append(f'<line x1="{px_p}" y1="{tubo_y}" x2="{px_p - 6}" y2="{tubo_y + 12}" stroke="{c_metal}" stroke-width="1.5" opacity="0.6"/>')
                    lines.append(f'<line x1="{px_p}" y1="{tubo_y}" x2="{px_p + 6}" y2="{tubo_y + 12}" stroke="{c_metal}" stroke-width="1.5" opacity="0.6"/>')
                lines.append(f'<rect x="{zx+2}" y="{zy_content + 6}" width="{zw-4}" height="3" rx="1" fill="{c_estante}" opacity="0.6"/>')
            elif ztipo == "Cajones":
                paso_c = zh_content // 3
                for k in range(3):
                    cy = zy_content + paso_c * k + 2
                    lines.append(f'<rect x="{zx+3}" y="{cy}" width="{zw-6}" height="{paso_c - 4}" rx="1" fill="{c_cajon}" opacity="0.7" stroke="{c_estructura}" stroke-width="0.5"/>')
                    lines.append(f'<rect x="{zx + zw//2 - 8}" y="{cy + (paso_c-4)//2 - 2}" width="16" height="4" rx="2" fill="{c_manija}" opacity="0.8"/>')

    elif tipo_modulo == "Pieza Suelta":
        lines.append(f'<rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" rx="3" fill="none" stroke="{c_estructura}" stroke-width="1.5" stroke-dasharray="6,4" opacity="0.5"/>')
        mid_x = ix + iw // 2
        mid_y = iy + ih // 2
        lines.append(f'<text x="{mid_x}" y="{mid_y - 8}" text-anchor="middle" font-size="14" fill="{c_texto}" opacity="0.5" font-weight="bold">{int(ancho_m)}</text>')
        lines.append(f'<text x="{mid_x}" y="{mid_y + 6}" text-anchor="middle" font-size="10" fill="{c_texto}" opacity="0.4">×</text>')
        lines.append(f'<text x="{mid_x}" y="{mid_y + 20}" text-anchor="middle" font-size="14" fill="{c_texto}" opacity="0.5" font-weight="bold">{int(alto_m)}</text>')
        lines.append(f'<line x1="{ix+2}" y1="{iy + ih//2}" x2="{ix + iw - 2}" y2="{iy + ih//2}" stroke="{c_texto}" stroke-width="0.5" opacity="0.2"/>')
        lines.append(f'<line x1="{ix + iw//2}" y1="{iy + 2}" x2="{ix + iw//2}" y2="{iy + ih - 2}" stroke="{c_texto}" stroke-width="0.5" opacity="0.2"/>')

    _label_soporte = f" + {tipo_base}" if tiene_soporte else ""
    lines.append(f'<text x="{W//2}" y="{H-2}" text-anchor="middle" font-size="8" fill="{c_texto}" opacity="0.5">{int(ancho_m)}×{int(alto_m)} mm{_label_soporte}</text>')
    lines.append('</svg>')
    return '\n'.join(lines)


# ===========================================================================
# INTERFAZ
# ===========================================================================
st.set_page_config(page_title="BVM — Sistema de Gestión para Carpintería", page_icon="🪵", layout="wide")

st.markdown("""<style>
/* ── Variables de diseño BVM ───────────────────────────────────── */
:root {
    --bvm-green:        #0F6E56;
    --bvm-green-light:  #1D9E75;
    --bvm-green-pale:   #E1F5EE;
    --bvm-surface:      #F8F8F6;
    --bvm-border:       #E0DED6;
    --bvm-text:         #1A1A1A;
    --bvm-text-muted:   #888780;
    --bvm-radius:       10px;
    --bvm-shadow:       0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --bvm-shadow-md:    0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
}

/* ── Tipografía global ─────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
}
h1 { font-size: 21px !important; font-weight: 600 !important; color: var(--bvm-text) !important; letter-spacing: -0.3px !important; }
h2 { font-size: 16px !important; font-weight: 600 !important; color: var(--bvm-text) !important; }
h3 { font-size: 14px !important; font-weight: 600 !important; color: var(--bvm-text) !important; }

/* ── Layout principal ──────────────────────────────────────────── */
[data-testid="stAppViewContainer"] > .main .block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1400px !important;
}

/* ── Sidebar premium ───────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0F6E56 0%, #0A5240 100%) !important;
    border-right: none !important;
    box-shadow: 2px 0 12px rgba(0,0,0,0.15) !important;
}
[data-testid="stSidebar"] * { color: rgba(255,255,255,0.88) !important; }
[data-testid="stSidebar"] .stRadio label {
    color: rgba(255,255,255,0.75) !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    padding: 4px 0 !important;
    transition: color 0.15s !important;
}
[data-testid="stSidebar"] .stRadio label:hover { color: white !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.12) !important; margin: 8px 0 !important; }
[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.08) !important;
    color: rgba(255,255,255,0.85) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    transition: background 0.15s !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.15) !important;
}
[data-testid="stSidebarNav"] { display: none; }

/* ── Botones ───────────────────────────────────────────────────── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1D9E75 0%, #0F6E56 100%) !important;
    border: none !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 13.5px !important;
    letter-spacing: 0.01em !important;
    box-shadow: 0 2px 6px rgba(15,110,86,0.3) !important;
    transition: all 0.15s !important;
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 4px 12px rgba(15,110,86,0.4) !important;
    transform: translateY(-1px) !important;
}
.stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    font-size: 13px !important;
    border-color: var(--bvm-border) !important;
    color: #444 !important;
    transition: border-color 0.15s, background 0.15s !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: var(--bvm-green-light) !important;
    color: var(--bvm-green) !important;
    background: var(--bvm-green-pale) !important;
}

/* ── Métricas ──────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: white !important;
    border-radius: var(--bvm-radius) !important;
    padding: 16px 18px !important;
    border: 1px solid var(--bvm-border) !important;
    box-shadow: var(--bvm-shadow) !important;
    transition: box-shadow 0.15s !important;
}
[data-testid="stMetric"]:hover { box-shadow: var(--bvm-shadow-md) !important; }
[data-testid="stMetricLabel"] {
    font-size: 11px !important;
    color: var(--bvm-text-muted) !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    font-weight: 600 !important;
}
[data-testid="stMetricValue"] { font-size: 24px !important; font-weight: 700 !important; color: var(--bvm-text) !important; }
[data-testid="stMetricDelta"] { font-size: 12px !important; }

/* ── Expanders ─────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid var(--bvm-border) !important;
    border-radius: var(--bvm-radius) !important;
    margin-bottom: 10px !important;
    box-shadow: var(--bvm-shadow) !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 12px 16px !important;
    background: var(--bvm-surface) !important;
    border-radius: var(--bvm-radius) !important;
    letter-spacing: 0.01em !important;
}
[data-testid="stExpander"] summary:hover { background: #F0F0EC !important; }

/* ── Inputs ────────────────────────────────────────────────────── */
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    border-radius: 7px !important;
    font-size: 13px !important;
    border-color: var(--bvm-border) !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
}
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextInput"] input:focus {
    border-color: var(--bvm-green-light) !important;
    box-shadow: 0 0 0 3px rgba(29,158,117,0.12) !important;
}
[data-testid="stSelectbox"] > div > div {
    border-radius: 7px !important;
    border-color: var(--bvm-border) !important;
    font-size: 13px !important;
}

/* ── Alertas e info ────────────────────────────────────────────── */
[data-testid="stAlert"]        { border-radius: 8px !important; font-size: 13px !important; }
[data-testid="stInfo"]         { background: var(--bvm-green-pale) !important; border-left: 3px solid var(--bvm-green-light) !important; border-radius: 0 8px 8px 0 !important; }
[data-testid="stSuccess"]      { border-radius: 8px !important; }
[data-testid="stDownloadButton"] button { border-radius: 8px !important; font-size: 13px !important; font-weight: 500 !important; }

/* ── Data editor / tablas ──────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 8px !important; overflow: hidden !important; border: 1px solid var(--bvm-border) !important; }

/* ── Toast notifications ───────────────────────────────────────── */
[data-testid="stToast"] {
    border-radius: 10px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.12) !important;
}

/* ── Scrollbar custom ──────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #D3D1C7; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #B0AEA6; }

/* ── Dividers ──────────────────────────────────────────────────── */
hr { border-color: var(--bvm-border) !important; margin: 16px 0 !important; }
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
for k, v in {
    "obra_modulos":  [],
    "edit_ctx":      None,
    "ultimo_agregado": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

maderas, fondos, config = traer_datos()

# Identificadores de permisos y rol multi-usuario
es_empleado = (_obtener_rol_actual() == "empleado")

_opciones_menu  = ["🪵 Cotizador", "♻️ Retazos", "📋 Historial", "⚙️ Precios"]
_editando_algo  = st.session_state.get("edit_ctx") is not None

# SIDEBAR
_user_email = st.session_state.get("user", None)
_user_email = _user_email.email if _user_email and hasattr(_user_email, "email") else ""
_user_initials = _user_email[:2].upper() if _user_email else "BV"
st.sidebar.markdown(f"""<div style="padding:12px 4px 16px 4px;border-bottom:1px solid rgba(255,255,255,0.12);margin-bottom:16px;">
<div style="display:flex;align-items:center;gap:10px;">
  <div style="font-size:26px;line-height:1;">🪵</div>
  <div>
    <div style="font-size:19px;font-weight:700;color:white;letter-spacing:-0.3px;">BVM</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.45);letter-spacing:0.05em;text-transform:uppercase;">Carpintería Pro</div>
  </div>
</div>
<div style="margin-top:14px;display:flex;align-items:center;gap:8px;">
  <div style="width:28px;height:28px;border-radius:50%;background:rgba(255,255,255,0.15);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:white;">{_user_initials}</div>
  <div style="font-size:11px;color:rgba(255,255,255,0.55);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:140px;">{_user_email}</div>
</div>
</div>""", unsafe_allow_html=True)

# UX: Indicador visual del Taller Activo en la barra lateral
_info_taller = _resolver_datos_miembro(_user_id())
if _info_taller:
    rol_label = "Propietario 👑" if _info_taller["rol"] == "dueño" else "Colaborador 🛠️"
    st.sidebar.markdown(f"""
    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:10px 12px;margin: -8px 0 16px 0;border:1px solid rgba(255,255,255,0.15);">
        <div style="font-size:10px;color:rgba(255,255,255,0.5);font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">TALLER ACTIVO</div>
        <div style="font-size:12px;font-weight:600;color:white;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{_info_taller["nombre_taller"]}</div>
        <div style="font-size:11px;color:#1D9E75;margin-top:2px;font-weight:500;">{rol_label}</div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.sidebar.markdown("""
    <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px;margin: -8px 0 16px 0;">
        <div style="font-size:11px;color:rgba(255,255,255,0.5);font-weight:500;">Modo de Uso: Individual</div>
    </div>
    """, unsafe_allow_html=True)

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
    """Extrae el dict de params de un módulo."""
    try:
        return ModuloBVM.from_raw(m).to_legacy_dict()
    except Exception:
        return ModuloBVM().to_legacy_dict()

def _serializar_obra_para_nube(mods):
    """Convierte lista de módulos al formato que se guarda en Supabase."""
    return [dict(_params_desde_mod(m), precio=m.get("precio", 0), nombre=m.get("nombre","")) for m in mods if m is not None]

def _limpiar_edicion():
    st.session_state["edit_ctx"] = None
    st.session_state.pop("_tipo_modulo_sel", None)
    st.session_state.pop("_ctx_sig_prev",    None)

def _guardar_obra_nube(mods, cliente, obra_id=None, total_con_logistica=None, logistica=None):
    mods  = [m for m in mods if m is not None]
    total = total_con_logistica if total_con_logistica is not None else sum(m["precio"] for m in mods)
    params = {
        "es_obra":   True,
        "modulos":   _serializar_obra_para_nube(mods),
        "logistica": logistica or {},
    }
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
    # Tipo de módulo
    # ───────────────────────────────────────────────────────────────────────
    _tipo_default = _v("tipo_modulo", "Bajo Mesada")
    _ctx_sig = f"{_tipo_default}_{_v('ancho_m',0)}_{_v('alto_m',0)}_{_v('precio_guardado',0)}" if ep else "none"
    if "_tipo_modulo_sel" not in st.session_state or st.session_state.get("_ctx_sig_prev") != _ctx_sig:
        st.session_state["_tipo_modulo_sel"] = _tipo_default
        st.session_state["_ctx_sig_prev"]    = _ctx_sig

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
    
    division_placard            = _v("division_placard", "Sin división")
    zona_izq                    = _v("zona_izq",   "Solo estantes")
    zona_der                    = _v("zona_der",   "Solo estantes")
    zona_unica                  = _v("zona_unica", "Solo estantes")
    altura_tubo                 = int(_v("altura_tubo", 1200))
    tiene_frentin_placard       = bool(_v("tiene_frentin_placard", False))
    cant_cajones_placard        = int(_v("cant_cajones_placard", 0))
    cant_estantes_izq_fijos     = int(_v("cant_estantes_izq_fijos",    0))
    cant_estantes_izq_moviles   = int(_v("cant_estantes_izq_moviles",  0))
    cant_estantes_der_fijos     = int(_v("cant_estantes_der_fijos",    0))
    cant_estantes_der_moviles   = int(_v("cant_estantes_der_moviles",  0))
    cant_estantes_unica_fijos   = int(_v("cant_estantes_unica_fijos",  1))
    cant_estantes_unica_moviles = int(_v("cant_estantes_unica_moviles",0))
    cant_paneles                = int(_v("cant_paneles", 1))
    nota_pieza                  = _v("nota_pieza", "")

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
            "Bajo Mesada":    '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="18" width="76" height="38" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="18" width="76" height="8" rx="1" fill="COLOR" opacity="0.25"/><line x1="41" y1="26" x2="41" y2="56" stroke="COLOR" stroke-width="1.2"/><rect x="5" y="30" width="33" height="22" rx="1.5" fill="COLOR" opacity="0.18"/><rect x="44" y="30" width="33" height="22" rx="1.5" fill="COLOR" opacity="0.18"/><circle cx="39" cy="41" r="2" fill="COLOR" opacity="0.6"/><circle cx="43" cy="41" r="2" fill="COLOR" opacity="0.6"/></svg>',
            "Cajonera":       '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="5" y="4" width="70" height="52" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="8" y="8" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><rect x="8" y="24" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><rect x="8" y="40" width="64" height="13" rx="1.5" fill="COLOR" opacity="0.2"/><circle cx="40" cy="14.5" r="2" fill="COLOR" opacity="0.7"/><circle cx="40" cy="30.5" r="2" fill="COLOR" opacity="0.7"/><circle cx="40" cy="46.5" r="2" fill="COLOR" opacity="0.7"/></svg>',
            "Alacena":        '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="2" width="76" height="52" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="2" width="76" height="7" rx="1" fill="COLOR" opacity="0.2"/><line x1="41" y1="9" x2="41" y2="54" stroke="COLOR" stroke-width="1.2"/><rect x="5" y="13" width="33" height="37" rx="1.5" fill="COLOR" opacity="0.18"/><rect x="44" y="13" width="33" height="37" rx="1.5" fill="COLOR" opacity="0.18"/><circle cx="39" cy="31" r="2" fill="COLOR" opacity="0.6"/><circle cx="43" cy="31" r="2" fill="COLOR" opacity="0.6"/></svg>',
            "Placard":        '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="2" width="76" height="56" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5"/><rect x="2" y="2" width="76" height="6" rx="1" fill="COLOR" opacity="0.3"/><line x1="41" y1="8" x2="41" y2="58" stroke="COLOR" stroke-width="1.5"/><rect x="5" y="11" width="33" height="4" rx="1" fill="COLOR" opacity="0.5"/><line x1="22" y1="15" x2="22" y2="40" stroke="COLOR" stroke-width="0.8" stroke-dasharray="2,2"/><rect x="44" y="11" width="33" height="4" rx="1" fill="COLOR" opacity="0.5"/><rect x="47" y="20" width="27" height="3" rx="1" fill="COLOR" opacity="0.35"/><rect x="47" y="28" width="27" height="3" rx="1" fill="COLOR" opacity="0.35"/><rect x="47" y="36" width="27" height="3" rx="1" fill="COLOR" opacity="0.35"/></svg>',
            "Pieza Suelta": '<svg viewBox="0 0 80 60" xmlns="http://www.w3.org/2000/svg"><rect x="5" y="5" width="70" height="50" rx="2" fill="COLOR" opacity="0.12" stroke="COLOR" stroke-width="1.5" stroke-dasharray="4,3"/><text x="40" y="26" text-anchor="middle" font-size="9" fill="COLOR" opacity="0.7" font-weight="bold">L</text><text x="40" y="38" text-anchor="middle" font-size="9" fill="COLOR" opacity="0.7" font-weight="bold">×</text><text x="40" y="50" text-anchor="middle" font-size="9" fill="COLOR" opacity="0.7" font-weight="bold">A</text><line x1="12" y1="8" x2="12" y2="52" stroke="COLOR" stroke-width="0.8" opacity="0.5"/><line x1="68" y1="8" x2="68" y2="52" stroke="COLOR" stroke-width="0.8" opacity="0.5"/><line x1="9" y1="10" x2="71" y2="10" stroke="COLOR" stroke-width="0.8" opacity="0.5"/><line x1="9" y1="50" x2="71" y2="50" stroke="COLOR" stroke-width="0.8" opacity="0.5"/></svg>',
        }
        col_bm, col_caj, col_ala, col_plac, col_panel = st.columns(5)
        for col_btn, nombre_btn in [(col_bm, "Bajo Mesada"), (col_caj, "Cajonera"), (col_ala, "Alacena"), (col_plac, "Placard"), (col_panel, "Pieza Suelta")]:
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
        ancho_m = c1.number_input("Ancho total (mm)", min_value=0.0, max_value=5000.0, value=float(_v("ancho_m", 0.0)), step=0.5, key="inp_ancho")
        alto_m  = c2.number_input("Alto total (mm)",  min_value=0.0, max_value=5000.0, value=float(_v("alto_m",  0.0)), step=0.5, key="inp_alto")
        prof_m  = c3.number_input("Profundidad (mm)", min_value=0.0, max_value=2000.0, value=float(_v("prof_m",  0.0)), step=0.5, key="inp_prof")
        mat_principal = st.selectbox("Material del cuerpo (18mm)", lista_maderas, index=idx_madera)
        esp_real      = st.number_input("Espesor real de placa (mm)", min_value=1.0, max_value=50.0, value=float(_v("esp_real", 18.0)), step=0.1)
        mat_fondo_sel = st.selectbox("Material del fondo", lista_fondos, index=idx_fondo)
        sin_fondo = mat_fondo_sel == "Sin fondo"

        if ancho_m > 0 and alto_m > 0:
            _warns = []
            if tipo_modulo == "Bajo Mesada" and alto_m > 950:
                _warns.append(f"⚠️ Altura {int(alto_m)}mm es inusual para un Bajo Mesada (estándar: 700-900mm)")
            if tipo_modulo == "Alacena" and alto_m > 1200:
                _warns.append(f"⚠️ Altura {int(alto_m)}mm es inusual para una Alacena (estándar: 300-900mm)")
            if ancho_m > 2400:
                _warns.append(f"⚠️ Ancho {int(ancho_m)}mm supera una placa estándar (2440mm) — verificá si necesita módulos separados")
            if prof_m > 700:
                _warns.append(f"⚠️ Profundidad {int(prof_m)}mm es inusual — verificá la medida")
            if prof_m > 0 and prof_m < 150:
                _warns.append(f"⚠️ Profundidad {int(prof_m)}mm puede ser muy pequeña")
            for w in _warns:
                st.warning(w)

      _editando = modo in ("editar_modulo_obra", "editar_legacy")
      with st.expander("🏗️ Configuración del módulo", expanded=_editando):
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

        elif tipo_modulo == "Placard":
            division_placard = _v("division_placard", "Sin división")
            zona_izq         = _v("zona_izq",   "Solo estantes")
            zona_der         = _v("zona_der",   "Solo estantes")
            zona_unica       = _v("zona_unica", "Solo estantes")
            altura_tubo      = int(_v("altura_tubo", 1200))
            tiene_frentin_placard = bool(_v("tiene_frentin_placard", False))
            cant_cajones_placard  = int(_v("cant_cajones_placard", 0))
            cant_estantes_izq_fijos    = int(_v("cant_estantes_izq_fijos",    0))
            cant_estantes_izq_moviles  = int(_v("cant_estantes_izq_moviles",  0))
            cant_estantes_der_fijos    = int(_v("cant_estantes_der_fijos",    0))
            cant_estantes_der_moviles  = int(_v("cant_estantes_der_moviles",  0))
            cant_estantes_unica_fijos  = int(_v("cant_estantes_unica_fijos",  1))
            cant_estantes_unica_moviles= int(_v("cant_estantes_unica_moviles",0))

            _div_opts = ["Sin división", "Una división central", "Dos divisiones"]
            division_placard = st.radio("División interna", _div_opts,
                                         index=_div_opts.index(division_placard) if division_placard in _div_opts else 0)
            tiene_frentin_placard = st.checkbox("¿Lleva frentín superior?", value=tiene_frentin_placard)

            _zona_opts = ["Solo estantes", "Ropa colgada", "Cajones"]
            if division_placard == "Sin división":
                st.markdown("**Contenido del placard**")
                zona_unica = st.selectbox("Tipo de zona", _zona_opts,
                                           index=_zona_opts.index(zona_unica) if zona_unica in _zona_opts else 0)
                if zona_unica == "Ropa colgada":
                    altura_tubo = st.number_input("Altura del tubo desde el piso (mm)",
                                                   value=altura_tubo, min_value=400, step=50)
                    _alto_sugerido = int(alto_m * 0.62) if alto_m > 0 else 1200
                    st.caption(f"💡 Sugerencia para {int(alto_m)}mm de alto: ~{_alto_sugerido}mm")
                c_ef, c_em = st.columns(2)
                cant_estantes_unica_fijos   = c_ef.number_input("Estantes fijos",   value=cant_estantes_unica_fijos,   min_value=0, key="est_u_f")
                cant_estantes_unica_moviles = c_em.number_input("Estantes móviles", value=cant_estantes_unica_moviles, min_value=0, key="est_u_m")
                if zona_unica == "Cajones":
                    cant_cajones_placard = st.number_input("Cantidad de cajones", value=max(1,cant_cajones_placard), min_value=1, max_value=8)

            else:
                _zonas_config = [("Zona izquierda", "zona_izq", "izq"),
                                  ("Zona derecha",   "zona_der", "der")]
                if division_placard == "Dos divisiones":
                    _zonas_config.insert(1, ("Zona central", "zona_unica", "unica"))

                for label_z, var_z, sufijo_z in _zonas_config:
                    st.markdown(f"**{label_z}**")
                    _val_actual = locals()[var_z] if var_z in locals() else "Solo estantes"
                    _nueva_zona = st.selectbox(f"Tipo — {label_z}", _zona_opts,
                                                index=_zona_opts.index(_val_actual) if _val_actual in _zona_opts else 0,
                                                key=f"zona_{sufijo_z}")
                    if var_z == "zona_izq":   zona_izq   = _nueva_zona
                    elif var_z == "zona_der": zona_der   = _nueva_zona
                    else:                     zona_unica = _nueva_zona

                    if _nueva_zona == "Ropa colgada":
                        altura_tubo = st.number_input(f"Altura tubo — {label_z} (mm)",
                                                       value=altura_tubo, min_value=400, step=50, key=f"tubo_{sufijo_z}")
                    c_ef2, c_em2 = st.columns(2)
                    if sufijo_z == "izq":
                        cant_estantes_izq_fijos   = c_ef2.number_input("Fijos",   value=cant_estantes_izq_fijos,   min_value=0, key=f"ef_{sufijo_z}")
                        cant_estantes_izq_moviles = c_em2.number_input("Móviles", value=cant_estantes_izq_moviles, min_value=0, key=f"em_{sufijo_z}")
                    elif sufijo_z == "der":
                        cant_estantes_der_fijos   = c_ef2.number_input("Fijos",   value=cant_estantes_der_fijos,   min_value=0, key=f"ef_{sufijo_z}")
                        cant_estantes_der_moviles = c_em2.number_input("Móviles", value=cant_estantes_der_moviles, min_value=0, key=f"em_{sufijo_z}")
                    else:
                        cant_estantes_unica_fijos   = c_ef2.number_input("Fijos",   value=cant_estantes_unica_fijos,   min_value=0, key=f"ef_{sufijo_z}")
                        cant_estantes_unica_moviles = c_em2.number_input("Móviles", value=cant_estantes_unica_moviles, min_value=0, key=f"em_{sufijo_z}")
                    if _nueva_zona == "Cajones":
                        cant_cajones_placard = st.number_input(f"Cajones — {label_z}", value=max(1,cant_cajones_placard), min_value=1, max_value=8, key=f"caj_{sufijo_z}")

            cant_cajones = 0

        elif tipo_modulo == "Pieza Suelta":
            st.markdown("""
<div style="background:#F0F4FF;border-left:3px solid #5B7FD4;border-radius:0 8px 8px 0;padding:12px 14px;margin-bottom:8px;">
<b style="color:#2A4099;">¿Para qué sirve?</b>
<div style="color:#2A4099;font-size:13px;margin-top:4px;line-height:1.6;">
Para piezas que no entran en ningún módulo automático:<br>
• Piezas a <b>falsa escuadra</b> (paredes que no están a 90°)<br>
• <b>Paneles de relleno</b> entre muebles y columnas<br>
• <b>Tapas de mesada</b>, espaldares, paneles decorativos<br>
• Cualquier corte especial que medís vos en obra
</div>
</div>""", unsafe_allow_html=True)
            cant_paneles = st.number_input("Cantidad de piezas", value=int(_v("cant_paneles", 1)), min_value=1, max_value=100)
            nota_pieza   = st.text_input("Descripción (opcional)", value=_v("nota_pieza", ""),
                                          placeholder="Ej: Panel lateral a falsa escuadra, Tapa mesada...")
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
        with st.expander("📦 Soporte", expanded=_editando):
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

      with st.expander("🔨 Días de taller", expanded=_editando):
          dias_prod = st.number_input("Días de trabajo en taller", value=float(_v("dias_prod", 0.0)), step=0.5)

    # ═══════════════════════════════════════════════════════════════════════
    # COLUMNA DERECHA — preview + planilla + precio + botones
    # ═══════════════════════════════════════════════════════════════════════
    with col_out:
      if ancho_m > 0 and alto_m > 0:
          svg_prev = generar_svg_mueble(tipo_modulo, ancho_m, alto_m, prof_m, tipo_tapa,
                                         cant_puertas, cant_cajones, estantes_fijos, estantes_moviles,
                                         tiene_parante, sin_fondo, distribucion_tapas,
                                         tipo_base=tipo_base, altura_base=altura_base,
                                         division_placard=division_placard,
                                         zona_izq=zona_izq, zona_der=zona_der, zona_unica=zona_unica)
          if svg_prev:
              st.markdown(f'<div style="text-align:center;padding:16px;background:white;border:1px solid #E0DED6;border-radius:10px;margin-bottom:24px;">{svg_prev}</div>', unsafe_allow_html=True)

      st.subheader("📐 Planilla de corte")
      if not cliente:
          st.markdown('''<div style="background:#FFF8E6;border-left:3px solid #EF9F27;border-radius:0 8px 8px 0;padding:12px 16px;">
          <b style="color:#854F0B;">👆 Ingresá el nombre del cliente primero</b></div>''', unsafe_allow_html=True)

      nombre_modulo = _v("nombre", f"{tipo_modulo} {ancho_m:.0f}mm")
      if alto_m > 0 and ancho_m > 0 and cliente:
          _div_pl   = division_placard            if tipo_modulo == "Placard" else "Sin división"
          _z_izq    = zona_izq                    if tipo_modulo == "Placard" else "Solo estantes"
          _z_der    = zona_der                    if tipo_modulo == "Placard" else "Solo estantes"
          _z_unica  = zona_unica                  if tipo_modulo == "Placard" else "Solo estantes"
          _h_tubo   = altura_tubo                 if tipo_modulo == "Placard" else 1200
          _ef_izq   = cant_estantes_izq_fijos     if tipo_modulo == "Placard" else 0
          _em_izq   = cant_estantes_izq_moviles   if tipo_modulo == "Placard" else 0
          _ef_der   = cant_estantes_der_fijos     if tipo_modulo == "Placard" else 0
          _em_der   = cant_estantes_der_moviles   if tipo_modulo == "Placard" else 0
          _ef_uni   = cant_estantes_unica_fijos   if tipo_modulo == "Placard" else 1
          _em_uni   = cant_estantes_unica_moviles if tipo_modulo == "Placard" else 0
          _caj_pl   = cant_cajones_placard         if tipo_modulo == "Placard" else 0
          _frent_pl = tiene_frentin_placard        if tipo_modulo == "Placard" else False
          _cant_pan = cant_paneles                 if tipo_modulo == "Pieza Suelta" else 1

          piezas = generar_despiece_bvm(
              tipo=tipo_modulo, ancho_m=ancho_m, alto_m=alto_m, prof_m=prof_m,
              esp_real=esp_real, tiene_parante=(_frent_pl if tipo_modulo=="Placard" else tiene_parante),
              tipo_parante=tipo_parante,
              distancia_parante=distancia_parante, cant_cajones=cant_cajones,
              tipo_tapa=tipo_tapa, tipo_base=tipo_base, altura_base=altura_base,
              luz_entre_tapas=luz_entre_tapas, luz_perimetral_tapa=luz_perimetral_tapa,
              alto_frentin_emb=alto_frentin_emb, aire_trasero=aire_trasero,
              esp_corredera=esp_corredera, distribucion_tapas=distribucion_tapas,
              cant_puertas=cant_puertas, tiene_cenefa=tiene_cenefa, alto_cenefa=alto_cenefa,
              estantes_fijos=estantes_fijos, estantes_moviles=estantes_moviles,
              tipo_estante_manual=tipo_estante_manual, sin_fondo=sin_fondo,
              tiene_parante_medio=tiene_parante_medio,
              division_placard=_div_pl, zona_izq=_z_izq, zona_der=_z_der, zona_unica=_z_unica,
              altura_tubo=_h_tubo,
              cant_estantes_izq_fijos=_ef_izq,   cant_estantes_izq_moviles=_em_izq,
              cant_estantes_der_fijos=_ef_der,   cant_estantes_der_moviles=_em_der,
              cant_estantes_unica_fijos=_ef_uni, cant_estantes_unica_moviles=_em_uni,
              cant_cajones_placard=_caj_pl,
              cant_paneles=_cant_pan,
              nota_pieza=nota_pieza if tipo_modulo == 'Pieza Suelta' else '',
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
      esp_real = esp_real if "esp_real" in dir() else 18.0
      retazos_stock = consultar_retazos_disponibles(mat_principal)
      if not df_corte.empty:
          ahorro_madera, matches = calcular_ahorro_retazos(df_corte, retazos_stock, maderas.get(mat_principal, 0.0))
      else:
          ahorro_madera, matches = 0.0, []
      total_costo_real = total_costo - ahorro_madera
      utilidad     = total_costo_real * config.get("ganancia_taller_pct", 0.30)
      precio_final = total_costo_real + utilidad
      pct_margen   = (utilidad / precio_final * 100) if precio_final > 0 else 0.0

      _precio_guardado = float(_v("precio_guardado", 0))
      precio_a_usar = precio_final if precio_final > 0 else _precio_guardado

      if precio_a_usar > 0:
          _nota   = " (precio guardado — recalculá si cambiaste medidas)" if precio_final == 0 and _precio_guardado > 0 else ""
          if es_empleado:
              st.markdown(f'''<div style="background:#0F6E56;border-radius:10px;padding:20px 24px;margin:8px 0 16px 0;text-align:center;">
              <div style="color:white;font-size:12px;opacity:0.8;margin-bottom:6px;">VALOR DEL MUEBLE{_nota}</div>
              <div style="color:white;font-size:44px;font-weight:700;letter-spacing:-1px;">${precio_a_usar:,.0f}</div>
              </div>''', unsafe_allow_html=True)
          else:
              _color  = "#0F6E56" if pct_margen >= 12 else "#A32D2D"
              _alerta = "Operación rentable" if pct_margen >= 12 else "Margen bajo — revisá los costos"
              _icono  = "✅" if pct_margen >= 12 else "⚠️"
              st.markdown(f'''<div style="background:{_color};border-radius:10px;padding:20px 24px;margin:8px 0 16px 0;text-align:center;">
              <div style="color:white;font-size:12px;opacity:0.8;margin-bottom:6px;">VALOR DEL MUEBLE{_nota}</div>
              <div style="color:white;font-size:44px;font-weight:700;letter-spacing:-1px;">${precio_a_usar:,.0f}</div>
              <div style="color:white;font-size:12px;opacity:0.8;margin-top:8px;">{_icono} Margen: {pct_margen:.1f}% — {_alerta}</div>
              </div>''', unsafe_allow_html=True)

      c1, c2, c3 = st.columns(3)
      if es_empleado:
          c1.metric("M² de placa", f"{m2_18mm:.2f}")
      else:
          c1.metric("Costo real",    f"${total_costo_real:,.0f}")
          c2.metric("M² de placa",   f"{m2_18mm:.2f}")
          c3.metric("Ganancia neta", f"${utilidad:,.0f}")

      if matches and not es_empleado:
          st.success(f"♻️ **¡Ahorro por retazos!** {len(matches)} pieza(s) — **${ahorro_madera:,.0f}**")
          with st.expander("Ver detalle"):
              for m_r in matches:
                  st.write(f"• **{m_r['pieza']}** → Retazo ID-{m_r['retazo_id']} — ${m_r['ahorro']:,.0f}")

      if precio_final > 0 and not es_empleado:
          with st.expander("📊 Desglose de costos"):
              st.bar_chart(pd.DataFrame({
                  "Categoría": ["Madera/Fondo","Herrajes","Operativo","Ganancia"],
                  "Monto":     [costo_madera+costo_fondo, costo_herrajes, costo_operativo+costo_base, utilidad],
              }), x="Categoría", y="Monto", color="#2e7d32")

      st.write("---")

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
              "division_placard":            division_placard           if tipo_modulo == "Placard" else "Sin división",
              "zona_izq":                    zona_izq                   if tipo_modulo == "Placard" else "Solo estantes",
              "zona_der":                    zona_der                   if tipo_modulo == "Placard" else "Solo estantes",
              "zona_unica":                  zona_unica                 if tipo_modulo == "Placard" else "Solo estantes",
              "altura_tubo":                 altura_tubo                if tipo_modulo == "Placard" else 1200,
              "cant_estantes_izq_fijos":     cant_estantes_izq_fijos    if tipo_modulo == "Placard" else 0,
              "cant_estantes_izq_moviles":   cant_estantes_izq_moviles  if tipo_modulo == "Placard" else 0,
              "cant_estantes_der_fijos":     cant_estantes_der_fijos    if tipo_modulo == "Placard" else 0,
              "cant_estantes_der_moviles":   cant_estantes_der_moviles  if tipo_modulo == "Placard" else 0,
              "cant_estantes_unica_fijos":   cant_estantes_unica_fijos  if tipo_modulo == "Placard" else 1,
              "cant_estantes_unica_moviles": cant_estantes_unica_moviles if tipo_modulo == "Placard" else 0,
              "cant_cajones_placard":        cant_cajones_placard       if tipo_modulo == "Placard" else 0,
              "tiene_frentin_placard":       tiene_frentin_placard      if tipo_modulo == "Placard" else False,
              "cant_paneles": cant_paneles if tipo_modulo == "Pieza Suelta" else 1,
              "nota_pieza":   nota_pieza   if tipo_modulo == "Pieza Suelta" else "",
          }

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

                  _oid = ctx.get("obra_id")
                  _cli = ctx.get("obra_cliente") or cliente
                  if _oid and _cli:
                      _log_prev = st.session_state.get("logistica_obra", {})
                      _tot_prev = sum(m["precio"] for m in mods) + _log_prev.get("costo_log_total", 0.0)
                      _guardar_obra_nube(mods, _cli, _oid,
                                          total_con_logistica=_tot_prev,
                                          logistica=_log_prev)
                  _limpiar_edicion()
                  st.session_state["_tipo_modulo_sel"] = "Bajo Mesada"
                  st.toast(f"✅ {nombre_modulo} actualizado", icon="✏️")
                  st.rerun()

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
                  _tipo_actual = st.session_state.get("_tipo_modulo_sel", "Bajo Mesada")
                  _limpiar_edicion()
                  st.session_state["_tipo_modulo_sel"] = _tipo_actual
                  st.toast(f"✅ {nombre_modulo} agregado — ${precio_a_usar:,.0f}", icon="🪵")
                  st.rerun()

      if st.session_state.get("ultimo_agregado"):
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
            col_mod, col_plan, col_dup, col_edit, col_del = st.columns([5, 1, 1, 1, 1])
            col_mod.write(f"**{i_m+1}. {mod['nombre']}** — {mod['ancho']}×{mod['alto']}×{mod['prof']} mm — {mod['material']} — `${mod['precio']:,.0f}`")
            if mod.get("df_corte") is not None and not mod["df_corte"].empty:
                _df_dl = mod["df_corte"].copy()
                _esp_m  = mod.get("params", {}).get("esp_real", 18.0)
                _mat_m  = mod.get("material", "")
                _mat_f  = mod.get("params", {}).get("mat_fondo_sel", "Fibroplus Blanco 3mm")
                _esp_f  = 5.5 if ("5.5" in _mat_f or "Faplac" in _mat_f) else 3.0
                _df_dl2 = _df_dl.rename(columns={"Pieza":"Name","L":"Length","A":"Width","Cant":"Quantity"})
                _df_dl2["Thickness"] = _df_dl2.apply(lambda r: _esp_f if str(r.get("Tipo","")).lower() in ["fondo","piso"] else _esp_m, axis=1)
                _df_dl2["Material"]  = _df_dl2.apply(lambda r: _mat_f  if str(r.get("Tipo","")).lower() in ["fondo","piso"] else _mat_m,  axis=1)
                _csv_dl = _df_dl2[["Name","Length","Width","Thickness","Quantity","Material"]].to_csv(index=False).encode("utf-8")
                col_plan.download_button("📋", data=_csv_dl,
                    file_name=f"Planilla_{mod['nombre'].replace(' ','_')}.csv",
                    mime="text/csv", key=f"dl_plan_{i_m}", help="Descargar planilla de corte")
            if col_dup.button("⧉", key=f"dup_mod_{i_m}", help="Duplicar este módulo"):
                import copy
                mod_copia = copy.deepcopy(mod)
                mod_copia["nombre"] = f"{mod['nombre']} (copia)"
                mod_copia["df_corte"] = mod.get("df_corte")
                st.session_state["obra_modulos"].insert(i_m + 1, mod_copia)
                st.toast(f"⧉ {mod['nombre']} duplicado", icon="📋")
                st.rerun()
            if col_edit.button("✏️", key=f"edit_mod_{i_m}", help="Editar este módulo"):
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

        if _OPTIMIZADOR_DISPONIBLE:
            with st.expander("📐 Optimización de Corte — ¿Cuántas placas necesito?", expanded=False):
                _mods_opt = [m for m in _mods_obra if m.get("df_corte") is not None]
                if not _mods_opt:
                    st.info("Calculá los módulos en esta sesión para optimizar el corte.")
                else:
                    col_pa, col_pb = st.columns(2)
                    _placa_w = col_pa.number_input("Ancho de placa estándar (mm)", value=PLACA_ANCHO_DEFAULT, step=10.0, key="opt_placa_w")
                    _placa_h = col_pb.number_input("Alto de placa estándar (mm)", value=PLACA_ALTO_DEFAULT, step=10.0, key="opt_placa_h")

                    if st.button("🧩 Calcular optimización", use_container_width=True, key="btn_optimizar"):
                        with st.spinner("Calculando la mejor distribución de piezas..."):
                            try:
                                _resultado_opt = optimizar_obra(_mods_opt, placa_ancho=_placa_w, placa_alto=_placa_h)
                                st.session_state["_resultado_optimizacion"] = _resultado_opt
                            except Exception as _e_opt:
                                st.error(f"No se pudo calcular la optimización: {_e_opt}")
                                st.session_state["_resultado_optimizacion"] = None

                    _resultado_opt = st.session_state.get("_resultado_optimizacion")
                    if _resultado_opt:
                        for _mat, _data in _resultado_opt.items():
                            st.markdown(f"#### {_mat}")
                            c_o1, c_o2 = st.columns(2)
                            c_o1.metric("Placas necesarias", f"{_data['cant_placas']}")
                            c_o2.metric("Desperdicio", f"{_data['desperdicio_pct']}%")
                            for i_p, _layout in enumerate(_data["placas"]):
                                st.caption(f"Placa {i_p+1} de {_mat} — {len(_layout)} pieza(s)")
                                _svg_placa = generar_svg_placa(_layout, _data["placa_ancho"], _data["placa_alto"])
                                st.markdown(f'<div style="text-align:center;margin-bottom:12px;">{_svg_placa}</div>', unsafe_allow_html=True)
                            st.write("---")

        if st.button("💾 Guardar obra en historial", use_container_width=True):
            if not cliente_obra:
                st.warning("Ingresá el nombre del cliente arriba.")
            else:
                _id_a_guardar = st.session_state.pop("_obra_id_historial", None)
                _log_data = {
                    "flete_sel": flete_sel, "costo_flete": costo_flete,
                    "dias_col": dias_col_obra, "costo_col": costo_col,
                    "costo_log_total": costo_log,
                    "dias_entrega": dias_entrega, "pct_seña": pct_seña,
                }
                _guardar_obra_nube(_mods_obra, cliente_obra, _id_a_guardar,
                                    total_con_logistica=total_obra,
                                    logistica=_log_data)
                st.toast(f"💾 Obra de {cliente_obra} guardada — ${total_obra:,.0f}", icon="💾")
                st.session_state["obra_modulos"]    = []
                st.session_state["logistica_obra"]  = {}
                st.session_state["ultimo_agregado"] = None
                st.session_state["_tipo_modulo_sel"] = "Bajo Mesada"
                st.session_state.pop("_obra_cliente_historial", None)
                st.session_state.pop("_obra_id_historial",      None)
                st.session_state.pop("_ctx_sig_prev",           None)
                st.session_state["edit_ctx"] = None
                for _k in ["inp_ancho", "inp_alto", "inp_prof"]:
                    if _k in st.session_state:
                        del st.session_state[_k]
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
            _traer_historial_db.clear()
        except Exception as e:
            st.error(f"Error: {e}")

    try:
        df_hist = traer_datos_historial()
        if df_hist.empty:
            st.info("No hay presupuestos guardados todavía.")
        else:
            total_pend = df_hist[df_hist['estado']=='Pendiente']['precio_final'].sum()
            total_pag  = df_hist[df_hist['estado']=='Pagado']['precio_final'].sum()

            total_senas = 0.0
            df_sen = df_hist[df_hist['estado']=='Señado']
            for _, row_s in df_sen.iterrows():
                pct_s = 50.0
                try:
                    if row_s.get('parametros'):
                        p_s = json.loads(row_s['parametros'])
                        if p_s.get("es_obra"):
                            pct_s = float(p_s.get("logistica", {}).get("pct_seña", 50))
                except:
                    pass
                total_senas += float(row_s.get('precio_final', 0)) * (pct_s / 100)

            c1,c2,c3 = st.columns(3)
            c1.metric("🔴 Pendientes",      f"${total_pend:,.0f}",  f"{len(df_hist[df_hist['estado']=='Pendiente'])} presupuestos")
            c2.metric("🟡 Señas cobradas",  f"${total_senas:,.0f}", f"{len(df_sen)} presupuestos")
            c3.metric("🟢 Pagados",         f"${total_pag:,.0f}",   f"{len(df_hist[df_hist['estado']=='Pagado'])} presupuestos")
            st.write("---")
            col_busq, col_filt = st.columns([2, 3])
            busqueda = col_busq.text_input("🔍 Buscar cliente", placeholder="Nombre del cliente...", label_visibility="collapsed")
            filtro   = col_filt.radio("Mostrar", ["Todos","Pendiente","Señado","Pagado"], horizontal=True)

            df_f = df_hist if filtro == "Todos" else df_hist[df_hist['estado'] == filtro]
            if busqueda.strip():
                df_f = df_f[df_f['cliente'].str.contains(busqueda.strip(), case=False, na=False)]
            df_f = df_f.sort_values("fecha", ascending=False) if "fecha" in df_f.columns else df_f

            _total_filtrado = df_f['precio_final'].sum() if not df_f.empty else 0
            st.markdown(f"<div style='font-size:13px;color:#888;margin-bottom:8px;'><b>{len(df_f)}</b> presupuesto(s) {'· búsqueda: <b>' + busqueda + '</b>' if busqueda else ''} {'· total filtrado: <b>$' + f'{_total_filtrado:,.0f}' + '</b>' if len(df_f) > 1 else ''}</div>", unsafe_allow_html=True)
            st.write("---")

            for idx, row in df_f.iterrows():
                estado_actual = row.get('estado','Pendiente')
                if estado_actual not in COLORES: estado_actual = 'Pendiente'
                icono, bg, tc = COLORES[estado_actual]
                id_venta = row.get('id')

                precio_total = float(row.get('precio_final', 0))
                pct_sena = 50
                try:
                    if row.get('parametros'):
                        p_dict = json.loads(row['parametros'])
                        if p_dict.get("es_obra"):
                            pct_sena = float(p_dict.get("logistica", {}).get("pct_seña", 50))
                except:
                    pass
                monto_sena = precio_total * (pct_sena / 100)
                saldo = precio_total - monto_sena
                if estado_actual == "Señado":
                    badge_text = f"Seña ({pct_sena}%): ${monto_sena:,.0f} | Saldo: ${saldo:,.0f}"
                elif estado_actual == "Pagado":
                    badge_text = f"Abonado: ${precio_total:,.0f} ✅"
                else:
                    badge_text = f"${precio_total:,.0f}"

                st.markdown(f"""<div style="background:{bg};border-radius:8px;padding:12px 16px;margin-bottom:4px;">
                <span style="color:{tc};font-weight:600;font-size:15px;">{icono} {row.get('cliente','Sin nombre')} — {row.get('mueble','')}</span>
                <span style="color:{tc};float:right;font-size:13px;font-weight:600;opacity:0.9;">{badge_text}</span></div>""", unsafe_allow_html=True)

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
                            _raw = row.get('parametros')
                            if not _raw or _raw in ('null', 'None', ''):
                                raise ValueError("Parámetros vacíos")
                            params = json.loads(_raw)
                            if not isinstance(params, dict):
                                raise ValueError("Schema inválido")
                            if params.get("es_obra"):
                                mods      = params.get("modulos", [])
                                cliente_h = row.get('cliente','')

                                mods_internos = []
                                for m in mods:
                                    p = _params_desde_mod(m)
                                    mods_internos.append({
                                        "nombre":    m.get("nombre", p.get("nombre","")),
                                        "tipo":      m.get("tipo_modulo", p.get("tipo_modulo","")),
                                        "ancho":     _safe_int(m.get("ancho_m", p.get("ancho_m", 0))),
                                        "alto":      _safe_int(m.get("alto_m",  p.get("alto_m",  0))),
                                        "prof":      _safe_int(m.get("prof_m",  p.get("prof_m",  0))),
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
                                    st.session_state["edit_ctx"] = {
                                        "modo":        "editar_modulo_obra",
                                        "idx":         0,
                                        "obra_id":     id_venta,
                                        "obra_cliente": cliente_h,
                                        "params":      mods_internos[0]["params"],
                                    }
                                else:
                                    st.session_state["edit_ctx"] = {
                                        "modo":        "elegir_modulo_obra",
                                        "obra_id":     id_venta,
                                        "obra_cliente": cliente_h,
                                    }
                            else:
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
                            _traer_historial_db.clear()
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
                            _traer_retazos_db.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")


# ===========================================================================
# CONFIGURACIÓN DE PRECIOS
# ===========================================================================
elif menu == "⚙️ Precios":
    st.title("⚙️ Configuración de precios")

    # 1. Gestión de Equipo o Taller (adaptado según rol del usuario)
    if es_empleado:
        with st.expander("👥 Mi Equipo / Taller", expanded=True):
            st.markdown(f"Formás parte del taller **{_info_taller['nombre_taller']}** como colaborador (🛠️ Rol: Empleado).")
            st.caption("No tenés permisos para invitar a otros usuarios ni editar tarifas de costo del taller.")
            st.write("")
            if st.button("🚪 Abandonar Taller", type="primary", use_container_width=True):
                if abandonar_taller():
                    st.toast("Has abandonado el taller. Volviendo al modo individual.", icon="🚪")
                    st.rerun()
    else:
        with st.expander("👥 Mi Equipo / Taller", expanded=False):
            st.caption("Compartí tu configuración de precios, historial y depósito de retazos con un empleado o socio. Ambos van a ver y editar los mismos datos.")
            col_inv1, col_inv2 = st.columns([3, 1])
            email_inv = col_inv1.text_input("Email del empleado/socio", placeholder="empleado@email.com", label_visibility="collapsed")
            if col_inv2.button("Invitar", use_container_width=True):
                if email_inv:
                    if invitar_a_taller(email_inv):
                        st.success(f"✅ {email_inv} ahora comparte tu taller en BVM.")
                        st.rerun()
                else:
                    st.warning("Ingresá un email.")
            st.caption("⚠️ El invitado necesita tener cuenta creada en BVM (pestaña Registro) antes de invitarlo.")

    # 2. Precios de Placas (Modo Lectura para Empleados)
    with st.expander("🪵 Precios de Placas (18mm)", expanded=True):
        for madera, precio in list(maderas.items()):
            col_name, col_price, col_del = st.columns([5, 3, 1] if not es_empleado else [7, 3])
            col_name.markdown(f"<div style='padding-top: 8px; font-weight: 500;'>{madera}</div>", unsafe_allow_html=True)
            maderas[madera] = col_price.number_input("Precio", value=float(precio), step=1000.0, key=f"p_{madera}", label_visibility="collapsed", disabled=es_empleado)
            if not es_empleado:
                if col_del.button("🗑️", key=f"del_{madera}", help=f"Eliminar {madera}"):
                    eliminar_precio_nube(madera, 'maderas')
                    _traer_datos_db.clear()
                    st.rerun()

        if not es_empleado:
            st.write("---")
            st.markdown("**➕ Agregar nueva placa**")
            c_nm, c_np, c_nb = st.columns([5, 3, 1])
            nueva_mad_n = c_nm.text_input("Nombre", key="new_mad_n", label_visibility="collapsed", placeholder="Ej: Enchapado Nogal 18mm")
            nueva_mad_p = c_np.number_input("Precio", min_value=0.0, step=1000.0, key="new_mad_p", label_visibility="collapsed")
            if c_nb.button("Agregar", key="add_mad", use_container_width=True):
                if nueva_mad_n and nueva_mad_p > 0:
                    actualizar_precio_nube(nueva_mad_n, nueva_mad_p, 'maderas')
                    _traer_datos_db.clear()
                    st.rerun()

    # 3. Herrajes (Modo Lectura para Empleados)
    _nombres_herraje = {
        'bisagra_cazoleta': 'Bisagra Cazoleta',
        'telescopica_45':   'Guía Telescópica 45cm',
        'telescopica_soft': 'Guía Cierre Suave',
    }
    _todos_herrajes = {k: v for k, v in config.items()
                       if k not in ['gastos_fijos_diarios','flete_capital','flete_norte','colocacion_dia','ganancia_taller_pct']}

    with st.expander("🔩 Herrajes, Cerraduras y Extras", expanded=False):
        for h_clave, h_precio in list(_todos_herrajes.items()):
            col_name, col_price, col_del = st.columns([5, 3, 1] if not es_empleado else [7, 3])
            label = _nombres_herraje.get(h_clave, h_clave)
            col_name.markdown(f"<div style='padding-top: 8px; font-weight: 500;'>{label}</div>", unsafe_allow_html=True)
            config[h_clave] = col_price.number_input("Precio", value=float(h_precio), step=100.0,
                                                      key=f"p_{h_clave}", label_visibility="collapsed", disabled=es_empleado)
            if not es_empleado:
                if col_del.button("🗑️", key=f"del_{h_clave}", help=f"Eliminar {label}"):
                    eliminar_precio_nube(h_clave, 'herrajes')
                    _traer_datos_db.clear()
                    st.rerun()

        if not es_empleado:
            st.write("---")
            st.markdown("**➕ Agregar nuevo herraje**")
            ch_nm, ch_np, ch_nb = st.columns([5, 3, 1])
            nuevo_herr_n = ch_nm.text_input("Nombre", key="new_herr_n", label_visibility="collapsed",
                                             placeholder="Ej: Cerradura cajón Hafele")
            nuevo_herr_p = ch_np.number_input("Precio", min_value=0.0, step=100.0, key="new_herr_p",
                                               label_visibility="collapsed")
            if ch_nb.button("Agregar", key="add_herr", use_container_width=True):
                if nuevo_herr_n and nuevo_herr_p > 0:
                    actualizar_precio_nube(nuevo_herr_n, nuevo_herr_p, 'herrajes')
                    _traer_datos_db.clear()
                    st.rerun()

    # 4. Datos Financieros Sensibles (Ocultos por completo para Empleados)
    if not es_empleado:
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
            _traer_datos_db.clear()
            st.success("✅ Configuración guardada")
