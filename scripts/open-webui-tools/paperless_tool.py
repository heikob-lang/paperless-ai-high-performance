"""
title: Paperless-ngx Manager
description: Suche Dokumente, setze Tags und Speicherpfade in Paperless-ngx über die REST API.
author: heiko
version: 0.1.0
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional


class Tools:
    """Paperless-ngx Manager Tool für Open WebUI.
    
    Ermöglicht die Suche nach Dokumenten, das Setzen von Tags und
    Speicherpfaden direkt aus dem Chat heraus.
    """

    # ── Konfiguration ──────────────────────────────────────────────
    # ── Konfiguration ──────────────────────────────────────────────
    # Passe diese Werte an dein Setup an:
    PAPERLESS_URL = "http://paperless-webserver:8000"  # Interne Docker-URL (nicht ändern!)
    PAPERLESS_TOKEN = "2051eaf6a446d1bbb6a034588604ac9a5e20b1ee"
    PUBLIC_PAPERLESS_URL = "http://localhost:8000" # Bei WSL2/Docker Desktop ist localhost meist korrekt!

    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {self.PAPERLESS_TOKEN}",
            "User-Agent": "OpenWebUI-Tool/1.0",
        }

    def _api_request(self, path: str, method: str = "GET", data: dict | None = None) -> dict:
        """Interne Hilfsfunktion für API-Aufrufe."""
        url = f"{self.PAPERLESS_URL}/api{path}"
        headers = self._headers()
        body = None
        if data:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
            
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            return {"error": f"HTTP {e.code}: {error_body}"}
        except Exception as e:
            return {"error": str(e)}

    # ... (internals skipped) ...

    # ── Dokumente suchen ───────────────────────────────────────────

    async def search_documents(self, query: str, max_results: int = 10) -> str:
        """
        Durchsucht alle Dokumente in Paperless-ngx nach einem Suchbegriff.
        Gibt Titel, ID, Datum und einen Textauszug zurück.
        WICHTIG: Verwenden Sie nur die wichtigsten Schlagwörter oder Rechnungsnummern für die Suche, keine ganzen Sätze oder Füllwörter! Beispiel: Suchen Sie nach "12824" anstatt "Rechnungsnummer 12824" oder "Rechnung".

        :param query: Der Suchbegriff (Volltextsuche). BITTE NUR EXAKTE SCHLAGWÖRTER ODER NUMMERN ANGEBEN!
        :param max_results: Maximale Anzahl der Ergebnisse (Standard: 10).
        :return: Gefundene Dokumente als formatierter Text.
        """
        params = {
            "page_size": min(max_results, 25),
            "ordering": "-created",
        }
        if query:
            params["query"] = query
            
        qs = urllib.parse.urlencode(params)
        url_debug = f"{self.PAPERLESS_URL}/api/documents/?{qs}"
        result = self._api_request(f"/documents/?{qs}")

        if "error" in result:
            return f"❌ API-Fehler: {result['error']}\nDEBUG URL: {url_debug}"

        docs = result.get("results")
        if docs is None:
            return f"❌ Fehler: Antwort enthält keine Ergebnisse.\nAntwort: {str(result)}\nURL: {url_debug}"

        if not docs:
            count = result.get("count", "?")
            return f"Keine Dokumente für '{query}' gefunden.\nDEBUG: URL={url_debug}\nCount={count}"

        lines = [f"**{len(docs)} Dokument(e) gefunden für '{query}':**\n"]
        for doc in docs:
            tags = ", ".join(str(t) for t in doc.get("tags", []))
            content_preview = (doc.get("content", "") or "")[:200].replace("\n", " ")
            link = f"{self.PUBLIC_PAPERLESS_URL}/documents/{doc['id']}"
            lines.append(
                f"- **#{doc['id']}** – [{doc.get('title', 'Ohne Titel')}]({link})\n"
                f"  📅 {doc.get('created', 'Unbekannt')[:10]} | "
                f"  🏷️ Tag-IDs: [{tags}]\n"
                f"  > {content_preview}…\n"
            )
        return "\n".join(lines)

    # ── Dokument-Details ───────────────────────────────────────────

    async def get_document_details(self, document_id: int) -> str:
        """
        Ruft die vollständigen Details eines Dokuments ab, inklusive Tags,
        Korrespondent, Dokumenttyp und Speicherpfad.

        :param document_id: Die ID des Dokuments in Paperless-ngx.
        :return: Formatierte Dokument-Details.
        """
        doc = self._api_request(f"/documents/{document_id}/")

        if "error" in doc:
            return f"❌ Fehler: {doc['error']}"

        # Tag-Namen auflösen
        tag_names = []
        for tag_id in doc.get("tags", []):
            tag_data = self._api_request(f"/tags/{tag_id}/")
            if "name" in tag_data:
                tag_names.append(tag_data["name"])

        # Korrespondent auflösen
        corr_name = "–"
        if doc.get("correspondent"):
            corr = self._api_request(f"/correspondents/{doc['correspondent']}/")
            corr_name = corr.get("name", "–")

        # Dokumenttyp auflösen
        doctype_name = "–"
        if doc.get("document_type"):
            dt = self._api_request(f"/document_types/{doc['document_type']}/")
            doctype_name = dt.get("name", "–")

        # Speicherpfad auflösen
        storage_name = "–"
        if doc.get("storage_path"):
            sp = self._api_request(f"/storage_paths/{doc['storage_path']}/")
            storage_name = sp.get("name", "–") + f" (`{sp.get('path', '')}`)"

        content_preview = (doc.get("content", "") or "")[:500]
        link = f"{self.PUBLIC_PAPERLESS_URL}/documents/{doc['id']}"

        return (
            f"## Dokument #{doc['id']}: [{doc.get('title', 'Ohne Titel')}]({link})\n\n"
            f"| Feld | Wert |\n|---|---|\n"
            f"| 📅 Erstellt | {doc.get('created', '–')} |\n"
            f"| 📅 Hinzugefügt | {doc.get('added', '–')} |\n"
            f"| 👤 Korrespondent | {corr_name} |\n"
            f"| 📂 Dokumenttyp | {doctype_name} |\n"
            f"| 📁 Speicherpfad | {storage_name} |\n"
            f"| 🏷️ Tags | {', '.join(tag_names) if tag_names else '–'} |\n"
            f"| 📄 Dateiname | {doc.get('original_file_name', '–')} |\n\n"
            f"**Inhalt (Auszug):**\n> {content_preview}…"
        )

    # ── Tags verwalten ─────────────────────────────────────────────

    async def list_tags(self) -> str:
        """
        Listet alle verfügbaren Tags in Paperless-ngx auf.

        :return: Liste aller Tags mit ID und Name.
        """
        result = self._api_request("/tags/?page_size=100")

        if "error" in result:
            return f"❌ Fehler: {result['error']}"

        tags = result.get("results", [])
        if not tags:
            return "Keine Tags vorhanden."

        lines = ["**Verfügbare Tags:**\n"]
        for tag in sorted(tags, key=lambda t: t.get("name", "")):
            count = tag.get("document_count", 0)
            lines.append(f"- `{tag['name']}` (ID: {tag['id']}, {count} Dokumente)")
        return "\n".join(lines)

    async def add_tags(self, document_id: int, tag_names: str) -> str:
        """
        Fügt einem Dokument Tags hinzu. Erstellt neue Tags falls nötig.
        Bestehende Tags des Dokuments bleiben erhalten.

        :param document_id: Die ID des Dokuments.
        :param tag_names: Komma-separierte Tag-Namen, z.B. "Rechnung, Wichtig, 2024".
        :return: Bestätigung der Tag-Zuweisung.
        """
        # Dokument laden
        doc = self._api_request(f"/documents/{document_id}/")
        if "error" in doc:
            return f"❌ Dokument #{document_id} nicht gefunden: {doc['error']}"

        existing_tag_ids = set(doc.get("tags", []))
        names = [n.strip() for n in tag_names.split(",") if n.strip()]

        # Alle Tags laden
        all_tags = self._api_request("/tags/?page_size=500")
        tag_map = {t["name"].lower(): t["id"] for t in all_tags.get("results", [])}

        new_tag_ids = set()
        created = []
        for name in names:
            if name.lower() in tag_map:
                new_tag_ids.add(tag_map[name.lower()])
            else:
                # Tag erstellen
                result = self._api_request("/tags/", method="POST", data={"name": name})
                if "id" in result:
                    new_tag_ids.add(result["id"])
                    created.append(name)
                else:
                    return f"❌ Fehler beim Erstellen von Tag '{name}': {result}"

        # Tags zusammenführen und speichern
        merged = list(existing_tag_ids | new_tag_ids)
        update = self._api_request(f"/documents/{document_id}/", method="PATCH", data={"tags": merged})

        if "error" in update:
            return f"❌ Fehler beim Speichern: {update['error']}"

        msg = f"✅ Tags für Dokument #{document_id} aktualisiert:\n"
        msg += f"- Hinzugefügt: {', '.join(names)}\n"
        if created:
            msg += f"- Neu erstellt: {', '.join(created)}\n"
        msg += f"- Gesamt: {len(merged)} Tags"
        return msg

    async def remove_tags(self, document_id: int, tag_names: str) -> str:
        """
        Entfernt Tags von einem Dokument.

        :param document_id: Die ID des Dokuments.
        :param tag_names: Komma-separierte Tag-Namen die entfernt werden sollen.
        :return: Bestätigung der Entfernung.
        """
        doc = self._api_request(f"/documents/{document_id}/")
        if "error" in doc:
            return f"❌ Dokument #{document_id} nicht gefunden: {doc['error']}"

        # Alle Tags laden für Name→ID Mapping
        all_tags = self._api_request("/tags/?page_size=500")
        tag_map = {t["name"].lower(): t["id"] for t in all_tags.get("results", [])}
        id_to_name = {t["id"]: t["name"] for t in all_tags.get("results", [])}

        names = [n.strip() for n in tag_names.split(",") if n.strip()]
        remove_ids = set()
        not_found = []
        for name in names:
            if name.lower() in tag_map:
                remove_ids.add(tag_map[name.lower()])
            else:
                not_found.append(name)

        remaining = [tid for tid in doc.get("tags", []) if tid not in remove_ids]
        update = self._api_request(f"/documents/{document_id}/", method="PATCH", data={"tags": remaining})

        if "error" in update:
            return f"❌ Fehler beim Speichern: {update['error']}"

        msg = f"✅ Tags entfernt von Dokument #{document_id}:\n"
        msg += f"- Entfernt: {', '.join(names)}\n"
        if not_found:
            msg += f"- ⚠️ Nicht gefunden: {', '.join(not_found)}\n"
        msg += f"- Verbleibend: {len(remaining)} Tags"
        return msg

    # ── Speicherpfade verwalten ────────────────────────────────────

    async def list_storage_paths(self) -> str:
        """
        Listet alle verfügbaren Speicherpfade in Paperless-ngx auf.

        :return: Liste aller Speicherpfade mit ID, Name und Pfad-Template.
        """
        result = self._api_request("/storage_paths/?page_size=100")

        if "error" in result:
            return f"❌ Fehler: {result['error']}"

        paths = result.get("results", [])
        if not paths:
            return "Keine Speicherpfade konfiguriert."

        lines = ["**Verfügbare Speicherpfade:**\n"]
        for p in sorted(paths, key=lambda x: x.get("name", "")):
            count = p.get("document_count", 0)
            lines.append(f"- **{p['name']}** (ID: {p['id']})\n  Pfad: `{p.get('path', '–')}` | {count} Dokumente")
        return "\n".join(lines)

    async def set_storage_path(self, document_id: int, path_name: str) -> str:
        """
        Weist einem Dokument einen Speicherpfad zu.
        Der Speicherpfad muss in Paperless-ngx bereits existieren.

        :param document_id: Die ID des Dokuments.
        :param path_name: Der Name des Speicherpfads (z.B. "Rechnungen/2024").
        :return: Bestätigung der Zuweisung.
        """
        # Speicherpfad suchen
        all_paths = self._api_request("/storage_paths/?page_size=100")
        if "error" in all_paths:
            return f"❌ Fehler: {all_paths['error']}"

        path_id = None
        for p in all_paths.get("results", []):
            if p["name"].lower() == path_name.lower():
                path_id = p["id"]
                break

        if path_id is None:
            available = ", ".join(p["name"] for p in all_paths.get("results", []))
            return (
                f"❌ Speicherpfad '{path_name}' nicht gefunden.\n\n"
                f"Verfügbare Pfade: {available or 'Keine konfiguriert'}"
            )

        update = self._api_request(
            f"/documents/{document_id}/", method="PATCH",
            data={"storage_path": path_id}
        )

        if "error" in update:
            return f"❌ Fehler beim Speichern: {update['error']}"

        return f"✅ Speicherpfad von Dokument #{document_id} auf **{path_name}** gesetzt."

    # ── Korrespondent setzen ───────────────────────────────────────

    async def set_correspondent(self, document_id: int, correspondent_name: str) -> str:
        """
        Weist einem Dokument einen Korrespondenten zu.
        Erstellt den Korrespondenten falls nötig.

        :param document_id: Die ID des Dokuments.
        :param correspondent_name: Der Name des Korrespondenten.
        :return: Bestätigung der Zuweisung.
        """
        # Korrespondenten suchen
        all_corr = self._api_request("/correspondents/?page_size=200")
        if "error" in all_corr:
            return f"❌ Fehler: {all_corr['error']}"

        corr_id = None
        for c in all_corr.get("results", []):
            if c["name"].lower() == correspondent_name.lower():
                corr_id = c["id"]
                break

        if corr_id is None:
            # Korrespondent erstellen
            result = self._api_request(
                "/correspondents/", method="POST",
                data={"name": correspondent_name}
            )
            if "id" in result:
                corr_id = result["id"]
            else:
                return f"❌ Korrespondent '{correspondent_name}' konnte nicht erstellt werden: {result}"

        update = self._api_request(
            f"/documents/{document_id}/", method="PATCH",
            data={"correspondent": corr_id}
        )

        if "error" in update:
            return f"❌ Fehler beim Speichern: {update['error']}"

        return f"✅ Korrespondent von Dokument #{document_id} auf **{correspondent_name}** gesetzt."

    # ── Statistik ──────────────────────────────────────────────────

    async def get_document_count(self) -> str:
        """
        Gibt die Gesamtanzahl der Dokumente in Paperless-ngx zurück.
        :return: Anzahl der Dokumente als Text.
        """
        result = self._api_request("/documents/?page_size=1")
        if "error" in result:
             return f"❌ Fehler: {result['error']}"
        
        count = result.get("count", 0)
        return f"Es befinden sich insgesamt **{count} Dokumente** im Paperless-Archiv."

    async def list_document_types(self) -> str:
        """
        Listet alle Dokumenttypen mit Anzahl der Dokumente auf.
        Hilft der KI zu verstehen, welche Kategorien existieren (z.B. Rechnung, Vertrag).
        """
        result = self._api_request("/document_types/?page_size=100")
        if "error" in result: return f"❌ Fehler: {result['error']}"
        
        types = result.get("results", [])
        if not types: return "Keine Dokumenttypen definiert."
        
        lines = ["**Verfügbare Dokumenttypen:**\n"]
        for t in sorted(types, key=lambda x: x.get("name", "")):
            count = t.get("document_count", 0)
            lines.append(f"- **{t['name']}** (ID: {t['id']}) | {count} Dokumente")
            
        return "\n".join(lines)

    async def list_correspondents(self) -> str:
        """
        Listet alle Korrespondenten (Absender) mit Anzahl der Dokumente auf.
        Hilft der KI zu verstehen, von wem Dokumente stammen.
        """
        result = self._api_request("/correspondents/?page_size=100")
        if "error" in result: return f"❌ Fehler: {result['error']}"
        
        corrs = result.get("results", [])
        if not corrs: return "Keine Korrespondenten definiert."
        
        lines = ["**Verfügbare Korrespondenten:**\n"]
        # Sort by count desc to show most frequent first
        for c in sorted(corrs, key=lambda x: x.get("document_count", 0), reverse=True):
            count = c.get("document_count", 0)
            if count > 0: # Show only relevant
                lines.append(f"- **{c['name']}** (ID: {c['id']}) | {count} Dokumente")
            
        return "\n".join(lines)

    async def filter_documents(self, query: str = "", document_type_id: int = None, correspondent_id: int = None, max_results: int = 10) -> str:
        """
        Sucht Dokumente mit spezifischen Filtern (Typ, Korrespondent).
        Kombiniert Volltextsuche mit Metadaten-Filter.
        
        :param query: Optionaler Suchbegriff.
        :param document_type_id: ID des Dokumenttyps (aus list_document_types).
        :param correspondent_id: ID des Korrespondenten (aus list_correspondents).
        """
        params = {
            "page_size": min(max_results, 25),
            "ordering": "-created",
        }
        if query: params["query"] = query
        if document_type_id: params["document_type__id"] = document_type_id
        if correspondent_id: params["correspondent__id"] = correspondent_id
        
        qs = urllib.parse.urlencode(params)
        result = self._api_request(f"/documents/?{qs}")

        if "error" in result:
            return f"❌ Fehler bei der Suche: {result['error']}"

        docs = result.get("results", [])
        count = result.get("count", 0)
        
        if not docs:
             count = result.get("count", "?")
             return f"Keine Dokumente gefunden (Total: {count}).\nDEBUG: URL={url_debug}\nCount={count}"

        lines = [f"**Gefunden: {count} Dokumente (zeige Top {len(docs)}):**\n"]
        for doc in docs:
            # Helper to get names would be nice, but expensive. We verify with ID.
            date = doc.get("created", "Unbekannt")[:10]
            title = doc.get("title", "Ohne Titel")
            link = f"{self.PUBLIC_PAPERLESS_URL}/documents/{doc['id']}"
            lines.append(f"- **#{doc['id']}** [{date}] [{title}]({link})")
            
        return "\n".join(lines)

    async def list_recent_documents(self, limit: int = 10) -> str:
        """
        Listet die neuesten Dokumente auf (ohne Filter).
        Nützlich, um einen Überblick zu bekommen, wenn man nicht genau weiß wonach man sucht.
        """
        return await self.search_documents("", max_results=limit)

    async def find_everything(self, query: str) -> str:
        """
        Die "Magische Suche": Findet Dokumente basierend auf Inhalt, Tags, Korrespondenten, Typen und Speicherpfaden.
        Aggregiert alle Ergebnisse zu einer umfassenden Übersicht.
        Nutze dies, wenn der Nutzer "alles über X" wissen will.
        """
        results = {} # id -> doc_info

        # 1. Volltextsuche
        fulltext = await self._api_request(f"/documents/?query={urllib.parse.quote(query)}&page_size=20")
        if "results" in fulltext:
            for doc in fulltext["results"]:
                doc["_match_reason"] = "Volltext/Titel"
                results[doc["id"]] = doc

        # 2. Suche in Korrespondenten
        corrs = await self._api_request(f"/correspondents/?name__icontains={urllib.parse.quote(query)}")
        if "results" in corrs:
            for corr in corrs["results"]:
                # Suche Dokumente dieses Korrespondenten
                docs = await self._api_request(f"/documents/?correspondent__id={corr['id']}&page_size=20")
                if "results" in docs:
                    for doc in docs["results"]:
                        if doc["id"] not in results:
                            doc["_match_reason"] = f"Korrespondent: {corr['name']}"
                            results[doc["id"]] = doc

        # 3. Suche in Tags
        tags = await self._api_request(f"/tags/?name__icontains={urllib.parse.quote(query)}")
        if "results" in tags:
            for tag in tags["results"]:
                docs = await self._api_request(f"/documents/?tags__id__all={tag['id']}&page_size=20")
                if "results" in docs:
                    for doc in docs["results"]:
                        if doc["id"] not in results:
                             doc["_match_reason"] = f"Tag: {tag['name']}"
                             results[doc["id"]] = doc
        
        # 4. Suche in Dokumenttypen
        types = await self._api_request(f"/document_types/?name__icontains={urllib.parse.quote(query)}")
        if "results" in types:
            for dt in types["results"]:
                docs = await self._api_request(f"/documents/?document_type__id={dt['id']}&page_size=20")
                if "results" in docs:
                    for doc in docs["results"]:
                        if doc["id"] not in results:
                            doc["_match_reason"] = f"Typ: {dt['name']}"
                            results[doc["id"]] = doc

        if not results:
            return f"Keine Ergebnisse für '{query}' in Inhalten, Tags oder Metadaten gefunden."

        # Formatieren
        lines = [f"**'Find Everything' Ergebnis für '{query}' ({len(results)} Treffer):**\n"]
        for doc_id, doc in sorted(results.items(), key=lambda x: x[1].get("created", ""), reverse=True):
            date = doc.get("created", "Unbekannt")[:10]
            title = doc.get("title", "Ohne Titel")
            reason = doc.get("_match_reason", "Unbekannt")
            link = f"{self.PUBLIC_PAPERLESS_URL}/documents/{doc_id}"
            lines.append(f"- **#{doc_id}** [{date}] [{title}]({link}) *(Gefunden via {reason})*")
        
        return "\n".join(lines)

    async def test_connection(self) -> str:
        """
        Testet die Verbindung zu Paperless und gibt Debug-Infos zurück.
        Nutze dies bei Problemen ("Teste Verbindung").
        """
        url = f"{self.PAPERLESS_URL}/api/documents/?page_size=1"
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                count = data.get("count", "unbekannt")
                first = data.get("results", [{}])[0].get("title", "-")
                return (
                    f"✅ Verbindung erfolgreich!\n"
                    f"URL: `{url}`\n"
                    f"Code: {resp.status}\n"
                    f"Anzahl Docs: {count}\n"
                    f"Beispiel: {first}\n"
                    f"Public URL: `{self.PUBLIC_PAPERLESS_URL}`"
                )
        except Exception as e:
            return f"❌ Verbindung gescheitert!\nURL: `{url}`\nFehler: {str(e)}"
