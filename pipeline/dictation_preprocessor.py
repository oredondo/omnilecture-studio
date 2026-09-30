import re

class DictationPreprocessor:
    """Preprocesses raw speech-to-text dictation with deterministic rules for spoken punctuation and formatting commands."""

    @staticmethod
    def remove_repetition_loops(text: str) -> str:
        """Removes Whisper silence hallucination loops (identical repeated lines or repeating phrases)."""
        if not text:
            return ""
        lines = text.splitlines()
        hallucination_patterns = [
            re.compile(r"^\s*gracias\.?\s*$", re.IGNORECASE),
            re.compile(r"^\s*(?:subt[ií]tulos|transcripci[oó]n)\s+(?:por|realizados).*$", re.IGNORECASE),
        ]
        filtered = [l for l in lines if not any(p.match(l) for p in hallucination_patterns)]

        # Collapse consecutive duplicate lines
        deduped = []
        for line in filtered:
            stripped = line.strip()
            if not stripped:
                deduped.append(line)
                continue
            if deduped and deduped[-1].strip().lower() == stripped.lower():
                continue
            deduped.append(line)

        # Collapse repeating patterns of length 1 to 4 lines
        i = 0
        final_lines = []
        while i < len(deduped):
            matched = False
            for k in range(1, 5):
                if i + 2 * k <= len(deduped):
                    pattern = [l.strip().lower() for l in deduped[i : i + k]]
                    if all(not p for p in pattern):
                        continue
                    repeats = 1
                    while i + (repeats + 1) * k <= len(deduped):
                        next_pattern = [l.strip().lower() for l in deduped[i + repeats * k : i + (repeats + 1) * k]]
                        if next_pattern == pattern:
                            repeats += 1
                        else:
                            break
                    if repeats > 1:
                        final_lines.extend(deduped[i : i + k])
                        i += repeats * k
                        matched = True
                        break
            if not matched:
                final_lines.append(deduped[i])
                i += 1

        return "\n".join(final_lines)

    @staticmethod
    def process(text: str) -> str:
        if not text:
            return ""

        cleaned = DictationPreprocessor.remove_repetition_loops(text)

        # 1. Spoken Punctuation: Dos puntos
        cleaned = re.sub(r'(?i)\b(?:dos\s+puntos)\b', ':', cleaned)

        # 2. Spoken Punctuation: Punto y coma
        cleaned = re.sub(r'(?i)\b(?:punto\s+y\s+coma)\b', ';', cleaned)

        # 3. Spoken Punctuation: Punto y aparte / Nuevo párrafo
        cleaned = re.sub(r'(?i)\b(?:punto\s+y\s+aparte|nuevo\s+p[aá]rrafo)\b', '\n\n', cleaned)

        # 4. Spoken Punctuation: Punto y seguido / Punto final
        cleaned = re.sub(r'(?i)\b(?:punto\s+y\s+seguido)\b', '. ', cleaned)
        cleaned = re.sub(r'(?i)\b(?:punto\s+final)\b', '.', cleaned)

        # 5. Spoken Punctuation: Abro / Cierro paréntesis
        cleaned = re.sub(
            r'(?i)\b(?:abro|abrir)\s+par[eé]ntesis\s*(.*?)\s*(?:cierro|cerrar|cero)\s+par[eé]ntesis\b',
            r'(\1)',
            cleaned,
            flags=re.DOTALL
        )

        # 6. Spoken Punctuation: Entre paréntesis
        cleaned = re.sub(
            r'(?i)\bentre\s+par[eé]ntesis\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'(\1)',
            cleaned
        )

        # 7. Common Whisper phonetic deformities of "entre paréntesis"
        cleaned = re.sub(
            r'(?i)\b(?:de\s+p[aá]nterismo|en\s+debarentesis|un\s+trepar[eé]ntesis|improbarentes|entreparece)\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'(\1)',
            cleaned
        )

        # 8. Spoken Punctuation: Abro / Cierro comillas & Entre comillas
        cleaned = re.sub(
            r'(?i)\b(?:abro|abrir)\s+comillas\s*(.*?)\s*(?:cierro|cerrar|cero)\s+comillas\b',
            r'"\1"',
            cleaned,
            flags=re.DOTALL
        )
        cleaned = re.sub(
            r'(?i)\bentre\s+comillas\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'"\1"',
            cleaned
        )

        # 9. Spoken Structure: Subpunto / Viñeta / Guión
        cleaned = re.sub(
            r'(?i)(?:^|\n)\s*(?:subpunto|gui[oó]n|vi[ñn]eta)\s*:?\s*',
            r'\n- ',
            cleaned
        )
        cleaned = re.sub(
            r'(?i)\b(?:subpunto|gui[oó]n|vi[ñn]eta)\s*:?\s*',
            r'\n- ',
            cleaned
        )

        # 10. Spoken Formatting: Asteriscos (Double and Single)
        cleaned = re.sub(
            r'(?i)\b(?:vamos\s+a\s+poner\s+(?:aqu[ií][, \t]+)?)?(?:un\s+par\s+de\s+|dos\s+)asteriscos?\b',
            '★★',
            cleaned
        )
        cleaned = re.sub(
            r'(?i)\basteriscos?[, \t]*[,;]?[, \t]*asteriscos?\b',
            '★★',
            cleaned
        )
        cleaned = re.sub(
            r'(?i)\b(?:vamos\s+a\s+poner\s+(?:aqu[ií][, \t]+)?|a\s+poner\s+(?:en\s+este\s+punto\s+(?:tambi[eé]n\s+)?)?|pon(?:me)?\s+(?:le\s+)?|con\s+)?asteriscos?\b',
            '★',
            cleaned
        )

        # 11. Spoken Formatting: Mayúsculas
        cleaned = re.sub(r'(?i)\b(?:y\s+)?subrayado\b', '', cleaned)
        # Suffix with 'ponme': 'ponme X en letras mayusculas'
        cleaned = re.sub(
            r'(?i)\bpon(?:me)?\s+([^,.;:\n]+?)\s+en\s+(?:letras\s+)?may[uú]sculas?\b',
            lambda m: m.group(1).strip().upper(),
            cleaned
        )
        # Prefix: 'ponme en letras mayúsculas X', 'en letras mayúsculas X', 'con mayúsculares X', 'por letras mayúsculas X'
        cleaned = re.sub(
            r'(?i)\b(?:pon(?:me)?\s+en\s+(?:letras\s+)?may[uú]sculas?|en\s+(?:letras\s+)?may[uú]sculas?|con\s+may[uú]sculares|por\s+letras\s+may[uú]sculas?)\b[ \t]*[:\-]?[ \t]*([^,.;\n]+?)(?=[,.;\n]|$)',
            lambda m: m.group(1).strip().upper(),
            cleaned
        )
        # Suffix: 'X, en letras mayúsculas' or 'X en letras mayúsculas' (excluding 'pon/ponme' as X)
        cleaned = re.sub(
            r'(?i)\b(?!(?:pon|ponme|poner|p[oó]nlo)\b)([^,.;:\n]+?)[, \t]+(?:p[oó]n(?:me)?(?:lo)?\s+)?en\s+(?:letras\s+)?may[uú]sculas?\b',
            lambda m: m.group(1).strip().upper(),
            cleaned
        )

        # 12. Spoken Formatting: En negrita / Destacado / Resalta
        cleaned = re.sub(
            r'(?i)\b(?:resalta(?:r)?|destaca(?:r)?|en\s+negrita|destacado)\s+([^,.;\n]+?)(?=[,.;\n]|$)',
            r'**\1**',
            cleaned
        )

        # 13. Normalize spaces around punctuation
        cleaned = re.sub(r'\s+:', ':', cleaned)
        cleaned = re.sub(r':(?!\s|\d)', ': ', cleaned)
        cleaned = re.sub(r'\(\s+', '(', cleaned)
        cleaned = re.sub(r'\s+\)', ')', cleaned)
        cleaned = re.sub(r'(?<=\w)\(', ' (', cleaned)
        cleaned = re.sub(r'\)(?=\w)', ') ', cleaned)
        cleaned = re.sub(r'(?<=\w)\s*"\s*(?=\w)', ' "', cleaned)
        cleaned = re.sub(r'(?<=\w)\s*"\s*(?=[,.;:\s]|$)', '"', cleaned)
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        return cleaned.strip()
