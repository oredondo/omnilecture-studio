import re

class DictationPreprocessor:
    """Preprocesses raw speech-to-text dictation with deterministic rules for spoken punctuation and formatting commands."""

    @staticmethod
    def process(text: str) -> str:
        if not text:
            return ""

        cleaned = text

        # 1. Spoken Punctuation: Colon / Dos puntos
        cleaned = re.sub(r'(?i)\b(?:dos\s+puntos|colon)\b', ':', cleaned)

        # 2. Spoken Punctuation: Semicolon / Punto y coma
        cleaned = re.sub(r'(?i)\b(?:punto\s+y\s+coma|semicolon)\b', ';', cleaned)

        # 3. Spoken Punctuation: New paragraph / Punto y aparte / Nuevo párrafo
        cleaned = re.sub(r'(?i)\b(?:punto\s+y\s+aparte|nuevo\s+p[aá]rrafo|new\s+paragraph)\b', '\n\n', cleaned)

        # 4. Spoken Punctuation: Period / Punto y seguido / Punto final
        cleaned = re.sub(r'(?i)\b(?:punto\s+y\s+seguido)\b', '. ', cleaned)
        cleaned = re.sub(r'(?i)\b(?:punto\s+final|full\s+stop)\b', '.', cleaned)

        # 5. Spoken Punctuation: Open / Close parentheses (Abro / Cierro paréntesis)
        cleaned = re.sub(
            r'(?i)\b(?:abro|abrir|open)\s+(?:par[eé]ntesis|parenthesis|bracket)\s*(.*?)\s*(?:cierro|cerrar|cero|close)\s+(?:par[eé]ntesis|parenthesis|bracket)\b',
            r'(\1)',
            cleaned,
            flags=re.DOTALL
        )

        # 6. Spoken Punctuation: In parentheses / Entre paréntesis
        cleaned = re.sub(
            r'(?i)\b(?:entre\s+par[eé]ntesis|in\s+parentheses)\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'(\1)',
            cleaned
        )

        # 7. Common Whisper phonetic deformities of "entre paréntesis"
        cleaned = re.sub(
            r'(?i)\b(?:de\s+p[aá]nterismo|en\s+debarentesis|un\s+trepar[eé]ntesis|improbarentes|entreparece)\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'(\1)',
            cleaned
        )

        # 8. Spoken Punctuation: Quotes / Comillas
        cleaned = re.sub(
            r'(?i)\b(?:abro|abrir|open)\s+(?:comillas|quotes?)\s*(.*?)\s*(?:cierro|cerrar|cero|close)\s+(?:comillas|quotes?)\b',
            r'"\1"',
            cleaned,
            flags=re.DOTALL
        )
        cleaned = re.sub(
            r'(?i)\b(?:entre\s+comillas|in\s+quotes?)\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'"\1"',
            cleaned
        )

        # 9. Spoken Structure: Sub-item / Bullet / Dash / Subpunto / Viñeta / Guión
        cleaned = re.sub(
            r'(?i)(?:^|\n)\s*(?:subpunto|gui[oó]n|vi[ñn]eta|sub-?item|bullet|dash)\s*:?\s*',
            r'\n- ',
            cleaned
        )
        cleaned = re.sub(
            r'(?i)\b(?:subpunto|gui[oó]n|vi[ñn]eta|sub-?item|bullet|dash)\s*:?\s*',
            r'\n- ',
            cleaned
        )

        # 10. Spoken Formatting: In bold / En negrita / Destacado
        cleaned = re.sub(
            r'(?i)\b(?:en\s+negrita|destacado|in\s+bold)\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'**\1**',
            cleaned
        )

        # 11. Normalize spaces around punctuation
        cleaned = re.sub(r'\s+:', ':', cleaned)
        cleaned = re.sub(r':(?!\s|\d)', ': ', cleaned)
        cleaned = re.sub(r'\(\s+', '(', cleaned)
        cleaned = re.sub(r'\s+\)', ')', cleaned)
        cleaned = re.sub(r'(?<=\w)\(', ' (', cleaned)
        cleaned = re.sub(r'\)(?=\w)', ') ', cleaned)
        cleaned = re.sub(r'(?<=\w)\s*"\s*(?=\w)', ' "', cleaned)
        cleaned = re.sub(r'(?<=\w)\s*"\s*(?=[,.;:\s]|$)', '"', cleaned)
        cleaned = re.sub(r':\s*\n', ':\n', cleaned)
        cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        return cleaned.strip()
