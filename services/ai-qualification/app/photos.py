"""Illustrative listing photos (free Unsplash photos in frontend/public/listings, credited in
frontend/public/listings/CREDITS.md). Listings of the same type share a small set; each
listing keeps the same photo because the choice depends only on its id."""

PHOTOS_PER_TYPE = {"apartment": 6, "villa": 4, "penthouse": 2, "studio": 2, "chalet": 2,
                   "duplex": 1, "townhouse": 1, "commercial": 1}


def photo_path(listing_id: str, property_type: str) -> str:
    kind = property_type if property_type in PHOTOS_PER_TYPE else "apartment"
    number = sum(map(ord, listing_id)) % PHOTOS_PER_TYPE[kind] + 1
    return f"/listings/{kind}-{number}.jpg"
