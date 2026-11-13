"""Business constants shared by the synthetic data generator, the model and the UI."""

# name -> (typical days between refills, typical cylinders per refill, usual product, credit days)
SEGMENTS = {
    "Restaurant": dict(interval=12, qty=2.0, product="19 kg", credit=15),
    "Hotel": dict(interval=8, qty=4.0, product="19 kg", credit=30),
    "Bakery": dict(interval=14, qty=2.0, product="19 kg", credit=15),
    "Catering": dict(interval=7, qty=3.0, product="19 kg", credit=15),
    "Canteen / Hostel": dict(interval=9, qty=3.0, product="19 kg", credit=30),
    "Street Food": dict(interval=18, qty=1.0, product="19 kg", credit=0),
    "Industrial": dict(interval=26, qty=2.0, product="33 kg", credit=30),
}
SEGMENT_NAMES = list(SEGMENTS)

# name, size_kg, selling price (INR), cost price (INR)
# Selling prices are the dealer's. Cost prices were not provided: ~10% below selling price is a placeholder.
PRODUCTS = [
    ("19 kg", 19.0, 2900, 2610),
    ("33 kg", 33.0, 4500, 4050),
]
