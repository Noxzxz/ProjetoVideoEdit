import streamlit as st

st.set_page_config(
    page_title="AI Video Pipeline",
    layout="centered",
)

st.title("AI Video Pipeline")
st.markdown("Pipeline de pos-producao de video 100% local com IA.")
st.markdown("---")

tab1, tab2, tab3 = st.tabs(["Upload", "Progresso", "Resultados"])

with tab1:
    st.header("Upload de Video")
    uploaded = st.file_uploader(
        "Selecione um arquivo de video",
        type=["mp4", "mov", "avi", "mkv"],
    )
    if uploaded:
        st.success(f"Video carregado: {uploaded.name}")
        if st.button("Iniciar Processamento"):
            st.info("Processamento iniciado...")

with tab2:
    st.header("Progresso")
    st.info("Nenhum processamento em andamento.")
    st.progress(0)

with tab3:
    st.header("Resultados")
    st.info("Nenhum resultado disponivel. Processe um video primeiro.")
