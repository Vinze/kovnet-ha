# KOVnet voor Home Assistant

Zie in Home Assistant wanneer je kind naar de opvang gaat. Deze integratie haalt het opvangrooster op uit **KOVnet**, het ouderportaal van veel kinderopvangorganisaties. Het rooster komt als agenda en als sensoren in Home Assistant.

> **Onofficieel.** Dit project is niet gemaakt door KOVnet en wordt niet door KOVnet ondersteund. Het gebruikt dezelfde (niet-gedocumenteerde) API als de KOVnet Ouderapp. KOVnet kan die zonder aankondiging veranderen. Gebruik het op eigen risico.

## Wat je krijgt

Per kind (per opvangcontract) een apparaat met:

| Entiteit | Wat het doet |
|---|---|
| `binary_sensor` **Opvang vandaag** | Aan als je kind vandaag opvang heeft. Attributen: start, eind, groep, afgemeld, in afwachting, gesloten, opmerking. |
| `sensor` **Volgende opvang** | Tijdstip waarop de volgende opvang begint. Attributen: eind, groep. |
| `calendar` **Opvang** | Alle opvangdagen van deze en volgende maand. Afgemelde en gesloten dagen staan erin als hele-dag-afspraak. |

Het rooster wordt elk uur opgehaald.

## Installatie

### Via HACS (aanbevolen)

1. Open HACS en ga naar het menu (⋮) → **Aangepaste repositories**.
2. Voeg `https://github.com/Vinze/kovnet-ha` toe, met type **Integratie**.
3. Zoek **KOVnet** en installeer het.
4. Herstart Home Assistant.

### Handmatig

1. Kopieer de map `custom_components/kovnet` naar `config/custom_components/kovnet` in je Home Assistant.
2. Herstart Home Assistant.

## Instellen

1. Ga naar **Instellingen → Apparaten en diensten → Integratie toevoegen**.
2. Zoek **KOVnet**.
3. Log in met hetzelfde e-mailadres en wachtwoord als in de KOVnet Ouderapp.
4. Staat tweestapsverificatie (2FA) aan, dan mailt KOVnet je een viercijferige code. Vul die in.
5. Heeft je e-mailadres accounts bij meerdere organisaties, kies dan de juiste.
6. Kies de kinderen (contracten) die je in Home Assistant wilt zien.

Je hoeft geen contractnummer op te zoeken. De integratie haalt je contracten zelf op.

### Tweestapsverificatie (2FA)

KOVnet gebruikt als 2FA een code die je per e-mail krijgt. Na het inloggen krijgt Home Assistant een token dat ongeveer **een jaar** geldig is. Je hoeft de code dus niet steeds opnieuw in te vullen.

Als het token verloopt of door KOVnet wordt ingetrokken:

- **Zonder 2FA** logt de integratie zelf opnieuw in.
- **Met 2FA** krijg je in Home Assistant een melding **Opnieuw inloggen**. Vul je wachtwoord in en daarna de nieuwe code uit je mail.

## Privacy

- Je e-mailadres, wachtwoord en token worden alleen opgeslagen in de configuratie van je eigen Home Assistant (`.storage/core.config_entries`).
- De integratie praat alleen met `app.kovnet.nl`. Er gaan geen gegevens naar andere partijen.
- Het wachtwoord wordt bewaard zodat de integratie zonder 2FA vanzelf opnieuw kan inloggen.
- Het inloggen werkt zoals in de app: e-mailadres en wachtwoord gaan via HTTPS als parameters in de URL. Ze zijn versleuteld onderweg, maar kunnen in de serverlogs van KOVnet terechtkomen.

## Beperkingen

- Alleen lezen: je kunt vanuit Home Assistant niets aanvragen, afmelden of ruilen.
- Alleen deze en volgende maand worden opgehaald.
- Komt er een nieuw contract bij (bijvoorbeeld een tweede kind), verwijder dan de koppeling en voeg hem opnieuw toe. Vink daarbij het nieuwe contract aan.

## Problemen melden

Maak een [issue](https://github.com/Vinze/kovnet-ha/issues) aan. Zet debug-logging aan via **Instellingen → Apparaten en diensten → KOVnet → Foutopsporing inschakelen** en voeg de relevante regels toe.

**Haal er eerst namen, e-mailadressen en tokens uit.**

## Upgraden vanaf 0.1.x

Versie 0.1 las de KOVnet-website uit. Vanaf 0.2 gebruikt de integratie de API van de app.

Bestaande koppelingen worden bij de eerste herstart automatisch omgezet. De entiteit-ID's blijven gelijk. Maak voor de zekerheid eerst een back-up.
