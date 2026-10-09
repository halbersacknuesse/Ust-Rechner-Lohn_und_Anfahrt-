# Lohnkosten-Rechner

Ein kleines Werkzeug für Handwerksbetriebe: Es berechnet aus Stundensatz, Arbeitszeit,
Anfahrtspauschale und Verbrauchsmaterial den Textbaustein, der die nach § 35a EStG
begünstigten Kosten auf der Rechnung ausweist – und legt ihn in die Zwischenablage.

```
Im Rechnungsbetrag sind Arbeits- und Fahrtkosten von 145,18€ brutto enthalten,
die Sie nach § 35a EStG steuerlich geltend machen können.
Die darin enthaltene Umsatzsteuer beträgt 23,18€.
```

Entstanden ist das Tool, weil dieser Satz bei jeder Rechnung neu getippt und neu
gerechnet werden musste – inklusive der Frage, ob man beim Runden gerade einen Cent
zu wenig ausweist.

## Zwei Varianten

| | `lohnkosten.py` | `lohnkosten.html` |
|---|---|---|
| Oberfläche | Qt (PySide6) | Browser |
| Plattform | Linux, Windows, macOS | alles mit Browser, auch Android/Samsung DeX |
| Installation | PySide6 nötig | keine, Datei öffnen genügt |
| Speicherort der Daten | `~/.local/share/lohnkosten/` | `localStorage` des Browsers |

Beide haben denselben Funktionsumfang und rechnen identisch – geprüft über alle
Kombinationen aus Zeiten, Stundensätzen, Pauschalen, Materialbeträgen und
Steuersätzen.

## Installation

**Qt-Version**

```bash
# Fedora
sudo dnf install python3-pyside6
# oder plattformunabhängig
pip install --user PySide6

python3 lohnkosten.py
```

**Webversion**

Die Datei `lohnkosten.html` im Browser öffnen. Sie ist vollständig eigenständig:
kein Server, kein Build, keine externen Ressourcen, kein Internetzugang nötig.
Auf dem Mobilgerät über „Zum Startbildschirm hinzufügen" einrichten.

## Funktionen

- **Stundensatz** als Regler mit ungleichmäßiger Skala: fein im üblichen Bereich,
  grob nach oben. Zwei frei definierbare Sätze (z. B. Geschäfts- und Privatkunden)
  rasten beim Ziehen ein und liegen zusätzlich als Schaltfläche bereit.
- **Arbeitszeit** von 0,5 bis 10 h, viertelstundengenau im häufigen Bereich,
  mit Rastpunkten bei 1, 1,5, 2 und 2,5 h und einem Zahlenfeld für krumme Zeiten.
- **Festpreis**: Das Nettolohn-Feld zeigt normalerweise Stundensatz × Zeit, lässt sich
  aber überschreiben, wenn die Leistung pauschal abgerechnet wird.
- **Anfahrtspauschalen** als Liste von Stufen, im Einstellungsreiter frei editierbar.
- **Verbrauchsmaterial** als freier Betrag.
- **Umsatzsteuer** 0 / 7 / 19 % oder frei.
- **Automatisches Kopieren** nach jeder Änderung; der Verlauf nimmt nur auf,
  was bewusst über die Schaltfläche kopiert wurde. Ein Klick auf einen Eintrag
  kopiert ihn erneut.
- Helles und dunkles Erscheinungsbild nach Systemeinstellung.

## Anpassen

Stundensätze, deren Bezeichnungen und die komplette Anfahrtsstaffel stellst du im
Reiter *Einstellungen* ein. Die Werte landen in
`~/.local/share/lohnkosten/einstellungen.json` beziehungsweise im `localStorage`
des Browsers – der Quelltext bleibt unberührt.

Im Kopf beider Dateien stehen die Voreinstellungen als Konstanten, unter anderem:

| Konstante | Bedeutung |
|---|---|
| `TEMPLATE` | der erzeugte Satz |
| `CURRENCY` | `"{}€"` oder `"{} €"` für ein Leerzeichen vor dem Zeichen |
| `RATE_STOPS`, `HOUR_STOPS` | die Rasterung der Regler |
| `CFG_DEFAULT` / `TRIPS_DEFAULT` | Stundensätze und Anfahrtsstaffel beim ersten Start |
| `TAX_PRESETS` | angebotene Steuersätze |

## Rundung

Beträge werden kaufmännisch auf Cent gerundet: Ein halber Cent geht immer aufwärts.
Das ist wichtiger, als es klingt – Pythons eingebautes `round()` rundet zur geraden
Zahl und macht aus 1,925 € eben 1,92 €. Die Qt-Version rechnet deshalb mit `Decimal`,
die Webversion vollständig in ganzen Zahlen (Beträge in Cent, Zeit in Hundertstel-
Stunden, Steuersatz in Zehntel-Prozent), weil JavaScript keinen Dezimaltyp kennt.

Der Rechenweg folgt der Rechnung:

1. Nettobetrag = Arbeitsleistung + Anfahrt + Material, auf Cent gerundet
2. Umsatzsteuer aus diesem gerundeten Nettobetrag, ebenfalls kaufmännisch
3. Bruttobetrag = Netto + USt als exakte Summe

Dadurch ergibt Brutto minus ausgewiesene Umsatzsteuer immer wieder genau den
Nettobetrag. Beide Varianten liefern über alle geprüften Kombinationen aus Zeiten,
Sätzen und Steuersätzen identische Ergebnisse.

## Datenschutz

Das Tool sendet nichts und lädt nichts nach. Es gibt keine Analyse, keine Schriftarten
von fremden Servern, keine Verbindung nach außen. Berechnungen bleiben auf dem Gerät.

## Rechtlicher Hinweis

Dieses Werkzeug erstellt einen Textbaustein, keine Steuerberatung. Ob und in welcher
Höhe Kosten nach § 35a EStG begünstigt sind, hängt vom Einzelfall ab. Grundlage ist
das Anwendungsschreiben des BMF zu § 35a EStG vom 9. November 2016: Arbeits-,
Maschinen- und Fahrtkosten sowie Verbrauchsmittel sind begünstigt, geliefertes
Material ist es nicht. Die Abgrenzung im Einzelfall gehört ins Steuerbüro, nicht in
ein Rechenprogramm.

Die voreingestellten Stundensätze und Anfahrtspauschalen sind Beispielwerte und keine
Empfehlung.

## Entstehung

Dieses Projekt ist in Zusammenarbeit mit einem KI-Assistenten (Claude) entstanden:
Oberfläche, Logik und diese README wurden überwiegend von der KI geschrieben,
anschließend von mir geprüft, getestet und angepasst. Rechenweg und Rundung habe
ich dabei besonders im Auge behalten, weil sie auf Rechnungen landen. Wer den Code
übernimmt, sollte ihn trotzdem selbst lesen und sich auf keine Zahl verlassen, die
er nicht nachgerechnet hat.

## Lizenz

[MIT](LICENSE)
