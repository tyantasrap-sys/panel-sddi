import re
import io
import logging
import pandas as pd
import streamlit as st
import gspread
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials

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

        # 1. Preparación del Diccionario incluyendo Columna D y Columna H
        diccionario_estados = {}
        for fila in datos_origen[1:]: 
            # Aseguramos que la fila de origen tenga al menos 8 elementos para leer la Columna H (índice 7)
            fila_segura_origen = fila + [""] * (8 - len(fila))
            titulo = fila_segura_origen[2].strip() # Columna C
            
            if titulo:
                estado = fila_segura_origen[3].strip() # Columna D
                dato_h = fila_segura_origen[7].strip() # Columna H
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
                
                # 2. Matriz que almacenará las columnas M y N juntas
                columnas_mn_actualizada = []
                hubo_modificacion_en_pestaña = False

                for idx, fila in enumerate(datos_destino):
                    # Cabecera
                    if idx == 0: 
                        val_m = fila[12] if len(fila) > 12 else "REVISADO"
                        val_n = fila[13] if len(fila) > 13 else "DATO ADICIONAL"
                        columnas_mn_actualizada.append([val_m, val_n])
                        continue
                    
                    # Aseguramos que la fila de destino tenga al menos 14 elementos para acceder hasta la N (índice 13)
                    fila_segura = fila + [""] * (14 - len(fila))
                    n_titulo = fila_segura[9].strip() # Columna J
                    estado_actual = fila_segura[12].strip() # Columna M
                    dato_n_actual = fila_segura[13].strip() # Columna N

                    # 3. Match y Actualización
                    if n_titulo in diccionario_estados:
                        nuevo_estado = diccionario_estados[n_titulo]["estado"]
                        nuevo_dato_h = diccionario_estados[n_titulo]["dato_h"]
                        
                        # Si hay un cambio ya sea en el estado o en el dato extra, lo actualizamos
                        if estado_actual != nuevo_estado or dato_n_actual != nuevo_dato_h:
                            estado_actual = nuevo_estado
                            dato_n_actual = nuevo_dato_h
                            hubo_modificacion_en_pestaña = True
                            
                    # Guardamos el par para la escritura en bloque (Columna M y Columna N)
                    columnas_mn_actualizada.append([estado_actual, dato_n_actual])

                # 4. Escritura en Bloque sin borrar el resto del libro
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
    
    # ENRUTAMIENTO Y FILTRADO ESTRICTO
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
        
        # ANONIMIZACIÓN SEGURA Y EXPANDIDA (Compraventa, Permuta, Desafectación, Subasta)
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
# ESTILOS CSS AVANZADOS Y UI (CORRECCIÓN DE TEMBLOR Y SIMETRÍA)
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

/* REGLAS ESTRICTAS CONTRA EL SHAKING Y ACTIVACIÓN DE CURSOR POINTER (MANITO) */
.celda-proc-clic, .mod-proc, .mod-proc-eq, .celda-equipo-clic, .mod-anio-gen, .mod-anio-eq, .mod-accion, .mod-accion-prof, .mod-anio-gen-eq, .mod-anio-prof { 
    cursor: pointer !important; 
    transition: background-color 0.2s ease, color 0.2s ease; 
}
.celda-proc-clic:hover, .mod-proc:hover, .mod-proc-eq:hover, .celda-equipo-clic:hover, .mod-anio-gen:hover, .mod-anio-eq:hover, .mod-accion:hover, .mod-accion-prof:hover, .mod-anio-gen-eq:hover, .mod-anio-prof:hover { 
    background-color: #D6EAF8 !important; 
    color: #1A5276 !important; 
}

.tarjeta-equipo { background-color: #FFFFFF; padding: 12px 10px; border-radius: 10px; border-top: 4px solid #2980B9; box-shadow: 0 3px 8px rgba(0,0,0,0.04); text-align: center; margin-bottom: 10px; height: 120px !important; display: flex; flex-direction: column; justify-content: center; }

/* TABLAS SIMÉTRICAS */
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
# FLUJO PRINCIPAL
# ==============================================================================
tab_gestion, tab_produccion = st.tabs(["📁 Gestión de Expedientes", "📊 Avance de Producción"])

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

with tab_produccion:
    st.markdown("<br><br><h2 style='text-align: center; color: #2C3E50;'>Estamos trabajando para integrar esta información, por lo pronto ingrese a:</h2><br>", unsafe_allow_html=True)
    col_izq, col_centro, col_der = st.columns([3, 4, 3])
    with col_centro:
        st.link_button("📊 Ir al Tablero de Control SDDI", "https://script.google.com/macros/s/AKfycbzNuA__KQObk_2JI8iuBxqFD5RyByc7jVHe7OudtrFrEnpIPBCc6D3SEZ0-BCofUYiJ/exec", type="primary", use_container_width=True)
    st.markdown("<br><br>", unsafe_allow_html=True)

st.markdown("<div style='text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #E0E6ED; color: #95A5A6; font-size: 13px;'><b>Diseñado y Desarrollado: Equipo de Gestión SDDI / tyantas-myps</b> &nbsp;|&nbsp; <span style='color: #95A5A6;'>(Información de Trámite Transparente)</span></div>", unsafe_allow_html=True)
