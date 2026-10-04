from pathlib import Path

from app.photos import PHOTOS_PER_TYPE, photo_path

PUBLIC = Path(__file__).resolve().parents[3] / "frontend" / "public"


def test_every_photo_a_listing_can_get_exists():
    for kind, count in PHOTOS_PER_TYPE.items():
        for number in range(1, count + 1):
            assert (PUBLIC / "listings" / f"{kind}-{number}.jpg").is_file()


def test_photo_is_stable_per_listing_and_falls_back_to_apartment():
    assert photo_path("NC-VIL-201", "villa") == photo_path("NC-VIL-201", "villa")
    assert photo_path("NC-VIL-201", "villa").startswith("/listings/villa-")
    assert photo_path("X-1", "castle").startswith("/listings/apartment-")
