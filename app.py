import streamlit as st
from streamlit_calendar import calendar
import datetime
import os
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
import PyPDF2
import streamlit.components.v1 as components
import numpy as np
from typing import List, Dict
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
    st.stop()

# Initialisiere den Mistral AI Client
model = "mistral-large-latest"
embedding_model = "mistral-embed"
client = MistralClient(api_key=api_key)


# --- 2. NEUE FUNKTIONEN FÜR CHUNKING UND EMBEDDINGS ---

def create_text_chunks(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """
    Teilt Text in überlappende Chunks auf.
    
    Args:
        text: Der zu teilende Text
        chunk_size: Maximale Größe eines Chunks in Zeichen
        overlap: Überlappung zwischen Chunks in Zeichen
    
    Returns:
        Liste von Text-Chunks
    """
    if not text or len(text) == 0:
        return []
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        # Ende des aktuellen Chunks
        end = start + chunk_size
        
        # Wenn wir nicht am Ende sind, versuche an einem Satzende zu trennen
        if end < text_length:
            # Suche nach dem letzten Punkt, Ausrufezeichen oder Fragezeichen
            last_period = max(
                text.rfind('.', start, end),
                text.rfind('!', start, end),
                text.rfind('?', start, end)
            )
            if last_period != -1 and last_period > start:
                end = last_period + 1
        
        # Chunk extrahieren
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # Nächsten Start mit Überlappung setzen
        start = end - overlap if end < text_length else text_length
    
    return chunks

def get_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Erstellt Embeddings für eine Liste von Texten.
    
    Args:
        texts: Liste von Texten
    
    Returns:
        Liste von Embedding-Vektoren
    """
    try:
        embeddings_response = client.embeddings(
            model=embedding_model,
            input=texts
        )
        return [data.embedding for data in embeddings_response.data]
    except Exception as e:
        st.error(f"Fehler beim Erstellen der Embeddings: {e}")
        return []

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Berechnet die Kosinus-Ähnlichkeit zwischen zwei Vektoren."""
    vec1_array = np.array(vec1)
    vec2_array = np.array(vec2)
    
    dot_product = np.dot(vec1_array, vec2_array)
    norm1 = np.linalg.norm(vec1_array)
    norm2 = np.linalg.norm(vec2_array)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)

def find_relevant_chunks(query: str, chunks_data: List[Dict], top_k: int = 3) -> List[Dict]:
    """
    Findet die relevantesten Chunks für eine Anfrage.
    
    Args:
        query: Die Suchanfrage
        chunks_data: Liste von Dictionaries mit 'text' und 'embedding'
        top_k: Anzahl der zurückzugebenden Top-Ergebnisse
    
    Returns:
        Liste der relevantesten Chunks mit Ähnlichkeitsscore
    """
    if not chunks_data:
        return []
    
    # Embedding für die Anfrage erstellen
    query_embeddings = get_embeddings([query])
    if not query_embeddings:
        return []
    
    query_embedding = query_embeddings[0]
    
    # Ähnlichkeiten berechnen
    similarities = []
    for chunk_data in chunks_data:
        similarity = cosine_similarity(query_embedding, chunk_data['embedding'])
        similarities.append({
            'text': chunk_data['text'],
            'similarity': similarity,
            'doc_name': chunk_data['doc_name']
        })
    
    # Nach Ähnlichkeit sortieren und Top-K zurückgeben
    similarities.sort(key=lambda x: x['similarity'], reverse=True)
    return similarities[:top_k]

def process_document_with_embeddings(text: str, doc_name: str) -> List[Dict]:
    """
    Verarbeitet ein Dokument: Chunking + Embeddings.
    
    Args:
        text: Dokumenttext
        doc_name: Name des Dokuments
    
    Returns:
        Liste von Dictionaries mit Chunks und ihren Embeddings
    """
    # Text in Chunks aufteilen
    chunks = create_text_chunks(text, chunk_size=1000, overlap=200)
    
    if not chunks:
        return []
    
    # Embeddings für alle Chunks erstellen
    with st.spinner(f"Erstelle Embeddings für {len(chunks)} Chunks..."):
        embeddings = get_embeddings(chunks)
    
    if not embeddings:
        return []
    
    # Chunks mit Embeddings kombinieren
    chunks_data = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        chunks_data.append({
            'text': chunk,
            'embedding': embedding,
            'doc_name': doc_name,
            'chunk_id': i
        })
    
    return chunks_data


# --- 3. URSPRÜNGLICHE FUNKTIONEN (AKTUALISIERT) ---

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

def ask_mistral(user_question, context=""):
    """Sendet eine Frage an die Mistral AI und gibt die Antwort zurück."""
    system_prompt = (
        "Du bist ein hilfreicher und einfühlsamer KI-Assistent. Deine Aufgabe ist es, "
        "Nutzer durch den Widerspruchsprozess für einen Pflegegrad in Deutschland zu führen. "
        "Antworte klar, strukturiert und verständlich. Gib keine Rechtsberatung, sondern nur "
        "allgemeine Informationen und Unterstützung. Wenn du auf Basis eines Dokuments antwortest, "
        "beziehe dich klar darauf und zitiere relevante Stellen."
    )
    
    messages = [ChatMessage(role="system", content=system_prompt)]
    
    if context:
        full_question = f"Basierend auf den folgenden relevanten Dokumentausschnitten:\n\n{context}\n\nBeantworte diese Frage: {user_question}"
        messages.append(ChatMessage(role="user", content=full_question))
    else:
        messages.append(ChatMessage(role="user", content=user_question))

    try:
        chat_response = client.chat(model=model, messages=messages)
        return chat_response.choices[0].message.content
    except Exception as e:
        return f"Ein Fehler ist bei der Kommunikation mit der KI aufgetreten: {e}"


# --- 4. SESSION STATE INITIALISIERUNG ---

if 'process_started' not in st.session_state:
    st.session_state.process_started = False
if 'ablehnungsdatum' not in st.session_state:
    st.session_state.ablehnungsdatum = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'uploaded_docs' not in st.session_state:
    st.session_state.uploaded_docs = {}
# NEU: Speicher für Chunks mit Embeddings
if 'document_chunks' not in st.session_state:
    st.session_state.document_chunks = []


# --- 5. AUFBAU DER STREAMLIT-OBERFLÄCHE ---

st.title("🛡️ Dein Assistent für den Pflegegrad-Widerspruch")

# Rechtlicher Hinweis
st.markdown("""
<style>
.disclaimer-box {
    background-color: #FFF3CD;
    color: #664D03;
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
        st.info("📊 Dokumente werden mit KI-Embeddings verarbeitet für bessere Suche")
        
        uploaded_file = st.file_uploader(
            "Lade Dokumente hoch (PDF)", type="pdf", key="file_uploader"
        )
        
        if uploaded_file:
            if uploaded_file.name not in st.session_state.uploaded_docs:
                with st.spinner(f"Verarbeite '{uploaded_file.name}'..."):
                    # PDF lesen
                    text = read_pdf(uploaded_file)
                    
                    if not text.startswith("Fehler"):
                        # Text speichern
                        st.session_state.uploaded_docs[uploaded_file.name] = text
                        
                        # Chunking und Embeddings erstellen
                        chunks_data = process_document_with_embeddings(text, uploaded_file.name)
                        
                        if chunks_data:
                            st.session_state.document_chunks.extend(chunks_data)
                            st.success(f"✅ '{uploaded_file.name}' verarbeitet: {len(chunks_data)} Chunks erstellt")
                        else:
                            st.warning(f"⚠️ '{uploaded_file.name}' hochgeladen, aber keine Chunks erstellt")
                    else:
                        st.error(text)
        
        # Dokumentenübersicht
        if st.session_state.uploaded_docs:
            st.write("**Hochgeladene Dokumente:**")
            
            # Zähle Chunks pro Dokument
            doc_chunk_counts = {}
            for chunk in st.session_state.document_chunks:
                doc_name = chunk['doc_name']
                doc_chunk_counts[doc_name] = doc_chunk_counts.get(doc_name, 0) + 1
            
            for doc_name in st.session_state.uploaded_docs.keys():
                chunk_count = doc_chunk_counts.get(doc_name, 0)
                st.info(f"📄 {doc_name}\n({chunk_count} Chunks)")
        
        # Statistiken
        if st.session_state.document_chunks:
            st.divider()
            st.metric("Gesamt-Chunks", len(st.session_state.document_chunks))
        
        st.divider()
        if st.button("Prozess neu starten"):
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

    # --- Hauptbereich mit Tabs ---
    tab1, tab2, tab3, tab4 = st.tabs(["Schritt-für-Schritt", "Kalender", "Chat-Assistent", "Pflegegrad-Rechner"])

    with tab1:
        st.header("Schritt-für-Schritt durch den Widerspruch")
        st.markdown("""
        Hier ist dein Fahrplan. Arbeite die Punkte nacheinander ab.
        
        - **Schritt 1: Fristwahrender Widerspruch (SOFORT)**
        - **Was?** Ein kurzes Schreiben an die Pflegekasse, in dem du formlos mitteilst: "Hiermit lege ich Widerspruch gegen den Bescheid vom [Datum des Bescheids] ein. Eine ausführliche Begründung reiche ich nach."
        - **Warum?** Damit verpasst du die wichtige 1-Monats-Frist nicht!
        - **Erledigt?**
            
        - **Schritt 2: Unterlagen sammeln (ca. 1-2 Wochen)**
        - **Was?** Sammle alle relevanten Dokumente:
        - Ärztliche Atteste, Berichte, Gutachten
        - Pflegetagebuch (sehr wichtig!)
        - Liste der benötigten Hilfsmittel
        - **Tipp:** Lade die Dokumente hier in der App hoch, um sie vom Chatbot analysieren zu lassen.
        - **Erledigt?**
            
        - **Schritt 3: Begründung formulieren (ca. 1 Woche)**
        - **Was?** Schreibe die ausführliche Begründung für deinen Widerspruch. Beschreibe genau, warum die Ablehnung oder die Einstufung falsch ist.
        - **Hilfe:** Nutze den Chat-Assistenten! Frage z.B.: "Hilf mir, eine Begründung zu formulieren. Mein Pflegetagebuch zeigt, dass ich Hilfe beim Anziehen brauche."
        - **Erledigt?**
    
        - **Schritt 4: Begründung abschicken**
        - **Was?** Schicke die ausführliche Begründung per Einschreiben an die Pflegekasse.
        - **Wichtig:** Hebe den Sendebeleg gut auf!
        - **Erledigt?**
        """)
    
    with tab2:
        st.header("Dein Fristenkalender")
        calendar_events = []
        fristen = get_fristen_info(st.session_state.ablehnungsdatum)
        for name, datum in fristen.items():
            calendar_events.append({
                "title": name, "start": datum.isoformat(), "end": datum.isoformat(),
                "allDay": True, "color": "red" if "endet" in name else "orange"
            })
        calendar_options = {
            "headerToolbar": {"left": "today prev,next", "center": "title", "right": "dayGridMonth,timeGridWeek"},
            "initialDate": st.session_state.ablehnungsdatum.isoformat(),
            "initialView": "dayGridMonth"
        }
        calendar(events=calendar_events, options=calendar_options)

    with tab3:
        st.header("Dein persönlicher Chat-Assistent")
        st.info("💡 Stelle hier deine Fragen. Die KI durchsucht automatisch deine hochgeladenen Dokumente nach relevanten Informationen!")
        
        # Chat-Historie anzeigen
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                # Zeige verwendete Quellen, falls vorhanden
                if message["role"] == "assistant" and "sources" in message:
                    with st.expander("📚 Verwendete Quellen"):
                        for source in message["sources"]:
                            st.caption(f"**{source['doc_name']}** (Relevanz: {source['similarity']:.2%})")
                            st.text(source['text'][:300] + "...")
        
        # Chat-Eingabe
        prompt = st.chat_input("Deine Frage an den Assistenten...")
        if prompt:
            # Benutzernachricht hinzufügen
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Relevante Chunks finden (wenn Dokumente vorhanden)
            context = ""
            sources = []
            
            if st.session_state.document_chunks:
                with st.spinner("Durchsuche Dokumente..."):
                    relevant_chunks = find_relevant_chunks(
                        prompt, 
                        st.session_state.document_chunks, 
                        top_k=3
                    )
                    
                    if relevant_chunks:
                        context = "Relevante Informationen aus deinen Dokumenten:\n\n"
                        for i, chunk in enumerate(relevant_chunks, 1):
                            context += f"[Quelle {i} - {chunk['doc_name']} (Relevanz: {chunk['similarity']:.2%})]:\n{chunk['text']}\n\n"
                            sources.append(chunk)
            
            # Antwort generieren
            with st.chat_message("assistant"):
                with st.spinner("Ich denke nach..."):
                    response = ask_mistral(prompt, context)
                    st.markdown(response)
                    
                    # Quellen anzeigen
                    if sources:
                        with st.expander("📚 Verwendete Quellen"):
                            for source in sources:
                                st.caption(f"**{source['doc_name']}** (Relevanz: {source['similarity']:.2%})")
                                st.text(source['text'][:300] + "...")
            
            # Antwort zur Historie hinzufügen
            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": response,
                "sources": sources
            })

    with tab4:
        st.header("Pflegegrad-Rechner (Externer Service)")
        st.warning(
            "Der Pflegegrad-Rechner von pflegehilfe.org kann aus Sicherheitsgründen nicht direkt in diese App "
            "eingebettet werden. Du kannst ihn aber über den folgenden Link in einem neuen Browser-Tab öffnen."
        )

        rechner_url = "https://www.pflegehilfe.org/service/pflegegrad-rechner/modul/1"

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
