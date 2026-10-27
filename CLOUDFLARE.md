# Fotostudio online zetten met Cloudflare (eenmalig, ±15 minuten)

Hierna open je de app op je telefoon via een vast adres zoals
`https://fotostudio-serenay.pages.dev`, log je in met je e-mail en zet je hem op
je beginscherm. Je laptop hoeft niet aan te staan.

**Privacy:** alles gebeurt op je telefoon zelf. Je foto's worden in de app op je
telefoon bewaard en **nergens naartoe gestuurd**, ook niet naar Cloudflare.
Cloudflare levert alleen de app zelf af, en alleen aan jou na het inloggen.

---

## Stap 1 — Cloudflare-account

1. Ga naar **dash.cloudflare.com/sign-up** en maak een gratis account met
   `serenayk1@hotmail.com`.
2. Bevestig je e-mailadres.

## Stap 2 — De app online zetten (Cloudflare Pages)

1. Klik links op **Workers & Pages** (soms onder *Compute*) en dan op **Create**
   (of *Create application*).
2. Kies het tabblad **Pages** en dan **Connect to Git** / *Import an existing Git repository*.
   (Zie je alleen "Workers"? Klik dan onderaan op *Looking to deploy Pages? Get started*.)
3. Klik **Connect GitHub**, log in en geef toegang tot **serenay-bws/photo-app**.
4. Kies de repository **photo-app** en klik **Begin setup**.
5. Vul in:
   - **Project name:** `fotostudio-serenay` (dit wordt je adres; moet uniek zijn)
   - **Production branch:** `fotostudio-app`
   - **Framework preset:** *None*
   - **Build command:** leeg laten
   - **Build output directory:** `site`
6. Klik **Save and Deploy**. Na een minuut staat er: *Success*. Je adres is
   `https://fotostudio-serenay.pages.dev`.

> Open het adres nog **niet** met anderen: eerst stap 3 (inloggen) instellen.

## Stap 3 — Alleen jij mag erin (Cloudflare Access)

1. Ga in het linkermenu naar **Zero Trust**.
   - De eerste keer kies je een *team name* (bv. `serenay`) en het **Free**-plan
     (gratis tot 50 gebruikers; soms vraagt Cloudflare een betaalkaart ter controle,
     er wordt niets afgeschreven).
2. Ga naar **Access → Applications** (of *Access controls → Applications*) en klik
   **Add an application** → **Self-hosted**.
3. Vul in:
   - **Application name:** `Fotostudio`
   - **Session duration:** `1 month` (dan hoef je maar één keer per maand in te loggen)
   - **Public hostname / Application domain:** `fotostudio-serenay.pages.dev`
   - Klik **Add domain / + Add** en voeg ook `*.fotostudio-serenay.pages.dev` toe
     (dat beschermt ook de testversies).
4. **Policy** (regel):
   - **Policy name:** `Alleen ik`
   - **Action:** `Allow`
   - **Include → Selector: Emails →** `serenayk1@hotmail.com`
5. **Login methods:** laat **One-time PIN** aangevinkt.
6. Klik **Save** / **Add application**.

Test het: open het adres in een privévenster. Je krijgt nu een Cloudflare-scherm
dat om je e-mail vraagt. Alleen `serenayk1@hotmail.com` krijgt een code; elk ander
adres komt er niet in.

## Stap 4 — Op je telefoon als app

1. Open **Safari** (iPhone) of **Chrome** (Android) en ga naar
   `https://fotostudio-serenay.pages.dev`.
2. Vul je e-mail in, open de mail van Cloudflare en typ de code over.
3. **iPhone:** tik op **Deel** (vierkantje met pijl) → **Zet op beginscherm** → **Voeg toe**.
   **Android:** tik op **⋮** → **Toevoegen aan startscherm**.
4. Open de app voortaan via het icoontje op je beginscherm.

## Goed om te weten

- **Je foto's staan in de app op je telefoon.** Verwijder je de app van je
  beginscherm, dan zijn ook de foto's in de app weg (je originelen in Foto's niet).
- **Exporteren:** tik op het downloadpijltje → **Bewaar / deel** → **Bewaar afbeelding**,
  dan komt de bewerkte foto in je fotorol.
- **AI-upscalen** gebeurt op je telefoon zelf. De eerste keer wordt het AI-model
  gedownload (±35 MB, liefst via wifi). Het werkt voor foto's tot een paar megapixel
  (bv. foto's uit WhatsApp of Instagram, oude foto's); grote camerafoto's zijn al
  scherp genoeg.
- **Updates:** als ik de app verbeter, zet Cloudflare de nieuwe versie automatisch online.
- Je laptop-versie (`Start.bat` / `Start.command`) blijft ook gewoon werken.
