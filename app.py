import re
import io
import pandas as pd
import streamlit as st

# 1. Configuración de la Interfaz (Debe ser la primera línea)
st.set_page_config(page_title="Trazabilidad SDDI", layout="wide", page_icon="🏛️", initial_sidebar_state="expanded")

# ==============================================================================
# LÓGICA DEL BOTÓN FLOTANTE MAESTRO Y CAPAS
# ==============================================================================
if 'capa_actual' not in st.session_state: st.session_state.capa_actual = 1
if 'equipo_sel' not in st.session_state: st.session_state.equipo_sel = None
# Por defecto mostramos la barra al iniciar
if 'barra_oculta' not in st.session_state: st.session_state.barra_oculta = False

def ir_a_capa(nivel, equipo=None):
    st.session_state.capa_actual = nivel
    if equipo is not None: st.session_state.equipo_sel = equipo

def toggle_barra():
    st.session_state.barra_oculta = not st.session_state.barra_oculta

# Control estricto por CSS de nuestra barra lateral
if st.session_state.barra_oculta:
    st.markdown('<style>[data-testid="stSidebar"] { display: none !important; transform: translateX(-100%) !important; }</style>', unsafe_allow_html=True)
    btn_text = "➡️ Mostrar menú"
else:
    # Se obliga a la barra a volver a la pantalla y ser visible
    st.markdown('<style>[data-testid="stSidebar"] { display: flex !important; visibility: visible !important; transform: translateX(0) !important; margin-left: 0px !important; }</style>', unsafe_allow_html=True)
    btn_text = "⬅️ Ocultar menú"

# Botón flotante único e indestructible
st.button(btn_text, on_click=toggle_barra, help="flotante")

# ==============================================================================
# ESTILOS CSS AVANZADOS (RESPONSIVE Y ANTI-BUGS)
# ==============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.block-container { padding-top: 1.5rem !important; padding-bottom: 5rem !important; }

/* ================================================================= */
/* 1. EXTERMINIO ABSOLUTO DE CONTROLES NATIVOS Y MARCAS DE AGUA      */
/* ================================================================= */
/* Matamos la flecha nativa y el header de Streamlit de raíz */
[data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"], header[data-testid="stHeader"] { 
    display: none !important; visibility: hidden !important; opacity: 0 !important; width: 0 !important; height: 0 !important;
}

/* Limpieza de basura visual de la nube */
footer, #MainMenu, [data-testid="stDecoration"], [data-testid="stToolbar"] { display: none !important; visibility: hidden !important; }
h1 a svg, h2 a svg, h3 a svg { display: none !important; } /* Clip de enlaces en títulos */
a[href*="github.com"], a[href*="streamlit.io"] { pointer-events: none !important; display: none !important; }
div[class*="viewerBadge"], div[class*="stDeployButton"], [data-testid="stAppDeployButton"] { display: none !important; }
[data-testid="stStatusWidget"] { visibility: hidden !important; height: 0px !important; }

/* ================================================================= */
/* 2. DISEÑO DEL BOTÓN FLOTANTE (ADAPTATIVO)                         */
/* ================================================================= */
/* Formato Base del Botón */
div[data-testid="stTooltipHoverTarget"] button {
    background-color: #2C3E50 !important; color: #FFFFFF !important; border: 2px solid #FFFFFF !important;
    box-shadow: 0 4px 10px rgba(0,0,0,0.3) !important; font-weight: 700 !important; transition: all 0.3s ease !important;
}
div[data-testid="stTooltipHoverTarget"] button:hover {
    background-color: #E74C3C !important; transform: translateY(-3px) !important; color: #FFFFFF !important;
}
div[role="tooltip"], div[data-baseweb="tooltip"] { display: none !important; } /* Ocultar tooltips nativos */

/* Posición en PC (Pantallas grandes) */
@media (min-width: 769px) {
    div[data-testid="stTooltipHoverTarget"] {
        position: fixed !important; top: 52% !important; left: 20px !important; z-index: 9999999 !important; width: auto !important;
    }
    div[data-testid="stTooltipHoverTarget"] button {
        border-radius: 30px !important; padding: 8px 20px !important; font-size: 14px !important;
    }
    /* En PC la barra empuja el contenido de forma natural */
    [data-testid="stSidebar"] {
        min-width: 185px !important; max-width: 185px !important;
        background-color: #EAECEE !important; border-right: 1px solid #D5DBDB !important;
    }
}

/* Posición en CELULAR (Pantallas pequeñas) -> MOVIDO A LA SUPERIOR DERECHA */
@media (max-width: 768px) {
    div[data-testid="stTooltipHoverTarget"] {
        position: fixed !important; 
        top: 15px !important; 
        right: 15px !important; 
        left: auto !important; /* Anulamos la regla izquierda de PC */
        bottom: auto !important; 
        transform: none !important; 
        z-index: 9999999 !important; 
        width: auto !important;
    }
    div[data-testid="stTooltipHoverTarget"] button {
        border-radius: 30px !important; padding: 8px 18px !important; font-size: 14px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4) !important; 
    }
    /* En celular la barra actúa como una cortina superpuesta (Overlay) para no aplastar los cuadros */
    [data-testid="stSidebar"] {
        position: fixed !important; top: 0 !important; left: 0 !important; height: 100vh !important;
        min-width: 220px !important; max-width: 220px !important; z-index: 9999998 !important;
        background-color: #EAECEE !important; box-shadow: 5px 0 15px rgba(0,0,0,0.3) !important;
    }
}

/* ================================================================= */
/* 3. ESTILOS COMPARTIDOS (Menú, Tarjetas y Cuadros)                 */
/* ================================================================= */
div[role="radiogroup"] > label > div:first-child { display: none !important; }
div[role="radiogroup"] > label {
    background-color: transparent; border-radius: 6px; padding: 10px 12px !important;
    margin-bottom: 8px !important; border-left: 4px solid transparent; transition: all 0.2s ease;
}
div[role="radiogroup"] > label p { font-weight: 600 !important; font-size: 14px !important; color: #5D6D7E !important; margin: 0 !important; }
div[role="radiogroup"] label[data-checked="true"], div[role="radiogroup"] label:has(input:checked) {
    background-color: #FFFFFF !important; border-left: 4px solid #2ECC71 !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
}
div[role="radiogroup"] label[data-checked="true"] p, div[role="radiogroup"] label:has(input:checked) p {
    color: #2C3E50 !important; font-weight: 800 !important;
}
div[role="radiogroup"] label[data-checked="true"]::after, div[role="radiogroup"] label:has(input:checked)::after {
    content: ""; position: absolute; left: -4px; top: 50%; transform: translateY(-50%); height: 14px; width: 4px; background-color: #E74C3C;
}

.tarjeta-metrica { background-color: #FFFFFF; padding: 8px 10px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); margin-bottom: 12px; text-align: center; height: 85px !important; display: flex; flex-direction: column; justify-content: center; align-items: center; }
.tarjeta-titulo { color: #7F8C8D; font-size: 10px; margin: 0; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; min-height: 24px; display: flex; align-items: flex-end; justify-content: center; padding-bottom: 2px; line-height: 1.1; }
.tarjeta-valor { color: #2C3E50; font-size: 26px; margin: 0 !important; font-weight: 700; line-height: 1; }
.tarjeta-equipo { background-color: #FFFFFF; padding: 12px 10px; border-radius: 10px; border-top: 4px solid #2980B9; box-shadow: 0 3px 8px rgba(0,0,0,0.04); text-align: center; margin-bottom: 10px; height: 120px !important; display: flex; flex-direction: column; justify-content: center; }
div[data-testid="stExpander"] summary p { font-size: 14px !important; font-weight: 400 !important; color: #2C3E50 !important; }
div[data-testid="stExpander"] div[data-testid="stButton"] button { min-height: 35px !important; padding: 2px 5px !important; }
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
        <div style='display: flex; flex-direction: row; align-items: center; justify-content: center; position: relative; width: 100%; margin-bottom: 25px; flex-wrap: wrap; gap: 20px;'>
            <div style='flex: 1 1 300px; text-align: center; order: 1;'>
                <h1 style='margin:0; color:#1A252F; font-size: clamp(24px, 4vw, 36px); line-height: 1.2;'>{titulo}</h1>
                <p style='margin:8px 0 0 0; color:#7F8C8D; font-size: 14px;'>{subtitulo}</p>
            </div>
            <div style='order: 2; flex-shrink: 0;'>
                <div style='width: 110px; min-height: 105px; background: linear-gradient(135deg, #656D74, #495057); border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.15); padding: 12px 14px; position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; margin: 0 auto;'>
                    <div style='position: absolute; right: 0; top: 0; width: 35px; height: 100%; background-image: radial-gradient(rgba(255,255,255,0.25) 1.5px, transparent 1.5px); background-size: 8px 8px; z-index: 1;'></div>
                    <div style='position: relative; z-index: 2; width: 100%; text-align: left;'>
                        <span style="color: #FFFFFF; font-size: 28px; font-weight: 900; letter-spacing: 0px; line-height: 1; margin-bottom: 6px; font-family: 'Inter', sans-serif; display: block;">SBN</span>
                        <div style="display: flex; width: 100%; height: 3px; margin-bottom: 6px;">
                            <div style="background-color: #FFFFFF; flex-grow: 1;"></div>
                            <div style="background-color: #E74C3C; width: 18px;"></div>
                        </div>
                        <span style="color: #FFFFFF; font-size: 13px; font-weight: 700; line-height: 1.2; letter-spacing: 0.5px; font-family: 'Inter', sans-serif; display: block;">DGPE</span>
                        <span style="color: #FFFFFF; font-size: 13px; font-weight: 700; line-height: 1.2; letter-spacing: 0.5px; font-family: 'Inter', sans-serif; display: block;">SDDI</span>
                    </div>
                </div>
            </div>
        </div>
        """
        st.markdown(html_encabezado, unsafe_allow_html=True)

def crear_tarjeta(titulo, valor, color_borde):
    st.markdown(f"""
    <div class="tarjeta-metrica" style="border-bottom: 4px solid {color_borde};">
        <div class="tarjeta-titulo">{titulo}</div>
        <div class="tarjeta-valor">{valor}</div>
    </div>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner=False)
def cargar_datos():
    # ¡Asegúrate de colocar tu enlace real del CSV aquí!
    url_sheet = "https://docs.google.com/spreadsheets/d/e/2PACX-1vT1sNYxj6znXHjwEGFZH58FXR1CUGUuw6Ro7dz2Y65byi6nkGP9s5f88FbUze-QT550MeucdeSpOIWm/pub?gid=0&single=true&output=csv" 
    df = pd.read_csv(url_sheet)
    if "Profesional" in df.columns:
        df["Profesional"] = df["Profesional"].astype(str).apply(lambda x: re.sub(r'[1Xx]+$', '', x.strip()) if pd.notna(x) else x)
    return df

# ==============================================================================
# MENU LATERAL (SIDEBAR)
# ==============================================================================
with st.sidebar:
    st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True) 
    menu_seleccion = st.radio("Navegación:", ["Gestión de Expedientes", "Avance de Producción"], label_visibility="collapsed")

# ==============================================================================
# MÓDULO 1: GESTIÓN DE EXPEDIENTES
# ==============================================================================
if menu_seleccion == "Gestión de Expedientes":
    try:
        with st.spinner("Conectando con la base de datos..."):
            df = cargar_datos()
    except Exception as e:
        st.error("Error al conectar con la base de datos. Asegúrate de colocar un enlace CSV válido en 'url_sheet'.")
        st.stop()

    if st.session_state.capa_actual == 1:
        mostrar_encabezado("Gestión de Expedientes SDDI", "Gestión y seguimiento de expedientes en trámite a nivel nacional.", mostrar_volver=False)

        total_exp = len(df)
        tramite_activo = df[df["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0]
        flujo_lento = df[df["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False)].shape[0]
        paralizados = df[df["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)].shape[0]

        m1, m2, m3, m4 = st.columns(4)
        with m1: crear_tarjeta("📁 Total en Trámite", total_exp, "#3498DB")
        with m2: crear_tarjeta("🟢 Trámite Activo (Semanas)", tramite_activo, "#2ECC71")
        with m3: crear_tarjeta("🟡 Flujo Lento (1 a 5 meses)", flujo_lento, "#F1C40F")
        with m4: crear_tarjeta("🚨 Paralizados (+6 meses)", paralizados, "#E74C3C")

        st.markdown("<hr style='border:none; border-top:1px solid #E0E6ED; margin:20px 0;'>", unsafe_allow_html=True)
        st.markdown("<h4 style='color:#2C3E50; text-align:center;'>Carga General por Equipos de Trabajo</h4><br>", unsafe_allow_html=True)

        equipos = sorted(df["Equipo"].dropna().astype(str).unique().tolist())
        cols_eq = st.columns(min(len(equipos), 4))

        for idx, eq in enumerate(equipos):
            with cols_eq[idx % 4]:
                df_eq = df[df["Equipo"] == eq]
                criticos = df_eq[df_eq["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)].shape[0]
                st.markdown(f"""
                <div class="tarjeta-equipo">
                    <h4 style="margin:0; color:#2C3E50; font-size:16px;">{eq}</h4>
                    <p style="margin:4px 0 0 0; color:#7F8C8D; font-size:12px;">Total: <b>{len(df_eq)}</b> expedientes</p>
                    <p style="margin:2px 0 8px 0; color:#E74C3C; font-size:11px; font-weight:600;">🚨 {criticos} paralizados</p>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"🔍 Ver Reporte: {eq}", key=f"btn_{eq}", use_container_width=True, type="primary"):
                    ir_a_capa(2, equipo=eq)
                    st.rerun()

    elif st.session_state.capa_actual == 2:
        eq_sel = st.session_state.equipo_sel
        df_eq = df[df["Equipo"] == eq_sel]
        mostrar_encabezado(f"Reporte Dinámico: {eq_sel}", "Evaluación detallada de estados y carga por especialista.", mostrar_volver=True)

        act = df_eq[df_eq["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0]
        len_f = df_eq[df_eq["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False)].shape[0]
        par = df_eq[df_eq["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)].shape[0]

        k1, k2, k3, k4 = st.columns(4)
        with k1: crear_tarjeta("Total Equipo", len(df_eq), "#3498DB")
        with k2: crear_tarjeta("🟢 Trámite Activo", act, "#2ECC71")
        with k3: crear_tarjeta("🟡 Flujo Lento", len_f, "#F1C40F")
        with k4: crear_tarjeta("🔴 Paralizados", par, "#E74C3C")

        st.markdown("<hr style='border:none; border-top:1px solid #E0E6ED; margin:20px 0;'><h4 style='color:#2C3E50;'>👨‍💼 Relación de Profesionales</h4>", unsafe_allow_html=True)

        profesionales = df_eq["Profesional"].value_counts().sort_values(ascending=False).index.tolist()

        for prof in profesionales:
            df_p = df_eq[df_eq["Profesional"] == prof]
            
            df_sddi = df_p[df_p["Tipo Doc"].astype(str).str.contains("generado", case=False, na=False)]
            s_act, s_len, s_par = sum(df_sddi["Trazabilidad"].str.contains("semana", case=False, na=False)), sum(df_sddi["Trazabilidad"].str.contains("mes", case=False, na=False)), sum(df_sddi["Trazabilidad"].str.contains("año|6 meses", case=False, na=False))
            
            df_ext = df_p[df_p["Tipo Doc"].astype(str).str.contains("Externo", case=False, na=False)]
            e_act, e_len, e_par = sum(df_ext["Trazabilidad"].str.contains("semana", case=False, na=False)), sum(df_ext["Trazabilidad"].str.contains("mes", case=False, na=False)), sum(df_ext["Trazabilidad"].str.contains("año|6 meses", case=False, na=False))

            with st.expander(f"👤 {prof} — Total: {len(df_p)} expedientes en trámite"):
                if f"f_{prof}" not in st.session_state: st.session_state[f"f_{prof}"] = "Oculto"

                col_lbl1, c1, c2, c3 = st.columns([3, 1, 1, 1])
                with col_lbl1: st.markdown(f"<div style='margin-top:5px; font-size:13px; color:#2C3E50;'>📄 <b>Generado SDDI</b> ({len(df_sddi)})</div>", unsafe_allow_html=True)
                with c1: 
                    if st.button(f"🟢 {s_act}", key=f"sa_{prof}", use_container_width=True): st.session_state[f"f_{prof}"] = "SA"
                with c2: 
                    if st.button(f"🟡 {s_len}", key=f"sl_{prof}", use_container_width=True): st.session_state[f"f_{prof}"] = "SL"
                with c3: 
                    if st.button(f"🔴 {s_par}", key=f"sp_{prof}", use_container_width=True): st.session_state[f"f_{prof}"] = "SP"

                col_lbl2, c4, c5, c6 = st.columns([3, 1, 1, 1])
                with col_lbl2: st.markdown(f"<div style='margin-top:5px; font-size:13px; color:#2C3E50;'>📥 <b>Externo Recibido</b> ({len(df_ext)})</div>", unsafe_allow_html=True)
                with c4: 
                    if st.button(f"🟢 {e_act}", key=f"ea_{prof}", use_container_width=True): st.session_state[f"f_{prof}"] = "EA"
                with c5: 
                    if st.button(f"🟡 {e_len}", key=f"el_{prof}", use_container_width=True): st.session_state[f"f_{prof}"] = "EL"
                with c6: 
                    if st.button(f"🔴 {e_par}", key=f"ep_{prof}", use_container_width=True): st.session_state[f"f_{prof}"] = "EP"

                f_actual = st.session_state[f"f_{prof}"]
                
                if f_actual != "Oculto":
                    st.markdown("<hr style='margin: 15px 0; border-top: 1px dashed #E0E6ED;'>", unsafe_allow_html=True)
                    st.info("💡 **Aviso:** Para que el botón automatice la búsqueda necesitas la extensión del bot en tu navegador.", icon="⚙️")
                    
                    df_m = df_p.copy()
                    if f_actual == "SA": df_m = df_sddi[df_sddi["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)]
                    elif f_actual == "SL": df_m = df_sddi[df_sddi["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False)]
                    elif f_actual == "SP": df_m = df_sddi[df_sddi["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)]
                    elif f_actual == "EA": df_m = df_ext[df_ext["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)]
                    elif f_actual == "EL": df_m = df_ext[df_ext["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False)]
                    elif f_actual == "EP": df_m = df_ext[df_ext["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)]
                    
                    if len(df_m) > 0:
                        if "Trazabilidad" in df_m.columns: df_m = df_m.sort_values(by="Trazabilidad", ascending=False)
                        df_m["URL_Tramite"] = "https://tramitetransparente.sbn.gob.pe/#auto=" + df_m["expediente"].astype(str)
                        cols_mostrar = ["expediente", "Tipo Doc", "Trazabilidad", "URL_Tramite"]
                        existentes = [c for c in cols_mostrar if c in df_m.columns]
                        
                        col_t, col_d = st.columns([5, 1.2])
                        with col_d:
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                columnas_exportar = [col for col in df_m.columns if col != "URL_Tramite"]
                                df_m[columnas_exportar].to_excel(writer, index=False, sheet_name='Expedientes')
                            
                            st.download_button(
                                label="📥 Bajar Excel",
                                data=buffer.getvalue(),
                                file_name=f"Reporte_{prof}_{f_actual}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True
                            )
                            st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)
                            if st.button("❌ Cerrar lista", key=f"c_{prof}", use_container_width=True):
                                st.session_state[f"f_{prof}"] = "Oculto"
                                st.rerun()

                        with col_t:
                            st.dataframe(
                                df_m[existentes], 
                                use_container_width=True, 
                                hide_index=True,
                                column_config={"URL_Tramite": st.column_config.LinkColumn("🔗 Acción", display_text="Abrir Trámite")}
                            )
                    else:
                        st.info("No hay expedientes en esta categoría.")

# ==============================================================================
# MÓDULO 2: AVANCE DE PRODUCCIÓN
# ==============================================================================
elif menu_seleccion == "Avance de Producción":
    st.markdown("<br><br><h2 style='text-align: center; color: #2C3E50;'>Estamos trabajando para integrar esta información, por lo pronto ingrese a:</h2>", unsafe_allow_html=True)
    
    html_enlace = """
    <div style='text-align: center; margin-top: 40px;'>
        <a href="https://script.google.com/macros/s/AKfycbzNuA__KQObk_2JI8iuBxqFD5RyByc7jVHe7OudtrFrEnpIPBCc6D3SEZ0-BCofUYiJ/exec" 
           target="_blank" 
           style="background-color: #E74C3C; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
           Tablero de Control SDDI
        </a>
    </div>
    """
    st.markdown(html_enlace, unsafe_allow_html=True)

# ==============================================================================
# FOOTER / FIRMA DEL DESARROLLADOR
# ==============================================================================
st.markdown("""
<div style='text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #E0E6ED; color: #95A5A6; font-size: 13px; font-family: sans-serif;'>
    <b>Diseñado y Desarrollado: SDDI / tyantas</b> &nbsp;|&nbsp; 
    <span style="color: #95A5A6;">(Entorno Asegurado)</span>
</div>
""", unsafe_allow_html=True)
