import streamlit as st
from streamlit_calendar import calendar
import datetime
import os
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
import PyPDF2
# NEU: Import für die iframe-Komponente, die wir für den Rechner brauchen
import streamlit.components.v1 as components

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

# --- 3. SESSION STATE INITIALISIERUNG ---

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

# =======================================================================
# NEU: DAUERHAFTER RECHTLICHER HINWEIS
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
                with st.spinner(f"Lese '{uploaded_file.name}'..."):
                    text = read_pdf(uploaded_file)
                    st.session_state.uploaded_docs[uploaded_file.name] = text
                    st.success(f"'{uploaded_file.name}' wurde erfolgreich geladen.")
        
        if st.session_state.uploaded_docs:
            st.write("Hochgeladene Dokumente:")
            for doc_name in st.session_state.uploaded_docs.keys():
                st.info(f"📄 {doc_name}")
        
        st.divider()
        if st.button("Prozess neu starten"):
            for key in st.session_state.keys():
                del st.session_state[key]
            st.rerun()

    # --- Hauptbereich mit Tabs ---
    # ANGEPASST: Vier Tabs, inklusive des Pflegegrad-Rechners
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
        st.info("Stelle hier deine Fragen zum Prozess oder zu deinen hochgeladenen Dokumenten.")
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        prompt = st.chat_input("Deine Frage an den Assistenten...")
        if prompt:
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            context = ""
            if st.session_state.uploaded_docs:
                context += "Folgende Dokumente wurden hochgeladen:\n"
                for name, text in st.session_state.uploaded_docs.items():
                    summary = (text[:2000] + '...') if len(text) > 2000 else text
                    context += f"\n--- Dokument: {name} ---\n{summary}\n"
            
            with st.chat_message("assistant"):
                with st.spinner("Ich denke nach..."):
                    response = ask_mistral(prompt, context)
                    st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})

    # =======================================================================
    # NEU: TAB FÜR DEN INTERAKTIVEN PFLEGEGRAD-RECHNER
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
    # =======================================================================

import streamlit as st
from streamlit_calendar import calendar
import datetime
import os
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
import PyPDF2
# Import für die components (wird für den Button-Link im Rechner-Tab verwendet)
import streamlit.components.v1 as components

# --- 1. GRUNDEINSTELLUNGEN & INITIALISIERUNG ---

# Konfiguriere die Streamlit-Seite (sollte immer als Erstes aufgerufen werden)
st.set_page_config(
    page_title="Pflegegrad Widerspruchs-Assistent",
    page_icon="🛡️",
    layout="wide"
)

# Lade den API-Schlüssel aus den Streamlit Secrets (für Deployment)
api_key = st.secrets.get("MISTRAL_API_KEY")

# Fallback auf Umgebungsvariablen (für lokale Entwicklung)
if not api_key:
    api_key = os.getenv("MISTRAL_API_KEY")

# Wichtige Prüfung, ob der API-Schlüssel vorhanden ist
if not api_key:
    st.error("Mistral API-Schlüssel nicht gefunden! Bitte konfiguriere das 'MISTRAL_API_KEY' Secret in den Einstellungen deiner App.")
    st.stop() # App anhalten, wenn kein Schlüssel da ist

# Initialisiere den Mistral AI Client (nur einmal)
model = "mistral-large-latest"
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
    else:
        full_question = user_question
    messages.append(ChatMessage(role="user", content=full_question))
    try:
        chat_response = client.chat(model=model, messages=messages)
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


# --- 4. AUFBAU DER STREAMLIT-OBERFLÄCHE ---

st.title("🛡️ Dein Assistent für den Pflegegrad-Widerspruch")

# DAUERHAFTER RECHTLICHER HINWEIS
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
    <strong>Wichtiger Hinweis:</strong> Dieser Assistent bietet allgemeine Informationen und Unterstützung. Er stellt <strong>keine Rechtsberatung</strong> dar und kann die individuelle Beratung durch einen Fachexperten (z.B. Anwalt, Pflegeberatung, Sozialverband) nicht ersetzen.
</div>
""", unsafe_allow_html=True)

st.markdown("Wir führen dich Schritt für Schritt durch den Prozess. Einfach, klar und strukturiert.")

# --- ANSICHT 1: STARTBILDSCHIRM ---
if not st.session_state.process_started:
    st.header("Schritt 1: Prozess starten und Fristen setzen")
    st.info("Der Widerspruch muss in der Regel **innerhalb eines Monats** nach Erhalt des Ablehnungsbescheids bei der Pflegekasse eingehen.")
    
    selected_date = st.date_input("Datum des Ablehnungsbescheids:", value=None, help="Wähle das Datum, an dem du den Brief von der Pflegekasse erhalten hast.")
    if st.button("Prozess starten", type="primary"):
        if selected_date:
            st.session_state.ablehnungsdatum = selected_date
            st.session_state.process_started = True
            st.rerun()
        else:
            st.warning("Bitte wähle zuerst das Datum aus.")

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
            st.metric(label="Tage bis Fristende für Widerspruch", value=f"{tage_verbleibend} Tage", delta=f"Endet am {widerspruchsfrist_ende.strftime('%d.%m.%Y')}", delta_color="inverse")
        
        st.divider()
        st.header("Dokumente verwalten")
        uploaded_file = st.file_uploader("Lade Dokumente hoch (PDF)", type="pdf")
        if uploaded_file:
            if uploaded_file.name not in st.session_state.uploaded_docs:
                with st.spinner(f"Lese '{uploaded_file.name}'..."):
                    text = read_pdf(uploaded_file)
                    st.session_state.uploaded_docs[uploaded_file.name] = text
                    st.success(f"'{uploaded_file.name}' geladen.")
        
        if st.session_state.uploaded_docs:
            st.write("Hochgeladene Dokumente:")
            for doc_name in st.session_state.uploaded_docs.keys(): st.info(f"📄 {doc_name}")
        
        st.divider()
        if st.button("Prozess neu starten"):
            for key in st.session_state.keys(): del st.session_state[key]
            st.rerun()

    # --- Hauptbereich mit Tabs ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Schritt-für-Schritt", "Kalender", "Chat-Assistent", "Pflegegrad-Rechner", "Formulierungshilfe"])

    with tab1:
        st.header("Schritt-für-Schritt durch den Widerspruch")
        # Inhalt wurde leicht gekürzt für bessere Übersicht
        st.markdown("""
        - **Schritt 1:** Fristwahrender Widerspruch (SOFORT)
        - **Schritt 2:** Unterlagen sammeln (Ärzte, Pflegetagebuch)
        - **Schritt 3:** Begründung formulieren (Hilfe von Tabs 3 & 5)
        - **Schritt 4:** Begründung per Einschreiben abschicken
        """)

    with tab2:
        st.header("Dein Fristenkalender")
        fristen = get_fristen_info(st.session_state.ablehnungsdatum)
        calendar_events = [{"title": name, "start": datum.isoformat(), "end": datum.isoformat(), "allDay": True, "color": "red" if "endet" in name else "orange"} for name, datum in fristen.items()]
        calendar(events=calendar_events, options={"initialView": "dayGridMonth"})

    with tab3:
        st.header("Dein persönlicher Chat-Assistent")
        st.info("Stelle hier deine Fragen zum Prozess oder zu deinen Dokumenten.")
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
        
        if prompt := st.chat_input("Deine Frage..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            
            context = "\n".join([f"--- DOKUMENT: {name} ---\n{text[:2000]}..." for name, text in st.session_state.uploaded_docs.items()])
            with st.chat_message("assistant"):
                with st.spinner("Denke..."):
                    response = ask_mistral(prompt, context)
                    st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})

    with tab4:
        st.header("Pflegegrad-Rechner (Externer Service)")
        st.warning("Der Pflegegrad-Rechner von pflegehilfe.org kann aus Sicherheitsgründen nicht direkt eingebettet werden. Du kannst ihn aber über den folgenden Link in einem neuen Browser-Tab öffnen.")
        rechner_url = "https://www.pflegehilfe.org/service/pflegegrad-rechner/modul/1"
        st.markdown(f'''
        <a href="{rechner_url}" target="_blank" style="display: inline-block; padding: 1em 2em; background-color: #0068c9; color: white; text-align: center; text-decoration: none; border-radius: 0.5rem; font-size: 1.1em; font-weight: bold; margin-top: 1em;">
            Zum Pflegegrad-Rechner wechseln
        </a>
        ''', unsafe_allow_html=True)
        st.info("Klicke auf den Button, fülle die Fragen auf der externen Seite aus und komm hierher zurück, um mit den Informationen weiterzuarbeiten.")
    
    # =======================================================================
    # NEU: TAB FÜR DIE WIDERSPRUCHS-FORMULIERUNGSHILFE
    # =======================================================================
    with tab5:
        st.header("📝 Formulierungshilfe für deine Widerspruchsbegründung")
        st.info("Nutze diese Bausteine und den Generator, um eine starke und persönliche Begründung zu erstellen.")

        st.subheader("1. Vorlage für den fristwahrenden Widerspruch")
        st.markdown("Dies ist der erste, kurze Widerspruch, den du sofort abschickst.")
        
        frist_widerspruch_text = f"""
        **[Dein Name]**\n
        **[Deine Adresse]**\n
        **[Deine Versichertennummer]**\n\n
        An die\n
        **[Name deiner Pflegekasse]**\n
        **[Adresse deiner Pflegekasse]**\n\n
        **Datum: {datetime.date.today().strftime('%d.%m.%Y')}**\n\n
        **Betreff: Widerspruch gegen den Bescheid vom {st.session_state.ablehnungsdatum.strftime('%d.%m.%Y')}, Aktenzeichen/Versichertennummer: [Dein Aktenzeichen]**\n\n
        Sehr geehrte Damen und Herren,\n\n
        hiermit lege ich gegen den oben genannten Bescheid fristwahrend Widerspruch ein.\n\n
        Eine ausführliche Begründung werde ich Ihnen in Kürze nachreichen.\n\n
        Ich bitte um eine schriftliche Bestätigung über den Eingang dieses Widerspruchs.\n\n
        Mit freundlichen Grüßen\n\n
        ________________________\n
        (Unterschrift)
        """
        st.code(frist_widerspruch_text, language="text")
        st.download_button("Vorlage herunterladen (.txt)", frist_widerspruch_text, file_name="fristwahrender_widerspruch.txt")
        
        st.divider()

        st.subheader("2. Generator für die ausführliche Begründung")
        st.markdown("Beschreibe hier in Stichpunkten, was deiner Meinung nach im Gutachten falsch bewertet wurde. Der Generator erstellt daraus einen ausformulierten Text.")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Beispiele für deine Stichpunkte:**")
            st.markdown(
                "- *Hilfe beim Anziehen wird täglich benötigt, nicht nur 2x pro Woche.*\n"
                "- *Treppensteigen ist ohne Hilfe gar nicht mehr möglich.*\n"
                "- *Nachts muss ich mehrmals auf die Toilette begleitet werden, das wurde nicht berücksichtigt.*\n"
                "- *Das MDK-Gutachten hat meine psychische Belastung (Depression) ignoriert.*"
            )

        with col2:
            user_reasons = st.text_area(
                "Deine Gründe in Stichpunkten (einer pro Zeile):",
                height=200,
                placeholder="z.B. Tägliche Hilfe beim Duschen nötig\nKann Mahlzeiten nicht selbst zubereiten\n..."
            )

        if st.button("Begründungstext erstellen", type="primary"):
            if user_reasons:
                reasons_list = [f"- {reason.strip()}" for reason in user_reasons.split('\n') if reason.strip()]
                reasons_formatted = "\n".join(reasons_list)

                begruendung_text = f"""
                **[Dein Name]**\n
                **[Deine Adresse]**\n\n
                An die\n
                **[Name deiner Pflegekasse]**\n
                **[Adresse deiner Pflegekasse]**\n\n
                **Datum: {datetime.date.today().strftime('%d.%m.%Y')}**\n\n
                **Betreff: Begründung zum Widerspruch vom [Datum des ersten Schreibens], Bescheid vom {st.session_state.ablehnungsdatum.strftime('%d.%m.%Y')}**\n\n
                Sehr geehrte Damen und Herren,\n\n
                bezugnehmend auf meinen Widerspruch vom [Datum des ersten Schreibens] möchte ich diesen wie folgt begründen:\n\n
                Die im MDK-Gutachten getroffenen Feststellungen spiegeln meinen tatsächlichen Pflege- und Unterstützungsbedarf nur unzureichend wider. Insbesondere in den folgenden Punkten weicht meine Alltagssituation erheblich von der Darstellung im Gutachten ab:\n\n
                {reasons_formatted}\n\n
                Diese Punkte zeigen, dass meine Selbstständigkeit weitaus stärker eingeschränkt ist, als im Gutachten angenommen wurde. Der tatsächliche tägliche Hilfebedarf rechtfertigt eine Einstufung in einen höheren Pflegegrad.\n\n
                Zur weiteren Untermauerung meiner Angaben lege ich [z.B. ein aktuelles Pflegetagebuch / einen Arztbericht von Dr. Mustermann] bei.\n\n
                Ich bitte Sie daher, Ihre Entscheidung auf Basis dieser ergänzenden Informationen erneut zu prüfen und den Pflegegrad entsprechend anzupassen. Für eine erneute Begutachtung stehe ich selbstverständlich zur Verfügung.\n\n
                Mit freundlichen Grüßen\n\n
                ________________________\n
                (Unterschrift)
                """
                st.subheader("Deine generierte Begründung")
                st.code(begruendung_text, language="text")
                st.download_button("Begründung herunterladen (.txt)", begruendung_text, file_name="widerspruch_begruendung.txt")
            else:
                st.warning("Bitte gib zuerst deine Gründe in das Textfeld ein.")

