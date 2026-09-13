import re
import io
import logging
import pandas as pd
import streamlit as st
import gspread
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials

import unicodedata
from html import escape
from typing import Dict, List, Optional, Tuple
import requests
try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except Exception:
    from difflib import SequenceMatcher, get_close_matches
    RAPIDFUZZ_AVAILABLE = False

# ==============================================================================
# CONFIGURACIÓN DEFENSIVA Y LOGGING
# ==============================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

st.set_page_config(page_title="Trazabilidad SDDI", layout="wide", page_icon="🏛️", initial_sidebar_state="collapsed")

# ==============================================================================
# SISTEMA DE SEGURIDAD (LOGIN)
# ==============================================================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div style='background-color: #FFFFFF; padding: 40px; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.1); text-align: center; border-top: 5px solid #2980B9;'>
            <h2 style='color: #2C3E50; margin-bottom: 5px;'>SBN | DGPE | SDDI</h2>
            <p style='color: #7F8C8D; margin-bottom: 25px;'>Sistema de Trazabilidad de expedientes SDDI</p>
        </div>
        """, unsafe_allow_html=True)
        
        clave_ingresada = st.text_input("Clave de acceso restringido", type="password", placeholder="Ingrese la contraseña...")
        
        if st.button("Acceder al Sistema", use_container_width=True, type="primary"):
            if clave_ingresada == "sddi26":
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas. Acceso denegado.")
    st.stop()

# ==============================================================================
# VARIABLES DE NAVEGACIÓN
# ==============================================================================
if 'capa_actual' not in st.session_state: st.session_state.capa_actual = 1
if 'equipo_sel' not in st.session_state: st.session_state.equipo_sel = None

def ir_a_capa(nivel, equipo=None):
    st.session_state.capa_actual = nivel
    if equipo is not None: st.session_state.equipo_sel = equipo

# ==============================================================================
# MOTOR RPA: SINCRONIZACIÓN DE GOOGLE SHEETS (ETL)
# ==============================================================================
def sincronizar_estados_sunarp(usuario_codigo):
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("⚠️ Falta configurar el JSON de Google Service Account en st.secrets.")
            return False

        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)

        ID_ORIGEN = "1t9PJU_kMebrqURJuNTZRnTaQESpWoE3hsh77dw0GgcY"
        wb_origen = client.open_by_key(ID_ORIGEN)
        ws_origen = wb_origen.get_worksheet(0)
        datos_origen = ws_origen.get_all_values()

        diccionario_estados = {}
        for fila in datos_origen[1:]: 
            fila_segura_origen = fila + [""] * (8 - len(fila))
            titulo = fila_segura_origen[2].strip() 
            
            if titulo:
                estado = fila_segura_origen[3].strip() 
                dato_h = fila_segura_origen[7].strip() 
                diccionario_estados[titulo] = {"estado": estado, "dato_h": dato_h}

        ID_DESTINO = "1U_M04niREqrrb88xODw6BflbIH4HTODzXZKjkwzAWfg"
        wb_destino = client.open_by_key(ID_DESTINO)

        mapeo_pestañas = {
            "MCHAVEZ": ["CAROLINA"],
            "KPAJUELO": ["KATHERINE"],
            "VGAMARRA": ["VICTOR"],
            "RJIMENEZ": ["RICARDO"],
            "VESPADIN": ["VALERIA", "VALERIA-SDDI"]
        }

        pestañas_a_procesar = mapeo_pestañas.get(usuario_codigo, [])

        for nombre_pestaña in pestañas_a_procesar:
            try:
                ws_destino = wb_destino.worksheet(nombre_pestaña)
                datos_destino = ws_destino.get_all_values()
                
                columnas_mn_actualizada = []
                hubo_modificacion_en_pestaña = False

                for idx, fila in enumerate(datos_destino):
                    if idx == 0: 
                        val_m = fila[12] if len(fila) > 12 else "REVISADO"
                        val_n = fila[13] if len(fila) > 13 else "DATO ADICIONAL"
                        columnas_mn_actualizada.append([val_m, val_n])
                        continue
                    
                    fila_segura = fila + [""] * (14 - len(fila))
                    n_titulo = fila_segura[9].strip() 
                    estado_actual = fila_segura[12].strip() 
                    dato_n_actual = fila_segura[13].strip() 

                    if n_titulo in diccionario_estados:
                        nuevo_estado = diccionario_estados[n_titulo]["estado"]
                        nuevo_dato_h = diccionario_estados[n_titulo]["dato_h"]
                        
                        if estado_actual != nuevo_estado or dato_n_actual != nuevo_dato_h:
                            estado_actual = nuevo_estado
                            dato_n_actual = nuevo_dato_h
                            hubo_modificacion_en_pestaña = True
                            
                    columnas_mn_actualizada.append([estado_actual, dato_n_actual])

                if hubo_modificacion_en_pestaña:
                    rango_escritura = f"M1:N{len(columnas_mn_actualizada)}"
                    ws_destino.update(values=columnas_mn_actualizada, range_name=rango_escritura)

            except gspread.exceptions.WorksheetNotFound:
                continue

        return True
    except Exception as e:
        return False

# ==============================================================================
# FUNCIÓN DE VENTANA EMERGENTE (MODAL MAESTRO BLINDADO)
# ==============================================================================
@st.dialog("📄 Reporte de expedientes solicitados", width="large")
def mostrar_modal_detalle(tipo_clic, param1, param2, param3, df_base):
    df_modal = df_base.copy()
    
    if tipo_clic == "PROC":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Procedimiento: {param1} | Año: {param2}</h5>", unsafe_allow_html=True)
        if param1 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 10].astype(str).str.strip().str.upper() == param1.upper()]
        if param2 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0] == str(param2)]
    
    elif tipo_clic == "PROC_EQ":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Equipo: {param3} | Procedimiento: {param1} | Año: {param2}</h5>", unsafe_allow_html=True)
        if param3 != 'TOTAL' and param3 != 'null': df_modal = df_modal[df_modal["Equipo"] == param3]
        if param1 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 10].astype(str).str.strip().str.upper() == param1.upper()]
        if param2 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0] == str(param2)]

    elif tipo_clic == "ACCION":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Equipo: {param1} | Estado: {param2}</h5>", unsafe_allow_html=True)
        if param1 != 'TOTAL' and param1 != 'null': df_modal = df_modal[df_modal["Equipo"] == param1]
        if param2 == 'ACTIVO': df_modal = df_modal[df_modal["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)]
        elif param2 == 'LENTO': df_modal = df_modal[df_modal["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False) & ~df_modal["Trazabilidad"].astype(str).str.contains("6 meses", case=False, na=False)]
        elif param2 == 'PARALIZADO': df_modal = df_modal[df_modal["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)]
        
    elif tipo_clic == "ANIO_GEN":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Resumen General | Año: {param1}</h5>", unsafe_allow_html=True)
        if param1 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0] == str(param1)]

    elif tipo_clic == "ANIO_GEN_EQ":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Equipo: {param1} | Resumen General Año: {param2}</h5>", unsafe_allow_html=True)
        if param1 != 'TOTAL' and param1 != 'null': df_modal = df_modal[df_modal["Equipo"] == param1]
        if param2 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0] == str(param2)]

    elif tipo_clic == "ANIO_EQ":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Equipo: {param1} | Año: {param2}</h5>", unsafe_allow_html=True)
        if param1 != 'TOTAL' and param1 != 'null': df_modal = df_modal[df_modal["Equipo"] == param1]
        if param2 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0] == str(param2)]

    elif tipo_clic == "ACCION_PROF":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Equipo: {param3} | Profesional: {param1} | Estado: {param2}</h5>", unsafe_allow_html=True)
        if param3 != 'TOTAL' and param3 != 'null': df_modal = df_modal[df_modal["Equipo"] == param3]
        if param1 != 'TOTAL': df_modal = df_modal[df_modal["Profesional"] == param1]
        if param2 == 'ACTIVO': df_modal = df_modal[df_modal["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)]
        elif param2 == 'LENTO': df_modal = df_modal[df_modal["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False) & ~df_modal["Trazabilidad"].astype(str).str.contains("6 meses", case=False, na=False)]
        elif param2 == 'PARALIZADO': df_modal = df_modal[df_modal["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)]

    elif tipo_clic == "ANIO_PROF":
        st.markdown(f"<h5 style='color:#2980B9; margin-top:0;'>Equipo: {param3} | Profesional: {param1} | Año: {param2}</h5>", unsafe_allow_html=True)
        if param3 != 'TOTAL' and param3 != 'null': df_modal = df_modal[df_modal["Equipo"] == param3]
        if param1 != 'TOTAL': df_modal = df_modal[df_modal["Profesional"] == param1]
        if param2 != 'TOTAL': df_modal = df_modal[df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0] == str(param2)]
    
    if len(df_base.columns) >= 13:
        df_final = pd.DataFrame()
        df_final["Expediente"] = df_modal.iloc[:, 0]
        df_final["Profesional"] = df_modal.iloc[:, 7]
        df_final["Año"] = df_modal.iloc[:, 9].astype(str).str.extract(r'((?:19|20)\d{2})')[0].fillna("S/F")
        df_final["Procedimiento"] = df_modal.iloc[:, 10]
        df_final["Administrado"] = df_modal.iloc[:, 11]
        df_final["Estado"] = df_modal.iloc[:, 12]
        
        df_final["Tipo Doc / Origen"] = df_modal.iloc[:, 5]
        df_final["Fecha_Ultima_Accion"] = df_modal.iloc[:, 3]
        df_final["Trazabilidad_Oculta"] = df_modal["Trazabilidad"] if "Trazabilidad" in df_modal.columns else df_modal.iloc[:, 5]
        
        terminos_privacidad = "COMPRAVENTA|PERMUTA|DESAFECTACI[OÓ]N|SUBASTA"
        mask_privacidad = df_final["Procedimiento"].astype(str).str.upper().str.contains(terminos_privacidad, regex=True)
        
        palabras_entidad = "MUNICIPALIDAD|GOBIERNO|MINISTERIO|S\.A\.|S\.A\.C\.|S\.R\.L\.|E\.I\.R\.L\.|ASOCIACION|EMPRESA|COMUNIDAD|CONSORCIO|DIRECCION|SUPERINTENDENCIA|UNIVERSIDAD|COOPERATIVA|SINDICATO|PROYECTO|IGLESIA|COMITE|JUNTA"
        mask_juridica = df_final["Administrado"].astype(str).str.upper().str.contains(palabras_entidad, na=False)
        mask_ocultar = mask_privacidad & ~mask_juridica
        df_final.loc[mask_ocultar, "Administrado"] = "PERSONA NATURAL"
        
        df_final["URL_Tramite"] = "https://tramitetransparente.sbn.gob.pe/#auto=" + df_final["Expediente"].astype(str)

        if tipo_clic in ["ACCION", "ACCION_PROF"]:
            hoy = pd.Timestamp.today().normalize()
            def calcular_dias(fecha_str):
                if pd.isna(fecha_str) or str(fecha_str).strip() in ["-", ""]: return "-"
                try:
                    fecha = pd.to_datetime(str(fecha_str).strip(), format='%d/%m/%Y', errors='coerce')
                    if pd.isna(fecha): return "-"
                    return f"{max(0, (hoy - fecha).days)} días"
                except:
                    return "-"
            df_final["Días Calendario"] = df_final["Fecha_Ultima_Accion"].apply(calcular_dias)
            cols_mostrar = ["Expediente", "Profesional", "Año", "Procedimiento", "Administrado", "Estado", "Tipo Doc / Origen", "Días Calendario", "URL_Tramite"]
        else:
            def calcular_alerta(val):
                v = str(val).lower()
                if "semana" in v: return "🟢 Trámite Activo"
                elif "año" in v or "6 meses" in v or "no se encontro resultado" in v: return "🔴 Paralizado"
                elif "mes" in v: return "🟡 Flujo Lento"
                return "⚪ Sin Datos"
            df_final["Alerta Visual"] = df_final["Trazabilidad_Oculta"].apply(calcular_alerta)
            cols_mostrar = ["Expediente", "Profesional", "Año", "Procedimiento", "Administrado", "Estado", "Alerta Visual", "URL_Tramite"]
        
        df_mostrar = df_final[cols_mostrar]
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            columnas_exportar = [col for col in df_mostrar.columns if col != "URL_Tramite"]
            df_mostrar[columnas_exportar].to_excel(writer, index=False, sheet_name='Detalle_Expedientes')
            
        col_btn, _ = st.columns([3, 7])
        with col_btn:
            st.download_button("📥 Bajar Excel", data=buffer.getvalue(), file_name=f"Reporte_Expedientes_{tipo_clic}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            
        st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)
        st.dataframe(df_mostrar, use_container_width=True, hide_index=True, column_config={"URL_Tramite": st.column_config.LinkColumn("🔗 Acción", display_text="Abrir Trámite")})
    else:
        st.error("No hay suficientes columnas en la base de datos para mostrar el detalle.")

# ==============================================================================
# ESTILOS CSS AVANZADOS Y UI
# ==============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif !important; background-color: #F4F7F6 !important; }
.block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; }

div[data-testid="stTextInput"] { display: none !important; visibility: hidden !important; height: 0 !important; overflow: hidden !important; margin: 0 !important; padding: 0 !important; }

button[kind="primary"] { background-color: #2980B9 !important; border-color: #2980B9 !important; color: white !important; font-weight: 700 !important; }
button[kind="primary"]:hover { background-color: #1A5276 !important; border-color: #1A5276 !important; }

[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 6px !important; border-bottom: 2px solid #BDC3C7 !important; margin-bottom: 10px !important; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { display: none !important; }
[data-testid="stTabs"] [data-baseweb="tab"] { background-color: #EAECEE !important; border-radius: 8px 8px 0px 0px !important; border: 1px solid #BDC3C7 !important; border-bottom: none !important; padding: 10px 20px !important; margin: 0 !important; transition: all 0.2s ease !important; }
[data-testid="stTabs"] [data-baseweb="tab"] p { font-size: 16px !important; font-weight: 600 !important; color: #7F8C8D !important; }
[data-testid="stTabs"] [data-baseweb="tab"]:hover { background-color: #D5DBDB !important; }
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] { background-color: #E8F4F8 !important; border-top: 5px solid #2ECC71 !important; border-bottom: 3px solid #E8F4F8 !important; margin-bottom: -2px !important; z-index: 99 !important; }
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] p { color: #2980B9 !important; font-weight: 900 !important; }

header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; visibility: hidden !important; width: 0 !important; height: 0 !important; }
footer, #MainMenu, [data-testid="stDecoration"], [data-testid="stToolbar"] { display: none !important; visibility: hidden !important; }
h1 a svg, h2 a svg, h3 a svg { display: none !important; } 

.tarjeta-metrica { background-color: #FFFFFF; padding: 6px 10px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); margin-bottom: 12px; text-align: center; height: 68px !important; display: flex; flex-direction: column; justify-content: center; align-items: center; position: relative; z-index: 1; }
.tarjeta-titulo { color: #7F8C8D; font-size: 10px; margin: 0; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; min-height: 18px; display: flex; align-items: flex-end; justify-content: center; padding-bottom: 2px; line-height: 1.1; pointer-events: none; }
.tarjeta-valor { color: #2C3E50; font-size: 24px; margin: 0 !important; font-weight: 700; line-height: 1; pointer-events: none; }

.tarjeta-clic { cursor: pointer; transition: all 0.2s ease; }
.tarjeta-clic:hover { transform: translateY(-3px); box-shadow: 0 6px 12px rgba(0,0,0,0.15) !important; z-index: 10; background-color: #FDFEFE !important; }

.celda-proc-clic, .mod-proc, .mod-proc-eq, .celda-equipo-clic, .mod-anio-gen, .mod-anio-eq, .mod-accion, .mod-accion-prof, .mod-anio-gen-eq, .mod-anio-prof { 
    cursor: pointer !important; 
    transition: background-color 0.2s ease, color 0.2s ease; 
}
.celda-proc-clic:hover, .mod-proc:hover, .mod-proc-eq:hover, .celda-equipo-clic:hover, .mod-anio-gen:hover, .mod-anio-eq:hover, .mod-accion:hover, .mod-accion-prof:hover, .mod-anio-gen-eq:hover, .mod-anio-prof:hover { 
    background-color: #D6EAF8 !important; 
    color: #1A5276 !important; 
}

.tarjeta-equipo { background-color: #FFFFFF; padding: 12px 10px; border-radius: 10px; border-top: 4px solid #2980B9; box-shadow: 0 3px 8px rgba(0,0,0,0.04); text-align: center; margin-bottom: 10px; height: 120px !important; display: flex; flex-direction: column; justify-content: center; }

.tabla-matricial { width: 100%; min-width: 750px; border-collapse: collapse; font-family: 'Inter', sans-serif; table-layout: fixed; }
.tabla-matricial th { background-color: #2980B9; color: #FFFFFF; text-align: center; padding: 6px 8px; font-size: 11px; font-weight: 700; border: 1px solid #1A5276; text-transform: uppercase; line-height: 1.2; word-wrap: break-word; }
.tabla-matricial th.header-secundario { background-color: #F8F9F9; color: #7F8C8D; border-bottom: 2px solid #BDC3C7; border-color: #E0E6ED; font-size: 12px; }
.tabla-matricial th.col-fija { width: 28%; min-width: 180px; text-align: left; padding-left: 15px; white-space: normal; }
.tabla-matricial td { background-color: #FFFFFF; color: #2C3E50; text-align: center; padding: 6px 5px; font-size: 13px; font-weight: 700; border: 1px solid #E0E6ED; word-wrap: break-word; }
.tabla-matricial td.col-equipo { background-color: #F4F6F7; text-align: left; padding-left: 15px; font-size: 13px; font-weight: 600; color: #2C3E50; border: 1px solid #E0E6ED; white-space: nowrap; }
.tabla-matricial td.col-proc { background-color: #F4F6F7; text-align: left; padding: 8px 15px; font-size: 11px; font-weight: 600; color: #1A252F; border: 1px solid #E0E6ED; white-space: normal; line-height: 1.3; }
</style>
""", unsafe_allow_html=True)

def mostrar_encabezado(titulo, subtitulo, mostrar_volver=False):
    col_btn, col_header = st.columns([1, 11])
    with col_btn:
        if mostrar_volver:
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
            if st.button("⬅️ Volver", use_container_width=True):
                ir_a_capa(1)
                st.rerun()
    with col_header:
        html_encabezado = f"""
        <div id='ancla-top'></div>
        <div style='display: flex; flex-direction: row; align-items: center; justify-content: center; position: relative; width: 100%; margin-bottom: 25px; flex-wrap: wrap; gap: 20px;'>
            <div style='flex: 1 1 300px; text-align: center; order: 1;'>
                <h1 style='margin:0; color:#1A252F; font-size: clamp(24px, 4vw, 36px); line-height: 1.2;'>{titulo}</h1>
                <p style='margin:8px 0 0 0; color:#7F8C8D; font-size: 14px;'>{subtitulo}</p>
            </div>
            <div style='order: 2; flex-shrink: 0;'>
                <div style='width: 110px; min-height: 105px; background: linear-gradient(135deg, #656D74, #495057); border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.15); padding: 12px 14px; position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; margin: 0 auto;'>
                    <div style='position: absolute; right: 0; top: 0; width: 35px; height: 100%; background-image: radial-gradient(rgba(255,255,255,0.25) 1.5px, transparent 1.5px); background-size: 8px 8px; z-index: 1;'></div>
                    <div style='position: relative; z-index: 2; width: 100%; text-align: left;'>
                        <span style="color: #FFFFFF; font-size: 28px; font-weight: 900; line-height: 1; margin-bottom: 6px; display: block;">SBN</span>
                        <div style="display: flex; width: 100%; height: 3px; margin-bottom: 6px;">
                            <div style="background-color: #FFFFFF; flex-grow: 1;"></div>
                            <div style="background-color: #E74C3C; width: 18px;"></div>
                        </div>
                        <span style="color: #FFFFFF; font-size: 13px; font-weight: 700; line-height: 1.2; display: block;">DGPE</span>
                        <span style="color: #FFFFFF; font-size: 13px; font-weight: 700; line-height: 1.2; display: block;">SDDI</span>
                    </div>
                </div>
            </div>
        </div>
        """
        st.markdown(html_encabezado, unsafe_allow_html=True)

def crear_tarjeta(titulo, valor, color_borde, id_click=""):
    clase_clic = ""
    if id_click == "acciones": clase_clic = "tarjeta-clic tarjeta-clic-acciones"
    elif id_click == "anios": clase_clic = "tarjeta-clic tarjeta-clic-anios"
    elif id_click == "acciones_prof": clase_clic = "tarjeta-clic tarjeta-clic-acciones-prof"
    elif id_click == "anios_prof": clase_clic = "tarjeta-clic tarjeta-clic-anios-prof"
    
    st.markdown(f"""
    <div class="tarjeta-metrica {clase_clic}" style="border-bottom: 4px solid {color_borde};">
        <div class="tarjeta-titulo">{titulo}</div>
        <div class="tarjeta-valor">{valor}</div>
    </div>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner=False)
def cargar_datos():
    url_sheet = "https://docs.google.com/spreadsheets/d/e/2PACX-1vT1sNYxj6znXHjwEGFZH58FXR1CUGUuw6Ro7dz2Y65byi6nkGP9s5f88FbUze-QT550MeucdeSpOIWm/pub?gid=0&single=true&output=csv" 
    df = pd.read_csv(url_sheet)
    if "Profesional" in df.columns:
        df["Profesional"] = df["Profesional"].astype(str).apply(lambda x: re.sub(r'[1Xx]+$', '', x.strip()) if pd.notna(x) else x)
    return df

@st.cache_data(ttl=300, show_spinner=False)
def cargar_datos_sunarp():
    url_sunarp = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTFQiw1QtTommj03HEMC0mQEQHYuyoluv9K0UP9u6GJDntCAjzOnk77RD_Plx8MoPgktulWknPjIoxd/pub?gid=0&single=true&output=csv"
    df_s = pd.read_csv(url_sunarp)
    df_s.columns = df_s.columns.str.strip().str.upper()
    mapeo_usuarios = {
        "CAROLINA": "MCHAVEZ", "VICTOR": "VGAMARRA", "VALERIA": "VESPADIN",
        "RICARDO": "RJIMENEZ", "KATHERINE": "KPAJUELO"
    }
    if "USUARIO" in df_s.columns:
        df_s["USUARIO_MAPEADO"] = df_s["USUARIO"].astype(str).str.strip().str.upper().map(mapeo_usuarios).fillna(df_s["USUARIO"])
    return df_s

def clasificar_estados_sunarp(df_base, usuarios):
    metricas = []
    try:
        if "USUARIO_MAPEADO" not in df_base.columns or "ESTADO" not in df_base.columns:
            return metricas
        for usu in usuarios:
            df_usu = df_base[df_base["USUARIO_MAPEADO"] == usu].copy()
            total = len(df_usu)
            if total == 0: continue

            estados = df_usu["ESTADO"].astype(str).str.upper().str.strip()
            insc = int(estados.str.contains("INSCRITO", case=False, na=False).sum())
            calif = int(estados.str.contains("CALIFICACIÓN|CALIFICACION", case=False, na=False).sum())
            tach = int(estados.str.contains("TACHADO", case=False, na=False).sum())
            obs = int(estados.str.contains("OBSERVADO", case=False, na=False).sum())
            liq = int(estados.str.contains("LIQUIDADO", case=False, na=False).sum())
            reing = int(estados.str.contains("REINGRESADO", case=False, na=False).sum())
            en_proc = int(estados.str.contains("EN PROCESO", case=False, na=False).sum())
            mask_conocidos = estados.str.contains("INSCRITO|CALIFICACIÓN|CALIFICACION|TACHADO|OBSERVADO|LIQUIDADO|REINGRESADO|EN PROCESO", case=False, na=False)
            otros = int((~mask_conocidos & (estados != "NAN") & (estados != "")).sum())
            
            metricas.append({
                "Usuario": usu, "Total": total,
                "Tarjetas": {
                    "Inscritos": {"valor": insc, "bg": "#28B463", "color": "#FFFFFF"},
                    "En Calificación": {"valor": calif, "bg": "#3498DB", "color": "#FFFFFF"},
                    "Tachados": {"valor": tach, "bg": "#8D6E63", "color": "#FFFFFF"},
                    "Observados": {"valor": obs, "bg": "#E74C3C", "color": "#FFFFFF"},
                    "Liquidados": {"valor": liq, "bg": "#196F3D", "color": "#FFFFFF"},
                    "Reingresados": {"valor": reing, "bg": "#85C1E9", "color": "#2C3E50"},
                    "En Proceso": {"valor": en_proc, "bg": "#E5E7E9", "color": "#2C3E50"},
                    "Otros": {"valor": otros, "bg": "#95A5A6", "color": "#FFFFFF"}
                }
            })
    except Exception as e:
        pass
    return metricas

def generar_tarjeta_html(etiqueta, config):
    if config["valor"] == 0: return ""
    return f"""
    <div style="background-color: {config['bg']}; padding: 4px 5px; border-radius: 4px; 
                text-align: center; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.15); 
                height: 45px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
        <div style="color: {config['color']}; font-size: 8px; font-weight: 800; 
                    text-transform: uppercase; letter-spacing: 0.1px; line-height: 1; margin-bottom: 2px;">
            {etiqueta}
        </div>
        <div style="color: {config['color']}; font-size: 20px; font-weight: 900; line-height: 1;">
            {config['valor']}
        </div>
    </div>
    """


# ==============================================================================
# MOTOR DE BÚSQUEDA UNIVERSO EXP. (integrado como tercer módulo)
# ==============================================================================
PUBLISHED_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vT1sNYxj6znXHjwEGFZH58FXR1CUGUuw6Ro7dz2Y65byi6nkGP9s5f88FbUze-QT550MeucdeSpOIWm/"
    "pub?output=xlsx"
)
SHEET_NAME = "UNIVERSO EXP."

def normalize_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def singularize_token(token: str) -> str:
    """Reduce plurales frecuentes a una forma de búsqueda más estable."""
    t = normalize_text(token)
    if len(t) <= 4:
        return t
    # Casos frecuentes en español; evitamos tocar términos muy cortos.
    irregular = {
        "MUNICIPALIDADES": "MUNICIPALIDAD",
        "MUNICIPIOS": "MUNICIPIO",
        "TRANSFERENCIAS": "TRANSFERENCIA",
        "COMPRAVENTAS": "COMPRAVENTA",
        "RESOLUCIONES": "RESOLUCION",
        "EMPRESAS": "EMPRESA",
        "ENTIDADES": "ENTIDAD",
        "GOBIERNOS": "GOBIERNO",
        "EXPEDIENTES": "EXPEDIENTE",
        "TRAMITES": "TRAMITE",
    }
    if t in irregular:
        return irregular[t]
    if t.endswith("ES") and len(t) > 5:
        return t[:-2]
    if t.endswith("S") and len(t) > 4:
        return t[:-1]
    return t


def normalize_search_phrase(text: str) -> str:
    parts = [singularize_token(x) for x in normalize_text(text).split()]
    return " ".join(parts)


def first_existing_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    normalized = {normalize_text(c): c for c in df.columns}
    for candidate in candidates:
        hit = normalized.get(normalize_text(candidate))
        if hit:
            return hit
    return None


def infer_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    return {
        "expediente": df.columns[0] if len(df.columns) >= 1 else None,  # A
        "entidad": df.columns[3] if len(df.columns) >= 4 else None,      # D
        "procedimiento": df.columns[11] if len(df.columns) >= 12 else None,  # L
        "departamento": first_existing_column(df, ["DEPARTAMENTO", "REGION", "REGIÓN"]),
        "provincia": first_existing_column(df, ["PROVINCIA"]),
        "distrito": first_existing_column(df, ["DISTRITO"]),
        "anio": first_existing_column(
            df,
            [
                "AÑO", "ANIO", "AÑO CREACION", "AÑO DE CREACION", "AÑO DE GENERACION",
                "AÑO EXPEDIENTE", "ANIO EXPEDIENTE", "FECHA", "FECHA DE INGRESO"
            ],
        ),
        "estado": first_existing_column(
            df,
            ["ESTADO", "SITUACION", "SITUACIÓN", "ESTADO DEL EXPEDIENTE", "SITUACION DEL EXPEDIENTE"],
        ),
        "marco_normativo": df.columns[29] if len(df.columns) >= 30 else None,  # AD
    }


@st.cache_data(ttl=300, show_spinner=False)
def cargar_universo_online() -> pd.DataFrame:
    response = requests.get(PUBLISHED_SHEET_URL, timeout=45)
    response.raise_for_status()
    if "text/html" in response.headers.get("content-type", "").lower():
        raise RuntimeError("Google devolvió HTML en lugar del libro XLSX publicado.")
    return pd.read_excel(io.BytesIO(response.content), sheet_name=SHEET_NAME)


# ============================================================================== 
# ÍNDICES DE BÚSQUEDA
# ============================================================================== 


def unique_clean_values(df: pd.DataFrame, col: Optional[str]) -> List[str]:
    if not col or col not in df.columns:
        return []
    vals = df[col].dropna().astype(str).str.strip()
    vals = [v for v in vals.unique().tolist() if v]
    return vals


def build_index(df: pd.DataFrame, col: Optional[str]) -> pd.DataFrame:
    vals = unique_clean_values(df, col)
    return pd.DataFrame({
        "original": vals,
        "norm": [normalize_text(v) for v in vals],
    })


def fuzzy_candidates(index_df: pd.DataFrame, query: str, min_score: float = 68, limit: int = 30) -> Tuple[List[str], float]:
    q = normalize_search_phrase(query)
    if not q or index_df.empty:
        return [], 0.0

    choices = index_df["norm"].tolist()
    results: List[Tuple[str, float]] = []

    if RAPIDFUZZ_AVAILABLE:
        matches = process.extract(q, choices, scorer=fuzz.WRatio, limit=limit)
        for matched, score, idx in matches:
            if float(score) >= min_score:
                results.append((index_df.iloc[idx]["original"], float(score)))
    else:
        for idx, val in enumerate(choices):
            score = SequenceMatcher(None, q, val).ratio() * 100
            if score >= min_score:
                results.append((index_df.iloc[idx]["original"], score))
        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:limit]

    # Si el texto de consulta está contenido en el valor, reforzamos la coincidencia.
    for idx, row in index_df.iterrows():
        if q and q in row["norm"]:
            item = row["original"]
            if item not in {x[0] for x in results}:
                results.append((item, 94.0))

    results.sort(key=lambda x: (-x[1], len(x[0])))
    return [x[0] for x in results[:limit]], (results[0][1] if results else 0.0)


def mask_contains(serie: pd.Series, text: str) -> pd.Series:
    q = normalize_text(text)
    if not q:
        return pd.Series(True, index=serie.index)
    return serie.astype(str).map(normalize_text).str.contains(q, regex=False, na=False)


def exact_or_fuzzy_field_mask(df: pd.DataFrame, col: Optional[str], query: str, min_score: float = 70) -> Tuple[pd.Series, float]:
    empty = pd.Series(False, index=df.index)
    if not col or col not in df.columns:
        return empty, 0.0

    q = normalize_search_phrase(query)
    if not q:
        return empty, 0.0

    serie = df[col].astype(str)
    norm = serie.map(normalize_text)

    # Coincidencia por frase.
    exact = norm.str.contains(q, regex=False, na=False)
    if exact.any():
        return exact, 100.0

    # Todas las palabras significativas en el mismo campo.
    tokens = [singularize_token(t) for t in q.split() if len(t) >= 2]
    if tokens:
        token_mask = pd.Series(True, index=df.index)
        for token in tokens:
            token_mask &= norm.str.contains(token, regex=False, na=False)
        if token_mask.any():
            return token_mask, 96.0

    # Variaciones históricas por valores únicos del campo.
    index_df = build_index(df, col)
    candidates, score = fuzzy_candidates(index_df, q, min_score=min_score, limit=40)
    if candidates:
        valid_norm = {normalize_text(v) for v in candidates}
        return norm.isin(valid_norm), score

    return empty, score


def procedure_family_mask(df: pd.DataFrame, col: Optional[str], query: str) -> Tuple[pd.Series, float]:
    """Busca una familia de procedimientos con normalización robusta.

    Para una consulta de una sola palabra, por ejemplo "constitucion",
    devuelve TODAS las denominaciones del campo L que contengan esa palabra
    como término independiente. La comparación ignora tildes, mayúsculas,
    espacios y caracteres Unicode invisibles.
    """
    empty = pd.Series(False, index=df.index)
    if not col or col not in df.columns:
        return empty, 0.0

    q = normalize_search_phrase(query)
    tokens = [t for t in q.split() if len(t) >= 2]
    if not tokens:
        return empty, 0.0

    norm = df[col].astype(str).map(normalize_text)

    # Búsqueda por término completo. El límite está dado por cualquier
    # carácter no alfanumérico, evitando AFECTACION -> DESAFECTACION.
    mask = pd.Series(True, index=df.index)
    for token in tokens:
        token_re = rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])"
        mask &= norm.str.contains(token_re, regex=True, na=False)

    if mask.any():
        return mask, 100.0 if len(tokens) == 1 else 98.0

    # Fallback robusto para casos donde Google Sheets haya introducido
    # caracteres Unicode/espacios atípicos dentro de la denominación.
    compact_norm = norm.str.replace(r"[^A-Z0-9]+", "", regex=True)
    compact_query = re.sub(r"[^A-Z0-9]+", "", q)
    if compact_query and len(compact_query) >= 3:
        compact_mask = compact_norm.str.contains(
            re.escape(compact_query), regex=False, na=False
        )
        if compact_mask.any():
            return compact_mask, 96.0

    return empty, 0.0


def procedure_field_mask(df: pd.DataFrame, col: Optional[str], query: str) -> Tuple[pd.Series, float]:
    """Busca procedimientos por términos/frases completos, evitando falsos positivos.

    Ej.: AFECTACION EN USO no coincide con DESAFECTACION solo porque
    comparte una parte de la palabra. Una consulta como COMPRAVENTA
    sí puede abarcar COMPRAVENTA DIRECTA y REGULARIZACION ... DE COMPRAVENTA,
    porque COMPRAVENTA aparece como término completo del procedimiento.
    """
    empty = pd.Series(False, index=df.index)
    if not col or col not in df.columns:
        return empty, 0.0
    q = normalize_search_phrase(query)
    if not q:
        return empty, 0.0

    norm = df[col].astype(str).map(normalize_text)

    # Para una sola palabra, la búsqueda es por familia de procedimiento: todos
    # los nombres de la columna L que contengan esa palabra completa.
    if len(q.split()) == 1:
        family_mask, family_score = procedure_family_mask(df, col, q)
        if family_mask.any():
            return family_mask, family_score

    phrase_re = rf"(?:^| ){re.escape(q)}(?: |$)"
    exact = norm.str.contains(phrase_re, regex=True, na=False)
    if exact.any():
        return exact, 100.0

    # Para frases de varios términos, todos deben existir como palabras completas.
    tokens = [t for t in q.split() if len(t) >= 2]
    if len(tokens) >= 2:
        token_mask = pd.Series(True, index=df.index)
        for token in tokens:
            token_re = rf"(?:^| ){re.escape(token)}(?: |$)"
            token_mask &= norm.str.contains(token_re, regex=True, na=False)
        if token_mask.any():
            return token_mask, 96.0

    # Último recurso: tolerancia alta para errores ortográficos. No usamos WRatio
    # porque puede considerar demasiado parecidas palabras como AFECTACION/DESAFECTACION.
    index_df = build_index(df, col)
    choices = index_df["norm"].tolist() if not index_df.empty else []
    if RAPIDFUZZ_AVAILABLE and choices:
        matches = process.extract(q, choices, scorer=fuzz.ratio, limit=10)
        strong = [(index_df.iloc[idx]["original"], float(score)) for _, score, idx in matches if float(score) >= 92]
        if strong:
            valid = {normalize_text(v) for v, _ in strong}
            best = max(score for _, score in strong)
            return norm.isin(valid), best
    elif choices:
        scores = []
        for idx, val in enumerate(choices):
            score = SequenceMatcher(None, q, val).ratio() * 100
            if score >= 92:
                scores.append((index_df.iloc[idx]["original"], score))
        if scores:
            valid = {normalize_text(v) for v, _ in scores}
            return norm.isin(valid), max(score for _, score in scores)

    return empty, 0.0


# ============================================================================== 
# PARSEO DE LA CONSULTA
# ============================================================================== 

STATUS_ATENDIDO = ["ARCHIVADO", "RESOLUCION EMITIDA", "RESOLUCION CONSENTIDA"]
STATUS_TRAMITE = ["GENERADO", "CON FICHA TECNICA", "TRAMITE"]

STOPWORDS = {
    "EN", "DE", "DEL", "LA", "EL", "LOS", "LAS", "POR", "PARA", "CON",
    "Y", "A", "ENTRE", "DESDE", "HASTA", "AL", "LOS", "ANOS", "ANO",
}

# Señales lingüísticas que suelen indicar que el usuario está buscando una entidad
# y no un procedimiento que casualmente contiene alguna de esas palabras.
ENTITY_CUES = {
    "EMPRESA", "SOCIEDAD", "MUNICIPALIDAD", "MUNICIPIO", "GOBIERNO", "MINISTERIO",
    "UNIVERSIDAD", "INVERSIONES", "CORPORACION", "CORPORACIÓN", "ASOCIACION", "ASOCIACIÓN",
    "COMUNIDAD", "CONSORCIO", "COOPERATIVA", "BANCO", "CAJA", "FUNDACION", "FUNDACIÓN",
    "INMOBILIARIA", "ORGANISMO", "INSTITUTO", "SUPERINTENDENCIA", "DIRECCION", "DIRECCIÓN",
}


class ParsedQuery:
    def __init__(self):
        self.raw = ""
        self.cleaned = ""
        self.entity_text = ""
        self.procedure_text = ""
        self.location_text = ""
        self.status_group = ""
        self.normative_key = ""
        self.year_min: Optional[int] = None
        self.year_max: Optional[int] = None
        self.year_explicit = False
        self.interpretation: List[Tuple[str, str]] = []
        self.mode = "general"
        self.direct_expediente = False
        self.ambiguous = False
        self.ambiguity_entity_text = ""
        self.ambiguity_procedure_text = ""


NORM_KNOWN_PATTERNS = [
    (re.compile(r"\b(?:DL|D L|DECRETO\s+LEGISLATIVO)\s*1192\b"), "DL 1192"),
    (re.compile(r"\b(?:LEY|L)\s*30556\b"), "LEY 30556"),
    (re.compile(r"\b(?:LEY|L)\s*29151\b"), "LEY 29151"),
]


def extract_normative(text: str) -> Tuple[str, str]:
    """Detecta marcos normativos y devuelve (texto_limpio, etiqueta)."""
    work = normalize_search_phrase(text)
    found = ""

    for pattern, label in NORM_KNOWN_PATTERNS:
        if pattern.search(work):
            found = label
            work = pattern.sub(" ", work)
            break

    if not found:
        # Forma genérica: LEY 12345 / DL 1234 / DECRETO LEGISLATIVO 1234.
        generic = re.search(
            r"\b(?:LEY|L|DL|DECRETO\s+LEGISLATIVO)\s*([0-9]{3,5})\b",
            work,
        )
        if generic:
            num = generic.group(1)
            prefix = generic.group(0).split()[0]
            found = f"LEY {num}" if prefix in {"LEY", "L"} else f"DL {num}"
            work = re.sub(re.escape(generic.group(0)), " ", work, count=1)

    # Los números desnudos 1192/30556/29151 son útiles en consultas naturales
    # como "transferencia 1192 en Lima". Nunca confundimos un año con esto.
    if not found:
        if re.search(r"\b1192\b", work):
            found = "DL 1192"
            work = re.sub(r"\b1192\b", " ", work, count=1)
        elif re.search(r"\b30556\b", work):
            found = "LEY 30556"
            work = re.sub(r"\b30556\b", " ", work, count=1)
        elif re.search(r"\b29151\b", work):
            found = "LEY 29151"
            work = re.sub(r"\b29151\b", " ", work, count=1)

    return re.sub(r"\s+", " ", work).strip(), found


YEAR_PATTERNS = [
    re.compile(r"\b(?:DEL|DESDE)\s+(19\d{2}|20\d{2})\s+(?:AL|HASTA)\s+(19\d{2}|20\d{2})\b"),
    re.compile(r"\bENTRE\s+(19\d{2}|20\d{2})\s+Y\s+(19\d{2}|20\d{2})\b"),
    re.compile(r"\b(19\d{2}|20\d{2})\s*(?:A|AL|-)\s*(19\d{2}|20\d{2})\b"),
]


def extract_years(text: str) -> Tuple[str, Optional[int], Optional[int], bool]:
    work = normalize_text(text)
    for pat in YEAR_PATTERNS:
        m = pat.search(work)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            cleaned = (work[:m.start()] + " " + work[m.end():]).strip()
            return re.sub(r"\s+", " ", cleaned), a, b, True

    years = [int(x) for x in re.findall(r"\b(?:19|20)\d{2}\b", work)]
    if len(years) >= 2:
        a, b = min(years), max(years)
        cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", work)
        return re.sub(r"\s+", " ", cleaned).strip(), a, b, True
    if len(years) == 1:
        cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", work)
        return re.sub(r"\s+", " ", cleaned).strip(), years[0], years[0], True

    return work, None, None, False


def extract_status(text: str) -> Tuple[str, str]:
    work = normalize_text(text)
    if re.search(r"\bATENDID(?:O|A|OS|AS)\b", work):
        return re.sub(r"\bATENDID(?:O|A|OS|AS)\b", " ", work).strip(), "ATENDIDOS"
    if re.search(r"\bEN\s+TRAMITE\b|\bTRAMITES?\b", work):
        cleaned = re.sub(r"\bEN\s+TRAMITE\b|\bTRAMITES?\b", " ", work).strip()
        return cleaned, "EN TRAMITE"
    return work, ""


def find_geo_phrase(query: str, geo_values: List[str]) -> Tuple[str, str]:
    """Devuelve (texto_geografico, query_sin_geografia), priorizando coincidencias largas."""
    q = normalize_text(query)
    if not q or not geo_values:
        return "", q

    # Nombres de 2+ palabras primero.
    normalized_geo = sorted(
        [(normalize_text(v), v) for v in geo_values if normalize_text(v)],
        key=lambda x: (-len(x[0]), x[0]),
    )
    for norm_geo, original in normalized_geo:
        if len(norm_geo) < 3:
            continue
        if re.search(rf"\b{re.escape(norm_geo)}\b", q):
            cleaned = re.sub(rf"\b{re.escape(norm_geo)}\b", " ", q, count=1)
            return original, re.sub(r"\s+", " ", cleaned).strip()

    # Frase posterior a EN.
    m = re.search(r"\bEN\s+(.+)$", q)
    if m:
        right = m.group(1).strip()
        # Exacto o fuzzy contra un nombre geográfico completo.
        exact = [orig for norm, orig in normalized_geo if norm == right]
        if exact:
            cleaned = q[:m.start()].strip()
            return exact[0], cleaned
        candidates, _ = fuzzy_candidates(
            pd.DataFrame({"original": [x[1] for x in normalized_geo], "norm": [x[0] for x in normalized_geo]}),
            right,
            min_score=86,
            limit=5,
        )
        if candidates:
            cleaned = q[:m.start()].strip()
            return candidates[0], cleaned

    return "", q



def direct_single_term_procedure_family(
    df: pd.DataFrame,
    procedimiento_col: Optional[str],
    text: str,
) -> str:
    """Devuelve el término si existe como palabra completa en la columna L.

    Esta ruta es deliberadamente directa para consultas de una sola palabra:
    por ejemplo CONSTITUCION debe recuperar la familia completa de procedimientos
    que contenga CONSTITUCION, sin pasar por la puntuación entidad/procedimiento.
    """
    if not procedimiento_col or procedimiento_col not in df.columns:
        return ""

    q = normalize_search_phrase(text)
    if len(q.split()) != 1 or len(q) < 3:
        return ""

    # Primero, coincidencia por palabra completa en la columna L.
    values = df[procedimiento_col].fillna("").astype(str)
    normalized = values.map(normalize_text)
    token_re = rf"(?<![A-Z0-9]){re.escape(q)}(?![A-Z0-9])"

    if normalized.str.contains(token_re, regex=True, na=False).any():
        return q

    # Fallback: compactar separadores para tolerar espacios/caracteres Unicode
    # anómalos de Google Sheets sin cambiar el significado de la palabra.
    compact = normalized.str.replace(r"[^A-Z0-9]+", "", regex=True)
    q_compact = re.sub(r"[^A-Z0-9]+", "", q)
    if len(q_compact) >= 3 and compact.str.contains(
        re.escape(q_compact), regex=False, na=False
    ).any():
        return q

    return ""


def find_procedure_candidate(query: str, procedure_index: pd.DataFrame) -> Tuple[str, str]:
    """Identifica una familia de procedimiento sin convertirla en un único registro.

    Si el usuario escribe COMPRAVENTA, devolvemos COMPRAVENTA como criterio de
    procedimiento y luego el filtro alcanza COMPRAVENTA DIRECTA,
    REGULARIZACION ... DE COMPRAVENTA, etc.
    """
    if procedure_index.empty:
        return "", query
    q = normalize_search_phrase(query)
    if not q:
        return "", q

    catalog = []
    for _, row in procedure_index.iterrows():
        original = str(row["original"]).strip()
        norm_proc = normalize_search_phrase(original)
        if norm_proc:
            catalog.append((norm_proc, original))

    # 0) Una sola palabra que aparezca como término completo dentro de cualquier
    # procedimiento se interpreta como familia. Esto cubre, por ejemplo,
    # CONSTITUCION aunque el nombre real sea CONSTITUCION DEL DERECHO DE SUPERFICIE.
    if len(q.split()) == 1:
        token_re = re.compile(rf"(?<![A-Z0-9]){re.escape(q)}(?![A-Z0-9])")
        if any(token_re.search(norm_proc) for norm_proc, _ in catalog):
            return q, ""

        # Fallback adicional: compactamos la denominación del procedimiento
        # para tolerar caracteres invisibles/espacios anómalos de Sheets.
        q_compact = re.sub(r"[^A-Z0-9]+", "", q)
        if q_compact:
            if any(q_compact in re.sub(r"[^A-Z0-9]+", "", norm_proc) for norm_proc, _ in catalog):
                return q, ""

    # 1) Coincidencia exacta con un procedimiento del catálogo.
    exact_map = {norm_proc: original for norm_proc, original in catalog}
    if q in exact_map:
        return exact_map[q], ""

    # 2) Si la consulta aparece como frase completa dentro de uno o varios
    # procedimientos, la tratamos como familia. Esto cubre CONSTITUCION, COMPRAVENTA,
    # TRANSFERENCIA, SERVIDUMBRE y cualquier otra familia presente realmente en L.
    family_hits = []
    q_re = re.compile(rf"(?:^| ){re.escape(q)}(?: |$)")
    for norm_proc, _ in catalog:
        if q_re.search(norm_proc):
            family_hits.append(norm_proc)
    if family_hits:
        cleaned = re.sub(rf"(?:^| ){re.escape(q)}(?: |$)", " ", q, count=1).strip()
        return q, re.sub(r"\s+", " ", cleaned).strip()

    # 3) Para consultas compuestas, buscar n-gramas exactos del texto en el catálogo.
    words = [t for t in q.split() if t not in STOPWORDS and len(t) >= 4]
    for size in range(min(4, len(words)), 0, -1):
        for start in range(0, len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            phrase_re = re.compile(rf"(?:^| ){re.escape(phrase)}(?: |$)")
            if any(phrase_re.search(norm_proc) for norm_proc, _ in catalog):
                cleaned = re.sub(rf"(?:^| ){re.escape(phrase)}(?: |$)", " ", q, count=1)
                return phrase, re.sub(r"\s+", " ", cleaned).strip()

    # 4) Tolerancia ortográfica para una palabra/frase corta, pero usando ratio puro.
    if words:
        candidates = []
        for phrase_size in range(min(3, len(words)), 0, -1):
            for start in range(0, len(words) - phrase_size + 1):
                phrase = " ".join(words[start:start + phrase_size])
                if RAPIDFUZZ_AVAILABLE:
                    matches = process.extract(phrase, [x[0] for x in catalog], scorer=fuzz.ratio, limit=3)
                    for _, score, idx in matches:
                        if float(score) >= 93:
                            candidates.append((phrase, float(score)))
                else:
                    for norm_proc, _ in catalog:
                        score = SequenceMatcher(None, phrase, norm_proc).ratio() * 100
                        if score >= 93:
                            candidates.append((phrase, score))
                if candidates:
                    phrase, _ = max(candidates, key=lambda x: x[1])
                    cleaned = q.replace(phrase, " ", 1)
                    return phrase, re.sub(r"\s+", " ", cleaned).strip()
    return "", q


def has_entity_cue(text: str) -> bool:
    tokens = set(normalize_search_phrase(text).split())
    return bool(tokens & {singularize_token(x) for x in ENTITY_CUES})


def choose_field_intent(
    df: pd.DataFrame,
    text: str,
    cols: Dict[str, Optional[str]],
    allow_ambiguity: bool = True,
) -> Tuple[str, str, float, Optional[Tuple[str, str]]]:
    """
    Decide si una consulta encaja mejor en Procedimiento o Entidad/Administrado.
    Devuelve (campo, valor, score, ambigüedad).
    La prioridad institucional es: procedimiento conocido > entidad genérica,
    salvo cuando el contexto contiene una señal clara de entidad.
    """
    q = normalize_search_phrase(text)
    if not q:
        return "", "", 0.0, None

    entity_mask, entity_score = exact_or_fuzzy_field_mask(
        df, cols.get("entidad"), q, min_score=70
    )
    proc_mask, proc_score = procedure_field_mask(
        df, cols.get("procedimiento"), q
    )

    # Coincidencia exacta con un procedimiento del catálogo: máxima prioridad.
    proc_exact = False
    proc_original = q
    proc_col = cols.get("procedimiento")
    if proc_col and proc_col in df.columns:
        norm_values = {normalize_search_phrase(v): v for v in unique_clean_values(df, proc_col)}
        if q in norm_values:
            proc_exact = True
            proc_original = norm_values[q]
            proc_score = 100.0

    if has_entity_cue(q) and entity_mask.any() and entity_score >= 70:
        return "entidad", q, entity_score, None

    if proc_exact and proc_mask.any():
        return "procedimiento", proc_original, 100.0, None

    if entity_mask.any() and proc_mask.any():
        diff = abs(entity_score - proc_score)
        # Solo mostramos una elección cuando EXISTEN coincidencias fuertes en
        # ambos campos. Una coincidencia débil o casual en Administrado no
        # debe generar una falsa ambigüedad.
        STRONG_AMBIGUITY_SCORE = 90
        MAX_AMBIGUITY_SCORE_DIFF = 5
        if (
            allow_ambiguity
            and entity_score >= STRONG_AMBIGUITY_SCORE
            and proc_score >= STRONG_AMBIGUITY_SCORE
            and diff <= MAX_AMBIGUITY_SCORE_DIFF
        ):
            return "", q, max(entity_score, proc_score), (q, q)

        # Si solo uno de los campos tiene una coincidencia claramente fuerte,
        # priorizamos ese campo sin preguntar al usuario.
        if proc_score >= entity_score:
            return "procedimiento", q, proc_score, None
        return "entidad", q, entity_score, None

    if proc_mask.any() and proc_score >= 72:
        return "procedimiento", q, proc_score, None
    if entity_mask.any() and entity_score >= 70:
        return "entidad", q, entity_score, None

    # Si no hay match directo, intentamos el catálogo de procedimientos para
    # detectar una palabra/fragmento dentro de una consulta más larga.
    return "", q, max(entity_score, proc_score), None


def procedure_in_catalog(text: str, procedure_index: pd.DataFrame) -> Tuple[str, float]:
    q = normalize_search_phrase(text)
    if not q or procedure_index.empty:
        return "", 0.0
    exact_map = {normalize_search_phrase(v): v for v in procedure_index["original"].tolist()}
    if q in exact_map:
        return exact_map[q], 100.0
    matches, score = fuzzy_candidates(procedure_index, q, min_score=82, limit=5)
    return (matches[0], score) if matches else ("", 0.0)


def attach_interpretation(p: ParsedQuery, field: str, value: str) -> None:
    if not value:
        return
    label = "Procedimiento" if field == "procedimiento" else "Entidad / administrado"
    shown = value if field == "procedimiento" else value.title()
    p.interpretation.append((label, shown))


def parse_query(
    query: str,
    df: pd.DataFrame,
    cols: Dict[str, Optional[str]],
    entity_index: pd.DataFrame,
    procedure_index: pd.DataFrame,
    geo_values: List[str],
) -> ParsedQuery:
    p = ParsedQuery()
    p.raw = query.strip()

    work, normative_key = extract_normative(query)
    p.normative_key = normative_key
    if normative_key:
        p.interpretation.append(("Marco normativo", normative_key))

    work, y1, y2, explicit_year = extract_years(work)
    work, status = extract_status(normalize_search_phrase(work))
    p.year_min, p.year_max, p.year_explicit = y1, y2, explicit_year
    p.status_group = status

    if status:
        p.interpretation.append(("Situación", "Atendidos" if status == "ATENDIDOS" else "En trámite"))
    if y1 is not None:
        p.interpretation.append(("Periodo", str(y1) if y1 == y2 else f"{y1}–{y2}"))

    # 1) Búsqueda directa por expediente.
    expediente_col = cols.get("expediente")
    if expediente_col and re.search(r"\d", work):
        compact = re.sub(r"\s+", "", work)
        if re.search(r"\d{2,}[-/]\d{2,4}", compact) or (
            len(compact) <= 30 and re.search(r"\d", compact) and not p.year_explicit
        ):
            p.direct_expediente = True
            p.cleaned = work
            p.mode = "expediente"
            p.interpretation.insert(0, ("Expediente", query.strip()))
            return p

    # 2) Consulta de una sola palabra que pertenece a una familia de procedimiento.
    # Se evalúa ANTES de geografía porque algunas denominaciones de procedimiento
    # pueden coincidir también con nombres geográficos. Un ejemplo real es
    # "CONSTITUCION", que también puede ser un nombre geográfico.
    direct_family = direct_single_term_procedure_family(
        df, cols.get("procedimiento"), work
    )
    if direct_family:
        p.procedure_text = direct_family
        p.interpretation.append(("Procedimiento", direct_family.title()))
        p.mode = "procedimiento"
        p.cleaned = ""
        return p

    # 3) Extraer geografía. La ubicación es un criterio obligatorio si la consulta la contiene.
    geo_match, residual = find_geo_phrase(work, geo_values)
    if geo_match:
        p.location_text = geo_match
        p.interpretation.append(("Ubicación", geo_match.title()))

    # 4) Forma explícita "X EN Y". Se prioriza procedimiento cuando X pertenece
    # a un procedimiento conocido; entidad gana cuando la frase contiene señales fuertes de entidad.
    m = re.search(r"\bEN\b", work)
    if m:
        left = work[:m.start()].strip()
        right = work[m.end():].strip()
        if left and right:
            geo_right, _ = find_geo_phrase(right, geo_values)
            if geo_right:
                p.location_text = geo_right
                # Prioridad: procedimiento conocido -> entidad -> ambigüedad.
                proc_exact, proc_exact_score = procedure_in_catalog(left, procedure_index)
                kind, value, score, ambiguity = choose_field_intent(df, left, cols, allow_ambiguity=True)
                if proc_exact and proc_exact_score >= 100:
                    p.procedure_text = proc_exact
                    p.interpretation.append(("Procedimiento", proc_exact))
                elif kind == "procedimiento":
                    p.procedure_text = value
                    p.interpretation.append(("Procedimiento", value))
                elif kind == "entidad":
                    p.entity_text = left
                    p.interpretation.append(("Entidad / administrado", left.title()))
                elif ambiguity:
                    p.ambiguous = True
                    p.ambiguity_entity_text = left
                    p.ambiguity_procedure_text = left
                    # Aplicación por defecto: procedimiento, por la jerarquía institucional.
                    p.procedure_text = left
                    p.interpretation.append(("Procedimiento", left.title()))
                else:
                    # Último recurso: entidad para mantener búsquedas naturales como "Sedapal en Piura".
                    p.entity_text = left
                    p.interpretation.append(("Entidad / administrado", left.title()))
                p.mode = "compuesta"
                p.cleaned = ""
                return p

    # 5) Si la consulta contiene una señal fuerte de entidad (por ejemplo,
    # "empresa", "municipalidad", "gobierno", "sociedad"), damos prioridad
    # a la entidad completa antes de interpretar una palabra interna como procedimiento.
    if not p.location_text and has_entity_cue(work) and cols.get("entidad"):
        entity_matches, entity_score = fuzzy_candidates(entity_index, work, min_score=70, limit=40)
        if entity_matches and entity_score >= 70:
            p.entity_text = work
            p.interpretation.append(("Entidad / administrado", work.title()))
            p.mode = "entidad"
            p.cleaned = ""
            return p

    # 6) Buscar un procedimiento conocido en cualquier parte de la consulta restante.
    proc, proc_residual = find_procedure_candidate(work, procedure_index)
    if proc:
        p.procedure_text = proc
        p.interpretation.append(("Procedimiento", proc))
        p.cleaned = proc_residual
        if p.location_text:
            p.mode = "compuesta"
            p.cleaned = ""
        else:
            p.mode = "procedimiento"
            if proc_residual:
                # Si todavía queda una frase de entidad reconocible, la añadiremos abajo.
                kind, value, score, ambiguity = choose_field_intent(df, proc_residual, cols, allow_ambiguity=True)
                if kind == "entidad":
                    p.entity_text = value
                    p.interpretation.append(("Entidad / administrado", value.title()))
                    p.cleaned = ""
                elif kind == "procedimiento":
                    p.cleaned = ""
        return p

    # 7) Si toda la frase coincide fuertemente con una entidad, tratarla como entidad.
    if cols.get("entidad"):
        entity_matches, entity_score = fuzzy_candidates(entity_index, work, min_score=70, limit=40)
        if entity_matches and entity_score >= 70:
            p.entity_text = work
            p.interpretation.append(("Entidad / administrado", work.title()))
            p.mode = "compuesta" if p.location_text else "entidad"
            p.cleaned = ""
            return p

    # 8) Residuo + ubicación, por ejemplo "municipalidades de Piura" o
    # "gobierno regional de Arequipa".
    if p.location_text and residual:
        kind, value, score, ambiguity = choose_field_intent(df, residual, cols, allow_ambiguity=True)
        if kind == "procedimiento":
            p.procedure_text = value
            p.interpretation.append(("Procedimiento", value))
        elif kind == "entidad":
            p.entity_text = value
            p.interpretation.append(("Entidad / administrado", value.title()))
        elif ambiguity:
            p.ambiguous = True
            p.ambiguity_entity_text = residual
            p.ambiguity_procedure_text = residual
            p.procedure_text = residual
            p.interpretation.append(("Procedimiento", residual.title()))
        else:
            p.entity_text = residual
            p.interpretation.append(("Entidad / administrado", residual.title()))
        p.mode = "compuesta"
        p.cleaned = ""
        return p

    # 9) Ubicación sola.
    if p.location_text:
        p.mode = "ubicacion"
        p.cleaned = residual
        return p

    # 10) Búsqueda libre: todos los términos significativos deben participar.
    # Si hay ambigüedad fuerte, la mostramos en UI; si no, se mantiene la búsqueda AND.
    p.cleaned = work
    p.interpretation.append(("Búsqueda", work.title()))
    p.mode = "general"
    return p


# ============================================================================== 
# MOTOR DE APLICACIÓN DE LA CONSULTA
# ============================================================================== 


def status_group_mask(df: pd.DataFrame, estado_col: Optional[str], group: str) -> pd.Series:
    if not estado_col or estado_col not in df.columns or not group:
        return pd.Series(True, index=df.index)
    s = df[estado_col].astype(str).map(normalize_text)
    if group == "ATENDIDOS":
        return (
            s.str.contains("ARCHIVADO", regex=False, na=False)
            | s.str.contains("RESOLUCION EMITIDA", regex=False, na=False)
            | s.str.contains("RESOLUCION CONSENTIDA", regex=False, na=False)
        )
    if group == "EN TRAMITE":
        return (
            s.str.contains("GENERADO", regex=False, na=False)
            | s.str.contains("CON FICHA TECNICA", regex=False, na=False)
            | s.str.contains("TRAMITE", regex=False, na=False)
            | s.str.contains("SUSPENDIDO CON RESOLUCION", regex=False, na=False)
        )
    return pd.Series(True, index=df.index)


def year_mask(df: pd.DataFrame, anio_col: Optional[str], y1: Optional[int], y2: Optional[int]) -> pd.Series:
    if not anio_col or y1 is None or y2 is None:
        return pd.Series(True, index=df.index)
    years = pd.to_numeric(
        df[anio_col].astype(str).str.extract(r"((?:19|20)\d{2})")[0],
        errors="coerce",
    )
    return years.between(y1, y2, inclusive="both").fillna(False)


def apply_parsed_query(df: pd.DataFrame, p: ParsedQuery, cols: Dict[str, Optional[str]], entity_index: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()

    if p.direct_expediente and cols.get("expediente"):
        q = normalize_text(p.raw)
        work = work[work[cols["expediente"]].astype(str).map(normalize_text).str.contains(q, regex=False, na=False)]
    else:
        mask = pd.Series(True, index=work.index)

        if p.entity_text and cols.get("entidad"):
            # La entidad se trata con tolerancia dentro del campo D, pero como condición AND.
            entity_mask, _ = exact_or_fuzzy_field_mask(work, cols["entidad"], p.entity_text, min_score=70)
            mask &= entity_mask

        if p.procedure_text and cols.get("procedimiento"):
            proc_mask, proc_score = procedure_field_mask(
                work, cols["procedimiento"], p.procedure_text
            )

            # Para una sola palabra de procedimiento, aseguramos el concepto
            # de "familia" directamente sobre la columna L.
            q_proc = normalize_search_phrase(p.procedure_text)
            if len(q_proc.split()) == 1 and not proc_mask.any():
                raw_proc = work[cols["procedimiento"]].astype(str)
                norm_proc = raw_proc.map(normalize_text)
                token_re = rf"(?<![A-Z0-9]){re.escape(q_proc)}(?![A-Z0-9])"
                proc_mask = norm_proc.str.contains(token_re, regex=True, na=False)

                if not proc_mask.any():
                    compact_series = norm_proc.str.replace(
                        r"[^A-Z0-9]+", "", regex=True
                    )
                    compact_q = re.sub(r"[^A-Z0-9]+", "", q_proc)
                    if compact_q:
                        proc_mask = compact_series.str.contains(
                            re.escape(compact_q), regex=False, na=False
                        )

            mask &= proc_mask

        if p.normative_key and cols.get("marco_normativo"):
            norm_col = cols["marco_normativo"]
            norm_series = work[norm_col].astype(str).map(normalize_text)
            if p.normative_key == "DL 1192":
                norm_mask = (norm_series.str.contains("1192", regex=False, na=False) | norm_series.str.contains("DECRETO LEGISLATIVO 1192", regex=False, na=False))
            elif p.normative_key == "LEY 30556":
                norm_mask = (norm_series.str.contains("30556", regex=False, na=False) | norm_series.str.contains("LEY 30556", regex=False, na=False))
            elif p.normative_key == "LEY 29151":
                norm_mask = (norm_series.str.contains("29151", regex=False, na=False) | norm_series.str.contains("LEY 29151", regex=False, na=False))
            else:
                generic_num = re.search(r"(\d{3,5})$", p.normative_key)
                norm_mask = norm_series.str.contains(generic_num.group(1), regex=False, na=False) if generic_num else pd.Series(False, index=work.index)
            mask &= norm_mask

        if p.location_text:
            geo_mask = pd.Series(False, index=work.index)
            for key in ("departamento", "provincia", "distrito"):
                col = cols.get(key)
                if col:
                    geo_mask |= mask_contains(work[col], p.location_text)
            # Ubicación es obligatoria cuando fue interpretada.
            mask &= geo_mask

        if p.status_group:
            mask &= status_group_mask(work, cols.get("estado"), p.status_group)

        if p.year_explicit:
            mask &= year_mask(work, cols.get("anio"), p.year_min, p.year_max)

        if p.mode == "general" and p.cleaned:
            tokens = [singularize_token(t) for t in normalize_text(p.cleaned).split() if t not in STOPWORDS and len(t) >= 2]
            search_fields = [cols.get("entidad"), cols.get("procedimiento"), cols.get("departamento"), cols.get("provincia"), cols.get("distrito")]
            search_fields = [x for x in search_fields if x]
            for token in tokens:
                token_match = pd.Series(False, index=work.index)
                for col in search_fields:
                    token_match |= mask_contains(work[col], token)
                mask &= token_match

        work = work[mask]

    return work


# ============================================================================== 
# PRIVACIDAD
# ============================================================================== 

LEGAL_ENTITY_RE = re.compile(
    r"MUNICIPALIDAD|MUNICIPIO|GOBIERNO|MINISTERIO|REGIONAL|MINERA|MINER[A-Z]*|"
    r"SOCIEDAD|INVERSIONES|EMPRESA|COMPA(N|Ñ)IA|CORPORACION|ASOCIACION|COMUNIDAD|"
    r"CONSORCIO|DIRECCION|SUPERINTENDENCIA|UNIVERSIDAD|COOPERATIVA|SINDICATO|"
    r"FUNDACION|PROYECTO|IGLESIA|COMITE|JUNTA|ORGANISMO|INSTITUTO|BANCO|CAJA|"
    r"INMOBILIARIA|ONG|S\.\s*A|S\.\s*R\.\s*L|E\.\s*I\.\s*R\.\s*L|"
    r"PERSONA JURIDICA", re.IGNORECASE
)


def aplicar_privacidad_venta(df_resultados: pd.DataFrame, cols: Dict[str, Optional[str]]) -> pd.DataFrame:
    out = df_resultados.copy()
    proc_col = cols.get("procedimiento")
    admin_col = cols.get("entidad")
    if not proc_col or not admin_col or proc_col not in out.columns or admin_col not in out.columns:
        return out

    proc = out[proc_col].astype(str).map(normalize_text)
    admin = out[admin_col].astype(str).map(normalize_text)
    # COMPRAVENTA también debe activar la regla.
    venta = proc.str.contains("VENTA", regex=False, na=False)
    juridica = admin.str.contains(LEGAL_ENTITY_RE, regex=True, na=False)
    out.loc[venta & ~juridica, admin_col] = "PERSONA NATURAL"
    return out

# ==============================================================================
# FLUJO PRINCIPAL
# ==============================================================================
tab_gestion, tab_produccion, tab_busqueda = st.tabs(["📁 Gestión de Expedientes", "📊 Avance de Producción", "🔎 Búsqueda de Expedientes"])

with tab_gestion:
    try:
        with st.spinner("Conectando con la base de datos..."):
            df = cargar_datos()
    except Exception as e:
        st.error("Error al conectar con la base de datos de Gestión.")
        st.stop()
        
    modal_trigger = st.text_input("modal_trigger", key="modal_trigger_input", label_visibility="hidden")
    
    if 'last_trigger' not in st.session_state: 
        st.session_state.last_trigger = ""
        
    if modal_trigger and modal_trigger != st.session_state.last_trigger:
        st.session_state.last_trigger = modal_trigger
        parts = modal_trigger.split("|||")
        if len(parts) >= 4:
            mostrar_modal_detalle(parts[0], parts[1], parts[2], parts[3], df)

    equipos_lista = sorted(df["Equipo"].dropna().astype(str).unique().tolist())

    if st.session_state.capa_actual == 1:
        mostrar_encabezado("Gestión de Expedientes SDDI", "Gestión y seguimiento de expedientes en trámite a nivel nacional.", mostrar_volver=False)

        # ------------------------------------------------------------------------------
        # CAPA 1 - BLOQUE 1: ÚLTIMA ACCIÓN REALIZADA
        # ------------------------------------------------------------------------------
        st.markdown("<h4 style='color:#2C3E50; margin-bottom:5px;'>📌 Expedientes por última acción realizada</h4>", unsafe_allow_html=True)
        tab_acc_gen, tab_acc_eq = st.tabs(["📊 Resumen General", "🏢 Comparativo por Equipos"])
        
        with tab_acc_gen:
            c_izq, m1, m2, m3, m4, c_der = st.columns([1, 3, 3, 3, 3, 1])
            with m1: crear_tarjeta("📁 Total en Trámite", len(df), "#3498DB", id_click="acciones")
            with m2: crear_tarjeta("🟢 Trámite Activo (1-3 semanas)", df[df["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0], "#2ECC71", id_click="acciones")
            with m3: crear_tarjeta("🟡 Flujo Lento (1 a 5 meses)", df[df["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False) & ~df["Trazabilidad"].astype(str).str.contains("6 meses", case=False, na=False)].shape[0], "#F1C40F", id_click="acciones")
            with m4: crear_tarjeta("🔴 Paralizados (+6 meses)", df[df["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)].shape[0], "#E74C3C", id_click="acciones")

        with tab_acc_eq:
            html_acc = """
            <div style="max-width: 900px; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF; overflow-x: auto;">
                <table class="tabla-matricial">
                    <thead>
                        <tr>
                            <th class="col-fija">EQUIPO DE TRABAJO</th>
                            <th style="background-color: #27AE60;">TRÁMITE ACTIVO<br><span style="font-size:8px; font-weight:500; opacity:0.9;">(1-3 SEMANAS)</span></th>
                            <th style="background-color: #F39C12;">FLUJO LENTO<br><span style="font-size:8px; font-weight:500; opacity:0.9;">(1 A 5 MESES)</span></th>
                            <th style="background-color: #C0392B;">PARALIZADOS<br><span style="font-size:8px; font-weight:500; opacity:0.9;">(+6 MESES)</span></th>
                            <th style="background-color: #1F618D;">TOTAL EXP.</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for eq in equipos_lista:
                df_e = df[df["Equipo"] == eq]
                t_tot = len(df_e)
                t_act = df_e[df_e["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0]
                t_len = df_e[df_e["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False) & ~df_e["Trazabilidad"].astype(str).str.contains("6 meses", case=False, na=False)].shape[0]
                t_par = df_e[df_e["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)].shape[0]
                
                html_acc += f"<tr>"
                html_acc += f"<td class='col-equipo celda-equipo-clic mod-accion' data-equipo='{eq}' data-tipo='TOTAL'>{eq}</td>"
                html_acc += f"<td class='celda-equipo-clic mod-accion' data-equipo='{eq}' data-tipo='ACTIVO'>{t_act}</td>"
                html_acc += f"<td class='celda-equipo-clic mod-accion' data-equipo='{eq}' data-tipo='LENTO'>{t_len}</td>"
                html_acc += f"<td class='celda-equipo-clic mod-accion' data-equipo='{eq}' data-tipo='PARALIZADO'>{t_par}</td>"
                html_acc += f"<td class='celda-equipo-clic mod-accion' data-equipo='{eq}' data-tipo='TOTAL' style='font-weight:900;'>{t_tot}</td>"
                html_acc += f"</tr>"
            html_acc += "</tbody></table></div>"
            st.markdown(html_acc, unsafe_allow_html=True)

        # ------------------------------------------------------------------------------
        # CAPA 1 - BLOQUE 2: AÑO DE CREACIÓN
        # ------------------------------------------------------------------------------
        st.markdown("<hr style='border:none; border-top:1px dashed #E0E6ED; margin:25px 0 15px 0;'>", unsafe_allow_html=True)
        st.markdown("<h4 style='color:#2C3E50; margin-bottom:5px;'>📅 Expedientes por año de creación</h4>", unsafe_allow_html=True)
        
        tab_anio_gen, tab_anio_proc, tab_anio_eq = st.tabs(["📊 Resumen General", "📋 Por Procedimiento", "🏢 Comparativo por Equipos"])
        
        if len(df.columns) >= 11:
            df['Año_Temp'] = df[df.columns[9]].astype(str).str.extract(r'((?:19|20)\d{2})')[0].fillna("S/F")
            df['Procedimiento_Temp'] = df[df.columns[10]].astype(str).str.strip().str.upper()
            df['Procedimiento_Temp'] = df['Procedimiento_Temp'].replace(['NAN', 'NONE', ''], 'SIN ESPECIFICAR')
            
            with tab_anio_gen:
                conteo_años = df['Año_Temp'].value_counts().sort_index(ascending=True)
                html_tabla = f"""
                <div style="overflow-x: auto; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF;">
                    <table class="tabla-matricial"><thead>
                    <tr><th colspan="{len(conteo_años)}" style="padding: 6px; letter-spacing: 1px; text-transform: uppercase;">TOTAL EXPEDIENTES POR AÑO: {len(df)}</th></tr><tr>
                """
                for año in conteo_años.index: html_tabla += f"<th class='header-secundario'>{año}</th>"
                html_tabla += "</tr></thead><tbody><tr>"
                for cantidad, año in zip(conteo_años.values, conteo_años.index):
                    html_tabla += f"<td class='celda-equipo-clic mod-anio-gen' data-anio='{año}'>{cantidad}</td>"
                html_tabla += "</tr></tbody></table></div>"
                st.markdown(html_tabla, unsafe_allow_html=True)
                
            with tab_anio_proc:
                list_años = df['Año_Temp'].value_counts().sort_index(ascending=True).index.tolist()
                procedimientos_ordenados = df['Procedimiento_Temp'].value_counts().index.tolist()
                
                html_anio_proc = """<div style="overflow-x: auto; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF;">
                    <table class="tabla-matricial"><thead><tr><th class="col-fija">PROCEDIMIENTO</th>"""
                for a in list_años: html_anio_proc += f"<th>{a}</th>"
                html_anio_proc += "<th style='background-color: #1F618D;'>TOTAL</th></tr></thead><tbody>"
                for proc in procedimientos_ordenados:
                    df_pr = df[df['Procedimiento_Temp'] == proc]
                    conteo_pr = df_pr['Año_Temp'].value_counts()
                    html_anio_proc += f"<tr><td class='col-proc mod-proc' data-proc='{proc}' data-anio='TOTAL' data-equipo='TOTAL'>{proc}</td>"
                    for a in list_años:
                        val = conteo_pr.get(a, 0)
                        txt = str(val) if val > 0 else "-"
                        if val > 0: html_anio_proc += f"<td class='mod-proc' data-proc='{proc}' data-anio='{a}' data-equipo='TOTAL'>{txt}</td>"
                        else: html_anio_proc += f"<td>{txt}</td>"
                    html_anio_proc += f"<td class='mod-proc' data-proc='{proc}' data-anio='TOTAL' data-equipo='TOTAL' style='font-weight:900;'>{len(df_pr)}</td></tr>"
                html_anio_proc += "</tbody></table></div>"
                st.markdown(html_anio_proc, unsafe_allow_html=True)

            with tab_anio_eq:
                list_años = df['Año_Temp'].value_counts().sort_index(ascending=True).index.tolist()
                
                html_anio_eq = """<div style="overflow-x: auto; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF;">
                    <table class="tabla-matricial"><thead><tr><th class="col-fija">EQUIPO DE TRABAJO</th>"""
                for a in list_años: html_anio_eq += f"<th>{a}</th>"
                html_anio_eq += "<th style='background-color: #1F618D;'>TOTAL</th></tr></thead><tbody>"
                for eq in equipos_lista:
                    df_e = df[df["Equipo"] == eq]
                    conteo_e = df_e['Año_Temp'].value_counts()
                    html_anio_eq += f"<tr><td class='col-equipo celda-equipo-clic mod-anio-eq' data-equipo='{eq}' data-anio='TOTAL'>{eq}</td>"
                    for a in list_años:
                        val = conteo_e.get(a, 0)
                        txt = str(val) if val > 0 else "-"
                        if val > 0: html_anio_eq += f"<td class='celda-equipo-clic mod-anio-eq' data-equipo='{eq}' data-anio='{a}'>{txt}</td>"
                        else: html_anio_eq += f"<td>{txt}</td>"
                    html_anio_eq += f"<td class='celda-equipo-clic mod-anio-eq' data-equipo='{eq}' data-anio='TOTAL' style='font-weight:900;'>{len(df_e)}</td></tr>"
                html_anio_eq += "</tbody></table></div>"
                st.markdown(html_anio_eq, unsafe_allow_html=True)
                
        # ------------------------------------------------------------------------------
        # CAPA 1 - BLOQUE 3: EQUIPOS DE TRABAJO
        # ------------------------------------------------------------------------------
        st.markdown("<hr style='border:none; border-top:1px solid #E0E6ED; margin:15px 0 20px 0;'><h4 style='color:#2C3E50; text-align:center;'>Carga General por Equipos de Trabajo</h4><br>", unsafe_allow_html=True)
        cols_eq = st.columns(min(len(equipos_lista), 4))
        for idx, eq in enumerate(equipos_lista):
            with cols_eq[idx % 4]:
                df_eq = df[df["Equipo"] == eq]
                criticos = df_eq[df_eq["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)].shape[0]
                st.markdown(f"""<div class="tarjeta-equipo"><h4 style="margin:0; color:#2C3E50; font-size:16px;">{eq}</h4>
                    <p style="margin:4px 0 0 0; color:#7F8C8D; font-size:12px;">Total: <b>{len(df_eq)}</b> expedientes</p>
                    <p style="margin:2px 0 8px 0; color:#E74C3C; font-size:11px; font-weight:600;">🚨 {criticos} paralizados</p></div>""", unsafe_allow_html=True)
                if st.button(f"🔍 Ver Reporte: {eq}", key=f"btn_{eq}", use_container_width=True, type="primary"):
                    ir_a_capa(2, equipo=eq)
                    st.rerun()

    # ==============================================================================
    # VISTA CAPA 2 (DETALLE DE EQUIPO)
    # ==============================================================================
    elif st.session_state.capa_actual == 2:
        components.html("<script> setTimeout(function() { window.parent.scrollTo(0, 0); }, 150); </script>", height=0, width=0)
        
        eq_sel = st.session_state.equipo_sel
        df_eq = df[df["Equipo"] == eq_sel].copy()
        profesionales_lista = df_eq["Profesional"].value_counts().sort_values(ascending=False).index.tolist()
        
        mostrar_encabezado(f"Reporte Dinámico: {eq_sel}", "Evaluación detallada de estados y carga por especialista.", mostrar_volver=True)

        # ------------------------------------------------------------------------------
        # CAPA 2 - BLOQUE 1: ÚLTIMA ACCIÓN REALIZADA
        # ------------------------------------------------------------------------------
        st.markdown("<div id='ancla-acciones'></div><h4 style='color:#2C3E50; margin-bottom:5px;'>📌 Expedientes por última acción realizada</h4>", unsafe_allow_html=True)
        t_acc_gen_prof, t_acc_prof = st.tabs(["📊 Resumen General", "👨‍💼 Por Profesional"])
        
        with t_acc_gen_prof:
            c_izq, k1, k2, k3, k4, c_der = st.columns([1, 3, 3, 3, 3, 1])
            with k1: crear_tarjeta("Total Equipo", len(df_eq), "#3498DB", id_click="acciones_prof")
            with k2: crear_tarjeta("🟢 Trámite Activo (1-3 semanas)", df_eq[df_eq["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0], "#2ECC71", id_click="acciones_prof")
            with k3: crear_tarjeta("🟡 Flujo Lento (1 a 5 meses)", df_eq[df_eq["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False) & ~df_eq["Trazabilidad"].astype(str).str.contains("6 meses", case=False, na=False)].shape[0], "#F1C40F", id_click="acciones_prof")
            with k4: crear_tarjeta("🔴 Paralizados (+6 meses)", df_eq[df_eq["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)].shape[0], "#E74C3C", id_click="acciones_prof")

        with t_acc_prof:
            html_acc_p = f"""
            <div style="max-width: 900px; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF; overflow-x: auto;">
                <table class="tabla-matricial">
                    <thead>
                        <tr>
                            <th class="col-fija">PROFESIONAL RESPONSABLE</th>
                            <th style="background-color: #27AE60;">TRÁMITE ACTIVO<br><span style="font-size:8px; font-weight:500; opacity:0.9;">(1-3 SEMANAS)</span></th>
                            <th style="background-color: #F39C12;">FLUJO LENTO<br><span style="font-size:8px; font-weight:500; opacity:0.9;">(1 A 5 MESES)</span></th>
                            <th style="background-color: #C0392B;">PARALIZADOS<br><span style="font-size:8px; font-weight:500; opacity:0.9;">(+6 MESES)</span></th>
                            <th style="background-color: #1F618D;">TOTAL EXP.</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for prof in profesionales_lista:
                df_pr = df_eq[df_eq["Profesional"] == prof]
                p_tot = len(df_pr)
                p_act = df_pr[df_pr["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0]
                p_len = df_pr[df_pr["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False) & ~df_pr["Trazabilidad"].astype(str).str.contains("6 meses", case=False, na=False)].shape[0]
                p_par = df_pr[df_pr["Trazabilidad"].astype(str).str.contains("año|6 meses|no se encontro resultado", case=False, na=False)].shape[0]
                
                html_acc_p += f"<tr>"
                html_acc_p += f"<td class='col-equipo celda-equipo-clic mod-accion-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-tipo='TOTAL'>{prof}</td>"
                html_acc_p += f"<td class='celda-equipo-clic mod-accion-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-tipo='ACTIVO'>{p_act}</td>"
                html_acc_p += f"<td class='celda-equipo-clic mod-accion-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-tipo='LENTO'>{p_len}</td>"
                html_acc_p += f"<td class='celda-equipo-clic mod-accion-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-tipo='PARALIZADO'>{p_par}</td>"
                html_acc_p += f"<td class='celda-equipo-clic mod-accion-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-tipo='TOTAL' style='font-weight:900;'>{p_tot}</td>"
                html_acc_p += f"</tr>"
            
            html_acc_p += "</tbody></table></div>"
            st.markdown(html_acc_p, unsafe_allow_html=True)

        # ------------------------------------------------------------------------------
        # CAPA 2 - BLOQUE 2: AÑO DE CREACIÓN
        # ------------------------------------------------------------------------------
        st.markdown("<hr style='border:none; border-top:1px dashed #E0E6ED; margin:25px 0 15px 0;'><div id='ancla-anios'></div><h4 style='color:#2C3E50; margin-bottom:5px;'>📅 Expedientes por año de creación</h4>", unsafe_allow_html=True)
        
        t_anio_gen_prof, t_anio_proc_prof, t_anio_prof = st.tabs(["📊 Resumen General", "📋 Por Procedimiento", "👨‍💼 Por Profesional"])
        
        if len(df.columns) >= 11:
            df_eq['Año_Temp'] = df_eq[df_eq.columns[9]].astype(str).str.extract(r'((?:19|20)\d{2})')[0].fillna("S/F")
            df_eq['Procedimiento_Temp'] = df_eq[df_eq.columns[10]].astype(str).str.strip().str.upper()
            df_eq['Procedimiento_Temp'] = df_eq['Procedimiento_Temp'].replace(['NAN', 'NONE', ''], 'SIN ESPECIFICAR')
            
            with t_anio_gen_prof:
                conteo_años_eq = df_eq['Año_Temp'].value_counts().sort_index(ascending=True)
                html_tabla_eq = f"""
                <div style="overflow-x: auto; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF;">
                    <table class="tabla-matricial"><thead><tr>
                    <th colspan="{len(conteo_años_eq) + 1}" style="padding: 6px; letter-spacing: 1px; text-transform: uppercase;">TOTAL EXPEDIENTES DEL EQUIPO POR AÑO: {len(df_eq)}</th>
                    </tr><tr>"""
                for año in conteo_años_eq.index: html_tabla_eq += f"<th class='header-secundario'>{año}</th>"
                html_tabla_eq += "<th style='background-color: #1F618D;'>TOTAL GENERAL</th></tr></thead><tbody><tr>"
                
                for cantidad, año in zip(conteo_años_eq.values, conteo_años_eq.index):
                    html_tabla_eq += f"<td class='celda-equipo-clic mod-anio-gen-eq' data-equipo='{eq_sel}' data-anio='{año}'>{cantidad}</td>"
                
                html_tabla_eq += f"<td class='celda-equipo-clic mod-anio-gen-eq' data-equipo='{eq_sel}' data-anio='TOTAL' style='font-weight:900; background-color: #E8F4F8;'>{len(df_eq)}</td>"
                html_tabla_eq += "</tr></tbody></table></div>"
                st.markdown(html_tabla_eq, unsafe_allow_html=True)

            with t_anio_proc_prof:
                list_años_eq = df_eq['Año_Temp'].value_counts().sort_index(ascending=True).index.tolist()
                procedimientos_ordenados_eq = df_eq['Procedimiento_Temp'].value_counts().index.tolist()
                
                html_anio_proc_eq = f"""<div style="overflow-x: auto; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF;">
                    <table class="tabla-matricial"><thead><tr><th class="col-fija">PROCEDIMIENTO</th>"""
                for a in list_años_eq: html_anio_proc_eq += f"<th>{a}</th>"
                html_anio_proc_eq += "<th style='background-color: #1F618D;'>TOTAL</th></tr></thead><tbody>"
                for proc in procedimientos_ordenados_eq:
                    df_pr = df_eq[df_eq['Procedimiento_Temp'] == proc]
                    conteo_pr = df_pr['Año_Temp'].value_counts()
                    html_anio_proc_eq += f"<tr><td class='col-proc mod-proc-eq' data-equipo='{eq_sel}' data-proc='{proc}' data-anio='TOTAL'>{proc}</td>"
                    for a in list_años_eq:
                        val = conteo_pr.get(a, 0)
                        txt = str(val) if val > 0 else "-"
                        if val > 0: html_anio_proc_eq += f"<td class='mod-proc-eq' data-equipo='{eq_sel}' data-proc='{proc}' data-anio='{a}'>{txt}</td>"
                        else: html_anio_proc_eq += f"<td>{txt}</td>"
                    html_anio_proc_eq += f"<td class='mod-proc-eq' data-equipo='{eq_sel}' data-proc='{proc}' data-anio='TOTAL' style='font-weight:900;'>{len(df_pr)}</td></tr>"
                
                html_anio_proc_eq += "<tr style='background-color: #F8F9F9; font-weight: 900;'><td class='col-proc mod-proc-eq' data-equipo='" + eq_sel + "' data-proc='TOTAL' data-anio='TOTAL' style='text-align: left; padding-left: 15px;'>TOTAL GENERAL</td>"
                for a in list_años_eq:
                    val_a = len(df_eq[df_eq['Año_Temp'] == a])
                    html_anio_proc_eq += f"<td class='mod-proc-eq' data-equipo='{eq_sel}' data-proc='TOTAL' data-anio='{a}'>{val_a}</td>"
                html_anio_proc_eq += f"<td class='mod-proc-eq' data-equipo='{eq_sel}' data-proc='TOTAL' data-anio='TOTAL' style='background-color: #E8F4F8; color: #2C3E50;'>{len(df_eq)}</td></tr>"
                
                html_anio_proc_eq += "</tbody></table></div>"
                st.markdown(html_anio_proc_eq, unsafe_allow_html=True)

            with t_anio_prof:
                list_años_eq = df_eq['Año_Temp'].value_counts().sort_index(ascending=True).index.tolist()
                html_anio_p = f"""<div style="overflow-x: auto; margin: 10px auto 20px auto; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); border: 1px solid #BDC3C7; background-color: #FFFFFF;">
                    <table class="tabla-matricial"><thead><tr><th class="col-fija">PROFESIONAL RESPONSABLE</th>"""
                for a in list_años_eq: html_anio_p += f"<th>{a}</th>"
                html_anio_p += "<th style='background-color: #1F618D;'>TOTAL</th></tr></thead><tbody>"
                for prof in profesionales_lista:
                    df_pr = df_eq[df_eq["Profesional"] == prof]
                    conteo_pr = df_pr['Año_Temp'].value_counts()
                    html_anio_p += f"<tr><td class='col-equipo celda-equipo-clic mod-anio-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-anio='TOTAL'>{prof}</td>"
                    for a in list_años_eq:
                        val = conteo_pr.get(a, 0)
                        txt = str(val) if val > 0 else "-"
                        if val > 0: html_anio_p += f"<td class='celda-equipo-clic mod-anio-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-anio='{a}'>{txt}</td>"
                        else: html_anio_p += f"<td>{txt}</td>"
                    html_anio_p += f"<td class='celda-equipo-clic mod-anio-prof' data-equipo='{eq_sel}' data-prof='{prof}' data-anio='TOTAL' style='font-weight:900;'>{len(df_pr)}</td></tr>"
                
                html_anio_p += "<tr style='background-color: #F8F9F9; font-weight: 900;'><td class='col-equipo celda-equipo-clic mod-anio-prof' data-equipo='" + eq_sel + "' data-prof='TOTAL' data-anio='TOTAL' style='text-align: left; padding-left: 15px;'>TOTAL GENERAL</td>"
                for a in list_años_eq:
                    val_a = len(df_eq[df_eq['Año_Temp'] == a])
                    html_anio_p += f"<td class='celda-equipo-clic mod-anio-prof' data-equipo='{eq_sel}' data-prof='TOTAL' data-anio='{a}'>{val_a}</td>"
                html_anio_p += f"<td class='celda-equipo-clic mod-anio-prof' data-equipo='{eq_sel}' data-prof='TOTAL' data-anio='TOTAL' style='background-color: #E8F4F8; color: #2C3E50;'>{len(df_eq)}</td></tr>"

                html_anio_p += "</tbody></table></div>"
                st.markdown(html_anio_p, unsafe_allow_html=True)

        # ------------------------------------------------------------------------------
        # CAPA 2 - BLOQUE EXCEPCIÓN: SEGUIMIENTO TÍTULOS SUNARP
        # ------------------------------------------------------------------------------
        if eq_sel == "Transversal":
            st.markdown("<hr style='border:none; border-top:1px solid #E0E6ED; margin:40px 0 20px 0;'><h4 style='color:#2C3E50;'>🏢 Seguimiento Títulos SUNARP</h4>", unsafe_allow_html=True)
            try:
                with st.spinner("Sincronizando base de datos registral..."): df_sunarp = cargar_datos_sunarp()
            except Exception as e:
                df_sunarp = pd.DataFrame()

            if not df_sunarp.empty:
                usuarios_sunarp = ["VESPADIN", "VGAMARRA", "MCHAVEZ", "RJIMENEZ", "KPAJUELO"]
                datos_procesados = clasificar_estados_sunarp(df_sunarp, usuarios_sunarp)
                for data in datos_procesados:
                    usu = data["Usuario"]
                    with st.expander(f"👤 {usu} — Total: {data['Total']} títulos asignados", expanded=False):
                        estados_activos = {k: v for k, v in data["Tarjetas"].items() if v["valor"] > 0}
                        if estados_activos:
                            columnas_tarjetas = st.columns(12)
                            idx_col = 0
                            for etiqueta, config in estados_activos.items():
                                with columnas_tarjetas[idx_col % 12]: st.markdown(generar_tarjeta_html(etiqueta, config), unsafe_allow_html=True)
                                idx_col += 1
                            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
                            _, col_btn = st.columns([10, 2])
                            with col_btn:
                                if st.button("Actualizar Estado", key=f"btn_rpa_{usu}", type="secondary", use_container_width=True):
                                    with st.spinner("Conectando..."):
                                        if sincronizar_estados_sunarp(usu):
                                            st.success("Carga Exitosa")
                                            st.rerun()

# ==============================================================================
# INYECCIÓN JAVASCRIPT GLOBAL ROBUSTA (DELEGACIÓN DE EVENTOS)
# ==============================================================================
components.html("""
<script>
setTimeout(function() {
    const parentDOM = window.parent.document;
    
    function triggerModal(type, p1, p2, p3='TOTAL') {
        const inputs = parentDOM.querySelectorAll('input[aria-label="modal_trigger"]');
        if(inputs.length > 0) {
            const input = inputs[0];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(input, type + "|||" + p1 + "|||" + p2 + "|||" + p3 + "|||" + Date.now());
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
        }
    }

    // DELEGACIÓN GLOBAL DE CLICS
    parentDOM.body.addEventListener('click', function(e) {
        const target = e.target.closest('td');
        if (!target) return;

        if (target.classList.contains('mod-accion')) { triggerModal('ACCION', target.getAttribute('data-equipo'), target.getAttribute('data-tipo'), 'TOTAL'); }
        else if (target.classList.contains('mod-anio-gen')) { triggerModal('ANIO_GEN', target.getAttribute('data-anio'), 'TOTAL', 'TOTAL'); }
        else if (target.classList.contains('mod-proc')) { triggerModal('PROC', target.getAttribute('data-proc'), target.getAttribute('data-anio'), 'TOTAL'); }
        else if (target.classList.contains('mod-anio-eq')) { triggerModal('ANIO_EQ', target.getAttribute('data-equipo'), target.getAttribute('data-anio'), 'TOTAL'); }
        else if (target.classList.contains('mod-accion-prof')) { triggerModal('ACCION_PROF', target.getAttribute('data-prof'), target.getAttribute('data-tipo'), target.getAttribute('data-equipo')); }
        else if (target.classList.contains('mod-anio-gen-eq')) { triggerModal('ANIO_GEN_EQ', target.getAttribute('data-equipo'), target.getAttribute('data-anio'), 'TOTAL'); }
        else if (target.classList.contains('mod-proc-eq')) { triggerModal('PROC_EQ', target.getAttribute('data-proc'), target.getAttribute('data-anio'), target.getAttribute('data-equipo')); }
        else if (target.classList.contains('mod-anio-prof')) { triggerModal('ANIO_PROF', target.getAttribute('data-prof'), target.getAttribute('data-anio'), target.getAttribute('data-equipo')); }
    });

    // CAMBIO DE PESTAÑAS (Métricas Superiores)
    parentDOM.querySelectorAll('.tarjeta-clic-acciones').forEach(el => { el.onclick = function() { const t = Array.from(parentDOM.querySelectorAll('[role="tab"]')).filter(t => t.textContent.includes('Comparativo por Equipos')); if(t.length > 0) t[0].click(); }; });
    parentDOM.querySelectorAll('.tarjeta-clic-anios').forEach(el => { el.onclick = function() { const t = Array.from(parentDOM.querySelectorAll('[role="tab"]')).filter(t => t.textContent.includes('Comparativo por Equipos')); if(t.length > 1) t[1].click(); }; });
    parentDOM.querySelectorAll('.tarjeta-clic-acciones-prof').forEach(el => { el.onclick = function() { const t = Array.from(parentDOM.querySelectorAll('[role="tab"]')).filter(t => t.textContent.includes('Por Profesional')); if(t.length > 0) t[0].click(); }; });
    parentDOM.querySelectorAll('.tarjeta-clic-anios-prof').forEach(el => { el.onclick = function() { const t = Array.from(parentDOM.querySelectorAll('[role="tab"]')).filter(t => t.textContent.includes('Por Profesional')); if(t.length > 1) t[1].click(); }; });
}, 400);
</script>
""", height=0, width=0)


# ============================================================================== 
# TERCER MÓDULO: BÚSQUEDA DE EXPEDIENTES
# ============================================================================== 

def render_busqueda_expedientes():
    """Renderiza el buscador avanzado sin alterar los módulos operativos existentes."""
    @st.cache_data(ttl=300, show_spinner=False)
    def _cargar_busqueda():
        return cargar_universo_online()

    try:
        with st.spinner("Conectando con el Universo de Expedientes..."):
            df_u = _cargar_busqueda()
    except Exception:
        st.error("No fue posible cargar la pestaña 'UNIVERSO EXP.' desde Google Sheets. Verifica la conexión a Internet y que la pestaña esté disponible.")
        return

    if df_u.empty:
        st.warning("La pestaña 'UNIVERSO EXP.' no contiene registros.")
        return

    cols_u = infer_columns(df_u)
    if not cols_u["expediente"] or not cols_u["entidad"] or not cols_u["procedimiento"]:
        st.error("No se pudieron identificar las columnas A (expediente), D (entidad) y L (procedimiento).")
        return

    entity_index_u = build_index(df_u, cols_u["entidad"])
    procedure_index_u = build_index(df_u, cols_u["procedimiento"])
    geo_values_u = []
    for key in ("departamento", "provincia", "distrito"):
        geo_values_u.extend(unique_clean_values(df_u, cols_u.get(key)))
    geo_values_u = sorted(set(geo_values_u), key=lambda x: (-len(normalize_text(x)), normalize_text(x)))

    prefix = "ux_"
    if f"{prefix}initialized" not in st.session_state:
        st.session_state[f"{prefix}initialized"] = True
        st.session_state[f"{prefix}query"] = ""
        st.session_state[f"{prefix}searched"] = False
        st.session_state[f"{prefix}parsed"] = None
        st.session_state[f"{prefix}situation"] = "Todas"
        st.session_state[f"{prefix}normative"] = "Todos"
        st.session_state[f"{prefix}filter_version"] = 0
        st.session_state[f"{prefix}dep"] = "Todos"
        st.session_state[f"{prefix}prov"] = "Todos"
        st.session_state[f"{prefix}dist"] = "Todos"
        st.session_state[f"{prefix}state"] = "Todos"

    def reset_search():
        st.session_state[f"{prefix}query"] = ""
        st.session_state[f"{prefix}searched"] = False
        st.session_state[f"{prefix}parsed"] = None
        st.session_state[f"{prefix}situation"] = "Todas"
        st.session_state[f"{prefix}normative"] = "Todos"
        st.session_state[f"{prefix}filter_version"] = st.session_state.get(f"{prefix}filter_version", 0) + 1
        st.session_state[f"{prefix}dep"] = "Todos"
        st.session_state[f"{prefix}prov"] = "Todos"
        st.session_state[f"{prefix}dist"] = "Todos"
        st.session_state[f"{prefix}state"] = "Todos"

    # Estilos aislados del módulo de búsqueda + responsive móvil.
    st.markdown("""
    <style>
      .ux-title {font-size:22px;font-weight:800;color:#1a252f;margin:3px 0 2px 0}
      .ux-hint {font-size:12px;color:#657079;line-height:1.35;margin-bottom:8px}
      .ux-summary {background:#fff;border:1px solid #c9ced3;padding:5px 8px;height:46px;}
      .ux-summary-label {font-size:8px;color:#667085;text-transform:uppercase;line-height:1}
      .ux-summary-value {font-size:17px;font-weight:800;color:#202428;line-height:1.05;margin-top:3px}
      .ux-result-count {background:#fff;border-left:4px solid #1d70b8;padding:9px 12px;font-weight:800;margin:9px 0}
      .ux-section-note {font-size:11px;color:#667085;margin:1px 0 3px 0}
      .ux-download {margin:4px 0 6px 0}

    input[aria-label="modal_trigger"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="stTextInput"]:has(input[aria-label="modal_trigger"]) {
        display: none !important;
    }


      .ux-section-note{font-size:11px;color:#667085;margin:5px 0 3px 0}
      [data-testid="stExpander"] details summary {
        font-weight: 700 !important;
      }
      @media(max-width:768px){
        [data-testid="stExpander"] details summary {
          font-size: 13px !important;
          padding-top: 8px !important;
          padding-bottom: 8px !important;
        }
      }

      @media(max-width:768px){
        .ux-title{font-size:18px}
        .ux-hint{font-size:11px}
        .ux-summary{height:44px;padding:4px 6px}
        .ux-summary-label{font-size:7px}
        .ux-summary-value{font-size:15px}
      }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="ux-title">🔎 Buscar en el universo</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ux-hint">Puede escribir una entidad, un administrado, un procedimiento, una ubicación, un expediente o combinar varios datos. Ej.: <b>“transferencias en Lima del 2020 al 2024”</b> o <b>“municipalidades de Piura atendidas”</b>.</div>',
        unsafe_allow_html=True,
    )

    query = st.text_input(
        "Entidad, administrado, expediente o consulta",
        placeholder="Ej.: Sedapal en Piura / Gobierno Regional de Arequipa 2020–2021",
        key=f"{prefix}query",
    )
    b1, b2 = st.columns([2.6, 1.35])
    with b1:
        buscar_u = st.button("🔎 Buscar", type="primary", use_container_width=True, key=f"{prefix}buscar")
    with b2:
        st.button("Limpiar búsqueda", use_container_width=True, on_click=reset_search, key=f"{prefix}limpiar")

    if buscar_u:
        st.session_state[f"{prefix}filter_version"] += 1
        st.session_state[f"{prefix}situation"] = "Todas"
        st.session_state[f"{prefix}normative"] = "Todos"
        st.session_state[f"{prefix}dep"] = "Todos"
        st.session_state[f"{prefix}prov"] = "Todos"
        st.session_state[f"{prefix}dist"] = "Todos"
        st.session_state[f"{prefix}state"] = "Todos"
        if not query.strip():
            st.session_state[f"{prefix}searched"] = False
            st.session_state[f"{prefix}parsed"] = None
        else:
            parsed_u = parse_query(query, df_u, cols_u, entity_index_u, procedure_index_u, geo_values_u)
            st.session_state[f"{prefix}parsed"] = parsed_u
            st.session_state[f"{prefix}searched"] = True

    base_u = df_u.copy()
    parsed_u = st.session_state.get(f"{prefix}parsed")

    if st.session_state.get(f"{prefix}searched") and parsed_u:
        # Ambigüedad solo cuando el motor realmente encontró evidencia fuerte en ambos campos.
        if parsed_u.ambiguous:
            st.markdown(
                "<div style='background:#fff9e6;border:1px solid #e8d899;padding:7px 9px;color:#6b5b00;font-size:11px;margin:8px 0;'>La consulta puede referirse a dos campos. Seleccione la interpretación que desea usar.</div>",
                unsafe_allow_html=True,
            )
            choice = st.radio(
                "Interpretación",
                [
                    f"Procedimiento: {parsed_u.ambiguity_procedure_text.title()}",
                    f"Administrado / entidad: {parsed_u.ambiguity_entity_text.title()}",
                ],
                index=0,
                horizontal=True,
                key=f"{prefix}ambiguity_{st.session_state[f'{prefix}filter_version']}",
                label_visibility="collapsed",
            )
            if choice.startswith("Procedimiento:"):
                parsed_u.entity_text = ""
                parsed_u.procedure_text = parsed_u.ambiguity_procedure_text
            else:
                parsed_u.procedure_text = ""
                parsed_u.entity_text = parsed_u.ambiguity_entity_text

        base_u = apply_parsed_query(base_u, parsed_u, cols_u, entity_index_u)

    # ------------------------------------------------------------------
    # UX: búsqueda primero; refinamiento progresivo después.
    # Los filtros no aparecen hasta que exista una búsqueda ejecutada.
    # ------------------------------------------------------------------
    if not st.session_state.get(f"{prefix}searched", False):
        st.markdown(
            '<div class="ux-section-note">Los filtros aparecerán aquí después de realizar una búsqueda.</div>',
            unsafe_allow_html=True,
        )
        work_u = base_u.copy()
    else:
        # Criterios activos compactos, sin crear un bloque visual pesado.
        if parsed_u and getattr(parsed_u, "interpretation", None):
            chips = []
            for field, value in parsed_u.interpretation[:6]:
                chips.append(
                    f"<span style='display:inline-block;background:#EAF4FB;border:1px solid #C5DFF2;"
                    f"border-radius:14px;padding:3px 8px;margin:2px 4px 2px 0;font-size:10px;"
                    f"color:#205A82;'>{escape(str(field))}: {escape(str(value))}</span>"
                )
            if chips:
                st.markdown(
                    "<div style='margin:2px 0 8px 0;'>" + "".join(chips) + "</div>",
                    unsafe_allow_html=True,
                )

        # Aplicamos primero los filtros rápidos.
        sit_options = ["Todas", "Atendidos", "En trámite"]
        situation_current = st.session_state.get(f"{prefix}situation", "Todas")
        if situation_current not in sit_options:
            situation_current = "Todas"

        # Detectar marcos presentes dentro del universo de la consulta.
        detected_norms = []
        norm_col = cols_u.get("marco_normativo")
        if norm_col and len(base_u):
            ns = base_u[norm_col].astype(str).map(normalize_text)
            if ns.str.contains("1192", regex=False, na=False).any():
                detected_norms.append("DL 1192")
            if ns.str.contains("30556", regex=False, na=False).any():
                detected_norms.append("Ley 30556")
            if ns.str.contains("29151", regex=False, na=False).any():
                detected_norms.append("Ley 29151")

        normative_current = st.session_state.get(f"{prefix}normative", "Todos")
        if normative_current not in (["Todos"] + detected_norms):
            normative_current = "Todos"

        # Primera línea: situación y, solo cuando corresponda, marco normativo.
        quick_cols = st.columns([1.0, 1.25] if len(detected_norms) >= 2 else [1.0, 1.0])
        with quick_cols[0]:
            situation_u = st.radio(
                "Situación",
                sit_options,
                index=sit_options.index(situation_current),
                horizontal=True,
                key=f"{prefix}situation_widget_{st.session_state[f'{prefix}filter_version']}",
            )
            st.session_state[f"{prefix}situation"] = situation_u

        normative_u = "Todos"
        with quick_cols[1]:
            if len(detected_norms) >= 2:
                options_n = ["Todos"] + detected_norms
                normative_u = st.radio(
                    "Marco normativo",
                    options_n,
                    index=options_n.index(normative_current),
                    horizontal=True,
                    key=f"{prefix}normative_widget_{st.session_state[f'{prefix}filter_version']}",
                )
            else:
                st.markdown(
                    "<div style='font-size:11px;color:#667085;padding-top:1.65rem;'>"
                    "Marco normativo: sin segmentación disponible</div>",
                    unsafe_allow_html=True,
                )
            st.session_state[f"{prefix}normative"] = normative_u

        work_u = base_u.copy()

        if situation_u != "Todas":
            work_u = work_u[
                status_group_mask(
                    work_u,
                    cols_u.get("estado"),
                    "ATENDIDOS" if situation_u == "Atendidos" else "EN TRAMITE",
                )
            ]

        if normative_u != "Todos" and norm_col:
            number = {
                "DL 1192": "1192",
                "Ley 30556": "30556",
                "Ley 29151": "29151",
            }[normative_u]
            work_u = work_u[
                work_u[norm_col]
                .astype(str)
                .map(normalize_text)
                .str.contains(number, regex=False, na=False)
            ]

        # Refinamiento avanzado en un acordeón: no invade la pantalla principal.
        with st.expander("⚙️ Refinar búsqueda", expanded=False):
            st.markdown(
                "<div style='font-size:10px;color:#667085;margin-bottom:6px;'>"
                "Ajusta los resultados sin modificar la consulta principal.</div>",
                unsafe_allow_html=True,
            )

            adv1 = st.columns(3)

            # Ubicación
            with adv1[0]:
                dep_col = cols_u.get("departamento")
                if dep_col:
                    values = ["Todos"] + sorted(unique_clean_values(work_u, dep_col))
                    current_dep = st.session_state.get(f"{prefix}dep", "Todos")
                    if current_dep not in values:
                        current_dep = "Todos"
                    dep_sel = st.selectbox(
                        "Departamento",
                        values,
                        index=values.index(current_dep),
                        key=f"{prefix}dep_{st.session_state[f'{prefix}filter_version']}",
                    )
                    st.session_state[f"{prefix}dep"] = dep_sel
                    if dep_sel != "Todos":
                        work_u = work_u[
                            work_u[dep_col].astype(str).str.strip() == dep_sel
                        ]

            with adv1[1]:
                prov_col = cols_u.get("provincia")
                if prov_col:
                    values = ["Todos"] + sorted(unique_clean_values(work_u, prov_col))
                    current_prov = st.session_state.get(f"{prefix}prov", "Todos")
                    if current_prov not in values:
                        current_prov = "Todos"
                    prov_sel = st.selectbox(
                        "Provincia",
                        values,
                        index=values.index(current_prov),
                        key=f"{prefix}prov_{st.session_state[f'{prefix}filter_version']}",
                    )
                    st.session_state[f"{prefix}prov"] = prov_sel
                    if prov_sel != "Todos":
                        work_u = work_u[
                            work_u[prov_col].astype(str).str.strip() == prov_sel
                        ]

            with adv1[2]:
                dist_col = cols_u.get("distrito")
                if dist_col:
                    values = ["Todos"] + sorted(unique_clean_values(work_u, dist_col))
                    current_dist = st.session_state.get(f"{prefix}dist", "Todos")
                    if current_dist not in values:
                        current_dist = "Todos"
                    dist_sel = st.selectbox(
                        "Distrito",
                        values,
                        index=values.index(current_dist),
                        key=f"{prefix}dist_{st.session_state[f'{prefix}filter_version']}",
                    )
                    st.session_state[f"{prefix}dist"] = dist_sel
                    if dist_sel != "Todos":
                        work_u = work_u[
                            work_u[dist_col].astype(str).str.strip() == dist_sel
                        ]

            adv2 = st.columns(3)

            # Administrado / entidad solo si NO formó parte de la consulta.
            mostrar_entidad = not (parsed_u and parsed_u.entity_text)
            with adv2[0]:
                ent_col = cols_u.get("entidad")
                if mostrar_entidad and ent_col:
                    values = ["Todas"] + sorted(unique_clean_values(work_u, ent_col))[:500]
                    current_ent = st.session_state.get(f"{prefix}entidad", "Todas")
                    if current_ent not in values:
                        current_ent = "Todas"
                    ent_sel = st.selectbox(
                        "Administrado / entidad",
                        values,
                        index=values.index(current_ent),
                        key=f"{prefix}entidad_{st.session_state[f'{prefix}filter_version']}",
                    )
                    st.session_state[f"{prefix}entidad"] = ent_sel
                    if ent_sel != "Todas":
                        work_u = work_u[
                            work_u[ent_col].astype(str).str.strip() == ent_sel
                        ]
                else:
                    st.markdown(
                        "<div style='font-size:11px;color:#667085;padding-top:1.55rem;'>"
                        "Administrado / entidad ya forma parte de la consulta</div>",
                        unsafe_allow_html=True,
                    )

            with adv2[1]:
                estado_col = cols_u.get("estado")
                if estado_col:
                    estados = ["Todos"] + sorted(unique_clean_values(work_u, estado_col))
                    current_state = st.session_state.get(f"{prefix}state", "Todos")
                    if current_state not in estados:
                        current_state = "Todos"
                    state_sel = st.selectbox(
                        "Estado original",
                        estados,
                        index=estados.index(current_state),
                        key=f"{prefix}state_{st.session_state[f'{prefix}filter_version']}",
                    )
                    st.session_state[f"{prefix}state"] = state_sel
                    if state_sel != "Todos":
                        work_u = work_u[
                            work_u[estado_col].astype(str).str.strip() == state_sel
                        ]

            with adv2[2]:
                anio_col = cols_u.get("anio")
                if anio_col:
                    years = pd.to_numeric(
                        work_u[anio_col]
                        .astype(str)
                        .str.extract(r"((?:19|20)\d{2})")[0],
                        errors="coerce",
                    )
                    available = sorted(years.dropna().astype(int).unique().tolist())
                    if len(available) >= 2:
                        start = (
                            parsed_u.year_min
                            if parsed_u and parsed_u.year_min in available
                            else min(available)
                        )
                        end = (
                            parsed_u.year_max
                            if parsed_u and parsed_u.year_max in available
                            else max(available)
                        )
                        start = max(min(available), start)
                        end = min(max(available), end)
                        if start > end:
                            start, end = min(available), max(available)

                        year_sel = st.slider(
                            "Año",
                            min_value=min(available),
                            max_value=max(available),
                            value=(start, end),
                            step=1,
                            key=f"{prefix}year_{st.session_state[f'{prefix}filter_version']}",
                        )
                        years_now = pd.to_numeric(
                            work_u[anio_col]
                            .astype(str)
                            .str.extract(r"((?:19|20)\d{2})")[0],
                            errors="coerce",
                        )
                        work_u = work_u[
                            years_now.between(
                                year_sel[0], year_sel[1], inclusive="both"
                            ).fillna(False)
                        ]
                    elif len(available) == 1:
                        st.markdown(
                            f"<div style='font-size:11px;color:#667085;padding-top:1.55rem;'>"
                            f"Año disponible: <b>{available[0]}</b></div>",
                            unsafe_allow_html=True,
                        )
    # ------------------------------------------------------------------
    # Fin del refinamiento progresivo
    # ------------------------------------------------------------------

    # Mostrar resultados.
    st.markdown(f'<div class="ux-result-count">{len(work_u):,} expediente(s) encontrados</div>', unsafe_allow_html=True)

    if work_u.empty:
        st.warning("No encontramos expedientes que cumplan todos los criterios indicados. Puede probar una denominación más amplia o aportar menos criterios.")
        return

    # Resumen compacto.
    metrics = [
        ("Expedientes", len(work_u)),
        ("Entidades", work_u[cols_u["entidad"]].nunique() if cols_u.get("entidad") else "—"),
        ("Departamentos", work_u[cols_u["departamento"]].nunique() if cols_u.get("departamento") else "—"),
        ("Años", work_u[cols_u["anio"]].astype(str).str.extract(r"((?:19|20)\d{2})")[0].nunique() if cols_u.get("anio") else "—"),
    ]
    cards = st.columns(4, gap="small")
    for card, (label, value) in zip(cards, metrics):
        with card:
            display = f"{value:,}" if isinstance(value, (int, float)) else str(value)
            st.markdown(f'<div class="ux-summary"><div class="ux-summary-label">{label}</div><div class="ux-summary-value">{display}</div></div>', unsafe_allow_html=True)

    display_u = aplicar_privacidad_venta(work_u, cols_u)
    display_cols = [
        cols_u["expediente"], cols_u["entidad"], cols_u["procedimiento"],
        cols_u.get("departamento"), cols_u.get("provincia"), cols_u.get("distrito"),
        cols_u.get("anio"), cols_u.get("estado"),
    ]
    display_cols = [c for c in display_cols if c and c in display_u.columns]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        display_u[display_cols].to_excel(writer, index=False, sheet_name="Resultados")
    st.markdown('<div class="ux-download">', unsafe_allow_html=True)
    st.download_button(
        "📥 Descargar resultados en Excel",
        data=buffer.getvalue(),
        file_name="Consulta_Universo_Expedientes.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
        key=f"{prefix}download_{st.session_state[f'{prefix}filter_version']}",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("### Resultados")

    # Tabla escritorio + tarjetas móviles. Cada fila abre Trámite Transparente.
    rows = []
    cards_html = []
    for _, row in display_u.iterrows():
        expediente = str(row.get(cols_u["expediente"], "")).strip()
        url = "https://tramitetransparente.sbn.gob.pe/#auto=" + expediente
        cells = []
        pairs = []
        for col in display_cols:
            val = row.get(col, "")
            if pd.isna(val): val = ""
            txt = escape(str(val))
            cells.append(f"<td>{txt}</td>")
            pairs.append(f"<div class='ux-mrow'><span>{escape(str(col))}</span><b>{txt}</b></div>")
        rows.append(
            f"<tr class='ux-rrow' data-url='{escape(url, quote=True)}' onclick=\"window.open(this.dataset.url,'_blank')\">{''.join(cells)}</tr>"
        )
        cards_html.append(
            f"<div class='ux-card' data-url='{escape(url, quote=True)}' onclick=\"window.open(this.dataset.url,'_blank')\">{''.join(pairs)}<div class='ux-open'>Abrir expediente ↗</div></div>"
        )
    headers = ''.join(f"<th>{escape(str(c))}</th>" for c in display_cols)
    html = f"""
    <style>
      .ux-tablewrap{{overflow-x:auto;max-height:68vh;width:100%}}
      .ux-table{{width:100%;border-collapse:collapse;font-size:12px;background:#fff}}
      .ux-table th{{position:sticky;top:0;z-index:2;background:#f1f3f5;color:#505a5f;padding:8px;border:1px solid #d9dde1;text-align:left;white-space:nowrap}}
      .ux-table td{{padding:8px;border:1px solid #e1e4e7;color:#202428;white-space:nowrap}}
      .ux-rrow{{cursor:pointer}}
      .ux-rrow:hover td{{background:#e8f3fb}}
      .ux-mobile{{display:none}}
      .ux-card{{background:#fff;border:1px solid #c9ced3;border-left:4px solid #1d70b8;border-radius:6px;margin:6px 0;padding:8px 9px;cursor:pointer}}
      .ux-mrow{{display:grid;grid-template-columns:minmax(92px,38%) 1fr;gap:7px;padding:4px 0;border-bottom:1px solid #eef0f2;font-size:12px}}
      .ux-mrow span{{color:#6b7277}}
      .ux-mrow b{{color:#202428;word-break:break-word;font-weight:600}}
      .ux-open{{margin-top:7px;text-align:right;color:#005ea8;font-weight:700;font-size:12px}}
      @media(max-width:768px){{.ux-desktop{{display:none}}.ux-mobile{{display:block}}.ux-tablewrap{{max-height:none}}}}
    </style>
    <div class='ux-desktop'><div class='ux-tablewrap'><table class='ux-table'><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>
    <div class='ux-mobile'>{''.join(cards_html)}</div>
    """
    components.html(html, height=min(760, max(250, 85 + min(len(display_u), 18) * 34)), scrolling=False)


with tab_busqueda:
    render_busqueda_expedientes()

with tab_produccion:
    st.markdown("<br><br><h2 style='text-align: center; color: #2C3E50;'>Estamos trabajando para integrar esta información, por lo pronto ingrese a:</h2><br>", unsafe_allow_html=True)
    col_izq, col_centro, col_der = st.columns([3, 4, 3])
    with col_centro:
        # Mejora Inyectada: Enlace con token de seguridad. (Misma lógica probada y sugerida)
        GAS_URL = "https://script.google.com/macros/s/AKfycbzNuA__KQObk_2JI8iuBxqFD5RyByc7jVHe7OudtrFrEnpIPBCc6D3SEZ0-BCofUYiJ/exec"
        SECRET_TOKEN = "MI_CLAVE_SECRETA_123" 
        enlace_seguro = f"{GAS_URL}?token={SECRET_TOKEN}"
        
        st.link_button("📊 Ir al Tablero de Control SDDI", enlace_seguro, type="primary", use_container_width=True)
    st.markdown("<br><br>", unsafe_allow_html=True)

st.markdown("<div style='text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #E0E6ED; color: #95A5A6; font-size: 13px;'><b>Diseñado y Desarrollado: Equipo de Gestión SDDI / tyantas-myps</b> &nbsp;|&nbsp; <span style='color: #95A5A6;'>(Información de Trámite Transparente)</span></div>", unsafe_allow_html=True)
