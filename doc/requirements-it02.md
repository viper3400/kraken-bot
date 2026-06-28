Der Seitwärtsmodus ist eigentlich die einfachste Idee überhaupt:

Du gehst davon aus, dass der Markt nicht trendet, sondern zwischen einer oberen und unteren Grenze pendelt.

Das bedeutet: Du versuchst nicht, einen Trend zu erwischen, sondern nutzt das ständige Hin und Her.

Beispiel

Solana bewegt sich seit mehreren Stunden zwischen:

* 148,00 USD (Untergrenze)
* 150,00 USD (Obergrenze)

Der Kurs sieht vereinfacht so aus:

150 ───────────────────── Widerstand
      /\      /\      /\
     /  \    /  \    /  \
149 ─    \__/    \__/    ─
148 ───────────────────── Unterstützung

Der Bot macht Folgendes:

* Bei 148,20 → Post-Only-Kauf.
* Bei 149,40 oder 149,80 → Post-Only-Verkauf.
* Danach wartet er wieder.

Er versucht also gar nicht, den Ausbruch über 150 USD mitzunehmen.

⸻

Wann funktioniert das?

Sehr gut, wenn:

* der Markt ruhig ist,
* keine Nachrichten kommen,
* keine starken Trends vorhanden sind,
* die Volatilität moderat ist.

Genau das passiert im Kryptomarkt erstaunlich oft – es gibt viele Stunden oder sogar Tage, in denen sich ein Coin überwiegend seitwärts bewegt.

⸻

Wann funktioniert es schlecht?

Wenn plötzlich ein Trend entsteht.

Beispiel:

150
149
148  Kauf
147
146
145
144

Der Bot kauft unten – aber statt einer Gegenbewegung setzt sich der Abwärtstrend fort.

Deshalb braucht der Seitwärtsmodus unbedingt eine Ausstiegsregel.

⸻

Wie erkennt der Bot eine Seitwärtsphase?

Das ist die eigentliche Herausforderung.

Eine einfache Möglichkeit:

* Die letzten 30 Kerzen hatten keine Bewegung größer als z. B. 2 %.
* EMA20 und EMA50 verlaufen nahezu horizontal.
* Der Abstand zwischen Tageshoch und Tagestief ist klein.

Dann sagt der Bot:

“Ich befinde mich wahrscheinlich in einer Range.”

⸻

Was mir an diesem Ansatz gefällt

Er passt gut zu deinem Wunsch nach:

* kleinen Gewinnen,
* Post-Only-Orders,
* wenigen Risiken.

Denn in einer Seitwärtsphase musst du keine 3 oder 5 % Gewinn erzielen. Oft reichen 0,5 bis 1 %.

⸻

Ich würde den Bot allerdings noch intelligenter machen

Nicht der Bot entscheidet:

“Ich kaufe.”

Sondern zuerst:

“In welchem Marktmodus befinde ich mich?”

Beispielsweise:

Markt analysieren
↓
Trend?
    ↓
   Ja  → Trendstrategie
↓
Nein
↓
Seitwärts?
↓
Ja → Range-Strategie
↓
Nein
↓
Nicht handeln

Das ist aus meiner Sicht der wichtigste Gedanke unseres gesamten Gesprächs.

Der Bot sollte nicht permanent nach Kaufgelegenheiten suchen. Er sollte zuerst entscheiden, ob die aktuelle Marktphase überhaupt zu einer seiner Strategien passt. Wenn weder ein klarer Trend noch eine saubere Seitwärtsphase vorliegt, tut er einfach nichts.

Diese Fähigkeit, bewusst nicht zu handeln, könnte langfristig wertvoller sein als jede Feinabstimmung der Ein- oder Ausstiegsregeln.