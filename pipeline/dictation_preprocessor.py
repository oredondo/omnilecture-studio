import re


class DictationPreprocessor:
    """Preprocesses raw speech-to-text dictation with deterministic rules
    for spoken punctuation, formatting commands, and phonetic spelling artifacts."""

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
        filtered = [line for line in lines if not any(p.match(line) for p in hallucination_patterns)]

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
                    pattern = [line.strip().lower() for line in deduped[i:i + k]]
                    if all(not p for p in pattern):
                        continue
                    repeats = 1
                    while i + (repeats + 1) * k <= len(deduped):
                        next_slice = deduped[i + repeats * k:i + (repeats + 1) * k]
                        next_pattern = [line.strip().lower() for line in next_slice]
                        if next_pattern == pattern:
                            repeats += 1
                        else:
                            break
                    if repeats > 1:
                        final_lines.extend(deduped[i:i + k])
                        i += repeats * k
                        matched = True
                        break
            if not matched:
                final_lines.append(deduped[i])
                i += 1

        return "\n".join(final_lines)

    @staticmethod
    def normalize_spelled_sequences(text: str) -> str:
        """Normalizes Spanish spoken letter names transcribed phonetically by Whisper inside spelled words."""
        if not text:
            return ""

        cleaned = text

        # 'H-A-P-P-I, griega' -> 'H-A-P-P-Y' (Whisper splits 'i griega' into '-I, griega')
        cleaned = re.sub(
            r'(?i)\b([A-Z])[-,.\s]+I[,.\s]+(?:y\s+)?(?:grieg[a-z]+|grieban)\b',
            r'\1-Y',
            cleaned
        )
        # 'F, F y grieban' or 'A-B y griega' -> 'F, F-Y' / 'A-B-Y'
        cleaned = re.sub(
            r'(?i)\b([A-Z])[-,.\s]+(?:y\s+|i\s+)?(?:grieg[a-z]+|grieban)\b',
            r'\1-Y',
            cleaned
        )
        # 'B-U-L-L-I-Y-N y latina N-G' -> 'B-U-L-L-I-Y-N-I-N-G'
        cleaned = re.sub(
            r'(?i)\b([A-Z])[-,.\s]+(?:y\s+|i\s+)latina[-,.\s]+(?=[A-Z]\b)',
            r'\1-I-',
            cleaned
        )
        # 'B-O-R-R-E-L-L-I. Latina' -> 'B-O-R-R-E-L-L-I'
        cleaned = re.sub(
            r'(?i)(?<=-I)[,.\s]+(?:y\s+|i\s+)?latina\b',
            '',
            cleaned
        )
        # 'M-A-S-I-N-O-U-D-Oble' or 'uve doble' / 'doble uve' in spelled sequences -> '-W'
        cleaned = re.sub(
            r'(?i)(?<=[A-Z])-(?:U-?D-?Oble|D-?Oble|uve\s+doble|doble\s+uve)\b',
            '-W',
            cleaned
        )
        cleaned = re.sub(
            r'(?i)\b(?:uve\s+doble|doble\s+uve)\b',
            'W',
            cleaned
        )

        return cleaned

    @staticmethod
    def process(text: str) -> str:
        if not text:
            return ""

        cleaned = DictationPreprocessor.remove_repetition_loops(text)
        cleaned = DictationPreprocessor.normalize_spelled_sequences(cleaned)

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
        deformities_pat = (
            r'(?i)\b(?:de\s+p[aá]nterismo|en\s+debarentesis|'
            r'un\s+trepar[eé]ntesis|improbarentes|entreparece)\s+([^,.;\n]+?)(?=[,.;\n]|$)'
        )
        cleaned = re.sub(
            deformities_pat,
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
        single_ast_pat = (
            r'(?i)\b(?:vamos\s+a\s+poner\s+(?:aqu[ií][, \t]+)?|'
            r'a\s+poner\s+(?:en\s+este\s+punto\s+(?:tambi[eé]n\s+)?)?|'
            r'pon(?:me)?\s+(?:le\s+)?|con\s+)?asteriscos?\b'
        )
        cleaned = re.sub(
            single_ast_pat,
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
        # Prefix: 'ponme en letras mayúsculas X', 'en letras mayúsculas X', etc.
        upper_prefix_pat = (
            r'(?i)\b(?:pon(?:me)?\s+en\s+(?:letras\s+)?may[uú]sculas?|'
            r'en\s+(?:letras\s+)?may[uú]sculas?|con\s+may[uú]sculares|'
            r'por\s+letras\s+may[uú]sculas?)\b[ \t]*[:\-]?[ \t]*([^,.;\n]+?)(?=[,.;\n]|$)'
        )
        cleaned = re.sub(
            upper_prefix_pat,
            lambda m: m.group(1).strip().upper(),
            cleaned
        )
        # Suffix: 'X, en letras mayúsculas' or 'X en letras mayúsculas' (excluding 'pon/ponme' as X)
        upper_suffix_pat = (
            r'(?i)\b(?!(?:pon|ponme|poner|p[oó]nlo)\b)([^,.;:\n]+?)'
            r'[, \t]+(?:p[oó]n(?:me)?(?:lo)?\s+)?en\s+(?:letras\s+)?may[uú]sculas?\b'
        )
        cleaned = re.sub(
            upper_suffix_pat,
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
