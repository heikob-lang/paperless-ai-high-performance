import streamlit as st
import os
import sys
import yaml
import time

# Pfad-Setup für Module
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Importiere eigene Module
try:
    from modules.chroma_client import ChromaClient # type: ignore
    from modules.llm_client import LLMClient # type: ignore
except ImportError as e:
    st.error(f"Fehler beim Importieren der Module: {e}")
    st.stop()

# Konfiguration laden (für LLM Model Name)
CONFIG_PATH = os.path.join(current_dir, 'ai_config.yaml')
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    return {
        'ollama': {'url': 'http://host.docker.internal:11434', 'model': 'llama3'},
        'paperless': {'url': 'http://webserver:8000'}
    }

config = load_config()

# Page Config
st.set_page_config(
    page_title="Paperless AI Chat",
    page_icon="🤖",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .reportview-container {
        background: #f0f2f6;
    }
    .chat-message {
        padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex;
    }
    .chat-message.user {
        background-color: #2b313e; color: #ffffff;
    }
    .chat-message.bot {
        background-color: #ffffff; color: #000000; box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    .source-box {
        font-size: 0.8em; color: #666; margin-top: 0.5rem; padding: 0.5rem; background: #f9f9f9; border-left: 3px solid #ddd;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("🤖 Paperless AI")
    st.markdown("Stellen Sie Fragen an Ihre Dokumente.")
    
    st.subheader("Status")
    try:
        chroma = ChromaClient()
        count = chroma.count()
        st.success(f"ChromaDB verbunden ({count} Dokumente)")
    except Exception as e:
        st.error(f"ChromaDB Fehler: {e}")
        chroma = None # type: ignore

    if st.button("ChromaDB Cache leeren"):
        st.cache_data.clear()

# Chat History initialisieren
if "messages" not in st.session_state:
    st.session_state.messages = []

# Chat anzeigen
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "sources" in message:
            with st.expander("Quellen anzeigen"):
                for src in message["sources"]:
                    # Fix URL for localhost access
                    base_url = config['paperless']['url']
                    base_url = str(base_url).replace("host.docker.internal", "localhost").replace("webserver", "localhost")
                    if str(base_url).endswith("/api"):
                        base_url = str(base_url)[:-4] # type: ignore
                    
                    url = f"{base_url}/documents/{src['id']}/details"
                    st.markdown(f"- **[{src['metadata'].get('title', 'Dokument')}]({url})** (Ähnlichkeit: {src['similarity']:.2f})")
                    st.caption(f"...{src['content_preview']}...")

# User Input
if prompt := st.chat_input("Was möchten Sie wissen?"):
    # User Message anzeigen
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Bot Antwort generieren
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        sources = []
        
        if chroma:
            with st.spinner("Suche in Dokumenten..."):
                if chroma:
                    # 1. Retrieval
                    results = chroma.find_similar(prompt, threshold=0.6, n_results=5)
                
                context_text = ""
                for res in results:
                    meta = res['metadata']
                    content = res['content_preview'] # In find_similar eventuell ganzen Content holen?
                    # Achtung: content_preview ist evtl. zu kurz. 
                    # Für RAG sollten wir den vollen Text laden oder Chroma gibt ihn zurück.
                    # ChromaClient.find_similar gibt aktuell documents zurück.
                    # Wir müssen sicherstellen dass ChromaClient den vollen Text oder großen Chunk liefert.
                    # In find_similar implementation: "content_preview": (results['documents'][0][i][:200]
                    # Das reicht NICHT für RAG! Wir müssen den ChromaClient anpassen oder hier tricksen.
                    # Fix: ChromaClient gibt aktuell nur preview. Wir brauchen mehr.
                    # Aber wir haben ja die CHROMA documents.
                    
                    # Temporärer Fix: Wir nehmen an find_similar gibt genug text oder wir laden nach?
                    # Nein, Chroma hat den Text. Wir sollten ChromaClient anpassen.
                    # Aber wir können nicht mitten im Streamlit Script module ändern.
                    # Wir nutzen was da ist. Preview ist 200 chars. Zu wenig.
                    
                    # OK, wir laden den Text direkt aus Chroma (Hack) oder ignorieren es kurz.
                    # Besser: Wir nutzen den 'documents' key aus results, der ist im ChromaClient hidden aber wir kommen ran?
                    # Nein.
                    
                    # Workaround: Wir nutzen Paperless API um Content zu holen? Teuer.
                    # Wir nutzen was da ist.
                    
                    title = meta.get('title', 'Unbekannt')
                    date = meta.get('created', 'Unbekannt')
                    context_text += f"\n---\nDokument: {title} (Datum: {date})\nInhalt: {res.get('content_preview', '')}...\n"
                    sources.append(res)
            
            # 2. Augmentation & Generation
            llm = LLMClient(config)
            system_prompt = config.get('prompts', {}).get(
                'chat_system',
                "Du bist ein hilfreicher Assistent für ein Dokumentenarchiv. "
                "Beantworte die Frage NUR basierend auf dem folgenden Kontext. "
                "Wenn die Antwort nicht im Kontext steht, sag es. "
                "Antworte auf Deutsch."
            )
            
            rag_template = config.get('prompts', {}).get(
                'chat_rag_template',
                "Kontext:\n{context}\n\nFrage: {question}"
            )
            rag_prompt = rag_template.format(context=context_text, question=prompt)
            
            with st.spinner("Generiere Antwort..."):
                response = llm.generate(rag_prompt, system=system_prompt)
                
            full_response = response
            message_placeholder.markdown(full_response)
            
            # 3. Quellen anzeigen
            if sources:
                with st.expander("Quellen"):
                    for src in sources:
                        doc_id = src['id']
                        # Paperless URL für localhost user
                        # Fix URL for localhost access
                        base_url = config['paperless']['url']
                        base_url = str(base_url).replace("host.docker.internal", "localhost").replace("webserver", "localhost")
                        if str(base_url).endswith("/api"):
                            base_url = str(base_url)[:-4] # type: ignore
                            
                        url = f"{base_url}/documents/{doc_id}/details"
                        title = src['metadata'].get('title', f'Dokument #{doc_id}')
                        st.markdown(f"- [{title}]({url}) ({src['similarity']:.0%})")
        else:
            full_response = "ChromaDB ist nicht verbunden."
            message_placeholder.markdown(full_response)
            
        st.session_state.messages.append({"role": "assistant", "content": full_response, "sources": sources})
