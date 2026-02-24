import streamlit as st
import pandas as pd

def consultar_retazos_disponibles(supabase, material, usuario_actual):
    try:
        res = supabase.table("retazos").select("*").eq("material", material).eq("usuario", usuario_actual).execute()
        return res.data
    except:
        return []

def registrar_retazo(supabase, material, largo, ancho, usuario_actual):
    data = {"material": material, "largo": largo, "ancho": ancho, "usuario" : usuario_actual}
    supabase.table("retazos").insert(data).execute()

def traer_datos_historial(supabase, usuario_actual):
    try:
        response = supabase.table("ventas").select("*").eq("usuario", usuario_actual).execute()
        return pd.DataFrame(response.data)
    except:
        return pd.DataFrame()
