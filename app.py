import os
import streamlit as st
import pandas as pd
import plotly.express as px

# 1. Configuración de tema base (Fondo gris humo para resaltar el blanco de las tarjetas)
os.makedirs(".streamlit", exist_ok=True)
with open(".streamlit/config.toml", "w", encoding="utf-8") as f:
    f.write('''[theme]
primaryColor = "#2980B9"
backgroundColor = "#F4F7F6" 
secondaryBackgroundColor = "#FFFFFF"
textColor = "#2C3E50"
font = "sans serif"
''')

st.set_page_config(page_title="Monitor SDDI", layout="wide", page_icon="🏛️")

# 2. Inyección de Tipografía Inter y estilos generales
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
/* Centrar las pestañas de las tablas */
.stTabs [data-baseweb="tab-list"] {
    justify-content: center;
}
/* Ocultar el menú superior derecho (Share, GitHub, etc.) sin romper la barra lateral */
[data-testid="stToolbar"] {visibility: hidden !important;}
/* Ocultar el footer o pie de página predeterminado */
footer {visibility: hidden !important;}
</style>
""", unsafe_allow_html=True)

# 3. Función constructora de Tarjetas (Tamaño Reducido 20%)
def crear_tarjeta(titulo, valor, color_borde):
    tarjeta_html = f"""
    <div style="
        background-color: #FFFFFF;
        padding: 12px 18px; /* Márgenes reducidos */
        border-radius: 8px;
        box-shadow: 0 3px 8px rgba(0,0,0,0.04);
        border-bottom: 4px solid {color_borde};
        margin-bottom: 15px;
        text-align: left;
    ">
        <p style="color: #7F8C8D; font-size: 13px; margin: 0; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">{titulo}</p>
        <h2 style="color: #2C3E50; font-size: 30px; margin: 4px 0 0 0; font-weight: 700;">{valor}</h2>
    </div>
    """
    st.markdown(tarjeta_html, unsafe_allow_html=True)

# 4. Carga de datos
@st.cache_data(ttl=300)
def cargar_datos():
    # Recuerda pegar aquí el enlace de tu Google Sheet
    url_sheet = "https://docs.google.com/spreadsheets/d/e/2PACX-1vT1sNYxj6znXHjwEGFZH58FXR1CUGUuw6Ro7dz2Y65byi6nkGP9s5f88FbUze-QT550MeucdeSpOIWm/pub?gid=0&single=true&output=csv" 
    return pd.read_csv(url_sheet)

try:
    df = cargar_datos()
except Exception as e:
    st.error("Error al conectar con Google Sheets. Verifica el enlace.")
    st.stop()

# 5. Panel lateral
st.sidebar.title("⚙️ Panel de Filtros")
equipos_disp = ["Todos"] + sorted(df["Equipo"].dropna().astype(str).unique().tolist())
equipo_sel = st.sidebar.selectbox("Área / Equipo:", equipos_disp)

if equipo_sel != "Todos":
    df_filtrado = df[df["Equipo"] == equipo_sel]
else:
    df_filtrado = df.copy()

profesionales_disp = ["Todos"] + sorted(df_filtrado["Profesional"].dropna().astype(str).unique().tolist())
prof_sel = st.sidebar.selectbox("Especialista:", profesionales_disp)

if prof_sel != "Todos":
    df_filtrado = df_filtrado[df_filtrado["Profesional"] == prof_sel]

# 6. Título Centrado
st.markdown("<h1 style='text-align: center; color: #1A252F; font-size: 42px;'>Centro de Monitoreo SDDI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #7F8C8D; font-size: 18px; margin-bottom: 40px;'>Gestión y seguimiento interactivo de la carga documentaria y expedientes.</p>", unsafe_allow_html=True)

# 7. Lógica de estados
total_exp = len(df_filtrado)
tramite_activo = df_filtrado[df_filtrado["Trazabilidad"].astype(str).str.contains("semana", case=False, na=False)].shape[0]
flujo_lento = df_filtrado[df_filtrado["Trazabilidad"].astype(str).str.contains("mes", case=False, na=False)].shape[0]
paralizados = df_filtrado[df_filtrado["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)].shape[0]

# 8. Renderizado de Tarjetas Personalizadas
col1, col2, col3, col4 = st.columns(4)
with col1:
    crear_tarjeta("📁 Total Asignados", total_exp, "#3498DB") 
with col2:
    crear_tarjeta("🟢 Trámite Activo", tramite_activo, "#2ECC71") 
with col3:
    crear_tarjeta("🟡 Flujo Lento", flujo_lento, "#F1C40F") 
with col4:
    crear_tarjeta("🚨 Requieren Acción", paralizados, "#E74C3C") 

st.markdown("<br>", unsafe_allow_html=True)

# 9. Gráficos
col_g1, col_g2 = st.columns(2)

with col_g1:
    st.markdown("<h3 style='color: #34495E; font-size: 18px; text-align: center;'>Distribución de Carga por Equipo</h3>", unsafe_allow_html=True)
    conteo = df_filtrado["Equipo"].value_counts().reset_index()
    conteo.columns = ["Equipo", "Expedientes"]
    fig1 = px.bar(
        conteo, x="Expedientes", y="Equipo", orientation='h', text="Expedientes", 
        color_discrete_sequence=["#3498DB"]
    )
    fig1.update_layout(yaxis={'categoryorder':'total ascending'}, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10))
    st.plotly_chart(fig1, use_container_width=True)

with col_g2:
    st.markdown("<h3 style='color: #34495E; font-size: 18px; text-align: center;'>Naturaleza del Documento</h3>", unsafe_allow_html=True)
    fig2 = px.pie(
        df_filtrado, names="Tipo Doc", hole=0.5, 
        color_discrete_sequence=["#3498DB", "#E74C3C", "#2ECC71"]
    )
    fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10))
    st.plotly_chart(fig2, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

# 10. Buscador y Tablas
st.markdown("<h2 style='text-align: center; color: #1A252F; font-size: 24px; margin-bottom: 20px;'>Búsqueda y Expedientes Prioritarios</h2>", unsafe_allow_html=True)
tab1, tab2 = st.tabs(["🔥 Alertas Críticas (Desatorar)", "🔍 Buscar Expediente Libremente"])

with tab2:
    busqueda = st.text_input("Ingresa el Nro de Expediente o nombre del especialista para localizarlo:")
    if busqueda:
        mask = df.astype(str).apply(lambda x: x.str.contains(busqueda, case=False)).any(axis=1)
        st.dataframe(df[mask], use_container_width=True)

with tab1:
    st.markdown("<p style='text-align: center; color: #7F8C8D;'>Expedientes estancados por más de 6 meses o 1 año. Priorizar atención inmediata.</p>", unsafe_allow_html=True)
    df_paralizados = df_filtrado[df_filtrado["Trazabilidad"].astype(str).str.contains("año|6 meses", case=False, na=False)]
    columnas_mostrar = ["expediente", "Tipo de Documento", "Equipo", "Profesional", "Trazabilidad"]
    columnas_existentes = [col for col in columnas_mostrar if col in df_paralizados.columns]
    st.dataframe(df_paralizados[columnas_existentes], use_container_width=True)
