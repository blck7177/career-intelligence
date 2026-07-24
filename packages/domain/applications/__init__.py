"""Application-tracker domain logic (pure, no DB/IO).

Currently holds the application status machine (`transitions`). Kept
dependency-free so the rules are trivially unit-testable and shared by both
the repository layer and the API layer.
"""
