# ÅkerSync · Jordbruksklass 5–10 · v0b

Utvidgar klass 9/10-analysen till hela premium–mellansegmentet: klass 5,6,7,8,9,10.

## Syfte

- beskriva hur sand/silt/lera/mull förändras längs klassgradienten 5→10,
- se om **variationen i textur minskar när klassen stiger**,
- ge en bättre empirisk grund för "Ferrari/Porsche/BMW/Audi/Volvo/Volkswagen-jord"-tänket.

## Population

Kommuner är inte urvalsenheten. Populationen definieras av klasspolygonerna.

Två populationer redovisas:

A. `historic_class_area`
B. `current_2025_farmland`

## Viktig output

- `class5_10_soil_summary.csv`
- `class5_10_texture_covariance.csv`
- `class5_10_organic_summary.csv`
- `class5_10_gradient_current_farmland.csv`
- `report.txt`

`class5_10_gradient_current_farmland.csv` är extra praktisk när man vill se hur medel, median och standardavvikelse ändras med klass.

## Hypoteser att kolla efter

1. Flyttar lerhaltens median systematiskt med klass?
2. Blir texturvariationen (särskilt `clay_sd_pct`) mindre ju högre klassen är?
3. Får klass 10 en smalare P10–P90-bredd än klass 9, 8, 7 ...?
4. Ser mullfördelningen annorlunda ut i klass 10 än i klass 5–8?
