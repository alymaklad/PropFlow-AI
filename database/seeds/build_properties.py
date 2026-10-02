#!/usr/bin/env python3
"""Generate database/seeds/properties.sql: a synthetic property catalog (fictional listings).

Verification times are relative (now() - N days) so the seed stays meaningful whenever it is
loaded. Some listings are deliberately unavailable or stale to exercise the matching filters,
and there is nothing in Marsa Matrouh, no Zamalek penthouse near 1M and no 5-bedroom Maadi
villa near 3M (the dataset's intended no-match cases).

Run: python3 database/seeds/build_properties.py
"""

from pathlib import Path

OUT = Path(__file__).with_name("properties.sql")

# (id, type, location, price, currency, bedrooms, bathrooms, delivery, availability,
#  verified_days_ago, amenities, description)
LISTINGS = [
    ("NC-APT-101", "apartment", "New Cairo", 6_800_000, "EGP", 3, 2, "ready", "available", 2, ["clubhouse", "parking"], "Third-floor apartment in a gated compound near the 90th Street."),
    ("NC-APT-102", "apartment", "New Cairo", 7_600_000, "EGP", 3, 3, "ready", "available", 5, ["garden view", "security"], "Corner unit with garden view, close to schools."),
    ("NC-APT-103", "apartment", "New Cairo", 5_200_000, "EGP", 3, 2, "under_construction", "available", 3, ["pool"], "Delivery in 2027, installments over 6 years."),
    ("NC-APT-104", "apartment", "New Cairo", 4_600_000, "EGP", 2, 2, "ready", "available", 1, ["parking"], "Two-bedroom near the American University."),
    ("NC-APT-105", "apartment", "New Cairo", 6_900_000, "EGP", 3, 2, "ready", "reserved", 1, ["clubhouse"], "Reserved: similar to NC-APT-101."),
    ("NC-APT-106", "apartment", "New Cairo", 7_100_000, "EGP", 3, 2, "ready", "available", 45, ["parking"], "Not re-verified recently."),
    ("NC-VIL-201", "villa", "New Cairo", 14_500_000, "EGP", 4, 4, "ready", "available", 4, ["private garden", "pool"], "Standalone villa with private garden."),
    ("NC-VIL-202", "villa", "New Cairo", 9_800_000, "EGP", 3, 3, "off_plan", "available", 6, ["garden"], "Off-plan twin villa, 8-year plan."),
    ("NC-VIL-203", "villa", "New Cairo", 15_500_000, "EGP", 4, 5, "ready", "available", 2, ["pool", "maid room"], "Family villa near main services."),
    ("NC-DUP-301", "duplex", "New Cairo", 9_600_000, "EGP", 4, 3, "ready", "available", 3, ["roof terrace"], "Duplex with roof terrace."),
    ("NC-OFF-401", "office", "New Cairo", 6_900_000, "EGP", None, 1, "ready", "available", 7, ["parking"], "150 sqm administrative unit."),
    ("SZ-VIL-201", "villa", "Sheikh Zayed", 14_200_000, "EGP", 4, 4, "ready", "available", 2, ["garden", "pool"], "Villa in a gated community."),
    ("SZ-VIL-202", "villa", "Sheikh Zayed", 11_500_000, "EGP", 4, 3, "under_construction", "available", 8, ["garden"], "Delivery next year."),
    ("SZ-VIL-203", "villa", "Sheikh Zayed", 19_500_000, "EGP", 5, 5, "ready", "available", 3, ["pool", "smart home"], "Five-bedroom standalone villa."),
    ("SZ-VIL-204", "villa", "Sheikh Zayed", 24_000_000, "EGP", 5, 6, "ready", "available", 5, ["pool", "large garden"], "Premium villa on a corner plot."),
    ("SZ-VIL-205", "villa", "Sheikh Zayed", 14_000_000, "EGP", 4, 4, "ready", "sold", 2, ["garden"], "Sold."),
    ("SZ-APT-101", "apartment", "Sheikh Zayed", 6_900_000, "EGP", 3, 2, "off_plan", "available", 4, ["clubhouse"], "Off-plan apartment, 8-year installments."),
    ("SZ-APT-102", "apartment", "Sheikh Zayed", 7_300_000, "EGP", 3, 2, "under_construction", "available", 2, ["pool"], "Delivery in 18 months."),
    ("OCT-LND-501", "land", "6th of October", 22_500_000, "EGP", None, None, "ready", "available", 10, [], "5,000 sqm residential plot."),
    ("OCT-APT-101", "apartment", "6th of October", 3_400_000, "EGP", 2, 1, "ready", "available", 6, ["parking"], "Starter apartment."),
    ("CAP-TWN-601", "townhouse", "New Capital", 10_200_000, "EGP", 3, 3, "off_plan", "available", 5, ["garden"], "Off-plan townhouse, R7 district."),
    ("CAP-APT-101", "apartment", "New Capital", 5_800_000, "EGP", 3, 2, "off_plan", "available", 3, ["clubhouse"], "Off-plan apartment."),
    ("MAD-APT-101", "apartment", "Maadi", 4_400_000, "EGP", 2, 1, "ready", "available", 1, ["balcony"], "Two-bedroom in Degla, ready to move."),
    ("MAD-APT-102", "apartment", "Maadi", 3_900_000, "EGP", 2, 2, "ready", "available", 9, ["elevator"], "Renovated two-bedroom."),
    ("MAD-APT-103", "apartment", "Maadi", 6_800_000, "EGP", 3, 2, "ready", "available", 4, ["garden"], "Ground floor with private garden."),
    ("ZAM-STU-701", "studio", "Zamalek", 3_300_000, "EGP", 0, 1, "ready", "available", 3, ["nile view"], "Studio with partial Nile view."),
    ("ZAM-STU-702", "studio", "Zamalek", 2_900_000, "EGP", 0, 1, "ready", "available", 12, [], "Compact studio near the club."),
    ("ZAM-PEN-801", "penthouse", "Zamalek", 26_000_000, "EGP", 3, 3, "ready", "available", 6, ["nile view", "terrace"], "Penthouse with terrace."),
    ("HEL-PEN-801", "penthouse", "Heliopolis", 13_200_000, "EGP", 3, 3, "ready", "available", 2, ["terrace"], "Penthouse with a large terrace."),
    ("HEL-APT-101", "apartment", "Heliopolis", 2_900_000, "EGP", 2, 1, "ready", "available", 5, ["quiet street"], "Two-bedroom on a quiet street."),
    ("NSR-COM-901", "commercial", "Nasr City", 2_400_000, "EGP", None, 1, "ready", "available", 7, ["street front"], "Ground-floor shop on a main street."),
    ("NCO-CHA-111", "chalet", "North Coast", 3_400_000, "EGP", 2, 1, "ready", "available", 4, ["sea view", "pool"], "Chalet with sea view."),
    ("NCO-CHA-112", "chalet", "North Coast", 3_900_000, "EGP", 2, 2, "ready", "available", 2, ["beach access"], "Chalet steps from the beach."),
    ("GOU-VIL-201", "villa", "El Gouna", 19_000_000, "EGP", 3, 3, "ready", "available", 6, ["lagoon view"], "Lagoon-front villa."),
    ("HRG-APT-101", "apartment", "Hurghada", 2_100_000, "EGP", 1, 1, "ready", "available", 3, ["sea view"], "One-bedroom holiday apartment."),
    ("HRG-APT-102", "apartment", "Hurghada", 140_000, "USD", 2, 2, "ready", "available", 5, ["pool"], "Two-bedroom priced in USD."),
    ("ALX-APT-101", "apartment", "Alexandria", 2_850_000, "EGP", 2, 1, "ready", "available", 4, ["sea view"], "Smouha two-bedroom."),
]


def sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, list):
        return "ARRAY[" + ", ".join(sql_value(x) for x in v) + "]::text[]" if v else "'{}'"
    if isinstance(v, int | float):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def main() -> None:
    rows = []
    for (lid, ptype, loc, price, cur, beds, baths, delivery, avail, days, amen, desc) in LISTINGS:
        values = [lid, ptype, loc, price, cur, beds, baths, delivery, amen, desc, avail]
        rows.append("    (" + ", ".join(map(sql_value, values))
                    + f", now() - interval '{days} days')")
    sql = (
        "-- Generated by build_properties.py: synthetic catalog, safe to re-run.\n"
        "INSERT INTO properties (listing_id, property_type, location, price, currency, bedrooms,\n"
        "                        bathrooms, delivery_status, amenities, description, availability,\n"
        "                        last_verified_at)\nVALUES\n" + ",\n".join(rows) + "\n"
        "ON CONFLICT (listing_id) DO UPDATE SET\n"
        "    property_type = EXCLUDED.property_type, location = EXCLUDED.location,\n"
        "    price = EXCLUDED.price, currency = EXCLUDED.currency, bedrooms = EXCLUDED.bedrooms,\n"
        "    bathrooms = EXCLUDED.bathrooms, delivery_status = EXCLUDED.delivery_status,\n"
        "    amenities = EXCLUDED.amenities, description = EXCLUDED.description,\n"
        "    availability = EXCLUDED.availability, last_verified_at = EXCLUDED.last_verified_at;\n"
    )
    OUT.write_text(sql, encoding="utf-8")
    print(f"wrote {len(rows)} listings to {OUT}")


if __name__ == "__main__":
    main()
