from .base_module import BaseModule
from typing import Dict, Any, Set
import requests
import re


class DuplicateDetector(BaseModule):
    def process(self, document_id: int, file_path: str, document_data: Dict[str, Any]) -> None:
        """
        Duplikat-Erkennung via ChromaDB Embedding-Ähnlichkeit.
        Zusätzlich abgesichert durch Metadaten-Checks (Datum, Beträge, Features),
        um False Positives bei Formularen zu vermeiden.
        Konsolidierte Logik aus test/processors.py (Best-of-Class).
        """
        if not self.config['modules']['duplicate_detector'].get('enabled', False):
            return

        print(f"running duplicate detection for {document_id}")
        
        current_content = document_data.get('content', '')
        if not current_content or len(current_content) < 50:
            print(f"Document {document_id} has too little content for duplicate check.")
            return

        # ChromaDB Client initialisieren
        try:
            from .chroma_client import ChromaClient
            chroma = ChromaClient()
        except Exception as e:
            print(f"ChromaDB nicht verfügbar, überspringe Duplikat-Check: {e}")
            return

        # Ähnlichkeitssuche via Embedding
        threshold = self.config['modules']['duplicate_detector'].get('threshold', 0.85)
        print(f"DEBUG: Searching ChromaDB (threshold={threshold})...")
        
        similar = chroma.find_similar(
            content=current_content,
            threshold=threshold,
            exclude_id=int(document_id),
            n_results=25
        )
        
        if similar:
            for best in similar:
                similarity = best['similarity']
                candidate_id = best['id']
                
                print(f"🔍 Checking Candidate {candidate_id} (Similarity: {similarity:.2f})...")
    
                # --- Safety Check: Metadaten-Vergleich ---
                is_confirmed_duplicate = True
                
                try:
                    candidate_doc = self.paperless.get_document(candidate_id)
                    if not candidate_doc:
                         print(f"⚠️ Candidate {candidate_id} not found in Paperless (Stale Vector). Skipping.")
                         continue

                    candidate_content = candidate_doc.get('content', '') if candidate_doc else ''
    
                    if candidate_content:
                        # 1. Feature-Extraktion
                        dates_current = self._extract_dates(current_content)
                        dates_candidate = self._extract_dates(candidate_content)
                        
                        feats_current = self._extract_features(current_content)
                        feats_candidate = self._extract_features(candidate_content)
    
                        # --- Priority 1: Datums-Check (Jaccard) ---
                        date_mismatch = False
                        
                        if dates_current and dates_candidate:
                            # Toleranz-Check: Bei extrem hoher Embedding-Ähnlichkeit (> 0.98) 
                            # sind wir bei Datums-Abweichungen (OCR Fehler möglich!) etwas gnädiger.
                            date_threshold = 0.8
                            if similarity > 0.98:
                                date_threshold = 0.5
                                print(f"ℹ️ High Similarity ({similarity:.2f}) -> Lowering date threshold to {date_threshold}")

                            jaccard_dates = self.calculate_jaccard(dates_current, dates_candidate)
                            if jaccard_dates < date_threshold:
                                print(f"⚠️ SAFETY CHECK FAILED: Dates do not match (Jaccard: {jaccard_dates:.2f}).")
                                print(f"   Current: {dates_current}")
                                print(f"   Candidate: {dates_candidate}")
                                is_confirmed_duplicate = False
                                date_mismatch = True
                            else:
                                print(f"✅ Safety Check: Dates match (Jaccard: {jaccard_dates:.2f})")
                        else:
                                print("ℹ️ Safety Check: No dates extracted in one or both docs. Skipping loose date check.")
    
                        # --- Priority 2: Feature-Check (IDs, IBANs) ---
                        if is_confirmed_duplicate and feats_current and feats_candidate:
                            feat_threshold = 0.8
                            if similarity > 0.98:
                                feat_threshold = 0.5
                            
                            jaccard_feats = self.calculate_jaccard(feats_current, feats_candidate)
                            
                            if jaccard_feats < feat_threshold:
                                print(f"⚠️ SAFETY CHECK FAILED: Features (IDs/IBANs) do not match (Jaccard: {jaccard_feats:.2f}).")
                                is_confirmed_duplicate = False
                            else:
                                print(f"✅ Safety Check: Features match (Jaccard: {jaccard_feats:.2f})")
    
                        # --- Priority 3: Word-Level Fallback ---
                        if is_confirmed_duplicate:
                            len_ratio = len(current_content) / len(candidate_content) if len(candidate_content) > 0 else 0
                            if len_ratio < 0.8 or len_ratio > 1.25:
                                    print(f"⚠️ SAFETY CHECK FAILED: Significant length difference (Ratio: {len_ratio:.2f})")
                                    is_confirmed_duplicate = False
    
                            elif similarity > 0.92 and not date_mismatch: 
                                    pass 
    
                            word_sim = self._check_word_similarity(current_content, candidate_content)
                            print(f"ℹ️ Safety Check Words: Jaccard={word_sim:.2f}")
                            
                            base_req = 0.85
                            if len(current_content) < 1500: base_req = 0.90
                            
                            if similarity > 0.95:
                                base_req -= 0.10 
                            
                            if word_sim < base_req:
                                    print(f"⚠️ SAFETY CHECK FAILED: Word-Similarity too low ({word_sim:.2f} < {base_req}). Content differs.")
                                    is_confirmed_duplicate = False
    
                    else:
                        print(f"⚠️ Warning: Could not retrieve content for candidate {candidate_id}. Document might be deleted. Skipping Safety Check.")
                        continue 
    
                except Exception as e:
                    print(f"⚠️ Error during Safety Check: {e}. Skipping candidate.")
                    continue
    
                if is_confirmed_duplicate:
                    print(f"✅ DUPLICATE CONFIRMED: {candidate_id}")
                    self.handle_duplicate(document_id, candidate_id, similarity)
                    return 
                else:
                    print(f"ℹ️ Duplicate rejected by Safety Check.")

        else:
            print(f"Kein Duplikat gefunden ({chroma.count()} Dokumente in ChromaDB)")

    def _extract_dates(self, text: str) -> Set[str]:
        """Extrahiert Datumsangaben (DD.MM.YYYY, MM/YYYY etc.) aus dem Text."""
        # Regex für gängige deutsche Datumsformate (erweitert aus test/processors.py)
        date_patterns = [
            r'(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{2,4})',  # 12.12.2023
            r'(\d{1,2})\.\s?(Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\w*\s?(\d{2,4})', # 12. Mai 2023
            r'(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})' # Mai 2023
        ]
        
        found_dates = set()
        map_months = {
            "Januar": "01", "Februar": "02", "März": "03", "April": "04", "Mai": "05", "Juni": "06",
            "Juli": "07", "August": "08", "September": "09", "Oktober": "10", "November": "11", "Dezember": "12"
        }

        for pattern in date_patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                try:
                    if len(m) == 3 and m[0].isdigit(): 
                        day, month, year_str = m
                        year = int(year_str)
                        normalized = f"{int(day)}.{int(month)}.{year if year > 100 else (year+2000 if year < 50 else year+1900)}"
                        found_dates.add(normalized)
                    elif len(m) == 2 and not m[0].isdigit():
                        month_name, year_str = m
                        year = int(year_str)
                        month_num = map_months.get(month_name, "00")
                        if month_num != "00":
                             found_dates.add(f"01.{month_num}.{year}")
                except:
                    continue
        return found_dates

    def _extract_features(self, text: str) -> Set[str]:
        """Extrahiert signifikante Merkmale (IDs, IBANs, Mails, Beträge)."""
        found = set()
        
        # 1. Geldbeträge
        amounts = re.findall(r'\b\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b', text)
        found.update(amounts)
        
        # 2. IBANs (Locker)
        ibans_loose = re.findall(r'DE\s?\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}', text)
        if ibans_loose:
             found.update([iban.replace(" ", "") for iban in ibans_loose])

        # 3. E-Mails
        mails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)
        found.update(mails)

        # 4. Spezifische IDs (Rechnungs-Nr etc.)
        id_patterns = [
            r'(?:Rechnungs|Kunden|Auftrags|Bestell|Vorgangs|Leistungs|Personal|Mitglieds)[-\s]?(?:Nr|Nummer|ID)[\.:\s]*([\w\-\/]{3,})',
            r'(?:Mandatsreferenz|Gläubiger-ID)[\.:\s]*([\w\-\/]{5,})',
            r'(?:Beleg|Dokument)[-\s]?(?:Nr)[\.:\s]*([\w\-\/]{3,})'
        ]
        for p in id_patterns:
            matches = re.findall(p, text, re.IGNORECASE)
            found.update(matches)

        return found

    def _check_word_similarity(self, text1: str, text2: str) -> float:
        """Vergleicht die Wortmengen zweier Texte (Jaccard)."""
        words1 = set(w for w in re.findall(r'\w+', text1.lower()) if len(w) > 2)
        words2 = set(w for w in re.findall(r'\w+', text2.lower()) if len(w) > 2)
        if not words1 or not words2: return 0.0
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        return len(intersection) / len(union) if union else 0.0

    def calculate_jaccard(self, set_a: Set[str], set_b: Set[str]) -> float:
        """Berechnet den Jaccard-Index (Intersection over Union)."""
        if not set_a and not set_b:
            return 0.0
        intersection = len(set_a.intersection(set_b))
        union = len(set_a.union(set_b))
        return intersection / union if union > 0 else 0.0

    def handle_duplicate(self, doc_id: int, original_id: int, similarity: float):
        """Markiert das Duplikat mit Note und Tag."""
        # Original-Titel holen
        original_title = f"Dokument #{original_id}"
        try:
            orig_doc = self.paperless.get_document(original_id)
            if orig_doc:
                original_title = orig_doc.get('title', original_title)
        except Exception:
            pass
        
        # Link zum Original bauen
        original_link = self.paperless.get_document_link(original_id)
        compare_link = self.paperless.get_comparison_link(original_id, doc_id)
        
        note_text = (
            f"⚠️ Mögliches Duplikat!\n"
            f"Original: {original_title} (ID: {original_id})\n"
            f"Ähnlichkeit: {similarity:.0%}\n\n"
            f"Kopieren Sie diesen Link in den Browser für einen Vergleich:\n"
            f"{compare_link}"
        )
        
        # Note hinzufügen
        try:
            url = f"{self.paperless.api_url}/documents/{doc_id}/notes/"
            payload = {"note": note_text}
            response = requests.post(url, headers=self.paperless.headers, json=payload)
            if response.status_code in (200, 201):
                print(f"✅ Note added to document {doc_id}")
            else:
                print(f"Note API returned {response.status_code}: {response.text[:200]}")
        except Exception as e:
            print(f"Error adding note: {e}")
        
        # "Duplikat" Tag hinzufügen
        try:
            url = f"{self.paperless.api_url}/tags/?name__iexact=Duplikat"
            resp = requests.get(url, headers=self.paperless.headers)
            tag_id = None
            if resp.status_code == 200:
                results = resp.json().get('results', [])
                if results:
                    tag_id = results[0]['id']
                else:
                    create_resp = requests.post(
                        f"{self.paperless.api_url}/tags/",
                        headers=self.paperless.headers,
                        json={"name": "Duplikat", "color": "#ff0000", "is_inbox_tag": False}
                    )
                    if create_resp.status_code in (200, 201):
                        tag_id = create_resp.json().get('id')
            
            if tag_id:
                doc = self.paperless.get_document(doc_id)
                if doc:
                    current_tags = doc.get('tags', [])
                    if tag_id not in current_tags:
                        current_tags.append(tag_id)
                        self.paperless.update_document(doc_id, {"tags": current_tags})
                        print(f"✅ Tag 'Duplikat' added to document {doc_id}")
        except Exception as e:
            print(f"Error adding tag: {e}")
