# 🎫 LFBBotTicketTool

Ein umfassendes, 100% deutschsprachiges Ticket-System für Red-DiscordBot.

## Features

- 🎫 **Multiple Ticket-Kategorien** - Verschiedene Ticket-Typen konfigurierbar
- 🔘 **Buttons & Dropdowns** - Moderne Discord UI-Elemente
- 📝 **Transkripte** - Automatische Text-Exporte
- ✋ **Claim-System** - Supporter können Tickets übernehmen
- ⭐ **Feedback-System** - Bewertungen nach Schließung
- 🚫 **Blacklist** - User von Tickets ausschließen
- ⏰ **Auto-Close** - Automatische Schließung bei Inaktivität
- 📊 **Statistiken** - Detaillierte Ticket-Statistiken
- 🔔 **DM-Benachrichtigungen** - User benachrichtigen
- 📋 **Logging** - Alle Events loggen
- 🎨 **Voll anpassbar** - Farben, Emojis, Nachrichten
- 🌐 **100% Deutsch** - Vollständig lokalisiert

---

## 📦 Installation

### Über GitHub (Empfohlen)

**Schritt 1: Repo hinzufügen**
```
[p]repo add lfbbottickettool https://github.com/DEIN-USERNAME/LFBBotTicketTool
```

**Schritt 2: Cog installieren**
```
[p]cog install lfbbottickettool LFBBotTicketTool
```

**Schritt 3: Cog laden**
```
[p]load LFBBotTicketTool
```

**Schritt 4: Einrichtung**
```
[p]ticketset quicksetup
```

---

## ⚡ Schnellstart

Nach der Installation:

1. **Support-Rolle setzen:**
   ```
   [p]ticketset supportrole @Support
   ```

2. **Panel erstellen:**
   ```
   [p]ticketset panel create
   ```

3. **Fertig!** 🎉

---

## 📋 Befehle

### User-Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `[p]ticket new [kategorie]` | Neues Ticket erstellen |
| `[p]ticket close [grund]` | Ticket schließen |
| `[p]ticket add @user` | User hinzufügen |
| `[p]ticket remove @user` | User entfernen |
| `[p]ticket claim` | Ticket übernehmen |
| `[p]ticket transcript` | Transkript erstellen |
| `[p]ticket info` | Ticket-Informationen |
| `[p]ticket stats [user]` | Statistiken |

### Admin-Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `[p]ticketset quicksetup` | 🚀 Schnelleinrichtung |
| `[p]ticketset showsettings` | Einstellungen anzeigen |
| `[p]ticketset supportrole @Rolle` | Support-Rolle setzen |
| `[p]ticketset category #Kategorie` | Ticket-Kategorie setzen |
| `[p]ticketset limit 5` | Max. Tickets pro User |
| `[p]ticketset autoclose 72 24` | Auto-Close nach 72h |

### Kategorien

| Befehl | Beschreibung |
|--------|--------------|
| `[p]ticketset category add Name 🎫 Beschreibung` | Neue Kategorie |
| `[p]ticketset category remove Name` | Kategorie löschen |
| `[p]ticketset category toggle Name` | Kategorie an/aus |
| `[p]ticketset category list` | Alle Kategorien |

### Panels

| Befehl | Beschreibung |
|--------|--------------|
| `[p]ticketset panel create` | Panel erstellen |
| `[p]ticketset panel delete <id>` | Panel löschen |
| `[p]ticketset panel list` | Alle Panels |

### Blacklist

| Befehl | Beschreibung |
|--------|--------------|
| `[p]ticketset blacklist add @user` | User hinzufügen |
| `[p]ticketset blacklist remove @user` | User entfernen |
| `[p]ticketset blacklist list` | Blacklist anzeigen |

---

## 🔄 Update

```
[p]cog update LFBBotTicketTool
```

---

## 🐛 Fehlerbehebung

### "Keine Berechtigung"
- Prüfe Bot-Rollen und Berechtigungen
- Bot braucht `manage_channels`

### Buttons funktionieren nicht
- Cog neu laden: `[p]reload LFBBotTicketTool`
- Panel neu erstellen: `[p]ticketset panel create`

---

## 📁 GitHub Repo erstellen

1. Erstelle ein neues Repository auf GitHub namens `LFBBotTicketTool`

2. Lade die 3 Dateien hoch:
   - `__init__.py`
   - `LFBBotTicketTool.py`
   - `info.json`

3. Füge das Repo zu RedBot hinzu:
   ```
   [p]repo add lfbbottickettool https://github.com/DEIN-USERNAME/LFBBotTicketTool
   ```

4. Installiere den Cog:
   ```
   [p]cog install lfbbottickettool LFBBotTicketTool
   ```

---

## Lizenz

MIT License - Frei verwendbar.

---

**🎫 LFBBotTicketTool - Das perfekte Ticket-System für deinen Discord Server!**
