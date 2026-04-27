import streamlit as st
from streamlit_calendar import calendar
import datetime
import os
from mistralai import Mistral
import PyPDF2
import streamlit.components.v1 as components

# NEU: Imports für Chunking und Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
import hashlib

# --- 1. GRUNDEINSTELLUNGEN & INITIALISIERUNG ---

# Lade den API-Schlüssel aus den Streamlit Secrets (für Deployment)
api_key = st.secrets.get("MISTRAL_API_KEY")

# Fallback auf Umgebungsvariablen (für lokale Entwicklung)
if not api_key:
    api_key = os.getenv("MISTRAL_API_KEY")

# Konfiguriere die Streamlit-Seite
st.set_page_config(
    page_title="Pflegegrad Widerspruchs-Assistent",
    page_icon="🛡️",
    layout="wide"
)

# Wichtige Prüfung, ob der API-Schlüssel vorhanden ist
if not api_key:
    st.error("Mistral API-Schlüssel nicht gefunden! Bitte konfiguriere das 'MISTRAL_API_KEY' Secret in den Einstellungen deiner App.")
    st.stop() # App anhalten, wenn kein Schlüssel da ist

# Initialisiere den Mistral AI Client
model = "mistral-large-latest"
client = Mistral(api_key=api_key)

# NEU: Initialisiere Embedding-Modell und Vektor-Datenbank
@st.cache_resource
def load_embedding_model():
    """Lädt das Sentence-Transformer-Modell (wird gecacht)."""
    return SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

@st.cache_resource
def init_vector_db():
    """Initialisiert ChromaDB als Vektor-Datenbank."""
    chroma_client = chromadb.Client(Settings(
        anonymized_telemetry=False,
        is_persistent=False
    ))
    return chroma_client

embedding_model = load_embedding_model()
chroma_client = init_vector_db()


# --- 2. FUNKTIONEN FÜR DIE APP-LOGIK ---

def get_fristen_info(ablehnungsdatum):
    """Berechnet wichtige Fristen basierend auf dem Ablehnungsdatum."""
    if ablehnungsdatum:
        widerspruchsfrist = ablehnungsdatum + datetime.timedelta(days=30)
        return {
            "Widerspruchsfrist endet am": widerspruchsfrist,
            "Empfehlung: Widerspruch einreichen bis": ablehnungsdatum + datetime.timedelta(days=25),
            "Empfehlung: Pflegetagebuch abschließen bis": ablehnungsdatum + datetime.timedelta(days=20),
        }
    return {}

def read_pdf(file):
    """Liest den Text aus einer hochgeladenen PDF-Datei."""
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        return f"Fehler beim Lesen der PDF-Datei: {e}"

def chunk_text(text, chunk_size=500, chunk_overlap=50):
    """
    Teilt Text in kleinere Chunks auf.
    
    Args:
        text: Der zu teilende Text
        chunk_size: Maximale Größe eines Chunks in Zeichen
        chunk_overlap: Überlappung zwischen Chunks
    
    Returns:
        Liste von Text-Chunks
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = text_splitter.split_text(text)
    return chunks

def create_embeddings(chunks):
    """
    Erstellt Embeddings für die Text-Chunks.
    
    Args:
        chunks: Liste von Text-Strings
    
    Returns:
        Liste von Embedding-Vektoren
    """
    embeddings = embedding_model.encode(chunks, show_progress_bar=False)
    return embeddings.tolist()

def store_chunks_in_vectordb(doc_name, chunks, embeddings):
    """
    Speichert Chunks und ihre Embeddings in ChromaDB.
    
    Args:
        doc_name: Name des Dokuments
        chunks: Liste der Text-Chunks
        embeddings: Liste der Embedding-Vektoren
    """
    # Erstelle oder hole Collection
    collection_name = "documents"
    
    try:
        collection = chroma_client.get_collection(collection_name)
    except:
        collection = chroma_client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
    
    st.session_state.vector_collection = collection
    
    # Erstelle IDs für die Chunks
    ids = [f"{doc_name}_chunk_{i}" for i in range(len(chunks))]
    
    # Metadaten für jeden Chunk
    metadatas = [{"source": doc_name, "chunk_id": i} for i in range(len(chunks))]
    
    # Speichere in der Datenbank
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas
    )
    
    return collection

def semantic_search(query, top_k=3):
    """
    Führt eine semantische Suche in den gespeicherten Dokumenten durch.
    
    Args:
        query: Die Suchanfrage
        top_k: Anzahl der zurückzugebenden relevantesten Chunks
    
    Returns:
        Liste der relevantesten Text-Chunks mit Metadaten
    """
    if st.session_state.vector_collection is None:
        return []
    
    # Erstelle Embedding für die Query
    query_embedding = embedding_model.encode([query])[0].tolist()
    
    # Suche in der Vektor-Datenbank
    results = st.session_state.vector_collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    return results

def process_document(file):
    """
    Vollständige Verarbeitung eines Dokuments: Lesen, Chunking, Embeddings.
    
    Args:
        file: Hochgeladene Datei
    
    Returns:
        Tuple: (original_text, chunks, anzahl_chunks)
    """
    # 1. Text extrahieren
    text = read_pdf(file)
    
    if text.startswith("Fehler"):
        return text, [], 0
    
    # 2. Text in Chunks aufteilen
    chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
    
    # 3. Embeddings erstellen
    embeddings = create_embeddings(chunks)
    
    # 4. In Vektor-Datenbank speichern
    store_chunks_in_vectordb(file.name, chunks, embeddings)
    
    # 5. Chunks für spätere Anzeige speichern
    st.session_state.doc_chunks[file.name] = chunks
    
    return text, chunks, len(chunks)

def ask_mistral(user_question, use_semantic_search=True):
    system_prompt = (
        "Du bist ein hilfreicher und einfühlsamer KI-Assistent. Deine Aufgabe ist es, "
        "Nutzer durch den Widerspruchsprozess für einen Pflegegrad in Deutschland zu führen. "
        "Antworte klar, strukturiert und verständlich. Gib keine Rechtsberatung, sondern nur "
        "allgemeine Informationen und Unterstützung. Wenn du auf Basis eines Dokuments antwortest, "
        "beziehe dich klar darauf und zitiere relevante Stellen."
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    
    context = ""
    
    # NEU: Nutze semantische Suche für relevanten Kontext
    if use_semantic_search and st.session_state.vector_collection is not None:
        search_results = semantic_search(user_question, top_k=3)
        
        if search_results and search_results['documents']:
            context = "Relevante Informationen aus deinen Dokumenten:\n\n"
            for i, (doc, metadata) in enumerate(zip(search_results['documents'][0], 
                                                     search_results['metadatas'][0])):
                context += f"[Aus {metadata['source']}]:\n{doc}\n\n"
    
    if context:
        full_question = f"{context}\n---\nFrage des Nutzers: {user_question}"
        messages.append({"role": "user", "content": full_question})
    else:
        messages.append({"role": "user", "content": user_question})

    try:
        chat_response = client.chat.complete(
            model=model, 
            messages=messages
        )
        return chat_response.choices[0].message.content
    except Exception as e:
        return f"Ein Fehler ist bei der Kommunikation mit der KI aufgetreten: {e}"

# --- 3. SESSION STATE INITIALISIERUNG ---

if 'process_started' not in st.session_state:
    st.session_state.process_started = False
if 'ablehnungsdatum' not in st.session_state:
    st.session_state.ablehnungsdatum = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'uploaded_docs' not in st.session_state:
    st.session_state.uploaded_docs = {}
# NEU: Für Vektor-Datenbank
if 'vector_collection' not in st.session_state:
    st.session_state.vector_collection = None
if 'doc_chunks' not in st.session_state:
    st.session_state.doc_chunks = {}


# --- 4. AUFBAU DER STREAMLIT-OBERFLÄCHE ---

st.title("🛡️ Dein Assistent für den Pflegegrad-Widerspruch")

# =======================================================================
# DAUERHAFTER RECHTLICHER HINWEIS
# =======================================================================
st.markdown("""
<style>
.disclaimer-box {
    background-color: #FFF3CD; /* Sanftes Gelb, passend zu Warnhinweisen */
    color: #664D03;           /* Dunkler Text für Kontrast */
    border: 1px solid #FFECB5;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-bottom: 1.5rem;
    text-align: center;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="disclaimer-box">
    <strong>Wichtiger Hinweis:</strong> Dieser Assistent bietet allgemeine Informationen und Unterstützung. Er stellt <strong>keine Rechtsberatung</strong> dar und kann eine individuelle Beratung durch einen Fachexperten (z.B. Anwalt, Pflegeberatung, Sozialverband) nicht ersetzen.
</div>
""", unsafe_allow_html=True)
# =======================================================================

st.markdown("Wir führen dich Schritt für Schritt durch den Prozess. Einfach, klar und strukturiert.")

# --- ANSICHT 1: STARTBILDSCHIRM ---
if not st.session_state.process_started:
    st.header("Schritt 1: Prozess starten und Fristen setzen")
    st.info(
        "Der Widerspruch muss in der Regel **innerhalb eines Monats** nach Erhalt des "
        "Ablehnungsbescheids bei der Pflegekasse eingehen. Trage hier das Datum ein."
    )
    
    selected_date = st.date_input(
        "Datum des Ablehnungsbescheids:",
        value=None,
        min_value=datetime.date.today() - datetime.timedelta(days=365),
        max_value=datetime.date.today(),
        help="Wähle das Datum, an dem du den Brief von der Pflegekasse erhalten hast."
    )

    if st.button("Prozess starten", type="primary"):
        if selected_date:
            st.session_state.ablehnungsdatum = selected_date
            st.session_state.process_started = True
            st.rerun()
        else:
            st.warning("Bitte wähle zuerst das Datum des Ablehnungsbescheids aus.")

# --- ANSICHT 2: HAUPTANSICHT NACH PROZESSSTART ---
else:
    # --- Linke Seitenleiste ---
    with st.sidebar:
        st.header("Dein Status")
        
        fristen = get_fristen_info(st.session_state.ablehnungsdatum)
        st.write(f"Bescheid vom: **{st.session_state.ablehnungsdatum.strftime('%d.%m.%Y')}**")
        
        widerspruchsfrist_ende = fristen.get("Widerspruchsfrist endet am")
        if widerspruchsfrist_ende:
            tage_verbleibend = (widerspruchsfrist_ende - datetime.date.today()).days
            st.metric(
                label="Tage bis Fristende für Widerspruch",
                value=f"{tage_verbleibend} Tage",
                delta=f"Frist endet am {widerspruchsfrist_ende.strftime('%d.%m.%Y')}",
                delta_color="inverse" if tage_verbleibend > 10 else ("off" if tage_verbleibend <= 0 else "normal")
            )
        st.divider()

        st.header("Dokumente verwalten")
        uploaded_file = st.file_uploader(
            "Lade Dokumente hoch (PDF)", type="pdf", key="file_uploader"
        )
        
        if uploaded_file:
            if uploaded_file.name not in st.session_state.uploaded_docs:
                with st.spinner(f"Verarbeite '{uploaded_file.name}'..."):
                    # Fortschrittsanzeige
                    progress_text = st.empty()
                    
                    progress_text.text("📄 Lese PDF...")
                    text, chunks, num_chunks = process_document(uploaded_file)
                    
                    if not text.startswith("Fehler"):
                        st.session_state.uploaded_docs[uploaded_file.name] = text
                        
                        progress_text.text(f"✅ Fertig! {num_chunks} Chunks erstellt.")
                        st.success(
                            f"'{uploaded_file.name}' wurde erfolgreich verarbeitet.\n\n"
                            f"📊 Statistik: {len(text)} Zeichen, {num_chunks} Chunks"
                        )
                    else:
                        st.error(text)
        
        if st.session_state.uploaded_docs:
            st.write("**Hochgeladene Dokumente:**")
            for doc_name in st.session_state.uploaded_docs.keys():
                num_chunks = len(st.session_state.doc_chunks.get(doc_name, []))
                with st.expander(f"📄 {doc_name}"):
                    st.write(f"Anzahl Chunks: {num_chunks}")
                    if st.button(f"Chunks anzeigen", key=f"show_{doc_name}"):
                        for i, chunk in enumerate(st.session_state.doc_chunks.get(doc_name, [])[:5]):
                            st.text_area(f"Chunk {i+1}", chunk, height=100, key=f"chunk_{doc_name}_{i}")
                        if num_chunks > 5:
                            st.info(f"... und {num_chunks - 5} weitere Chunks")
        
        st.divider()
        if st.button("Prozess neu starten"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # --- Hauptbereich mit Tabs ---
    tab1, tab2, tab3, tab4 = st.tabs(["Schritt-für-Schritt", "Kalender", "Chat-Assistent", "Pflegegrad-Rechner"])

    with tab1:
        st.header("Schritt-für-Schritt durch den Widerspruch")
        st.markdown("""
        Hier ist dein Fahrplan. Arbeite die Punkte nacheinander ab.
        
        ### Schritt 1: Fristwahrender Widerspruch (SOFORT)
        - **Was?** Ein kurzes Schreiben an die Pflegekasse, in dem du formlos mitteilst: "Hiermit lege ich Widerspruch gegen den Bescheid vom [Datum des Bescheids] ein. Eine ausführliche Begründung reiche ich nach."
        - **Warum?** Damit verpasst du die wichtige 1-Monats-Frist nicht!
        - **Erledigt?** ☐
            
        ### Schritt 2: Unterlagen sammeln (ca. 1-2 Wochen)
        - **Was?** Sammle alle relevanten Dokumente:
            - Ärztliche Atteste, Berichte, Gutachten
            - Pflegetagebuch (sehr wichtig!)
            - Liste der benötigten Hilfsmittel
        - **Tipp:** Lade die Dokumente hier in der App hoch, um sie vom Chatbot analysieren zu lassen.
        - **Erledigt?** ☐
            
        ### Schritt 3: Begründung formulieren (ca. 1 Woche)
        - **Was?** Schreibe die ausführliche Begründung für deinen Widerspruch. Beschreibe genau, warum die Ablehnung oder die Einstufung falsch ist.
        - **Hilfe:** Nutze den Chat-Assistenten! Frage z.B.: "Hilf mir, eine Begründung zu formulieren. Mein Pflegetagebuch zeigt, dass ich Hilfe beim Anziehen brauche."
        - **Erledigt?** ☐
    
        ### Schritt 4: Begründung abschicken
        - **Was?** Schicke die ausführliche Begründung per Einschreiben an die Pflegekasse.
        - **Wichtig:** Hebe den Sendebeleg gut auf!
        - **Erledigt?** ☐
        """)
    
    with tab2:
        st.header("Dein Fristenkalender")
        calendar_events = []
        fristen = get_fristen_info(st.session_state.ablehnungsdatum)
        for name, datum in fristen.items():
            calendar_events.append({
                "title": name, 
                "start": datum.isoformat(), 
                "end": datum.isoformat(),
                "allDay": True, 
                "color": "red" if "endet" in name else "orange"
            })
        calendar_options = {
            "headerToolbar": {
                "left": "today prev,next", 
                "center": "title", 
                "right": "dayGridMonth,timeGridWeek"
            },
            "initialDate": st.session_state.ablehnungsdatum.isoformat(),
            "initialView": "dayGridMonth"
        }
        calendar(events=calendar_events, options=calendar_options)

    with tab3:
        st.header("Dein persönlicher Chat-Assistent")
        
        # NEU: Info-Box über semantische Suche
        if st.session_state.uploaded_docs:
            st.success(
                f"🔍 Semantische Suche aktiv! Ich durchsuche {len(st.session_state.uploaded_docs)} "
                f"Dokument(e) nach relevanten Informationen zu deiner Frage."
            )
        else:
            st.info("Stelle hier deine Fragen zum Prozess. Lade Dokumente hoch für dokumentenspezifische Antworten.")
        
        # Chat-Historie anzeigen
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        # Neuer Chat-Input
        prompt = st.chat_input("Deine Frage an den Assistenten...")
        if prompt:
            # Nutzerfrage hinzufügen
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Antwort generieren
            with st.chat_message("assistant"):
                with st.spinner("Ich durchsuche die Dokumente und denke nach..."):
                    # Nutze die neue semantische Suche
                    response = ask_mistral(prompt, use_semantic_search=True)
                    st.markdown(response)
            
            st.session_state.chat_history.append({"role": "assistant", "content": response})

    with tab4:
        st.header("Pflegegrad-Rechner (Externer Service)")
        st.warning(
            "Der Pflegegrad-Rechner von pflegehilfe.org kann aus Sicherheitsgründen nicht direkt in diese App "
            "eingebettet werden. Du kannst ihn aber über den folgenden Link in einem neuen Browser-Tab öffnen."
        )

        rechner_url = "https://www.pflegehilfe.org/service/pflegegrad-rechner/modul/1"

        # Ein großer, klickbarer Button/Link
        st.markdown(f'''
        <a href="{rechner_url}" target="_blank" style="display: inline-block; padding: 1em 2em; background-color: #0068c9; color: white; text-align: center; text-decoration: none; border-radius: 0.5rem; font-size: 1.1em; font-weight: bold; margin-top: 1em;">
            Zum Pflegegrad-Rechner wechseln
        </a>
        ''', unsafe_allow_html=True)
        
        st.markdown("---")
        st.info(
            "**Anleitung:**\n"
            "1. Klicke auf den Button, um den Rechner zu öffnen.\n"
            "2. Fülle die Fragen auf der externen Seite aus.\n"
            "3. Komm hierher zurück, um mit den Informationen weiterzuarbeiten."
        )
