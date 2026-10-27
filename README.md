# Fotostudio

Een foto-app die lokaal op je eigen computer draait. Je kunt er foto's mee
**upscalen met AI** (Real-ESRGAN, 2× en 4×) en ze bewerken in een **VSCO-achtige
stijl**: presets met één klik, een Auto-knop, schuifregelaars, voor/na-vergelijking
en eigen presets opslaan. Alles blijft op je computer, er gaat niets naar
internet.

## Starten

**Eenmalig:** download deze map (op GitHub: groene knop **Code → Download ZIP**)
en pak de ZIP uit, bijvoorbeeld in je map Documenten.

Dan:

| Computer | Wat je doet |
|---|---|
| **Windows** | Dubbelklik op **`Start.bat`** |
| **Mac** | Klik met de rechtermuisknop op **`Start.command`** → **Open** → **Open** (alleen de eerste keer zo, daarna gewoon dubbelklikken) |
| **Linux** | Dubbelklik op `start.sh`, of typ `./start.sh` in een terminal |

De **eerste keer** installeert de app zelf alles wat nodig is. Dat duurt een paar
minuten en je hebt daarvoor internet nodig. Daarna start hij binnen een paar
seconden en werkt hij ook zonder internet.

De app opent vanzelf in je browser. Gebeurt dat niet, ga dan naar
**http://localhost:8000**.

Er blijft een zwart venster openstaan: dat is de app zelf. **Laat het open**
zolang je de app gebruikt. Klaar? Sluit dat venster.

> Windows laat misschien een blauwe waarschuwing zien ("Windows heeft uw pc
> beschermd"). Klik op **Meer informatie → Toch uitvoeren**. Vraagt de Windows
> Firewall iets, kies dan **Toestaan** (privé-netwerken), anders werkt de app niet
> op je telefoon.

## Op je telefoon

1. Start de app op je computer.
2. Klik in de app rechtsboven op **Telefoon**.
3. Scan de QR-code met de camera van je telefoon.

Je telefoon moet op **hetzelfde wifi-netwerk** zitten als je computer. Het
upscalen gebeurt op je computer, je telefoon is alleen het scherm.

Tip: op de iPhone kun je via **Deel → Zet op beginscherm** een icoontje maken.

## Zo werkt het

- **Foto's toevoegen:** sleep ze in het venster of klik op **Foto's**. Meerdere
  tegelijk mag. JPG, PNG, WEBP en iPhone-foto's (HEIC) werken allemaal.
- **Presets:** de kleine plaatjes onder je foto laten zien hoe jouw foto eruitziet
  met dat filter. Klik erop om het toe te passen. Met de balk erboven stel je
  de **sterkte** in.
  - *Moody Dark* — donker, gedempte kleuren, diepe zwarten, vignet en korrel
  - *Clean Bright* — licht en luchtig
  - *Film Warm* — warme tinten, korrel, licht vervaagde zwarten
  - *Cool Grey* — koel en ingetogen, editorial
  - *B&W Contrast* — zwart-wit met veel contrast
  - *Soft Matte* — zacht en mat
  - *Dark Luxe* — veel donkerder, strak en clean (de donkere Instagram-look)
  - *Gym Bronze* — donker en contrastrijk met een warme, bronzen huid
- **Auto:** de app bekijkt helderheid, contrast en kleuren van je foto en kiest
  zelf de best passende preset plus correcties. Daarna kun je alles nog aanpassen.
- **Bewerk:** schuifregelaars voor belichting, contrast, hoge lichten,
  schaduwen, zwarten, fade, verzadiging, temperatuur, tint, scherpte, korrel en
  vignet. Onder **Kleurtinten** pas je alleen de huid/oranje tinten, het groen of
  het blauw aan. **Dubbelklik** op een regelaar om hem terug te zetten.
- **Kopieer look:** tik op **Kopieer** (achter de presets) en kies een
  voorbeeldfoto waarvan je de stijl mooi vindt, bijvoorbeeld een screenshot van
  Instagram. De app meet licht, contrast, kleuren en huidtinten van het voorbeeld
  en maakt er een nieuwe preset van ("Look 1", "Look 2", ...) die je op al je
  foto's kunt gebruiken. Werkt het best als het voorbeeld een vergelijkbare
  foto is (bv. ook een portret).
- **Voor/na:** klik op **Voor/na** en sleep de lijn over de foto. Of houd de foto
  even ingedrukt om het origineel te zien.
- **Eigen preset:** stel alles in zoals je wilt en klik op **Opslaan als preset**
  (of op het **+** achter de presets). Verwijderen: beweeg met de muis over je
  preset en klik op het kruisje (op de telefoon: lang indrukken).
- **AI verbeteren:** in het tabblad *Upscale*. Real-ESRGAN maakt je foto scherper
  en haalt ruis en JPG-blokjes weg, maar het formaat blijft gelijk. Je presets en
  bewerkingen blijven gewoon staan; ze worden er daarna overheen gelegd.
- **Upscale:** kies **2×** of **4×**. De AI voegt echt detail toe in plaats van de
  foto alleen groter te maken. Met **Alles 2×/4×** doe je al je foto's achter
  elkaar. Heeft je computer een geschikte videokaart, dan gaat het snel; zonder
  videokaart werkt het ook, alleen trager (een gewone telefoonfoto duurt dan
  ongeveer 1 à 2 minuten). Foto's worden maximaal 8192 pixels breed.
- **Exporteren:** klik op **Exporteer**. Je krijgt een JPG in hoge kwaliteit (97%,
  volle resolutie, zonder kleurstreepjes in donkere verlopen). Presets maken je
  foto nooit kleiner of waziger.
  Bij meerdere foto's kies je *Alle foto's met de huidige instellingen* (batch).
  Op je computer komen de foto's in de map **Afbeeldingen → Fotostudio**
  (klik op *Open map*). Op je telefoon worden ze gedownload (bij meerdere
  foto's als één zip-bestand).

Je foto's en instellingen worden bewaard in de map `data` in de app-map. Je
originele bestanden worden nooit aangepast.

## Problemen?

- **"Kan geen verbinding maken"** — staat het zwarte venster nog open? Start de app
  opnieuw met `Start.bat` / `Start.command`.
- **Telefoon kan de app niet openen** — zit hij op hetzelfde wifi-netwerk? Sta de
  app toe in de firewall. Werkt het via gastwifi niet: gastnetwerken blokkeren
  vaak verkeer tussen apparaten.
- **Upscalen is traag** — dan is er geen geschikte videokaart gevonden en rekent
  de processor. Dat werkt prima, alleen langzamer. In het tabblad *Upscale* zie
  je welke motor gebruikt wordt.

---

## Voor ontwikkelaars

- Backend: Python + FastAPI (`app/`), gestart via [uv](https://docs.astral.sh/uv/)
  (`uv run python -m app`). uv installeert zelf Python en alle dependencies uit
  `uv.lock`.
- Upscaling (`app/upscaler.py`):
  - GPU: officiële `realesrgan-ncnn-vulkan` (model `realesrgan-x4plus`). Wordt bij de eerste
    start van GitHub gedownload (checksum gecontroleerd) en getest; software-Vulkan
    (llvmpipe/SwiftShader) wordt overgeslagen.
  - CPU-fallback: `realesr-general-x4v3` via ONNX Runtime
    (`app/models/realesr-general-x4v3.onnx`, omgezet met `tools/convert_model.py`).
  - Forceer de CPU met `FOTOSTUDIO_ENGINE=cpu`.
- Bewerkingen: dezelfde formules in `app/edits.py` (numpy, voor export) en
  `app/static/js/renderer.js` (WebGL, live-preview).
- Instellingen via omgevingsvariabelen: `FOTOSTUDIO_PORT`, `FOTOSTUDIO_DATA`,
  `FOTOSTUDIO_MAX_SIDE`, `FOTOSTUDIO_NO_BROWSER=1`.
- Tests: `uv run pytest` (inclusief echte upscale- en exporttest).

Real-ESRGAN © Xintao Wang e.a., BSD-3-licentie — https://github.com/xinntao/Real-ESRGAN
