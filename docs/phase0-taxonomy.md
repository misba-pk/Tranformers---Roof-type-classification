# Phase 0 — Problem definition

Fill this in yourself after the Day 1 reading + Day 2 Overpass query. Writing it in your own words
is the point — it's the thing you'll be able to explain in an interview without re-reading a paper.

## 1. Class taxonomy

<!-- Start binary (residential / non-residential), then list the extended classes you're actually
going to support, based on REAL tag frequency in Berlin (Day 2 Overpass query), not a paper's table.
For each class, note roughly how many Berlin buildings back it up. -->

**DRAFT — capped at 9 classes because that's the most granular functional taxonomy with
evidence behind it (ref. 9: kappa 0.844 binary -> 0.754 at 9-class). Overwrite once you've read
ref. 9's actual class definitions and run the Day 2 Overpass tag-frequency query — drop or merge
any class below your minimum-count threshold instead of keeping it just because it's on this list.**

### Tier 1 — binary (the safety-net milestone)
- Residential
- Non-residential

### Tier 2 — extended (draft seed, verify against ref. 9 + real Berlin counts)
1. Residential — `house, apartments, residential, detached, terrace, dormitory`
2. Commercial / retail — `commercial, retail, kiosk, supermarket`
3. Office
4. Industrial — `industrial, warehouse, manufacture`
5. Public / civic — `public, government, civic, fire_station, police`
6. Education — `school, university, kindergarten, college`
7. Religious — `church, mosque, synagogue, temple, chapel`
8. Health — `hospital, clinic`
9. Other / ancillary / mixed — `barn, farm_auxiliary, garage, shed, roof, service, yes` (fallback + unclassifiable)

Berlin count check (fill after Day 2 query):

| Class | # Berlin buildings (draft) | Keep as own class? |
|---|---|---|
| 1. Residential | | |
| 2. Commercial/retail | | |
| 3. Office | | |
| 4. Industrial | | |
| 5. Public/civic | | |
| 6. Education | | |
| 7. Religious | | |
| 8. Health | | |
| 9. Other/ancillary | | |

## 2. OSM tag -> class mapping table

<!-- building=* value -> your class. Built from your own Overpass export + value_counts(), not assumed. -->

Built from the real `building["building"].value_counts()` output for Friedrichshain-Kreuzberg
(80 distinct tag values, 12,697 buildings). Binary mapping used for the Path A provisional-label
test (§1 Tier 1). Re-derive/expand for the Tier-2 taxonomy once ALKIS labels (Path B) are in.

**Residential:**
`apartments, residential, house, terrace, detached, bungalow, dormitory, semidetached_house,
static_caravan, houseboat`

**Non-residential:**
`commercial, office, garages, shed, school, retail, service, garage, industrial, kindergarten,
allotment_house, warehouse, hotel, hospital, hut, church, outbuilding, civic, kiosk, train_station,
sports_hall, toilets, sports_centre, parking, electricity, bunker, government, public, museum,
carport, chapel, transportation, stable, religious, greenhouse, pavilion, college, supermarket,
roundhouse, windmill, mosque, glasshouse, guardhouse, watchtower, arena, fire_station, synagogue,
cinema, gym, theatre, sewage_pumping_station, grandstand, gasometer, station`

**Excluded (label = None -- dropped from training, not forced into either class):**
- `yes` -- zero function information, by far the largest excluded value.
- `roof, construction, ruins, container, tent` -- no reliable function signal.
- `bridge, elevator, boat, ship, staircase, stairs, viaduct, floating_platform, vault, tower` --
  infrastructure/objects mistagged with `building=*`, not real occupiable buildings.

**Judgment calls worth remembering (not obvious from the tag name alone):**
- `allotment_house` and `hut` -> non-residential. German *Kleingarten* allotment houses aren't
  legally permitted as permanent residences despite the name.
- `carport` -> non-residential, not residential -- it's an ancillary structure, not a dwelling.

## 2b. ALKIS `bezgfk` -> class mapping table (Path B, the paper-faithful ground truth)

Built from the real `alkis_buildings["bezgfk"].value_counts()` output (149 distinct values,
21,734 buildings after excluding building *parts* -- see below). Mirrors the paper's own
approach of an explicit reviewed allowlist per Table 4, with an explicit exclusion bucket,
rather than defaulting ambiguous categories into non-residential.

**Residential:**
`Wohnhaus, Wohngebäude, Wohnheim, "Studenten-, Schülerwohnheim", Schwesternwohnheim`

**Non-residential:** everything else observed in this borough's data that isn't in the
Residential or Excluded lists below (~99 categories: commercial, industrial, institutional,
public, religious, education, health, recreation, infrastructure/utility buildings).

**Excluded (label = None -- dropped from training, not forced into either class):**
- Mixed-use compounds: `Wohngebäude mit Handel und Dienstleistungen`,
  `Gebäude für Handel und Dienstleistung mit Wohnen`, `Wohngebäude mit Gewerbe und Industrie`,
  `Gemischt genutztes Gebäude mit Wohnen`, `Wohngebäude mit Gemeinbedarf`,
  `Gebäude für Gewerbe und Industrie mit Wohnen`, `Gebäude für öffentliche Zwecke mit Wohnen`
  -- ~2,084 buildings (~9.6% of this borough's stock) are officially, cadastrally both
  residential and non-residential in the same structure. Direct confirmation of the mixed-use
  urban-form hypothesis behind the Path A/Path B accuracy gap.
- Ancillary parking/storage (ambiguous which use it belongs to): `Garage, Tiefgarage, Schuppen,
  Parkhaus, Parkdeck, Gebäude zum Parken, Gartenhaus`
- Agricultural: `Stall, Stall im Zoo, Land- und forstwirtschaftliches Betriebsgebäude,
  Gebäude für Land- und Forstwirtschaft, Scheune und Stall, Treibhaus`
- Ambiguous institutional/residential care: `Seniorenheim, Obdachlosenheim, Kinderheim,
  "Heilanstalt, Pflegeanstalt, Pflegestation", Kaserne`
- Unspecified/not clearly a building type: `Nach Quellenlage nicht zu spezifizieren, Toilette,
  Empfangsgebäude, Wochenendhaus, Bootshaus`

**Also excluded before any of the above:** 31,096 ALKIS records with `bezgfk = null` --
confirmed via `bezbat` to be architectural sub-parts of buildings (loggias, recessed floors,
passageways, high-rise segments), not separate unlabeled buildings.

**Building tags used as features (Path B only, since the label is now independent of OSM):**
fixed 29-value list from the paper (`apartments, church, civic, commercial, construction,
detached, dormitory, garage, garages, greenhouse, hospital, hotel, house, industrial,
kindergarten, office, parking, public, residential, retail, roof, school, semidetached_house,
service, shed, static_caravan, terrace, warehouse, yes`) + `miscellaneous` for everything else --
not a dummy column per value actually observed in this borough, so the feature set stays
identical across boroughs/regions.

## 3. Success metric

<!-- Why macro-F1 / Cohen's kappa over plain accuracy — in your own words, referencing what you saw
in Zhou et al.'s minority-class F1 numbers. -->

## 4. Scope boundary

<!-- What's explicitly out of scope (e.g. this is footprint-level classification, not pixel/image
segmentation; single time snapshot, not temporal). -->

## 5. Three-minute interview answer

<!-- Write out, in plain sentences, the answer to: "what problem are you solving, why a graph
transformer specifically, and what prior work justifies that choice?" If you can't write it without
opening a paper, that's the gap to close before Phase 1. -->
