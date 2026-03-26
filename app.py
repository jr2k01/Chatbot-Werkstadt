import streamlit as st
from streamlit_calendar import calendar
import datetime
import os
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
import PyPDF2

# NEUER Code für GitHub Secrets (und lokale Entwicklung, wenn Variable gesetzt)
import os
import streamlit as st # Streamlit muss für st.secrets importiert sein

# --- 1. GRUNDEINSTELLUNGEN & INITIALISIERUNG ---

# Versuche, den Schlüssel aus den Streamlit Secrets zu laden (für Deployment)
api_key = st.secrets.get("MISTRAL_API_KEY")

# Fallback auf Umgebungsvariablen (für GitHub Codespaces/Actions)
if not api_key:
    api_key = os.getenv("MISTRAL_API_KEY")

# **WICHTIGE PRÜFUNG HINZUFÜGEN**
if not api_key:
    st.error("Mistral API-Schlüssel nicht gefunden! Bitte konfiguriere das 'MISTRAL_API_KEY' Secret in den Einstellungen deiner App.")
    st.stop() # App anhalten, wenn kein Schlüssel da ist

# Initialisiere den Mistral Client
client = MistralClient(api_key=api_key)

# Konfiguriere die Streamlit-Seite
st.set_page_config(
    page_title="Pflegegrad Widerspruchs-Assistent",
    page_icon="🛡️",
    layout="wide"
)

# Initialisiere den Mistral AI Client
model = "mistral-large-latest"  # Oder ein anderes Modell deiner Wahl
client = MistralClient(api_key=api_key)


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

def ask_mistral(user_question, context=""):
    """Sendet eine Frage an die Mistral AI und gibt die Antwort zurück."""
    system_prompt = (
        "Du bist ein hilfreicher und einfühlsamer KI-Assistent. Deine Aufgabe ist es, "
        "Nutzer durch den Widerspruchsprozess für einen Pflegegrad in Deutschland zu führen. "
        "Antworte klar, strukturiert und verständlich. Gib keine Rechtsberatung, sondern nur "
        "allgemeine Informationen und Unterstützung. Wenn du auf Basis eines Dokuments antwortest, "
        "beziehe dich klar darauf."
    )
    
    messages = [ChatMessage(role="system", content=system_prompt)]
    
    if context:
        full_question = f"Basierend auf dem folgenden Dokumentkontext:\n---\n{context}\n---\nBeantworte diese Frage: {user_question}"
        messages.append(ChatMessage(role="user", content=full_question))
    else:
        messages.append(ChatMessage(role="user", content=user_question))

    try:
        chat_response = client.chat(model=model, messages=messages)
        return chat_response.choices[0].message.content
    except Exception as e:
        return f"Ein Fehler ist bei der Kommunikation mit der KI aufgetreten: {e}"

# --- 3. SESSION STATE INITIALISIERUNG (Daten zwischen Interaktionen speichern) ---

if 'process_started' not in st.session_state:
    st.session_state.process_started = False
if 'ablehnungsdatum' not in st.session_state:
    st.session_state.ablehnungsdatum = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'uploaded_docs' not in st.session_state:
    st.session_state.uploaded_docs = {}


# --- 4. AUFBAU DER STREAMLIT-OBERFLÄCHE ---

st.title("🛡️ Dein Assistent für den Pflegegrad-Widerspruch")
st.markdown("Wir führen dich Schritt für Schritt durch den Prozess. Einfach, klar und strukturiert.")

# --- ANSICHT 1: STARTBILDSCHIRM ---
if not st.session_state.process_started:
    st.header("Schritt 1: Prozess starten und Fristen setzen")
    st.info(
        "Der Widerspruch muss in der Regel **innerhalb eines Monats** nach Erhalt des "
        "Ablehnungsbescheids bei der Pflegekasse eingehen. Trage hier das Datum ein, "
        "an dem du den Bescheid erhalten hast."
    )
    
    # Datumseingabe
    selected_date = st.date_input(
        "Datum des Ablehnungsbescheids:",
        value=None, # Standardwert None, damit es klar ist, dass nichts ausgewählt wurde
        min_value=datetime.date.today() - datetime.timedelta(days=365),
        max_value=datetime.date.today(),
        help="Wähle das Datum, an dem du den Brief von der Pflegekasse erhalten hast."
    )

    if st.button("Prozess starten", type="primary"):
        if selected_date:
            st.session_state.ablehnungsdatum = selected_date
            st.session_state.process_started = True
            st.rerun() # Seite neu laden, um die Hauptansicht anzuzeigen
        else:
            st.warning("Bitte wähle zuerst das Datum des Ablehnungsbescheids aus.")

# --- ANSICHT 2: HAUPTANSICHT NACH PROZESSSTART ---
else:
    # --- Linke Seitenleiste für Navigation und Status ---
    with st.sidebar:
        st.header("Dein Status")
        
        # Fristen anzeigen
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

        # Dokumenten-Upload
        st.header("Dokumente verwalten")
        uploaded_file = st.file_uploader(
            "Lade Dokumente hoch (PDF)",
            type="pdf",
            accept_multiple_files=False, # Erstmal nur eine Datei zur Vereinfachung
            key="file_uploader"
        )
        if uploaded_file:
            if uploaded_file.name not in st.session_state.uploaded_docs:
                with st.spinner(f"Lese '{uploaded_file.name}'..."):
                    text = read_pdf(uploaded_file)
                    st.session_state.uploaded_docs[uploaded_file.name] = text
                    st.success(f"'{uploaded_file.name}' wurde erfolgreich geladen.")
        
        # Anzeige der hochgeladenen Dokumente
        if st.session_state.uploaded_docs:
            st.write("Hochgeladene Dokumente:")
            for doc_name in st.session_state.uploaded_docs.keys():
                st.info(f"📄 {doc_name}")
        
        st.divider()
        if st.button("Prozess neu starten"):
            # Alle Session-Daten zurücksetzen
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

    # --- Hauptbereich mit Tabs ---
    tab1, tab2, tab3 = st.tabs(["Schritt-für-Schritt Anleitung", "Kalender", "Chat-Assistent"])

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
        
        # Kalender-Events erstellen
        calendar_events = []
        for name, datum in fristen.items():
            calendar_events.append({
                "title": name,
                "start": datum.isoformat(),
                "end": datum.isoformat(),
                "allDay": True, # Ganztägiges Event
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

        # Kalender anzeigen
        calendar(events=calendar_events, options=calendar_options)

    with tab3:
        st.header("Dein persönlicher Chat-Assistent")
        st.info("Stelle hier deine Fragen zum Prozess oder zu deinen hochgeladenen Dokumenten.")

        # Chat-Verlauf anzeigen
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        # Nutzereingabe
        prompt = st.chat_input("Deine Frage an den Assistenten...")
        if prompt:
            # Eingabe des Nutzers zum Verlauf hinzufügen und anzeigen
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # Kontext aus Dokumenten für die KI vorbereiten
            context = ""
            if st.session_state.uploaded_docs:
                context += "Folgende Dokumente wurden hochgeladen:\n"
                for name, text in st.session_state.uploaded_docs.items():
                    # Nur einen Ausschnitt des Textes verwenden, um das Token-Limit nicht zu sprengen
                    summary = (text[:2000] + '...') if len(text) > 2000 else text
                    context += f"\n--- Dokument: {name} ---\n{summary}\n"
            
            # KI-Antwort generieren und anzeigen
            with st.chat_message("assistant"):
                with st.spinner("Ich denke nach..."):
                    response = ask_mistral(prompt, context)
                    st.markdown(response)
            
            # KI-Antwort zum Verlauf hinzufügen
            st.session_state.chat_history.append({"role": "assistant", "content": response})
